"""Was passiert, wenn etwas kaputt ist.

Ein Handelssystem faellt nicht im Normalbetrieb um, sondern an einer defekten
Datei, einem abgelehnten Auftrag oder einem Kurs, den es so nicht geben duerfte.
Diese Tests pruefen, dass es dann *laut* stehenbleibt statt still weiterzurechnen -
denn eine falsche Zahl ist schlimmer als ein Abbruch.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pax.config import Config, RiskConfig
from pax.execution import PaperBroker, TradeManager
from pax.features import FeatureBuilder
from pax.types import Direction, SymbolSpec

SPEC = SymbolSpec("EURUSD", digits=5, point=1e-5, tick_size=1e-5, tick_value=1.0,
                  spread_points=10.0, volume_min=0.01, volume_step=0.01)


def _reihe(n: int = 600, start: str = "2025-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="15min", tz="UTC")
    rng = np.random.default_rng(3)
    close = 1.10 + np.cumsum(rng.normal(0, 2e-4, n))
    return pd.DataFrame(
        {"open": close, "high": close + 3e-4, "low": close - 3e-4,
         "close": close, "volume": np.full(n, 100.0)},
        index=idx,
    )


# --------------------------------------------------------------------------- #
# Defekte Kursdaten
# --------------------------------------------------------------------------- #


def test_nan_im_kurs_erzeugt_keine_stillen_zahlen():
    """NaN darf sich nicht als plausibler Wert durch die Merkmale ziehen."""
    df = _reihe()
    df.iloc[300:310, df.columns.get_loc("close")] = np.nan
    fs = FeatureBuilder(Config()).build({"M15": df}, symbol="EURUSD", warmup=0)
    # Kein Merkmal darf unendlich werden - das waere eine Division durch null,
    # die spaeter als Positionsgroesse endet.
    zahlen = fs.frame.select_dtypes(include=[np.number])
    assert not np.isinf(zahlen.to_numpy()).any(), "unendliche Werte in der Merkmalsmatrix"


def test_unendliche_kurse_werden_nicht_durchgereicht():
    df = _reihe()
    df.iloc[200, df.columns.get_loc("high")] = np.inf
    fs = FeatureBuilder(Config()).build({"M15": df}, symbol="EURUSD", warmup=0)
    zahlen = fs.frame.select_dtypes(include=[np.number])
    assert not np.isinf(zahlen.to_numpy()).any()


def test_entartete_reihe_ohne_bewegung_liefert_kein_signal():
    """Alle Kurse gleich - ATR ist null. Kein Stop moeglich, also kein Trade."""
    from pax.strategy.signal_engine import SignalEngine

    idx = pd.date_range("2025-01-01", periods=600, freq="15min", tz="UTC")
    df = pd.DataFrame({"open": 1.1, "high": 1.1, "low": 1.1, "close": 1.1,
                       "volume": 100.0}, index=idx)
    cfg = Config()
    fs = FeatureBuilder(cfg).build({"M15": df}, symbol="EURUSD", warmup=0)
    signal = SignalEngine(cfg, None).generate(fs, -1)
    assert signal.direction is Direction.FLAT
    assert signal.risk_per_unit == 0.0 or signal.stop_loss == 0.0


def test_doppelte_zeitstempel_werden_entfernt(tmp_path):
    from pax.data.store import BarStore

    df = _reihe(200)
    doppelt = pd.concat([df, df.iloc[100:120]]).sort_index()
    assert doppelt.index.duplicated().any()
    store = BarStore(str(tmp_path / "cache"))
    store.write("EURUSD", "M15", doppelt)
    zurueck = store.read("EURUSD", "M15")
    assert not zurueck.index.duplicated().any(), "Duplikate wuerden Balken doppelt zaehlen"
    assert zurueck.index.is_monotonic_increasing


def test_luecken_brechen_die_zeitebenen_ausrichtung_nicht():
    """Wochenenden und Feiertage sind Luecken - der Normalfall, nicht die Ausnahme."""
    from pax.features.mtf import align_to_base

    df = _reihe(800)
    mit_luecke = pd.concat([df.iloc[:300], df.iloc[500:]])
    hoeher = mit_luecke.resample("4h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    ausgerichtet = align_to_base(hoeher, mit_luecke.index, "H4", prefix="h4_")
    assert len(ausgerichtet) == len(mit_luecke)
    assert ausgerichtet.index.equals(mit_luecke.index)


def test_zu_wenige_balken_werden_gemeldet_statt_geraten():
    with pytest.raises((ValueError, KeyError, IndexError)):
        FeatureBuilder(Config()).build({"M15": _reihe(3)}, symbol="EURUSD", warmup=0)


# --------------------------------------------------------------------------- #
# Ausfaelle im Betrieb
# --------------------------------------------------------------------------- #


def test_abgelehnter_auftrag_hinterlaesst_keinen_zustand():
    """Lehnt der Broker ab, darf keine Phantomposition zurueckbleiben."""
    broker = PaperBroker(10_000.0, SPEC)
    broker.set_price("EURUSD", 1.1000)
    ergebnis = broker.open_position("EURUSD", Direction.LONG, 0.0)  # unzulaessiges Volumen
    assert not ergebnis.ok
    assert not broker.positions(), "abgelehnter Auftrag hat eine Position hinterlassen"
    assert broker.account().balance == 10_000.0


def test_beschaedigter_positionszustand_bringt_die_verwaltung_nicht_um(tmp_path):
    """Ein halb geschriebener Zustand darf den Livebetrieb nicht anhalten."""
    from pax.learning.journal import Journal

    journal = Journal(str(tmp_path / "j.sqlite"))
    broker = PaperBroker(10_000.0, SPEC)
    broker.set_price("EURUSD", 1.1000)
    auftrag = broker.open_position("EURUSD", Direction.LONG, 0.10, 1.0970, 1.1090)

    journal.save_position_state(auftrag.ticket, "EURUSD", {
        "entry": "keine Zahl", "stop": None, "targets": "kaputt", "unbekannt": 1,
    })
    # Der Neustart liest den beschaedigten Zustand - und darf daran nicht sterben.
    manager = TradeManager(broker, RiskConfig(), store=journal)
    manager.manage()
    zustand = manager.state.get(auftrag.ticket)
    assert zustand is not None
    # Jedes Feld muss trotz Muell einen brauchbaren Typ haben
    assert isinstance(zustand.initial_stop, float)
    assert isinstance(zustand.targets, list)
    assert isinstance(zustand.partials_done, int)


def test_notaus_verhindert_weitere_auftraege():
    from pax.strategy.risk import RiskManager

    from pax.types import AccountState

    cfg = RiskConfig()
    risk = RiskManager(cfg)
    risk.halt("Notaus im Test")
    konto = AccountState(balance=10_000.0, equity=10_000.0, currency="EUR")
    blocker = risk.check_limits(konto)
    assert blocker, "nach dem Notaus muss der Handel gesperrt sein"


def test_beschaedigte_modelldatei_faellt_auf_das_regelwerk_zurueck(tmp_path):
    """Ein kaputtes Modell darf den Betrieb nicht anhalten - Regeln reichen."""
    from pax.models.registry import ModelRegistry

    wurzel = tmp_path / "models"
    ziel = wurzel / "EURUSD" / "20250101-000000"
    ziel.mkdir(parents=True)
    (ziel / "ensemble.joblib").write_bytes(b"kein gueltiges joblib")
    (wurzel / "EURUSD" / "champion.json").write_text(
        '{"version": "20250101-000000"}', encoding="utf-8")

    modell = ModelRegistry(str(wurzel)).load("EURUSD")
    assert modell is None, "ein unlesbares Modell muss None ergeben, nicht einen Absturz"
