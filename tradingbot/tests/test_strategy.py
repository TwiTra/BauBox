"""Regelwerk, Signalbildung und Risikomanagement."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from pax.config import Config, RiskConfig
from pax.strategy.portfolio import Portfolio
from pax.strategy.risk import RiskManager, _guess_correlation
from pax.strategy.rules import RuleEngine, _detect_prefixes
from pax.strategy.signal_engine import SignalEngine, _conviction, raw_bias_for
from pax.types import AccountState, Direction, Position, Signal, SymbolSpec, Trade, ExitReason

NOW = datetime(2026, 9, 7, 13, 0, tzinfo=timezone.utc)
SPEC = SymbolSpec("EURUSD", digits=5, point=1e-5, tick_size=1e-5, tick_value=1.0)


def _signal(**kw) -> Signal:
    basis = dict(
        symbol="EURUSD", time=NOW, direction=Direction.LONG, score=0.7,
        entry=1.1000, stop_loss=1.0970, take_profits=[1.1060],
        risk_reward=2.0, prob_win=0.55, expected_r=0.3,
    )
    basis.update(kw)
    return Signal(**basis)


# --------------------------------------------------------------------------- #
# Regelwerk
# --------------------------------------------------------------------------- #


def test_zeitebenen_praefixe_werden_nicht_geraten():
    """`r2_20` ist die Regressionsgüte, keine Zeiteinheit."""
    row = pd.Series({"r2_20": 1.0, "h1_struct_trend": 1.0, "h4_adx": 20.0, "atr": 0.001})
    assert _detect_prefixes(row) == ["h1_", "h4_"]


def test_regelwerk_bewertet_gleichlaufende_zeitebenen_positiv():
    engine = RuleEngine()
    bullisch = pd.Series({
        "struct_trend": 1.0, "h1_struct_trend": 1.0, "h4_struct_trend": 1.0,
        "premium_discount": -0.6, "struct_event": 1.0, "struct_event_dir": 1.0,
        "bars_since_struct_event": 3.0, "swing_sequence": 0.8, "ema_stack": 1.0,
        "adx": 30.0, "di_diff": 18.0, "rsi": 58.0, "pattern_score": 0.5,
    })
    ergebnis = engine.evaluate(bullisch)
    assert ergebnis.direction is Direction.LONG
    assert ergebnis.score > 0.3
    assert any("Aufwärtsstruktur" in r for r in ergebnis.reasons)


def test_regelwerk_bleibt_bei_widerspruch_neutral():
    engine = RuleEngine()
    widerspruch = pd.Series({
        "struct_trend": 1.0, "h1_struct_trend": -1.0, "h4_struct_trend": 1.0,
        "premium_discount": 0.0, "adx": 12.0, "di_diff": 0.0, "rsi": 50.0,
    })
    ergebnis = engine.evaluate(widerspruch)
    assert abs(ergebnis.score) < 0.25


def test_regelwerk_warnt_bei_ungeeignetem_regime():
    ergebnis = RuleEngine().evaluate(pd.Series({
        "struct_trend": 1.0, "vol_regime": 3.0, "trendiness": 0.1, "liquidity_score": 0.3,
    }))
    assert len(ergebnis.warnings) >= 2


def test_beitraege_summieren_sich_zum_score():
    ergebnis = RuleEngine().evaluate(pd.Series({"struct_trend": 1.0, "premium_discount": -0.5}))
    assert sum(ergebnis.contributions.values()) == pytest.approx(ergebnis.score, abs=1e-9)


# --------------------------------------------------------------------------- #
# Signal-Engine
# --------------------------------------------------------------------------- #


def test_ueberzeugungskennlinie_ist_umkehrbar():
    for c in (0.3, 0.45, 0.58, 0.8):
        assert _conviction(raw_bias_for(c)) == pytest.approx(c, abs=1e-9)


def test_ueberzeugung_ist_monoton():
    werte = [_conviction(x) for x in (0.0, 0.1, 0.3, 0.6, 1.0)]
    assert werte == sorted(werte)
    assert werte[0] == 0.0 and werte[-1] < 1.0


def test_signal_setzt_stop_hinter_die_struktur(featureset, config):
    engine = SignalEngine(config)
    sig = engine.generate(featureset, -1, SPEC)
    if sig.is_actionable:
        abstand = sig.risk_per_unit / sig.atr
        assert config.risk.min_stop_atr <= abstand <= config.risk.max_stop_atr


def test_signale_erfuellen_alle_mindestanforderungen(featureset, config):
    engine = SignalEngine(config)
    signale = engine.generate_series(featureset, SPEC)
    handelbar = [s for s in signale if s.is_actionable]
    assert len(signale) == len(featureset.frame)
    for s in handelbar:
        assert s.score >= config.risk.min_signal_score
        assert s.risk_reward >= config.risk.min_risk_reward
        assert s.expected_r > 0
        assert s.risk_per_unit > 0
        if s.direction is Direction.LONG:
            assert s.stop_loss < s.entry < min(s.take_profits)
        else:
            assert s.stop_loss > s.entry > max(s.take_profits)


def test_teilgewinnanteile_ergeben_hundert_prozent(featureset, config):
    for s in SignalEngine(config).generate_series(featureset, SPEC):
        if s.is_actionable:
            assert sum(s.tp_fractions) == pytest.approx(1.0, abs=1e-6)
            assert len(s.tp_fractions) == len(s.take_profits)


def test_sperre_verhindert_das_signal(featureset, config):
    from pax.learning.feedback import Blocklist, BlockRule

    frei = SignalEngine(config).generate_series(featureset, SPEC)
    anzahl_frei = sum(s.is_actionable for s in frei)

    sperre = Blocklist()
    for wert in ("asien", "london_vormittag", "ueberschneidung", "newyork", "spaet"):
        sperre.add(BlockRule("hour_bucket", wert, "Test", NOW.isoformat(),
                             (NOW + timedelta(days=30)).isoformat(), 50, -0.5))
    gesperrt = SignalEngine(config, blocklist=sperre).generate_series(featureset, SPEC)
    assert sum(s.is_actionable for s in gesperrt) == 0
    assert anzahl_frei >= 0


def test_block_kontext_deckt_alle_stunden_ab():
    for stunde in range(24):
        ctx = SignalEngine.block_context(_signal(time=NOW.replace(hour=stunde)))
        assert ctx["hour_bucket"] in {"asien", "london_vormittag", "ueberschneidung", "newyork", "spaet"}
        assert ctx["score_bucket"] in {"knapp", "mittel", "gut", "sehr_gut"}


# --------------------------------------------------------------------------- #
# Risiko
# --------------------------------------------------------------------------- #


def _konto(balance: float = 10_000.0) -> AccountState:
    return AccountState(balance, balance, free_margin=balance * 0.9)


def test_positionsgroesse_trifft_das_zielrisiko():
    plan = RiskManager(RiskConfig(use_kelly=False)).plan(_signal(), _konto(), SPEC)
    assert plan.allowed
    assert plan.risk_pct == pytest.approx(0.005, abs=0.0015)
    assert plan.volume * plan.stop_points * SPEC.value_per_point == pytest.approx(plan.risk_amount)


def test_kelly_daempft_und_verstaerkt_nicht():
    """Wer 0,5 % einstellt, darf nicht plötzlich mit 2 % im Markt stehen."""
    cfg = RiskConfig(risk_per_trade=0.005, use_kelly=True)
    stark = RiskManager(cfg).plan(_signal(score=0.95, prob_win=0.65), _konto(), SPEC)
    schwach = RiskManager(cfg).plan(_signal(score=0.5, prob_win=0.34), _konto(), SPEC)
    assert stark.risk_pct <= 1.5 * cfg.risk_per_trade + 1e-9
    assert schwach.risk_pct < stark.risk_pct


def test_ohne_vorteil_faellt_das_risiko_stark():
    plan = RiskManager(RiskConfig()).plan(_signal(prob_win=0.25, risk_reward=1.5), _konto(), SPEC)
    assert plan.kelly_raw == 0.0
    assert plan.risk_pct < 0.002


def test_tagesverlustgrenze_stoppt_den_handel():
    rm = RiskManager(RiskConfig(max_daily_loss=0.03))
    konto = _konto()
    rm.update_account(konto)
    rm.record_trade(-400.0)
    plan = rm.plan(_signal(), konto, SPEC)
    assert not plan.allowed
    assert "Tagesverlust" in plan.blockers[0]


def test_verlustserie_verkleinert_die_position():
    rm = RiskManager(RiskConfig(max_daily_loss=0.9))
    konto = _konto()
    ohne = rm.plan(_signal(), konto, SPEC).risk_pct
    for _ in range(5):
        rm.record_trade(-1.0)
    assert rm.plan(_signal(), konto, SPEC).risk_pct < ohne


def test_positionsobergrenze():
    rm = RiskManager(RiskConfig(max_open_positions=2))
    offen = [
        Position(i, f"SYM{i}", Direction.LONG, 0.1, 1.0, NOW, 0.99, 1.02) for i in range(2)
    ]
    plan = rm.plan(_signal(), _konto(), SPEC, offen)
    assert not plan.allowed


def test_zu_kleines_konto_wird_abgelehnt():
    plan = RiskManager(RiskConfig()).plan(_signal(), _konto(120.0), SPEC)
    assert not plan.allowed
    assert any("Mindestlot" in b for b in plan.blockers)


def test_korrelationsschaetzung_ist_plausibel():
    assert _guess_correlation("EURUSD", "EURUSD") == 1.0
    assert _guess_correlation("EURUSD", "GBPUSD") > 0.5
    assert _guess_correlation("EURUSD", "USDCHF") < 0
    assert abs(_guess_correlation("EURUSD", "XAUUSD")) < 0.5


# --------------------------------------------------------------------------- #
# Portfolio
# --------------------------------------------------------------------------- #


def test_portfolio_buchhaltung():
    p = Portfolio()
    p.reset(10_000)
    pos = Position(1, "EURUSD", Direction.LONG, 0.1, 1.10, NOW, 1.097, 1.106)
    p.add(pos)
    assert p.has("EURUSD", Direction.LONG)
    assert p.exposure()["EURUSD"] == pytest.approx(0.1)
    assert p.open_risk(10_000) > 0

    p.close(Trade("EURUSD", Direction.LONG, 0.1, 1.10, NOW, 1.106, NOW, 60.0, 2.0,
                  ExitReason.TAKE_PROFIT, ticket=1))
    assert p.balance == pytest.approx(10_060.0)
    assert p.stats()["trades"] == 1
    assert not p.positions


def test_nachgezogener_stop_senkt_das_offene_risiko():
    p = Portfolio()
    p.reset(10_000)
    pos = Position(1, "EURUSD", Direction.LONG, 0.1, 1.10, NOW, 1.097, 1.106)
    p.add(pos)
    vorher = p.open_risk(10_000)
    pos.stop_loss = 1.101  # über dem Einstieg
    assert p.open_risk(10_000) < vorher
