"""Der Modell-Zoo.

Warum überhaupt mehrere Modelle? Weil jedes eine andere Schwäche hat.
Gradient Boosting findet scharfe Schwellen, aber überanpasst sich gern an
Rauschen. Random Forests sind stabil, aber stumpf an Übergängen. Die logistische
Regression ist langweilig - und genau deshalb bricht sie bei Regimewechseln
nicht so brutal ein wie die Baumverfahren. Ein neuronales Netz findet
Wechselwirkungen, die Bäume nur stufenweise abbilden.

Fehlt eine Bibliothek, fällt genau dieses Mitglied weg und der Rest arbeitet
weiter. Nichts hier ist Pflicht außer scikit-learn.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..utils import get_logger

log = get_logger("zoo")

# Bibliotheken werden weich importiert: nicht installiert = Mitglied entfällt.
try:
    import lightgbm as lgb

    HAS_LGB = True
except Exception:
    HAS_LGB = False

try:
    import xgboost as xgb

    HAS_XGB = True
except Exception:
    HAS_XGB = False

try:
    import catboost as cb

    HAS_CATBOOST = True
except Exception:
    HAS_CATBOOST = False

try:
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        HistGradientBoostingClassifier,
        RandomForestClassifier,
    )
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer

    HAS_SKLEARN = True
except Exception as exc:  # pragma: no cover - scikit-learn ist Pflicht
    HAS_SKLEARN = False
    _SKLEARN_ERROR = exc


def _hist_gb(cfg: Any) -> Any:
    return HistGradientBoostingClassifier(
        max_iter=400,
        learning_rate=0.045,
        max_depth=5,
        min_samples_leaf=40,
        l2_regularization=1.0,
        max_leaf_nodes=31,
        early_stopping=True,
        n_iter_no_change=30,
        validation_fraction=0.12,
        random_state=cfg.random_state,
    )


def _random_forest(cfg: Any) -> Any:
    return RandomForestClassifier(
        n_estimators=400,
        max_depth=9,
        min_samples_leaf=25,
        max_features="sqrt",
        # Ohne Bootstrap-Balancing dominiert bei schiefen Labels die Mehrheitsklasse
        class_weight="balanced_subsample",
        n_jobs=cfg.n_jobs,
        random_state=cfg.random_state,
    )


def _extra_trees(cfg: Any) -> Any:
    return ExtraTreesClassifier(
        n_estimators=400,
        max_depth=11,
        min_samples_leaf=20,
        max_features="sqrt",
        class_weight="balanced_subsample",
        n_jobs=cfg.n_jobs,
        random_state=cfg.random_state + 1,
    )


def _logistic(cfg: Any) -> Any:
    # Skalierung ist hier zwingend - ohne sie dominieren großskalige Merkmale.
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    C=0.35, max_iter=2000, class_weight="balanced", random_state=cfg.random_state
                ),
            ),
        ]
    )


def _mlp(cfg: Any) -> Any:
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            (
                "clf",
                MLPClassifier(
                    hidden_layer_sizes=(96, 32),
                    alpha=3e-3,
                    learning_rate_init=1.2e-3,
                    max_iter=350,
                    early_stopping=True,
                    n_iter_no_change=20,
                    validation_fraction=0.12,
                    random_state=cfg.random_state,
                ),
            ),
        ]
    )


def _lightgbm(cfg: Any) -> Any:
    return lgb.LGBMClassifier(
        n_estimators=600,
        learning_rate=0.035,
        num_leaves=31,
        max_depth=6,
        min_child_samples=40,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.7,
        reg_alpha=0.1,
        reg_lambda=1.0,
        n_jobs=cfg.n_jobs,
        random_state=cfg.random_state,
        verbose=-1,
    )


def _xgboost(cfg: Any) -> Any:
    return xgb.XGBClassifier(
        n_estimators=500,
        learning_rate=0.035,
        max_depth=5,
        min_child_weight=8,
        subsample=0.8,
        colsample_bytree=0.7,
        reg_alpha=0.1,
        reg_lambda=1.5,
        n_jobs=cfg.n_jobs,
        random_state=cfg.random_state,
        eval_metric="logloss",
        tree_method="hist",
    )


def _catboost(cfg: Any) -> Any:
    return cb.CatBoostClassifier(
        iterations=600,
        learning_rate=0.04,
        depth=6,
        l2_leaf_reg=4.0,
        random_seed=cfg.random_state,
        verbose=False,
        allow_writing_files=False,
        thread_count=cfg.n_jobs if cfg.n_jobs > 0 else -1,
    )


MEMBER_FACTORIES: dict[str, tuple[Callable[[Any], Any], Callable[[], bool]]] = {
    "hist_gradient_boosting": (_hist_gb, lambda: HAS_SKLEARN),
    "random_forest": (_random_forest, lambda: HAS_SKLEARN),
    "extra_trees": (_extra_trees, lambda: HAS_SKLEARN),
    "logistic": (_logistic, lambda: HAS_SKLEARN),
    "mlp": (_mlp, lambda: HAS_SKLEARN),
    "lightgbm": (_lightgbm, lambda: HAS_LGB),
    "xgboost": (_xgboost, lambda: HAS_XGB),
    "catboost": (_catboost, lambda: HAS_CATBOOST),
}


def available_members(requested: "list[str] | None" = None) -> list[str]:
    """Welche der gewünschten Mitglieder lassen sich hier tatsächlich bauen?"""
    if not HAS_SKLEARN:  # pragma: no cover
        raise ImportError(
            f"scikit-learn wird zwingend benötigt: {_SKLEARN_ERROR}. "
            "Bitte 'pip install scikit-learn' ausführen."
        )
    names = requested if requested is not None else list(MEMBER_FACTORIES)
    out = []
    for name in names:
        entry = MEMBER_FACTORIES.get(name)
        if entry is None:
            log.warning("Unbekanntes Modell im Ensemble: %s", name)
            continue
        if not entry[1]():
            log.info("Modell '%s' übersprungen - Bibliothek nicht installiert", name)
            continue
        out.append(name)
    if not out:  # pragma: no cover
        raise RuntimeError("Kein einziges Ensemble-Mitglied verfügbar")
    return out


def build_member(name: str, cfg: Any) -> Any:
    """Ein Ensemble-Mitglied erzeugen."""
    entry = MEMBER_FACTORIES.get(name)
    if entry is None:
        raise ValueError(f"Unbekanntes Modell: {name}")
    if not entry[1]():
        raise ImportError(f"Für '{name}' fehlt die Bibliothek")
    return entry[0](cfg)


def supports_sample_weight(name: str) -> bool:
    """Nimmt das Mitglied Stichprobengewichte entgegen?

    Das MLP kann es nicht - dort werden die Gewichte beim Training ignoriert,
    was in den Berichten offen ausgewiesen wird.
    """
    return name != "mlp"


def library_versions() -> dict[str, str]:
    """Für die Modell-Metadaten: womit wurde trainiert?"""
    out: dict[str, str] = {}
    try:
        import sklearn

        out["scikit-learn"] = sklearn.__version__
    except Exception:  # pragma: no cover
        pass
    if HAS_LGB:
        out["lightgbm"] = lgb.__version__
    if HAS_XGB:
        out["xgboost"] = xgb.__version__
    if HAS_CATBOOST:
        out["catboost"] = cb.__version__
    return out
