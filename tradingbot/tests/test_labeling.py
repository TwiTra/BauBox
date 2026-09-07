"""Zielvariablen und Stichprobengewichte."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pax.labeling import (
    barrier_outcome,
    concurrency,
    direction_labels,
    label_report,
    meta_labels,
    sample_weights,
    uniqueness_weights,
)


def _konstruierte_reihe() -> tuple[pd.DataFrame, pd.Series]:
    """Erste Kerze steigt zum Ziel, danach fällt der Kurs zum Stop."""
    idx = pd.date_range("2026-01-01", periods=12, freq="1h", tz="UTC")
    close = [100.0] + [101.0, 103.0, 103.0] + [99.0] * 8
    df = pd.DataFrame(
        {"open": close, "close": close,
         "high": [c + 0.2 for c in close], "low": [c - 0.2 for c in close]},
        index=idx,
    )
    return df, pd.Series(1.0, index=idx)


def test_barriere_erkennt_ziel_zuerst():
    df, atr = _konstruierte_reihe()
    res = barrier_outcome(df, atr, up_atr=2.0, dn_atr=1.0, max_bars=8)
    assert res.label.iloc[0] == 1.0          # 102 wird vor 99 erreicht
    assert res.bars_held.iloc[0] == 2.0
    assert res.r_multiple.iloc[0] == pytest.approx(2.0)


def test_shortrichtung_dreht_die_barrieren():
    df, atr = _konstruierte_reihe()
    res = barrier_outcome(df, atr, 2.0, 1.0, 8, side=-1)
    assert res.label.iloc[0] == -1.0         # für einen Short läuft es sofort schief


def test_pessimistische_aufloesung_ist_nie_besser(bars, atr):
    pess = barrier_outcome(bars, atr, 2.0, 1.0, 48, pessimistic=True)
    opti = barrier_outcome(bars, atr, 2.0, 1.0, 48, pessimistic=False)
    assert pess.r_multiple.mean() <= opti.r_multiple.mean()


def test_labels_sind_ausgewogen_und_verwertbar(bars, atr):
    y, usable, res = direction_labels(bars, atr, 1.5, 1.5, 48, 0.25)
    bericht = label_report(y, usable, res)
    assert bericht["anteil_verwertbar"] > 0.9
    assert 0.35 < bericht["anteil_aufwaerts"] < 0.65
    assert set(y.unique()) <= {0.0, 1.0}


def test_letzte_balken_sind_nicht_verwertbar(bars, atr):
    """Am Reihenende fehlt die Zukunft - diese Beispiele dürfen nicht ins Training."""
    _, usable, _ = direction_labels(bars, atr, 1.5, 1.5, 48)
    assert not usable.iloc[-48:].any()


def test_hoeheres_gewinnziel_senkt_die_trefferquote(bars, atr):
    eng = barrier_outcome(bars, atr, 1.0, 1.0, 48)
    weit = barrier_outcome(bars, atr, 3.0, 1.0, 48)
    assert (weit.label > 0).mean() < (eng.label > 0).mean()


def test_ueberlappung_senkt_das_gewicht():
    """Zwanzig Beispiele, die denselben Zeitraum abdecken, sind nicht zwanzig."""
    exit_index = pd.Series(np.full(50, 49.0))
    w = uniqueness_weights(exit_index)
    assert w.sum() < 5
    einzeln = pd.Series(np.arange(50, dtype=float))
    assert uniqueness_weights(einzeln).sum() == pytest.approx(50.0)


def test_gleichzeitigkeit_zaehlt_richtig():
    exit_index = pd.Series([2.0, 3.0, 4.0])
    c = concurrency(exit_index, 5)
    assert c[0] == 1 and c[2] == 3


def test_gewichte_sind_positiv_und_normiert(bars, atr):
    _, _, res = direction_labels(bars, atr, 1.5, 1.5, 48)
    w = sample_weights(res, decay=0.5)
    assert (w >= 0).all()
    assert w.sum() == pytest.approx(len(w), rel=1e-6)


def test_meta_labels_nur_dort_wo_ein_vorschlag_vorlag(bars, atr):
    side = pd.Series(0.0, index=bars.index)
    side.iloc[100:200] = 1.0
    y, usable, _ = meta_labels(bars, atr, side, 2.0, 1.0, 24)
    assert not usable.iloc[:100].any()
    assert usable.iloc[100:200].any()
