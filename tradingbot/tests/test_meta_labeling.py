"""Meta-Labeling: Das Regelwerk liefert die Seite, das Modell bewertet sie.

Der Sinn der ganzen Uebung ist, eine Ableitung loszuwerden: Bisher wurde aus
einer Richtungswahrscheinlichkeit erschlossen, ob *dieser* Trade gewinnt. Genau
diese Ableitung hat drei Fehler erzeugt. Das Meta-Label beantwortet die Frage
direkt.

Damit gibt es aber zwei Bedeutungen von `proba`, und sie zu verwechseln waere
derselbe Fehler in neuem Gewand. Diese Tests halten sie auseinander.
"""

from __future__ import annotations

import numpy as np
import pytest

from pax.config import Config
from pax.labeling import DIRECTION, META, build_labels, rule_sides
from pax.strategy.signal_engine import (
    HorizonModels,
    ModelProfile,
    SignalEngine,
    _logit,
    skill_from_auc,
)


# --------------------------------------------------------------------------- #
# Aufbau der Zielvariable
# --------------------------------------------------------------------------- #


def test_regelseiten_sind_dreiwertig_und_zeitrichtig(config, featureset):
    sides = rule_sides(config, featureset)
    assert len(sides) == len(featureset.frame)
    assert sides.index.equals(featureset.frame.index)
    assert set(np.unique(sides)) <= {-1.0, 0.0, 1.0}
    assert (sides != 0).any(), "das Regelwerk schlaegt nirgends etwas vor"


def test_meta_labeling_wird_gewaehlt_wenn_eingeschaltet(config, featureset):
    config.labels.use_meta_labeling = True
    config.labels.min_meta_samples = 1
    _, usable, _, kind = build_labels(config, featureset)
    assert kind == META
    # Trainiert wird nur dort, wo das Regelwerk ueberhaupt etwas vorschlug -
    # genau die Verteilung, auf der das Modell spaeter entscheidet.
    sides = rule_sides(config, featureset)
    assert not (usable & (sides == 0)).any()


def test_ohne_meta_labeling_bleibt_das_richtungslabel(config, featureset):
    config.labels.use_meta_labeling = False
    _, _, _, kind = build_labels(config, featureset)
    assert kind == DIRECTION


def test_zu_wenige_vorschlaege_fallen_auf_das_richtungslabel_zurueck(config, featureset):
    """Lieber ein Richtungsmodell als ein Meta-Modell aus einer Handvoll Beispiele."""
    config.labels.use_meta_labeling = True
    config.labels.min_meta_samples = 10**9
    _, _, _, kind = build_labels(config, featureset)
    assert kind == DIRECTION


# --------------------------------------------------------------------------- #
# Die beiden Bedeutungen von proba
# --------------------------------------------------------------------------- #


class _Regel:
    def __init__(self, score: float) -> None:
        self.score = score
        self.reasons: list[str] = []
        self.warnings: list[str] = []


def _engine(cfg: Config, kind: str, base_rate: float, skill: float) -> SignalEngine:
    return SignalEngine(cfg, None, profile=ModelProfile(kind, base_rate, skill))


def test_meta_modell_dreht_die_richtung_niemals_um(config):
    """Eine schlechte Gewinnaussicht fuer einen Long heisst nicht, dass ein Short gewinnt."""
    engine = _engine(config, "meta", base_rate=0.35, skill=1.0)
    for score in (0.6, -0.6):
        for proba in (0.01, 0.1, 0.35, 0.9, 0.99):
            combined, _ = engine._fuse(_Regel(score), proba, {})
            assert np.sign(combined) == np.sign(score), (
                f"Richtung gekippt bei score={score}, proba={proba}"
            )


def test_meta_modell_auf_basisrate_ist_neutral(config):
    engine = _engine(config, "meta", base_rate=0.35, skill=1.0)
    ohne, _ = engine._fuse(_Regel(0.6), None, {})
    auf_basis, _ = engine._fuse(_Regel(0.6), 0.35, {})
    assert auf_basis == pytest.approx(ohne, abs=1e-9)


def test_meta_modell_verstaerkt_und_daempft_in_die_richtige_richtung(config):
    engine = _engine(config, "meta", base_rate=0.35, skill=1.0)
    neutral, _ = engine._fuse(_Regel(0.6), 0.35, {})
    besser, _ = engine._fuse(_Regel(0.6), 0.60, {})
    schlechter, _ = engine._fuse(_Regel(0.6), 0.15, {})
    assert schlechter < neutral < besser


def test_meta_erwartungswert_ist_bei_passendem_crv_genau_proba(config):
    """Stimmt das CRV mit den Meta-Barrieren ueberein, ist keine Umrechnung noetig."""
    from pax.strategy.signal_engine import _win_probability

    config.labels.tp_atr, config.labels.sl_atr = 2.0, 1.0
    rr_meta = 2.0
    for proba in (0.20, 1 / 3, 0.45, 0.60):
        edge = _logit(proba) - _logit(1.0 / (1.0 + rr_meta))
        assert _win_probability(edge, rr_meta) == pytest.approx(proba, abs=1e-9)


def test_fairer_meta_wert_ergibt_keinen_erwartungswert(config):
    """Ein Meta-Modell auf dem fairen Wert 1/(1+CRV) darf nichts versprechen."""
    from pax.strategy.signal_engine import _win_probability

    rr = 2.0
    p = _win_probability(_logit(1 / 3) - _logit(1 / 3), rr)
    assert p * rr - (1 - p) == pytest.approx(0.0, abs=1e-9)


def test_richtungsmodell_bleibt_beim_alten_verhalten(config):
    """Der andere Pfad darf sich durch das Meta-Labeling nicht veraendert haben."""
    engine = _engine(config, "direction", base_rate=0.5, skill=0.0)
    ohne, _ = engine._fuse(_Regel(0.6), None, {})
    neutral, _ = engine._fuse(_Regel(0.6), 0.5, {})
    assert neutral == pytest.approx(ohne, abs=1e-9)


# --------------------------------------------------------------------------- #
# Kenndaten des Modells
# --------------------------------------------------------------------------- #


def test_profil_hat_vorrang_vor_dem_modellobjekt(config):
    """Der Vorwaertstest uebergibt nur Zahlen - ohne Profil waere das Gewicht null."""
    engine = SignalEngine(config, None, profile=ModelProfile("meta", 0.4, 0.8))
    assert engine.label_kind == "meta"
    assert engine.base_rate == pytest.approx(0.4)
    assert engine.model_skill == pytest.approx(0.8)

    blank = SignalEngine(config, None)
    assert blank.label_kind == "direction"
    assert blank.model_skill == 0.0


def test_guete_aus_auc():
    assert skill_from_auc(0.50) == 0.0
    assert skill_from_auc(0.40) == 0.0, "unter Zufall ist keine Guete"
    assert skill_from_auc(0.75) == 1.0
    assert skill_from_auc(0.90) == 1.0
    assert 0.0 < skill_from_auc(0.55) < 0.5


def test_alte_modelle_gelten_als_richtungsmodelle(config):
    """Ein Modell ohne die Angabe darf nicht als Meta-Modell missdeutet werden."""
    class _Alt:
        report = type("R", (), {"auc": 0.6})()

    assert HorizonModels(medium=_Alt()).label_kind == "direction"
    assert HorizonModels(medium=_Alt()).base_rate == pytest.approx(0.5)
