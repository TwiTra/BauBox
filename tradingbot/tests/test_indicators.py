"""Indikatoren: Formeln stimmen, und nichts schaut in die Zukunft."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pax.features import indicators as ind


def test_ema_entspricht_manueller_rechnung():
    """adjust=False startet die Rekursion beim ersten Wert, nicht beim Mittel."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    alpha = 2 / (3 + 1)
    expected = 1.0
    for value in (2.0, 3.0, 4.0, 5.0):
        expected = alpha * value + (1 - alpha) * expected
    assert ind.ema(s, 3).iloc[-1] == pytest.approx(expected, rel=1e-9)


def test_rsi_ohne_verluste_ist_maximal():
    """Ein rein steigender Kurs hat RSI 100, nicht 50 - die Division durch null
    darf nicht still zu 'neutral' werden."""
    assert ind.rsi(pd.Series(np.arange(1, 40, dtype=float)), 14).iloc[-1] == pytest.approx(100.0)
    assert ind.rsi(pd.Series(np.arange(40, 1, -1, dtype=float)), 14).iloc[-1] == pytest.approx(0.0)
    flach = pd.Series(np.full(40, 5.0))
    assert ind.rsi(flach, 14).iloc[-1] == pytest.approx(50.0)


def test_true_range_beruecksichtigt_luecken():
    df = pd.DataFrame({"open": [10, 20], "high": [11, 21], "low": [9, 19], "close": [10, 20]})
    tr = ind.true_range(df)
    # Zweite Kerze: |21 - 10| = 11 schlägt die Kerzenspanne von 2
    assert tr.iloc[1] == pytest.approx(11.0)


def test_rsi_grenzfaelle():
    steigend = pd.Series(np.arange(1, 60, dtype=float))
    fallend = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert ind.rsi(steigend, 14).iloc[-1] > 99
    assert ind.rsi(fallend, 14).iloc[-1] < 1


def test_atr_ist_positiv_und_endlich(bars):
    a = ind.atr(bars, 14).dropna()
    assert len(a) > 0
    assert (a > 0).all()
    assert np.isfinite(a).all()


def test_donchian_schliesst_aktuellen_balken_aus(bars):
    """Sonst berührt der Kurs sein eigenes Extrem und jeder Ausbruch wäre trivial."""
    dc = ind.donchian(bars, 20)
    valid = dc["dc_upper"].notna()
    prior_max = bars["high"].shift(1).rolling(20, min_periods=20).max()
    assert np.allclose(dc["dc_upper"][valid], prior_max[valid])


def test_efficiency_ratio_liegt_zwischen_null_und_eins(bars):
    er = ind.efficiency_ratio(bars["close"], 20).dropna()
    assert er.between(0, 1).all()


def test_hurst_erkennt_trend_und_rauschen():
    rng = np.random.default_rng(0)
    trend = pd.Series(np.cumsum(np.abs(rng.normal(1.0, 0.1, 900))))
    noise = pd.Series(np.cumsum(rng.normal(0, 1, 900)))
    assert ind.hurst(trend, 120).dropna().median() > ind.hurst(noise, 120).dropna().median()


@pytest.mark.parametrize("cut", [1, 17, 60])
def test_alle_indikatoren_sind_kausal(bars, cut):
    """Der wichtigste Test der Datei: Zukunft abschneiden darf nichts ändern."""
    voll = ind.add_all(bars)
    gekuerzt = ind.add_all(bars.iloc[:-cut])
    gemeinsam = gekuerzt.index[-200:]
    abweichung = (voll.loc[gemeinsam] - gekuerzt.loc[gemeinsam]).abs().max().max()
    assert abweichung == 0.0, f"Lookahead bei cut={cut}: {abweichung}"


def test_rolling_rank_bleibt_im_einheitsintervall(bars):
    r = ind.rolling_rank(ind.atr(bars, 14), 250).dropna()
    assert r.between(0, 1).all()
