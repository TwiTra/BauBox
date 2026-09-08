"""Der Erwartungswert und die Fusion - drei Eigenschaften, die vorher fehlten.

Alle drei Fehler hatten dieselbe Wurzel: Die Richtungswahrscheinlichkeit wurde
verwendet, als beantworte sie eine Frage, auf die sie nicht trainiert war. Das
Ergebnis war ein Bot, der auf echten EURUSD-Daten entweder gar nicht handelte
oder ausschliesslich Shorts mit erfundenem Erwartungswert nahm.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pax.config import Config
from pax.labeling import direction_labels
from pax.strategy.signal_engine import HorizonModels, _logit, _win_probability


# --------------------------------------------------------------------------- #
# 1. Kein Vorteil darf keinen Erwartungswert ergeben
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rr", [0.8, 1.0, 1.5, 2.0, 3.0, 5.0])
def test_ohne_vorteil_ist_der_erwartungswert_exakt_null(rr):
    """Der faire Anker.

    Vorher wurde bei fehlender Meinung p = 0.5 gesetzt und gegen ein CRV von 2
    gerechnet: E[R] = 0.5*2 - 0.5 = +0.5 R geschenkt, auf jedem Balken. Ein
    weiter entferntes Ziel ist aber kein Vorteil, sondern nur ein selteneres
    Ereignis.
    """
    p = _win_probability(0.0, rr)
    assert p == pytest.approx(1.0 / (1.0 + rr), abs=1e-12)
    assert p * rr - (1.0 - p) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("rr", [1.0, 2.0, 3.0])
def test_vorteil_wirkt_in_die_richtige_richtung(rr):
    besser = _win_probability(_logit(0.60), rr)
    neutral = _win_probability(0.0, rr)
    schlechter = _win_probability(_logit(0.40), rr)
    assert schlechter < neutral < besser
    assert besser * rr - (1.0 - besser) > 0.0
    assert schlechter * rr - (1.0 - schlechter) < 0.0


# --------------------------------------------------------------------------- #
# 2. Das Richtungslabel muss symmetrisch sein
# --------------------------------------------------------------------------- #


def test_richtungslabel_ist_auf_zufallspfad_ausgeglichen():
    """Basisrate ~ 0.5 auf einem driftlosen Pfad.

    Mit den frueher uebergebenen 2:1-Barrieren lag sie bei ~1/3. Ein kalibriertes
    Modell gibt dann im Mittel 0.33 aus, was die Fusion als dauerhafte
    Short-Neigung liest - eine Aussage ueber die Barrierewahl, nicht ueber den
    Markt.
    """
    rng = np.random.default_rng(11)
    n = 6000
    close = 1.10 + np.cumsum(rng.normal(0.0, 1e-4, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 5e-5,
            "low": close - 5e-5,
            "close": close,
            "volume": np.ones(n),
        },
        index=idx,
    )
    atr = pd.Series(np.full(n, 3e-4), index=idx)

    y, usable, _ = direction_labels(df, atr, 1.5, max_bars=48, min_return_atr=0.25)
    basisrate = float(y[usable].mean())
    assert 0.42 < basisrate < 0.58, f"Basisrate {basisrate:.3f} statt ~0.5"


def test_richtungslabel_nimmt_kein_barrierepaar_mehr():
    """Die Asymmetrie darf gar nicht mehr ausdrueckbar sein."""
    import inspect

    params = list(inspect.signature(direction_labels).parameters)
    assert "barrier_atr" in params
    assert "tp_atr" not in params and "sl_atr" not in params


# --------------------------------------------------------------------------- #
# 3. Ein ahnungsloses Modell darf die Regeln nicht ueberstimmen
# --------------------------------------------------------------------------- #


class _Modell:
    def __init__(self, auc: float) -> None:
        self.report = type("R", (), {"auc": auc})()


def test_guete_steuert_das_modellgewicht():
    assert HorizonModels().skill == 0.0
    assert HorizonModels(medium=_Modell(0.50)).skill == pytest.approx(0.0)
    assert HorizonModels(medium=_Modell(0.75)).skill == pytest.approx(1.0)
    assert 0.0 < HorizonModels(medium=_Modell(0.55)).skill < 0.5


def test_ahnungsloses_modell_loescht_die_regelmeinung_nicht(config):
    """Der Fehler, der auf echten Daten zu null Trades fuehrte.

    Bei festen Gewichten schrumpft der Regelanteil auf 45 %. Da der Rohwert fuer
    die Mindestschwelle 0.2424 erreichen muss, der Regel-Score aber selten ueber
    0.5 kommt, war die Schwelle mit Modell strukturell unerreichbar - unabhaengig
    vom Setup.
    """
    from pax.strategy.signal_engine import SignalEngine

    engine = SignalEngine(config, None)
    engine.models = HorizonModels(medium=_Modell(0.50))

    class _Regel:
        score = 0.60
        reasons: list[str] = []
        warnings: list[str] = []

    ohne, _ = engine._fuse(_Regel(), None, {})
    mit, _ = engine._fuse(_Regel(), 0.5, {})
    assert mit == pytest.approx(ohne, abs=1e-9), (
        "Ein Modell ohne Meinung muss neutral sein, nicht daempfend"
    )
