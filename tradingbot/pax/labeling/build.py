"""Zielvariable für das Training - an genau einer Stelle.

Vorher stand dieser Aufbau dreimal im Code: in der CLI, in der Evolution und im
Vorwärtstest. Genau so konnte sich ein falscher Aufruf von `direction_labels`
durch das ganze System ziehen, ohne dass es an einer Stelle auffiel. Wer die
Zielvariable ändert, ändert sie jetzt hier - oder gar nicht.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Config
from ..features.builder import FeatureSet
from ..utils import get_logger
from .barriers import BarrierResult, direction_labels, meta_labels

log = get_logger("labeling")

DIRECTION = "direction"
META = "meta"


def rule_sides(cfg: Config, fs: FeatureSet) -> pd.Series:
    """Für jeden Balken die Seite, die das Regelwerk vorschlägt (+1 / -1 / 0).

    Das Regelwerk liest ausschließlich die Merkmalszeile des jeweiligen Balkens,
    ist also genauso kausal wie die Merkmale selbst.
    """
    from ..strategy.rules import RuleEngine, _detect_prefixes

    engine = RuleEngine()
    frame = fs.frame
    if frame.empty:
        return pd.Series(dtype=float, index=frame.index, name="side")

    # Präfixe einmal bestimmen statt je Zeile - und Wörterbücher statt
    # pandas-Zeilen, weil `iloc` je Zeile hier den Löwenanteil der Zeit frisst.
    prefixes = _detect_prefixes(frame.iloc[0])
    sides = [
        engine.evaluate(row, tf_prefixes=prefixes).direction.sign
        for row in frame.to_dict("records")
    ]
    return pd.Series(np.asarray(sides, dtype=float), index=frame.index, name="side")


def build_labels(
    cfg: Config, fs: FeatureSet
) -> tuple[pd.Series, pd.Series, BarrierResult, str]:
    """Zielvariable, Verwertbarkeitsmaske, Barriereergebnis und Art des Labels.

    Zwei Arten, und die Art muss mitgeführt werden, weil `proba` je nach Art
    etwas völlig anderes bedeutet:

    * `direction` - "geht es zuerst hinreichend hoch oder runter?", symmetrische
      Barrieren, neutraler Punkt 0.5. Die Richtung kommt vom Modell.
    * `meta` - "hätte der vom Regelwerk vorgeschlagene Trade funktioniert?",
      die echten Trade-Barrieren, neutraler Punkt ist die Basisrate. Die
      Richtung kommt vom Regelwerk, das Modell bewertet sie nur noch.

    Wer diese beiden Bedeutungen verwechselt, baut sich eine erfundene
    Richtungsneigung ein - genau der Fehler, den es hier schon gab.
    """
    lb = cfg.labels
    if not lb.use_meta_labeling:
        y, usable, res = direction_labels(
            fs.base, fs.atr, lb.direction_atr, lb.max_horizon_bars, lb.min_return_atr
        )
        return y, usable, res, DIRECTION

    sides = rule_sides(cfg, fs)
    vorschlaege = int((sides != 0).sum())
    if vorschlaege < lb.min_meta_samples:
        log.warning(
            "Meta-Labeling verlangt Vorschläge des Regelwerks, es gibt aber nur %d "
            "(mindestens %d nötig) - es wird auf Richtungslabel zurückgefallen.",
            vorschlaege, lb.min_meta_samples,
        )
        y, usable, res = direction_labels(
            fs.base, fs.atr, lb.direction_atr, lb.max_horizon_bars, lb.min_return_atr
        )
        return y, usable, res, DIRECTION

    y, usable, res = meta_labels(
        fs.base, fs.atr, sides, lb.tp_atr, lb.sl_atr, lb.max_horizon_bars
    )
    return y, usable, res, META
