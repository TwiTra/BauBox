"""Broker-Abstraktion und Positionsführung."""

from __future__ import annotations

import pytest

from pax.config import RiskConfig
from pax.execution import PaperBroker, TradeManager
from pax.types import Direction, SymbolSpec

SPEC = SymbolSpec("EURUSD", digits=5, point=1e-5, tick_size=1e-5, tick_value=1.0,
                  spread_points=10.0, volume_min=0.01, volume_step=0.01)


@pytest.fixture
def broker() -> PaperBroker:
    b = PaperBroker(10_000.0, SPEC)
    b.set_price("EURUSD", 1.1000)
    return b


def test_paper_broker_grundfunktionen(broker):
    assert broker.account().balance == 10_000.0
    ergebnis = broker.open_position("EURUSD", Direction.LONG, 0.10, 1.0970, 1.1090)
    assert ergebnis.ok and ergebnis.ticket > 0
    # Kauf zum Briefkurs, also inklusive Spread
    assert ergebnis.price == pytest.approx(1.1000 + SPEC.spread_points * SPEC.point)
    assert len(broker.positions()) == 1

    broker.set_price("EURUSD", 1.1050)
    assert broker.account().equity > broker.account().balance
    schliessen = broker.close_position(ergebnis.ticket)
    assert schliessen.ok
    assert not broker.positions()
    assert broker.balance > 10_000.0


def test_teilschliessung_laesst_rest_offen(broker):
    ergebnis = broker.open_position("EURUSD", Direction.LONG, 0.10)
    broker.close_position(ergebnis.ticket, 0.04)
    offen = broker.positions()
    assert len(offen) == 1
    assert offen[0].volume == pytest.approx(0.06)


def test_manager_nimmt_teilgewinn_und_zieht_stop_nach(broker):
    ergebnis = broker.open_position("EURUSD", Direction.LONG, 0.10, 1.0970, 1.1090)
    pos = broker.positions()[0]
    manager = TradeManager(broker, RiskConfig())
    manager.register(pos, targets=[1.1031, 1.1091], fractions=[0.4, 0.3])
    risiko = pos.entry_price - 1.0970

    broker.set_price("EURUSD", pos.entry_price + 0.3 * risiko)
    assert not manager.manage()  # zu früh für alles

    broker.set_price("EURUSD", 1.1035)  # über dem ersten Ziel
    arten = {a.kind for a in manager.manage()}
    assert "partial" in arten
    assert broker.positions()[0].volume < 0.10

    broker.set_price("EURUSD", pos.entry_price + 1.2 * risiko)
    manager.manage()
    assert broker.positions()[0].stop_loss >= pos.entry_price

    broker.set_price("EURUSD", pos.entry_price + 2.5 * risiko)
    manager.manage()
    assert broker.positions()[0].stop_loss > pos.entry_price


def test_manager_vergisst_fremd_geschlossene_positionen(broker):
    ergebnis = broker.open_position("EURUSD", Direction.LONG, 0.10, 1.0970, 1.1090)
    manager = TradeManager(broker, RiskConfig())
    manager.register(broker.positions()[0])
    assert ergebnis.ticket in manager.state
    broker.close_position(ergebnis.ticket)
    manager.manage()
    assert ergebnis.ticket not in manager.state


def test_manager_uebernimmt_unbekannte_positionen(broker):
    broker.open_position("EURUSD", Direction.SHORT, 0.05, 1.1030, 1.0950)
    manager = TradeManager(broker, RiskConfig())
    manager.manage()
    assert len(manager.state) == 1


def test_not_aus_schliesst_alles(broker):
    broker.open_position("EURUSD", Direction.LONG, 0.05)
    broker.open_position("EURUSD", Direction.SHORT, 0.05)
    manager = TradeManager(broker, RiskConfig())
    manager.manage()
    aktionen = manager.close_all("Test")
    assert len(aktionen) == 2
    assert not broker.positions()
