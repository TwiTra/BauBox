"""Modell-Ensemble: lernt es etwas - und lernt es nur das Richtige?"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pax.config import ModelConfig
from pax.models import ModelEnsemble, ModelRegistry, available_members
from pax.models.zoo import build_member, library_versions, supports_sample_weight


@pytest.fixture(scope="module")
def lernbare_daten():
    """Daten mit einem eingebauten, klar lernbaren Zusammenhang."""
    rng = np.random.default_rng(11)
    n = 1200
    X = pd.DataFrame(rng.normal(size=(n, 12)), columns=[f"f{i}" for i in range(12)])
    signal = 1.4 * X["f0"] - 1.1 * X["f3"] + 0.7 * X["f0"] * X["f3"]
    y = (signal + rng.normal(0, 1.1, n) > 0).astype(float).to_numpy()
    exits = np.minimum(np.arange(n) + 20, n - 1).astype(float)
    return X, y, np.ones(n), exits


@pytest.fixture(scope="module")
def cfg() -> ModelConfig:
    return ModelConfig(
        members=["hist_gradient_boosting", "logistic"], n_splits=3,
        min_train_samples=200, max_features=12, random_state=0,
    )


def test_verfuegbare_mitglieder_werden_gefiltert():
    verfuegbar = available_members(["logistic", "gibtesnicht", "lightgbm"])
    assert "logistic" in verfuegbar
    assert "gibtesnicht" not in verfuegbar
    assert "scikit-learn" in library_versions()


def test_unbekanntes_mitglied_wirft():
    with pytest.raises(ValueError):
        build_member("phantasiemodell", ModelConfig())


def test_mlp_bekommt_keine_gewichte():
    assert not supports_sample_weight("mlp")
    assert supports_sample_weight("logistic")


def test_ensemble_lernt_echten_zusammenhang(lernbare_daten, cfg):
    X, y, w, exits = lernbare_daten
    ensemble = ModelEnsemble(cfg)
    bericht = ensemble.fit(X, y, w, exits)
    assert bericht.auc > 0.7
    assert bericht.n_samples == len(X)
    assert ensemble.fitted
    assert len(ensemble.models) >= 1
    assert "Ensemble trainiert" in bericht.summary()


def test_wichtigste_merkmale_sind_die_eingebauten(lernbare_daten, cfg):
    X, y, w, exits = lernbare_daten
    ensemble = ModelEnsemble(cfg)
    ensemble.fit(X, y, w, exits)
    top = list(ensemble.feature_importance.head(4).index)
    assert "f0" in top and "f3" in top


def test_gemischte_labels_liefern_zufallsniveau(lernbare_daten, cfg):
    """Der entscheidende Gegenprobe-Test: ohne Zusammenhang darf nichts gelernt werden."""
    X, y, w, exits = lernbare_daten
    rng = np.random.default_rng(5)
    ensemble = ModelEnsemble(cfg)
    bericht = ensemble.fit(X, rng.permutation(y), w, exits)
    assert bericht.auc < 0.58, f"AUC {bericht.auc} auf gemischten Labels - das riecht nach Leck"


def test_wahrscheinlichkeiten_sind_begrenzt_und_kalibriert(lernbare_daten, cfg):
    X, y, w, exits = lernbare_daten
    ensemble = ModelEnsemble(cfg)
    ensemble.fit(X, y, w, exits)
    p = ensemble.predict_proba(X)
    assert len(p) == len(X)
    assert (p >= cfg.prob_clip - 1e-9).all() and (p <= 1 - cfg.prob_clip + 1e-9).all()
    # Ein kalibriertes Modell trifft im Mittel die Grundrate
    assert abs(p.mean() - y.mean()) < 0.12


def test_kalibrierungsfehler_wird_ehrlich_gemessen(lernbare_daten, cfg):
    """Ein Kalibrator, der sich selbst bewertet, meldet immer exakt 0."""
    X, y, w, exits = lernbare_daten
    bericht = ModelEnsemble(cfg).fit(X, y, w, exits)
    assert bericht.oof_metrics["calibration_error"] > 0.0
    assert "uncalibrated_auc" in bericht.oof_metrics


def test_uneinigkeit_der_mitglieder(lernbare_daten, cfg):
    X, y, w, exits = lernbare_daten
    ensemble = ModelEnsemble(cfg)
    ensemble.fit(X, y, w, exits)
    d = ensemble.disagreement(X)
    assert len(d) == len(X)
    assert (d >= 0).all()
    assert ensemble.member_probabilities(X).shape[1] == len(ensemble.models)


def test_fehlende_merkmale_werden_gemeldet(lernbare_daten, cfg):
    X, y, w, exits = lernbare_daten
    ensemble = ModelEnsemble(cfg)
    ensemble.fit(X, y, w, exits)
    with pytest.raises(ValueError, match="fehlen"):
        ensemble.predict_proba(X.drop(columns=["f0"]))


def test_zu_wenige_beispiele_werden_abgelehnt(cfg):
    X = pd.DataFrame(np.random.default_rng(0).normal(size=(50, 5)))
    with pytest.raises(ValueError, match="Zu wenige"):
        ModelEnsemble(cfg).fit(X, np.random.default_rng(0).integers(0, 2, 50))


def test_nur_eine_klasse_wird_abgelehnt(lernbare_daten, cfg):
    X, _, w, exits = lernbare_daten
    with pytest.raises(ValueError, match="eine Klasse"):
        ModelEnsemble(cfg).fit(X, np.ones(len(X)), w, exits)


def test_speichern_und_laden_ist_verlustfrei(lernbare_daten, cfg, tmp_path):
    X, y, w, exits = lernbare_daten
    ensemble = ModelEnsemble(cfg)
    ensemble.fit(X, y, w, exits)
    ensemble.save(tmp_path / "m")
    geladen = ModelEnsemble.load(tmp_path / "m")
    assert np.allclose(geladen.predict_proba(X), ensemble.predict_proba(X))
    assert geladen.selected_features == ensemble.selected_features
    assert geladen.report.auc == ensemble.report.auc


def test_registry_verwaltet_champion(lernbare_daten, cfg, tmp_path):
    X, y, w, exits = lernbare_daten
    registry = ModelRegistry(tmp_path / "models", keep=3)
    assert registry.champion("EURUSD") is None

    erstes = ModelEnsemble(cfg, version="v1")
    erstes.fit(X, y, w, exits)
    registry.save(erstes, "EURUSD")
    registry.promote("EURUSD", "v1", "erstes Modell")
    assert registry.champion("EURUSD") == "v1"

    zweites = ModelEnsemble(cfg, version="v2")
    zweites.fit(X, y, w, exits)
    registry.save(zweites, "EURUSD")
    assert registry.champion("EURUSD") == "v1"  # Speichern befördert nicht

    registry.promote("EURUSD", "v2", "besser")
    assert registry.champion("EURUSD") == "v2"
    assert len(registry.history("EURUSD")) == 2
    assert registry.load("EURUSD").version == "v2"
    assert len(registry.catalogue()) == 2


def test_registry_behaelt_champion_beim_aufraeumen(lernbare_daten, cfg, tmp_path):
    X, y, w, exits = lernbare_daten
    registry = ModelRegistry(tmp_path / "models", keep=1)
    for name in ("v1", "v2", "v3"):
        e = ModelEnsemble(cfg, version=name)
        e.fit(X, y, w, exits)
        registry.save(e, "EURUSD")
        if name == "v1":
            registry.promote("EURUSD", "v1", "Champion")
    assert "v1" in registry.versions("EURUSD")
    assert registry.load("EURUSD") is not None
