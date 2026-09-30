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


# --------------------------------------------------------------------------- #
# Zustandssicherung - der Manager muss einen Neustart überstehen
# --------------------------------------------------------------------------- #


def _journal(tmp_path):
    from pax.learning.journal import Journal

    return Journal(tmp_path / "j.sqlite")


def _mit_teilgewinn(broker, store):
    """Position eröffnen, einen Teilgewinn nehmen, Stop auf Einstand ziehen."""
    ergebnis = broker.open_position("EURUSD", Direction.LONG, 0.10, 1.0970, 1.1090)
    pos = broker.positions()[0]
    manager = TradeManager(broker, RiskConfig(), store=store)
    manager.register(pos, targets=[1.1031, 1.1061, 1.1091], fractions=[0.3, 0.3],
                     max_hold_minutes=1440)
    risiko = pos.entry_price - 1.0970
    broker.set_price("EURUSD", 1.1035)
    manager.manage()
    broker.set_price("EURUSD", pos.entry_price + 1.2 * risiko)
    manager.manage()
    return manager, pos, risiko


def test_zustand_uebersteht_neustart(broker, tmp_path):
    """Ohne Ablage begänne der Bot nach jedem Neustart bei null."""
    store = _journal(tmp_path)
    manager, pos, _ = _mit_teilgewinn(broker, store)
    vorher = manager.state[pos.ticket]
    assert vorher.partials_done == 1 and vorher.break_even_done

    # Neustart: frischer Manager, dieselbe Ablage
    neu = TradeManager(broker, RiskConfig(), store=_journal(tmp_path))
    neu.manage()
    nachher = neu.state[pos.ticket]
    assert nachher.partials_done == vorher.partials_done
    assert nachher.break_even_done == vorher.break_even_done
    assert nachher.initial_stop == pytest.approx(vorher.initial_stop)
    assert nachher.targets == vorher.targets
    assert nachher.max_hold_minutes == vorher.max_hold_minutes


def test_ohne_ablage_geht_der_zustand_verloren(broker, tmp_path):
    """Belegt den Schaden, den die Ablage verhindert - und macht ihn messbar."""
    manager, pos, _ = _mit_teilgewinn(broker, _journal(tmp_path))
    echtes_risiko = abs(pos.entry_price - manager.state[pos.ticket].initial_stop)

    blind = TradeManager(broker, RiskConfig())  # keine Ablage
    blind.manage()
    zustand = blind.state[pos.ticket]

    # 1) Der nachgezogene Stop wird für den ursprünglichen gehalten
    angenommenes_risiko = abs(pos.entry_price - zustand.initial_stop)
    assert angenommenes_risiko < echtes_risiko / 5
    # 2) Die restlichen Ziele sind weg
    assert len(zustand.targets) < 3
    # 3) Der Zeitausstieg ist stillschweigend abgeschaltet
    assert zustand.max_hold_minutes == 0


def test_kein_zweiter_teilgewinn_nach_neustart(broker, tmp_path):
    """Der Zähler muss den Neustart überleben, sonst wird erneut abgerechnet."""
    store = _journal(tmp_path)
    _, pos, _ = _mit_teilgewinn(broker, store)
    volumen = broker.positions()[0].volume

    neu = TradeManager(broker, RiskConfig(), store=_journal(tmp_path))
    neu.manage()
    broker.set_price("EURUSD", 1.1040)  # wieder über dem ersten Ziel
    neu.manage()
    assert broker.positions()[0].volume == pytest.approx(volumen)
    assert neu.state[pos.ticket].partials_done == 1


def test_geschlossene_position_raeumt_die_ablage(broker, tmp_path):
    store = _journal(tmp_path)
    ergebnis = broker.open_position("EURUSD", Direction.LONG, 0.10, 1.0970, 1.1090)
    manager = TradeManager(broker, RiskConfig(), store=store)
    manager.register(broker.positions()[0])
    assert ergebnis.ticket in store.load_position_states()

    broker.close_position(ergebnis.ticket)
    manager.manage()
    assert ergebnis.ticket not in store.load_position_states()


def test_manager_laeuft_ohne_ablage_weiter(broker):
    """Die Ablage ist optional - ohne sie darf nichts brechen."""
    broker.open_position("EURUSD", Direction.LONG, 0.10, 1.0970, 1.1090)
    manager = TradeManager(broker, RiskConfig())
    assert manager.manage() == []
    assert len(manager.state) == 1


def test_unlesbarer_zustand_bricht_nicht(broker, tmp_path):
    store = _journal(tmp_path)
    broker.open_position("EURUSD", Direction.LONG, 0.10, 1.0970, 1.1090)
    ticket = broker.positions()[0].ticket
    store.save_position_state(ticket, "EURUSD", {"partials_done": "kaputt", "unbekannt": 1})
    manager = TradeManager(broker, RiskConfig(), store=store)
    manager.manage()
    assert ticket in manager.state  # Notfallaufnahme statt Absturz
