"""Vorwärts-Backtest: kein Balken darf von einem Modell gehandelt werden, das ihn kannte."""

from __future__ import annotations

import numpy as np
import pytest

from pax.backtest import walk_forward_backtest
from pax.backtest.walkforward import (
    WalkForwardResult,
    WindowResult,
    format_walkforward_report,
)
from pax.types import Direction, SymbolSpec

SPEC = SymbolSpec("EURUSD", digits=5, point=1e-5, tick_size=1e-5, tick_value=1.0,
                  spread_points=10.0, volume_min=0.01, volume_step=0.01)


@pytest.fixture(scope="module")
def schnell():
    """Kleinstmögliche Modellkonfiguration - der Test prüft den Ablauf, nicht die Güte."""
    from pax.config import ModelConfig

    return ModelConfig(members=["logistic"], n_splits=3, min_train_samples=200,
                       max_features=15, feature_selection=True, random_state=0)


@pytest.fixture(scope="module")
def ergebnis(featureset, schnell):
    from pax.config import Config

    cfg = Config()
    cfg.model = schnell
    cfg.data.warmup_bars = 300
    return walk_forward_backtest(cfg, featureset, SPEC, folds=2, train_frac=0.6, verbose=False)


def test_fenster_werden_trainiert(ergebnis):
    assert ergebnis.trained_windows >= 1
    for w in ergebnis.windows:
        assert w.train_rows > 0 and w.test_rows > 0
        assert w.test_from is not None and w.test_to is not None
        assert w.test_from < w.test_to
        assert 0.0 <= w.auc <= 1.0
        assert w.members >= 1


def test_fenster_folgen_zeitlich_aufeinander(ergebnis):
    """Kein Testfenster darf vor einem früheren liegen oder es überlappen."""
    fenster = [w for w in ergebnis.windows if w.test_from and w.test_to]
    for davor, danach in zip(fenster, fenster[1:]):
        assert davor.test_to <= danach.test_from


def test_ausserhalb_der_fenster_wird_nicht_gehandelt(ergebnis):
    """Der Anfang der Historie dient nur dem Training - dort darf kein Trade stehen."""
    assert ergebnis.backtest is not None
    fenster = [w for w in ergebnis.windows if w.test_from]
    if not fenster:
        pytest.skip("kein Fenster trainiert")
    erster_start = min(w.test_from for w in fenster)
    for trade in ergebnis.backtest.trades:
        assert trade.entry_time >= erster_start


def test_nur_ein_teil_der_balken_wird_gehandelt(ergebnis):
    """Bei train_frac 0,6 darf höchstens gut die Hälfte der Balken handelbar sein."""
    assert 0 < ergebnis.traded_bars < ergebnis.total_bars
    assert ergebnis.traded_bars / ergebnis.total_bars < 0.75


def test_trades_werden_ihrem_fenster_zugeordnet(ergebnis):
    summe = sum(w.trades for w in ergebnis.windows)
    assert summe == len(ergebnis.trades)


def test_kennzahlen_sind_berechenbar(ergebnis):
    m = ergebnis.metrics()
    assert "trades" in m
    c = ergebnis.consistency()
    assert "auc_mittel" in c or c.get("fenster_mit_trades") == 0


def test_zu_wenige_daten_werden_gemeldet(featureset, schnell):
    from pax.config import Config

    cfg = Config()
    cfg.model = schnell
    kurz = featureset.frame.iloc[:50]
    beschnitten = type(featureset)(
        frame=kurz, base=featureset.base.iloc[:50], atr=featureset.atr.iloc[:50],
        timeframe=featureset.timeframe, symbol="EURUSD",
    )
    with pytest.raises(ValueError, match="Zu wenige"):
        walk_forward_backtest(cfg, beschnitten, SPEC, folds=2, verbose=False)


# --------------------------------------------------------------------------- #
# Bericht
# --------------------------------------------------------------------------- #


def _kunstergebnis(werte: list[float]) -> WalkForwardResult:
    r = WalkForwardResult(symbol="TEST", total_bars=100, traded_bars=50, duration_s=1.0)
    for i, v in enumerate(werte, 1):
        r.windows.append(WindowResult(i, 100, 50, auc=0.5, trades=5, total_r=v))
    return r


def test_bericht_warnt_wenn_ein_fenster_alles_traegt():
    text = format_walkforward_report(_kunstergebnis([10.7, -1.5, -2.2, -3.8, 2.7]))
    assert "trägt mehr als das Gesamtergebnis" in text
    assert "%" not in text.split("ACHTUNG")[1].split("\n")[0]  # keine sinnlose 182-%-Angabe


def test_bericht_warnt_bei_konzentriertem_ergebnis():
    text = format_walkforward_report(_kunstergebnis([7.0, 1.0, 1.0, 0.5, 0.5]))
    assert "70 % des Gesamtergebnisses" in text


def test_bericht_schweigt_bei_gleichmaessigem_ergebnis():
    text = format_walkforward_report(_kunstergebnis([2.0, 1.8, 2.2, 1.9, 2.1]))
    assert "ACHTUNG" not in text


def test_bericht_warnt_bei_fehlendem_vorteil():
    r = _kunstergebnis([1.0, 1.0])
    for w in r.windows:
        w.auc = 0.49
    assert "Kein belastbarer Vorteil" in format_walkforward_report(r)
