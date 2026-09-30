"""Journal, Fehleranalyse und Weiterentwicklung."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from pax.config import LearningConfig
from pax.learning import (
    Blocklist,
    Evolver,
    FeedbackAnalyzer,
    Journal,
    population_stability_index,
)
from pax.learning.feedback import BlockRule
from pax.models import ModelRegistry
from pax.types import Direction, ExitReason, Horizon, Signal, Trade, VolRegime

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _trade(i: int, r: float, stunde: int = 13, regime=VolRegime.NORMAL) -> Trade:
    ein = (NOW - timedelta(hours=300 - i)).replace(hour=stunde)
    return Trade(
        symbol="EURUSD", direction=Direction.LONG if i % 2 else Direction.SHORT,
        volume=0.1, entry_price=1.10, entry_time=ein, exit_price=1.10 + r * 0.003,
        exit_time=ein + timedelta(hours=3), profit=r * 100.0, r_multiple=r,
        exit_reason=ExitReason.TAKE_PROFIT if r > 0 else ExitReason.STOP_LOSS,
        horizon=Horizon.MEDIUM, regime=regime, signal_score=0.65, prob_win=0.58,
        max_adverse_r=0.4, bars_held=12, ticket=i,
    )


@pytest.fixture
def journal(tmp_path) -> Journal:
    return Journal(tmp_path / "j.sqlite")


def test_journal_schreibt_und_liest(journal):
    for i in range(10):
        journal.record_trade(_trade(i, 1.0 if i % 2 else -1.0))
    df = journal.trades()
    assert len(df) == 10
    assert df["exit_time"].is_monotonic_increasing
    assert journal.count_trades() == 10
    stats = journal.stats()
    assert stats["trades"] == 10
    assert stats["gewinnquote"] == pytest.approx(0.5)


def test_journal_trennt_quellen(journal):
    journal.record_trade(_trade(1, 1.0), source="live")
    journal.record_trade(_trade(2, -1.0), source="backtest")
    assert journal.count_trades(source="live") == 1
    assert journal.count_trades(source="backtest") == 1
    assert len(journal.trades(source="live")) == 1


def test_journal_haelt_auch_abgelehnte_signale_fest(journal):
    sig = Signal("EURUSD", NOW, Direction.LONG, 0.7, 1.10, 1.097, [1.106])
    journal.record_signal(sig, taken=True)
    journal.record_signal(sig, taken=False, reject_reason="Score unter Mindestwert")
    df = journal.signals()
    assert len(df) == 2
    assert set(df["taken"]) == {0, 1}


def test_journal_export_und_aufraeumen(journal, tmp_path):
    journal.record_trade(_trade(1, 1.0))
    journal.record_training("EURUSD", "v1", 0.56, 5000, 100, True, "erstes Modell")
    pfade = journal.export_csv(tmp_path / "export")
    assert len(pfade) == 3 and all(p.exists() for p in pfade)
    assert journal.last_training("EURUSD") is not None
    assert journal.vacuum(keep_days=0) >= 0


def test_fehleranalyse_findet_die_schwache_stelle(journal):
    """Asien verliert systematisch - das muss die Analyse sehen."""
    rng = np.random.default_rng(2)
    for i in range(140):
        stunde = [3, 9, 13, 17][i % 4]
        r = float(rng.normal(-0.6 if stunde == 3 else 0.15, 0.8))
        journal.record_trade(_trade(i, r, stunde))
    analyzer = FeedbackAnalyzer(LearningConfig())
    scheiben = analyzer.slices(journal.trades(), min_trades=10)
    schwaechste = next(s for s in scheiben if s.dimension == "hour_bucket")
    assert schwaechste.value == "asien"
    assert schwaechste.expectancy_r < 0
    bericht = analyzer.report(journal.trades())
    assert "SCHWÄCHSTE BEREICHE" in bericht and "asien" in bericht


def test_fehleranalyse_meldet_ueberschaetzte_wahrscheinlichkeit(journal):
    for i in range(80):
        journal.record_trade(_trade(i, -1.0 if i % 3 else 1.0))
    bericht = FeedbackAnalyzer(LearningConfig()).report(journal.trades())
    assert "VERSPROCHEN GEGEN EINGETRETEN" in bericht
    assert "überschätzt" in bericht


def test_sperre_entsteht_nur_bei_genug_belegen(journal, tmp_path):
    cfg = LearningConfig(min_trades_for_feedback=40, blocklist_min_trades=15)
    analyzer = FeedbackAnalyzer(cfg)
    sperren = Blocklist(path=tmp_path / "b.json")

    for i in range(20):
        journal.record_trade(_trade(i, -1.0, 3))
    assert analyzer.update_blocklist(journal.trades(), sperren) == []  # zu wenige insgesamt

    rng = np.random.default_rng(4)
    for i in range(20, 140):
        stunde = [3, 9, 13, 17][i % 4]
        journal.record_trade(_trade(i, float(rng.normal(-0.7 if stunde == 3 else 0.2, 0.6)), stunde))
    neu = analyzer.update_blocklist(journal.trades(), sperren)
    assert any(r.dimension == "hour_bucket" and r.value == "asien" for r in neu)


def test_richtung_wird_nie_gesperrt(journal, tmp_path):
    """Eine ganze Handelsrichtung zu sperren wäre zu grob."""
    rng = np.random.default_rng(6)
    for i in range(160):
        r = float(rng.normal(-0.8 if i % 2 else 0.3, 0.5))
        journal.record_trade(_trade(i, r))
    neu = FeedbackAnalyzer(LearningConfig()).update_blocklist(
        journal.trades(), Blocklist(path=tmp_path / "b.json")
    )
    assert all(r.dimension != "direction" for r in neu)


def test_sperren_verfallen(tmp_path):
    sperren = Blocklist(path=tmp_path / "b.json")
    abgelaufen = BlockRule("regime", "hoch", "alt", NOW.isoformat(),
                           (NOW - timedelta(days=1)).isoformat(), 20, -0.5)
    gueltig = BlockRule("regime", "extrem", "aktuell", NOW.isoformat(),
                        (NOW + timedelta(days=30)).isoformat(), 20, -0.5)
    sperren.add(abgelaufen)
    sperren.add(gueltig)
    assert len(sperren.active_rules()) == 1
    assert sperren.check({"regime": "hoch"}) is None
    assert sperren.check({"regime": "extrem"}) is not None
    assert sperren.prune() == 1


def test_sperren_ueberleben_das_speichern(tmp_path):
    pfad = tmp_path / "b.json"
    sperren = Blocklist(path=pfad)
    sperren.add(BlockRule("regime", "extrem", "Test", NOW.isoformat(),
                          (NOW + timedelta(days=30)).isoformat(), 20, -0.5))
    sperren.save()
    assert len(Blocklist.load(pfad).active_rules()) == 1


def test_psi_erkennt_verschiebung():
    rng = np.random.default_rng(1)
    a = rng.normal(0, 1, 4000)
    assert population_stability_index(a, rng.normal(0, 1, 4000)) < 0.05
    assert population_stability_index(a, rng.normal(1.5, 1.5, 4000)) > 0.3
    assert population_stability_index(a[:5], a[:5]) == 0.0  # zu wenig Daten


def test_evolver_ohne_modell_will_trainieren(config, tmp_path):
    evolver = Evolver(config, ModelRegistry(tmp_path / "m"), Journal(tmp_path / "j.sqlite"))
    noetig, grund = evolver.should_retrain("EURUSD")
    assert noetig and "kein Modell" in grund


def test_evolver_lehnt_schwachen_herausforderer_ab(config):
    evolver = Evolver(config)
    vergleich = {"champion_auc": 0.60, "challenger_auc": 0.605, "folds": 5,
                 "challenger_wins": 3, "win_ratio": 0.6}
    uebernehmen, grund = evolver._decide(vergleich, 5000)
    assert not uebernehmen and "Mindestverbesserung" in grund


def test_evolver_lehnt_unbestaendigen_herausforderer_ab(config):
    vergleich = {"champion_auc": 0.55, "challenger_auc": 0.60, "folds": 5,
                 "challenger_wins": 2, "win_ratio": 0.4}
    uebernehmen, grund = Evolver(config)._decide(vergleich, 5000)
    assert not uebernehmen and "unbeständig" in grund


def test_evolver_uebernimmt_klar_besseren(config):
    vergleich = {"champion_auc": 0.53, "challenger_auc": 0.59, "folds": 5,
                 "challenger_wins": 5, "win_ratio": 1.0}
    uebernehmen, grund = Evolver(config)._decide(vergleich, 5000)
    assert uebernehmen and "besser" in grund


def test_evolver_lehnt_bei_zu_wenigen_beispielen_ab(config):
    vergleich = {"champion_auc": 0.5, "challenger_auc": 0.7, "folds": 5,
                 "challenger_wins": 5, "win_ratio": 1.0}
    uebernehmen, _ = Evolver(config)._decide(vergleich, 10)
    assert not uebernehmen
