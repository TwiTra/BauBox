"""Backtest-Engine: Kosten, Reihenfolge und die unbequemen Annahmen."""

from __future__ import annotations

from datetime import timezone

import numpy as np
import pandas as pd
import pytest

from pax.backtest import BacktestEngine, format_report
from pax.backtest.report import exit_breakdown, monthly_table, trade_frame
from pax.strategy import SignalEngine
from pax.types import Direction, ExitReason, Signal, SymbolSpec

SPEC = SymbolSpec("EURUSD", digits=5, point=1e-5, tick_size=1e-5, tick_value=1.0,
                  spread_points=10.0, volume_min=0.01, volume_step=0.01)


def _leere_signale(fs) -> list[Signal]:
    return [
        Signal(symbol="EURUSD", time=t.to_pydatetime(), direction=Direction.FLAT,
               score=0.0, entry=float(c), stop_loss=0.0)
        for t, c in zip(fs.frame.index, fs.base["close"])
    ]


def test_ohne_signale_bleibt_das_konto_unveraendert(featureset, config):
    result = BacktestEngine(config, SPEC).run(featureset, _leere_signale(featureset))
    assert result.trades == []
    assert result.final_balance == pytest.approx(config.backtest.initial_balance)
    assert len(result.equity) == len(featureset.frame)


def test_einstieg_erfolgt_zur_eroeffnung_des_folgebalkens(featureset, config):
    """Ein Signal aus dem Schlusskurs darf nicht zum Schlusskurs ausgeführt werden."""
    signale = _leere_signale(featureset)
    i = 500
    bar = featureset.base.iloc[i]
    atr = float(featureset.atr.iloc[i])
    signale[i] = Signal(
        symbol="EURUSD", time=featureset.frame.index[i].to_pydatetime(),
        direction=Direction.LONG, score=0.9, entry=float(bar["close"]),
        stop_loss=float(bar["close"]) - 1.5 * atr,
        take_profits=[float(bar["close"]) + 3.0 * atr], tp_fractions=[1.0],
        risk_reward=2.0, prob_win=0.6, expected_r=0.5, atr=atr, max_hold_bars=200,
    )
    result = BacktestEngine(config, SPEC).run(featureset, signale)
    assert len(result.trades) == 1
    trade = result.trades[0]
    naechste_eroeffnung = float(featureset.base["open"].iloc[i + 1])
    spread = SPEC.spread_points * SPEC.point
    schlupf = config.backtest.slippage_points * SPEC.point
    assert trade.entry_price == pytest.approx(
        SPEC.normalize_price(naechste_eroeffnung + spread + schlupf), abs=SPEC.point
    )
    assert trade.entry_price != pytest.approx(float(bar["close"]))


def test_kosten_werden_vollstaendig_verbucht(featureset, config):
    config.backtest.commission_per_lot = 10.0
    signale = _leere_signale(featureset)
    for i in (300, 800, 1200):
        bar = featureset.base.iloc[i]
        atr = float(featureset.atr.iloc[i])
        signale[i] = Signal(
            symbol="EURUSD", time=featureset.frame.index[i].to_pydatetime(),
            direction=Direction.LONG, score=0.9, entry=float(bar["close"]),
            stop_loss=float(bar["close"]) - 1.5 * atr,
            take_profits=[float(bar["close"]) + 3.0 * atr], tp_fractions=[1.0],
            risk_reward=2.0, prob_win=0.6, expected_r=0.5, atr=atr, max_hold_bars=100,
        )
    result = BacktestEngine(config, SPEC).run(featureset, signale)
    assert result.costs["kommission"] > 0
    assert result.costs["spread_und_schlupf"] > 0
    assert result.costs["gesamt"] > 0


def test_stop_gewinnt_wenn_beide_barrieren_im_selben_balken_liegen(config):
    """Ohne Tickdaten ist die Reihenfolge unbekannt - die günstige Annahme wäre gelogen."""
    from pax.features.builder import FeatureSet
    from pax.types import Timeframe

    idx = pd.date_range("2026-01-01", periods=14, freq="15min", tz="UTC")
    base = pd.DataFrame(
        {"open": 1.10, "high": 1.10, "low": 1.10, "close": 1.10, "volume": 100.0}, index=idx
    )
    # Balken 3 durchläuft sowohl Ziel als auch Stop
    base.iloc[3, base.columns.get_loc("high")] = 1.120
    base.iloc[3, base.columns.get_loc("low")] = 1.080
    fs = FeatureSet(frame=pd.DataFrame(index=idx), base=base,
                    atr=pd.Series(0.005, index=idx), timeframe=Timeframe.M15, symbol="EURUSD")

    signale = [Signal("EURUSD", t.to_pydatetime(), Direction.FLAT, 0.0, 1.10, 0.0) for t in idx]
    signale[1] = Signal("EURUSD", idx[1].to_pydatetime(), Direction.LONG, 0.9, 1.10,
                        1.095, [1.115], [1.0], risk_reward=3.0, prob_win=0.6,
                        expected_r=0.8, atr=0.005, max_hold_bars=50)
    config.backtest.intrabar_worst_case = True
    result = BacktestEngine(config, SPEC).run(fs, signale)
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason is ExitReason.STOP_LOSS
    assert result.trades[0].r_multiple < 0


def test_ablehnungsgruende_werden_gebuendelt(featureset, config):
    signale = SignalEngine(config).generate_series(featureset, SPEC)
    result = BacktestEngine(config, SPEC).run(featureset, signale)
    # Der Zahlenwert steht in Klammern und darf keine eigene Kategorie erzeugen
    assert all("(" not in grund for grund in result.rejections)
    assert len(result.rejections) < 15


def test_kapitalkurve_hat_die_richtige_laenge(featureset, config):
    signale = SignalEngine(config).generate_series(featureset, SPEC)
    result = BacktestEngine(config, SPEC).run(featureset, signale)
    assert len(result.equity) == len(featureset.frame)
    assert len(result.balance) == len(featureset.frame)
    assert result.equity.index.equals(featureset.frame.index)


def test_bericht_ist_auch_ohne_trades_lesbar(featureset, config):
    result = BacktestEngine(config, SPEC).run(featureset, _leere_signale(featureset))
    text = format_report(result, "EUR")
    assert "Kein einziger Trade" in text
    assert trade_frame(result).empty
    assert monthly_table(result).empty


def test_bericht_mit_trades(featureset, config):
    signale = _leere_signale(featureset)
    for i in range(200, 1400, 120):
        bar = featureset.base.iloc[i]
        atr = float(featureset.atr.iloc[i])
        signale[i] = Signal(
            "EURUSD", featureset.frame.index[i].to_pydatetime(), Direction.LONG, 0.9,
            float(bar["close"]), float(bar["close"]) - 1.5 * atr,
            [float(bar["close"]) + 3.0 * atr], [1.0], risk_reward=2.0, prob_win=0.6,
            expected_r=0.5, atr=atr, max_hold_bars=80,
        )
    result = BacktestEngine(config, SPEC).run(featureset, signale)
    assert result.trades
    text = format_report(result, "EUR", n_trials=20)
    for abschnitt in ("ERGEBNIS", "TRADES", "RISIKO", "EHRLICHKEITSPRÜFUNG", "AUSSTIEGSGRÜNDE"):
        assert abschnitt in text
    assert not exit_breakdown(result).empty
    assert "Deflated Sharpe" in text


def test_signalzahl_muss_zur_balkenzahl_passen(featureset, config):
    with pytest.raises(ValueError):
        BacktestEngine(config, SPEC).run(featureset, _leere_signale(featureset)[:-5])


def test_kursziele_kollabieren_nicht_auf_den_boden(featureset, config):
    """Regressionstest gegen den stillsten aller Fehler: null Trades.

    Ein zu enger Filter lässt die ganze Kette formal fehlerfrei durchlaufen -
    Signale werden erzeugt, geprüft, abgelehnt, und am Ende steht ein leerer
    Bericht mit Exit-Code 0. Genau das passierte, als das Kursziel vom
    *nächstgelegenen* Nebenlevel gedeckelt wurde: Da neben dem Kurs praktisch
    immer irgendein Level liegt, fiel das CRV reihenweise auf seinen Boden von
    0,5 und blieb damit unter jeder Mindestanforderung.

    Geprüft wird die Signatur des Fehlers, nicht seine Folge. Eine Trade-Zahl
    wäre zu stumpf - auf diesen Daten kamen selbst mit dem Fehler noch sieben
    Signale durch. Der Anteil bodengedeckelter Ziele dagegen sprang von 0 auf
    61 Prozent und ist über Bibliotheksversionen hinweg stabil.
    """
    signale = SignalEngine(config).generate_series(featureset, SPEC)
    crv = pd.Series([s.risk_reward for s in signale])
    am_boden = float((crv <= 0.501).mean())
    assert am_boden < 0.20, (
        f"{am_boden:.1%} aller Signale haben ein CRV am unteren Anschlag - "
        "die Zielfindung wird von Nahzielen gedeckelt"
    )
    assert crv.median() >= config.risk.min_risk_reward * 0.8

    handelbar = [s for s in signale if s.is_actionable]
    assert handelbar, "kein einziges handelbares Signal - ein Filter ist zu streng"
    result = BacktestEngine(config, SPEC).run(featureset, signale)
    assert result.trades, "handelbare Signale vorhanden, aber kein Trade zustande gekommen"
    assert result.signals_actionable == len(handelbar)
    assert all(np.isfinite(t.r_multiple) for t in result.trades)
    assert all(t.entry_price > 0 and t.stop_loss > 0 for t in result.trades)
