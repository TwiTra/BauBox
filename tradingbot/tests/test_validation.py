"""Gesperrte Faltungen und Kennzahlen."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pax.validation.metrics import (
    classification_metrics,
    deflated_sharpe,
    equity_metrics,
    expected_calibration_error,
    probabilistic_sharpe,
    roc_auc,
    trading_metrics,
)
from pax.validation.splits import (
    PurgedKFold,
    check_no_overlap,
    purged_train_test_split,
    walk_forward_windows,
)

N = 800
EXITS = pd.Series(np.minimum(np.arange(N) + 40, N - 1).astype(float))


def test_purged_kfold_laesst_nichts_ueberlappen():
    cv = PurgedKFold(5, EXITS, embargo_frac=0.02)
    falten = list(cv.split(np.zeros((N, 3))))
    assert len(falten) == 5
    for train, test in falten:
        assert check_no_overlap(train, test, EXITS)
        assert not set(train.tolist()) & set(test.tolist())


def test_purging_entfernt_tatsaechlich_beispiele():
    ohne = list(PurgedKFold(4, EXITS, 0.0, purge=False).split(np.zeros((N, 2))))
    mit = list(PurgedKFold(4, EXITS, 0.0, purge=True).split(np.zeros((N, 2))))
    assert len(mit[1][0]) < len(ohne[1][0])


def test_embargo_sperrt_die_zeit_nach_dem_test():
    cv = PurgedKFold(4, None, embargo_frac=0.05)
    train, test = next(iter(cv.split(np.zeros((N, 2)))))
    luecke = train.min() - test.max()
    assert luecke > 1


def test_walk_forward_trainiert_nur_auf_vergangenem():
    fenster = walk_forward_windows(N, folds=4, train_frac=0.6, exit_index=EXITS)
    assert len(fenster) == 4
    for train, test in fenster:
        assert train.max() < test.min()
        assert check_no_overlap(train, test, EXITS)


def test_rollendes_fenster_verschiebt_den_start():
    wachsend = walk_forward_windows(N, 4, 0.6, anchored=True)
    rollend = walk_forward_windows(N, 4, 0.6, anchored=False)
    assert all(t.min() == 0 for t, _ in wachsend)
    assert rollend[-1][0].min() > 0


def test_walk_forward_meldet_zu_wenig_daten():
    with pytest.raises(ValueError):
        walk_forward_windows(40, folds=5, train_frac=0.6)


def test_zeitliche_aufteilung():
    train, test = purged_train_test_split(N, 0.25, EXITS, 0.01)
    assert train.max() < test.min()


def test_auc_kennt_perfekt_und_zufall():
    y = np.array([0, 0, 1, 1], dtype=float)
    assert roc_auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == pytest.approx(1.0)
    assert roc_auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == pytest.approx(0.0)
    assert roc_auc(y, np.array([0.5, 0.5, 0.5, 0.5])) == pytest.approx(0.5)


def test_kalibrierungsfehler_erkennt_ueberschaetzung():
    y = np.zeros(200)
    y[:60] = 1.0
    gut = np.full(200, 0.3)
    schlecht = np.full(200, 0.9)
    assert expected_calibration_error(y, gut) < expected_calibration_error(y, schlecht)


def test_handelskennzahlen():
    r = np.array([1.0, -1.0, 2.0, -1.0, 1.0])
    m = trading_metrics(r)
    assert m["trades"] == 5
    assert m["win_rate"] == pytest.approx(0.6)
    assert m["expectancy_r"] == pytest.approx(0.4)
    assert m["profit_factor"] == pytest.approx(2.0)
    assert m["max_consecutive_losses"] == 1


def test_kapitalkurve():
    eq = pd.Series([100, 110, 105, 120, 118], dtype=float)
    m = equity_metrics(eq, periods_per_year=252)
    assert m["total_return"] == pytest.approx(0.18)
    assert m["max_drawdown"] < 0


def test_deflated_sharpe_bestraft_viele_versuche():
    """Wer 500 Varianten testet, findet auch im Rauschen eine gute."""
    einzeln = deflated_sharpe(0.15, 300, n_trials=1)
    wenige = deflated_sharpe(0.15, 300, n_trials=5)
    viele = deflated_sharpe(0.15, 300, n_trials=500)
    assert einzeln > wenige > viele
    assert viele < 0.5


def test_deflated_sharpe_bleibt_bei_wenigen_versuchen_aussagekraeftig():
    """Mit fester Varianz 1,0 fiel der Wert schon bei 5 Versuchen auf 0 - und
    unterschied damit gar nichts mehr."""
    gut = deflated_sharpe(0.25, 400, n_trials=5)
    schlecht = deflated_sharpe(0.02, 400, n_trials=5)
    assert gut > 0.5
    assert gut > schlecht


def test_sortino_bestraft_nur_die_verlustseite():
    """Gleiches Mittel, aber flachere Verluste -> besserer Sortino."""
    import numpy as np

    from pax.validation.metrics import _sortino

    viele_kleine = np.array([-0.1] * 9 + [1.0])
    wenige_grosse = np.array([0.1] * 9 + [-0.8])
    assert _sortino(viele_kleine) > _sortino(wenige_grosse)


def test_psr_waechst_mit_der_stichprobe():
    assert probabilistic_sharpe(0.1, 1000) > probabilistic_sharpe(0.1, 50)


def test_klassifikationskennzahlen_vollstaendig():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 500).astype(float)
    p = np.clip(0.5 + 0.2 * (y - 0.5) + rng.normal(0, 0.1, 500), 0.01, 0.99)
    m = classification_metrics(y, p)
    assert m["auc"] > 0.7
    assert 0 <= m["brier"] <= 1
    assert m["n"] == 500
