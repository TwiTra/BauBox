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


def _echte_geometrie(market):
    """Zeitebenen so aufbauen, wie echte Daten aussehen.

    Die hoeheren Ebenen werden aus der Basis verdichtet, und die laufende,
    noch unvollstaendige Periode faellt dabei weg. Der Tagesbalken hinkt der
    Basis dadurch um bis zu zwei Tage hinterher - anders als bei Reihen, die
    fuer jede Ebene bis zum selben Zeitpunkt erzeugt werden.
    """
    from pax.features.mtf import resample_ohlcv

    # Genug Balken, damit die Tagesebene ueberhaupt Merkmale traegt: Unter rund
    # 100 Tagesbalken ueberspringt der Builder die Ebene, und der Fehlalarm
    # bliebe unsichtbar - genau deshalb fiel er in der Testsuite nie auf.
    basis = market.generate(bars=12000, timeframe="M15")
    # Mitten am Tag enden, damit der laufende Tagesbalken unvollstaendig ist
    basis = basis[basis.index <= basis.index[-1].normalize() + pd.Timedelta(hours=20)]
    return {
        "M15": basis,
        "H1": resample_ohlcv(basis, "H1"),
        "H4": resample_ohlcv(basis, "H4"),
        "D1": resample_ohlcv(basis, "D1"),
    }


# --------------------------------------------------------------------------- #
# Die Kausalitaetspruefung selbst
# --------------------------------------------------------------------------- #


def test_kausalitaetspruefung_meldet_bei_tagesdaten_keinen_fehlalarm(market):
    """Regressionstest: Die Pruefung kuerzte nach Balkenzahl statt nach Zeit.

    Bei cut=64 auf M15-Basis ergibt `cut // scale` fuer D1 eine Null, aufgerundet
    auf einen Balken - also 24 Stunden statt 16. Der gekuerzte Rahmen verlor
    damit einen Tagesbalken, den der volle Rahmen fuer denselben Basisbalken zu
    Recht verwendete, und die Pruefung meldete einen Lookahead, den es nicht
    gab. Fuer H1 und H4 ging die Rechnung zufaellig auf - der Fehlalarm trat nur
    bei Tagesdaten auf, also genau dort, wo niemand ihn suchte.
    """
    from pax.config import Config
    from pax.features import FeatureBuilder, assert_causal

    frames = _echte_geometrie(market)
    assert len(frames["D1"]) >= 100, "zu wenige Tagesbalken - die Ebene wird uebersprungen"
    # Die Geometrie ist der ganze Punkt: Der Tagesbalken hinkt der Basis um
    # gut zwei Tage hinterher, weil der laufende Tag noch nicht geschlossen
    # ist. Genau dann faellt der Balken, den die alte Kuerzung zu viel
    # abschnitt, in den Vergleichsbereich.
    abstand = frames["M15"].index[-1] - frames["D1"].index[-1]
    assert abstand > pd.Timedelta(hours=40), f"Testaufbau greift nicht: {abstand}"

    builder = FeatureBuilder(Config())
    diffs = assert_causal(builder, frames, cut=64, check_rows=120)
    assert max(diffs.values()) == 0.0


def test_kausalitaetspruefung_findet_einen_echten_lookahead(market, monkeypatch):
    """Die Gegenprobe: Ohne sie waere die Korrektur oben nur eine Abschwaechung."""
    import pandas as pd

    from pax.config import Config
    from pax.features import FeatureBuilder, assert_causal
    from pax.features import mtf

    frames = _echte_geometrie(market)
    builder = FeatureBuilder(Config())

    echt = mtf.align_to_base

    def ohne_versatz(higher, base_index, higher_tf, prefix=""):
        """Hoeheren Balken schon bei Oeffnung sichtbar machen - der klassische Fehler.

        Der Versatz wird vorab abgezogen, damit ihn `align_to_base` gleich
        wieder aufaddiert: Der Balken ist damit ab seiner Oeffnung sichtbar
        statt ab seinem Schluss.
        """
        from pax.types import Timeframe

        tf = Timeframe.parse(higher_tf)
        verschoben = higher.copy()
        verschoben.index = verschoben.index - pd.Timedelta(minutes=tf.minutes)
        return echt(verschoben, base_index, higher_tf, prefix=prefix)

    monkeypatch.setattr(mtf, "align_to_base", ohne_versatz)
    monkeypatch.setattr("pax.features.builder.align_to_base", ohne_versatz, raising=False)

    with pytest.raises(AssertionError, match="Lookahead"):
        assert_causal(builder, frames, cut=64, check_rows=120)
