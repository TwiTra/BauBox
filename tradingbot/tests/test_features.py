"""Merkmalsmatrix - hier entscheidet sich, ob das ganze System ehrlich ist."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pax.config import Config
from pax.features import FeatureBuilder, assert_causal
from pax.features.mtf import align_to_base, alignment_score, confirm_lag_bars
from pax.features.regime import RegimeDetector
from pax.features.smc import SMCAnalyzer, detect_sweeps
from pax.features.structure import StructureAnalyzer
from pax.features.indicators import atr as atr_fn
from pax.types import Horizon, Timeframe


def test_matrix_hat_erwartete_form(featureset):
    assert len(featureset.frame) > 1000
    assert len(featureset.frame.columns) > 150
    assert featureset.frame.index.is_monotonic_increasing
    assert not featureset.frame.index.duplicated().any()


def test_matrix_ist_endlich_und_luckenlos(featureset):
    numerisch = featureset.frame.select_dtypes(include=[np.number])
    assert np.isfinite(numerisch.to_numpy()).all()
    assert featureset.frame.isna().sum().sum() == 0


def test_hoehere_zeitebenen_sind_vertreten(featureset):
    assert any(c.startswith("h1_") for c in featureset.frame.columns)
    assert any(c.startswith("h4_") for c in featureset.frame.columns)
    assert "mtf_trend_agree" in featureset.frame.columns


def test_keine_absoluten_preisspalten(featureset):
    """Das Modell soll Verhalten lernen, nicht den Kursstand auswendig."""
    verboten = ("swing_high", "swing_low", "ema_8", "ema_200", "bb_upper", "dc_upper", "st_line")
    for name in featureset.frame.columns:
        assert not any(name == v or name.endswith("_" + v) for v in verboten), name


@pytest.mark.parametrize("cut", [16, 64])
def test_gesamte_matrix_ist_kausal(frames, cut):
    """Die zentrale Prüfung: kein einziges Merkmal darf in die Zukunft sehen."""
    builder = FeatureBuilder(Config())
    diffs = assert_causal(builder, frames, cut=cut, check_rows=100)
    assert max(diffs.values()) == 0.0


def test_ausrichtung_nutzt_nur_geschlossene_balken(frames):
    base = frames["M15"]
    higher = frames["H4"]
    aligned = align_to_base(higher[["close"]], base.index, "H4")
    span = pd.Timedelta(hours=4)
    geprueft = 0
    for probe in base.index[-300:]:
        value = aligned.loc[probe, "close"]
        if pd.isna(value):
            continue
        erlaubt = higher.index[higher.index + span <= probe]
        if len(erlaubt) == 0:
            continue
        geprueft += 1
        assert float(value) == pytest.approx(float(higher.loc[erlaubt[-1], "close"]))
    assert geprueft > 100


def test_ausrichtungswert_bestraft_widerspruch():
    einig = alignment_score({Horizon.SHORT: 0.8, Horizon.MEDIUM: 0.8, Horizon.LONG: 0.8})
    uneinig = alignment_score({Horizon.SHORT: 0.8, Horizon.MEDIUM: -0.8, Horizon.LONG: 0.8})
    assert einig > 0.6
    assert abs(uneinig) < 0.3
    assert alignment_score({}) == 0.0


def test_bestaetigungsverzoegerung():
    assert confirm_lag_bars("M15", "H4") == 16
    assert confirm_lag_bars("H1", "H1") == 1


def test_regime_erkennung_liefert_gueltige_bereiche(bars):
    r = RegimeDetector().analyze(bars)
    assert r["vol_rank"].between(0, 1).all()
    assert r["trendiness"].between(0, 1).all()
    assert set(r["trend_regime"].unique()) <= {-1.0, 0.0, 1.0}
    assert set(r["vol_regime"].unique()) <= {0.0, 1.0, 2.0, 3.0}


def test_smc_findet_zonen_und_bleibt_kausal(bars, atr):
    ms = StructureAnalyzer(3, 0.5).analyze(bars, atr)
    an = SMCAnalyzer()
    ergebnis = an.analyze(bars, atr, ms.events, ms.swings, ms.frame)
    arten = {z.kind for z in ergebnis.zones}
    assert {"fvg", "order_block"} <= arten

    kurz_df = bars.iloc[:-40]
    kurz_atr = atr_fn(kurz_df, 14)
    ms2 = StructureAnalyzer(3, 0.5).analyze(kurz_df, kurz_atr)
    kurz = an.analyze(kurz_df, kurz_atr, ms2.events, ms2.swings, ms2.frame)
    gemeinsam = kurz.frame.index[-200:]
    abweichung = (ergebnis.frame.loc[gemeinsam] - kurz.frame.loc[gemeinsam]).abs().max().max()
    assert abweichung == 0.0


def test_fvg_zone_liegt_zwischen_den_richtigen_kerzen(bars, atr):
    zonen = SMCAnalyzer(fvg_min_atr=0.15).find_fvgs(bars, atr)
    assert zonen
    for z in zonen[:30]:
        i = z.created_index
        if z.direction.value == "long":
            assert z.bottom == pytest.approx(float(bars["high"].iloc[i - 2]))
            assert z.top == pytest.approx(float(bars["low"].iloc[i]))
        else:
            assert z.top == pytest.approx(float(bars["low"].iloc[i - 2]))
            assert z.bottom == pytest.approx(float(bars["high"].iloc[i]))


def test_order_block_wird_erst_mit_dem_bruch_bekannt(bars, atr):
    ms = StructureAnalyzer(3, 0.5).analyze(bars, atr)
    zonen = SMCAnalyzer().find_order_blocks(bars, atr, ms.events)
    assert zonen
    for z in zonen:
        assert z.meta["confirmed_index"] > z.created_index


def test_sweep_erkennt_docht_mit_rueckeroberung():
    idx = pd.date_range("2026-01-01", periods=30, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {"open": 1.10, "high": 1.101, "low": 1.099, "close": 1.100}, index=idx
    )
    # Balken 25 sticht nach unten heraus und schließt wieder darüber
    df.iloc[25, df.columns.get_loc("low")] = 1.090
    df.iloc[25, df.columns.get_loc("close")] = 1.1005
    atr = pd.Series(0.002, index=idx)
    sweeps = detect_sweeps(df, atr)
    assert sweeps["sweep_raw"].iloc[25] > 0
