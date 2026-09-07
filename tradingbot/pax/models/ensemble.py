"""Das Ensemble - mehrere Modelle, eine kalibrierte Wahrscheinlichkeit.

Der Ablauf ist bewusst konservativ:

1. **Merkmalsauswahl**: konstante und stark redundante Spalten fliegen raus,
   der Rest wird nach Wichtigkeit gekürzt. Weniger Merkmale, weniger Zufall.
2. **Out-of-Fold-Vorhersagen** für jedes Mitglied über gesperrte Faltungen.
   Nur diese Vorhersagen sind ehrlich - alles andere hat die Antwort gesehen.
3. **Auswahl**: Mitglieder unter der Mindest-AUC fliegen aus dem Ensemble. Ein
   schlechtes Modell verwässert ein gutes.
4. **Verschmelzung** per Stapelung, Gewichtung oder Mittelwert.
5. **Kalibrierung**: aus einem Score wird eine Wahrscheinlichkeit, auf die man
   Positionsgrößen stützen kann.
6. **Neutraining** aller Mitglieder auf allen Daten.

Punkt 5 wird meist übersehen und ist für den Handel der wichtigste: die
Positionsgröße hängt direkt an der Wahrscheinlichkeit. Ein unkalibriertes
Modell, das bei jedem zweiten Setup "80 %" sagt, ruiniert das Konto durch zu
große Positionen, selbst wenn seine Rangfolge stimmt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..config import ModelConfig
from ..utils import get_logger, read_json, write_json
from ..validation.metrics import classification_metrics, roc_auc
from ..validation.splits import PurgedKFold
from .zoo import available_members, build_member, library_versions, supports_sample_weight

log = get_logger("ensemble")

try:
    import joblib
except ImportError:  # pragma: no cover
    joblib = None  # type: ignore[assignment]

from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


@dataclass
class FitReport:
    """Was beim Training herauskam - Grundlage jeder Champion-Entscheidung."""

    n_samples: int = 0
    n_features: int = 0
    members: dict[str, dict[str, Any]] = field(default_factory=dict)
    dropped_members: dict[str, str] = field(default_factory=dict)
    blend: str = "stacking"
    weights: dict[str, float] = field(default_factory=dict)
    oof_metrics: dict[str, float] = field(default_factory=dict)
    selected_features: list[str] = field(default_factory=list)
    calibration: str = "isotonic"
    trained_at: str = ""
    duration_s: float = 0.0
    libraries: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def auc(self) -> float:
        return float(self.oof_metrics.get("auc", 0.5))

    def summary(self) -> str:
        best = sorted(self.members.items(), key=lambda kv: -kv[1].get("auc", 0))[:3]
        lines = [
            f"Ensemble trainiert: {self.n_samples} Beispiele, {self.n_features} Merkmale, "
            f"{len(self.members)} Mitglieder ({self.blend})",
            f"  Out-of-Fold: AUC {self.auc:.4f} | Trefferquote {self.oof_metrics.get('accuracy', 0):.4f} "
            f"| Brier {self.oof_metrics.get('brier', 0):.4f} "
            f"| Kalibrierungsfehler {self.oof_metrics.get('calibration_error', 0):.4f}",
            "  Beste Mitglieder: " + ", ".join(f"{n} ({m['auc']:.3f})" for n, m in best),
        ]
        if self.dropped_members:
            lines.append("  Aussortiert: " + ", ".join(f"{k} ({v})" for k, v in self.dropped_members.items()))
        for w in self.warnings:
            lines.append(f"  Hinweis: {w}")
        return "\n".join(lines)


class ModelEnsemble:
    """Trainiert und kombiniert mehrere Klassifikatoren zu einer Wahrscheinlichkeit."""

    def __init__(self, cfg: "ModelConfig | None" = None, version: str = "") -> None:
        self.cfg = cfg or ModelConfig()
        self.version = version or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.models: dict[str, Any] = {}
        self.weights: dict[str, float] = {}
        self.meta_model: Any = None
        self.calibrator: Any = None
        self.selected_features: list[str] = []
        self.report = FitReport()
        self._importance: pd.Series = pd.Series(dtype=float)
        self._fitted = False

    # ------------------------------------------------------------------ #
    # Training
    # ------------------------------------------------------------------ #

    def fit(
        self,
        X: pd.DataFrame,
        y: "pd.Series | np.ndarray",
        sample_weight: "pd.Series | np.ndarray | None" = None,
        exit_index: "pd.Series | np.ndarray | None" = None,
    ) -> FitReport:
        """Ensemble anlernen. `exit_index` steuert das Purging der Faltungen."""
        start = time.perf_counter()
        cfg = self.cfg
        X = pd.DataFrame(X).replace([np.inf, -np.inf], np.nan)
        y = np.asarray(pd.Series(y).astype(float)).ravel()
        w = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, dtype=float).ravel()

        if len(X) != len(y):
            raise ValueError(f"X und y passen nicht zusammen: {len(X)} vs {len(y)}")
        if len(X) < cfg.min_train_samples:
            raise ValueError(
                f"Zu wenige Trainingsbeispiele: {len(X)} < {cfg.min_train_samples}. "
                "Mehr Historie laden oder min_train_samples senken."
            )
        classes = np.unique(y)
        if len(classes) < 2:
            raise ValueError("Die Zielvariable hat nur eine Klasse - so lässt sich nichts lernen")

        report = FitReport(
            n_samples=len(X), blend=cfg.blend, calibration=cfg.calibration,
            trained_at=datetime.now(timezone.utc).isoformat(), libraries=library_versions(),
        )
        balance = float(min(y.mean(), 1 - y.mean()))
        if balance < 0.25:
            report.warnings.append(f"Schiefe Klassenverteilung ({y.mean():.2f} positiv)")

        # --- 1) Merkmalsauswahl -------------------------------------- #
        self.selected_features = self._select_features(X, y, w)
        Xs = X[self.selected_features]
        report.n_features = len(self.selected_features)
        report.selected_features = list(self.selected_features)

        # --- 2) Out-of-Fold-Vorhersagen ------------------------------ #
        member_names = available_members(cfg.members)
        cv = PurgedKFold(cfg.n_splits, exit_index, cfg.embargo_frac)
        folds = list(cv.split(Xs))
        if not folds:
            raise RuntimeError("Kreuzvalidierung ergab keine nutzbare Faltung")

        oof = {}
        for name in member_names:
            try:
                preds = self._oof_predict(name, Xs, y, w, folds)
            except Exception as exc:
                log.warning("Mitglied '%s' konnte nicht trainiert werden: %s", name, exc)
                report.dropped_members[name] = f"Trainingsfehler: {type(exc).__name__}"
                continue
            covered = np.isfinite(preds)
            if covered.sum() < 50:
                report.dropped_members[name] = "zu wenige Out-of-Fold-Vorhersagen"
                continue
            auc = roc_auc(y[covered], preds[covered], w[covered])
            oof[name] = preds
            report.members[name] = {
                "auc": round(float(auc), 4),
                "coverage": round(float(covered.mean()), 3),
                "uses_weights": supports_sample_weight(name),
            }
            log.info("  %-24s OOF-AUC %.4f", name, auc)

        # --- 3) Schwache Mitglieder aussortieren --------------------- #
        keep = [n for n in oof if report.members[n]["auc"] >= cfg.min_member_auc]
        if not keep:
            # Lieber das beste vorhandene behalten als gar nichts - der Aufrufer
            # sieht an der Warnung, dass hier kein Vorteil messbar war.
            best = max(oof, key=lambda n: report.members[n]["auc"], default=None)
            if best is None:
                raise RuntimeError("Kein einziges Mitglied ließ sich trainieren")
            keep = [best]
            report.warnings.append(
                f"Kein Mitglied erreichte AUC >= {cfg.min_member_auc}; "
                f"nur '{best}' ({report.members[best]['auc']:.3f}) behalten. "
                "Das Modell hat auf diesen Daten keinen nachweisbaren Vorteil."
            )
        for name in list(oof):
            if name not in keep:
                report.dropped_members[name] = f"AUC {report.members[name]['auc']:.3f} unter Schwelle"
                report.members.pop(name, None)

        oof_matrix = np.column_stack([oof[n] for n in keep])
        valid = np.isfinite(oof_matrix).all(axis=1)
        if valid.sum() < 50:
            raise RuntimeError("Zu wenige vollständige Out-of-Fold-Zeilen für die Verschmelzung")

        # --- 4) Verschmelzung ---------------------------------------- #
        blended = self._fit_blender(oof_matrix[valid], y[valid], w[valid], keep, report)

        # --- 5) Kalibrierung ----------------------------------------- #
        # Erst eine ehrliche Bewertung: ein Kalibrator, der auf denselben Daten
        # geprüft wird, auf die er angepasst wurde, meldet immer Fehler 0.
        honest = self._honest_calibrated(blended, y[valid], w[valid])
        self.calibrator = self._fit_calibrator(blended, y[valid], w[valid])
        report.oof_metrics = classification_metrics(y[valid], honest, w[valid])
        report.oof_metrics["uncalibrated_auc"] = round(
            float(roc_auc(y[valid], blended, w[valid])), 4
        )

        # --- 6) Neutraining auf allen Daten -------------------------- #
        self.models = {}
        for name in keep:
            model = build_member(name, cfg)
            self._fit_member(model, name, Xs, y, w)
            self.models[name] = model

        self._importance = self._collect_importance(Xs.columns)
        report.duration_s = round(time.perf_counter() - start, 2)
        self.report = report
        self._fitted = True
        log.info(report.summary())
        return report

    # ------------------------------------------------------------------ #

    def _select_features(self, X: pd.DataFrame, y: np.ndarray, w: np.ndarray) -> list[str]:
        """Konstante und redundante Spalten entfernen, dann nach Wichtigkeit kürzen."""
        numeric = X.select_dtypes(include=[np.number])
        # Praktisch konstante Spalten tragen nichts bei und stören die Skalierung
        std = numeric.std(ddof=0)
        cols = [c for c in numeric.columns if np.isfinite(std[c]) and std[c] > 1e-10]
        if not cols:
            raise ValueError("Alle Merkmale sind konstant - da ist etwas grundlegend schiefgelaufen")

        # Stark korrelierte Paare ausdünnen: das zweite Merkmal bringt fast nichts
        sub = numeric[cols]
        if len(cols) > 2:
            corr = sub.corr().abs().to_numpy(copy=True)
            np.fill_diagonal(corr, 0.0)
            drop: set[int] = set()
            for i in range(len(cols)):
                if i in drop:
                    continue
                for j in range(i + 1, len(cols)):
                    if j not in drop and np.isfinite(corr[i, j]) and corr[i, j] > 0.97:
                        drop.add(j)
            cols = [c for k, c in enumerate(cols) if k not in drop]

        if not self.cfg.feature_selection or len(cols) <= self.cfg.max_features:
            return cols

        try:
            from sklearn.ensemble import ExtraTreesClassifier

            probe = ExtraTreesClassifier(
                n_estimators=180, max_depth=9, min_samples_leaf=25,
                n_jobs=self.cfg.n_jobs, random_state=self.cfg.random_state,
            )
            probe.fit(X[cols].fillna(0.0), y, sample_weight=w)
            imp = pd.Series(probe.feature_importances_, index=cols).sort_values(ascending=False)
            return list(imp.head(self.cfg.max_features).index)
        except Exception as exc:  # pragma: no cover
            log.warning("Merkmalsauswahl fehlgeschlagen (%s) - alle Spalten werden verwendet", exc)
            return cols

    def _fit_member(self, model: Any, name: str, X: pd.DataFrame, y: np.ndarray, w: np.ndarray) -> None:
        data = X.fillna(0.0) if not _handles_nan(name) else X
        if supports_sample_weight(name):
            # Pipelines nehmen Gewichte nur mit Schritt-Präfix entgegen und melden
            # das je nach scikit-learn-Version als TypeError oder ValueError.
            attempts = (
                {"clf__sample_weight": w} if hasattr(model, "named_steps") else {"sample_weight": w},
                {"sample_weight": w},
            )
            for kwargs in attempts:
                try:
                    model.fit(data, y, **kwargs)
                    return
                except (TypeError, ValueError) as exc:
                    if "sample_weight" not in str(exc):
                        raise  # echter Datenfehler, nicht die Signatur
        model.fit(data, y)

    def _oof_predict(
        self, name: str, X: pd.DataFrame, y: np.ndarray, w: np.ndarray,
        folds: list[tuple[np.ndarray, np.ndarray]],
    ) -> np.ndarray:
        """Vorhersagen, die das jeweilige Modell nie im Training gesehen hat."""
        out = np.full(len(X), np.nan)
        for train_idx, test_idx in folds:
            if len(np.unique(y[train_idx])) < 2:
                continue
            model = build_member(name, self.cfg)
            self._fit_member(model, name, X.iloc[train_idx], y[train_idx], w[train_idx])
            data = X.iloc[test_idx]
            out[test_idx] = model.predict_proba(data.fillna(0.0) if not _handles_nan(name) else data)[:, 1]
        return out

    def _fit_blender(
        self, matrix: np.ndarray, y: np.ndarray, w: np.ndarray, names: list[str], report: FitReport
    ) -> np.ndarray:
        """Mitgliedsvorhersagen zu einem Score verschmelzen."""
        blend = self.cfg.blend
        if blend == "stacking" and matrix.shape[1] > 1:
            # Auf Logits stapeln: dort ist der Zusammenhang linear und die
            # Regression braucht weniger Daten, um ihn zu finden.
            self.meta_model = LogisticRegression(C=1.0, max_iter=1000, random_state=self.cfg.random_state)
            self.meta_model.fit(_logit(matrix), y, sample_weight=w)
            coefs = dict(zip(names, np.round(self.meta_model.coef_[0], 4).tolist()))
            report.weights = {k: float(v) for k, v in coefs.items()}
            self.weights = {n: 1.0 for n in names}
            return self.meta_model.predict_proba(_logit(matrix))[:, 1]

        if blend == "weighted" and matrix.shape[1] > 1:
            aucs = np.array([max(0.0, report.members[n]["auc"] - 0.5) for n in names])
            weights = aucs / aucs.sum() if aucs.sum() > 0 else np.ones(len(names)) / len(names)
            self.weights = dict(zip(names, weights.tolist()))
            report.weights = {k: round(float(v), 4) for k, v in self.weights.items()}
            self.meta_model = None
            return matrix @ weights

        self.weights = {n: 1.0 / len(names) for n in names}
        report.weights = {k: round(float(v), 4) for k, v in self.weights.items()}
        self.meta_model = None
        report.blend = "mean"
        return matrix.mean(axis=1)

    def _fit_calibrator(self, scores: np.ndarray, y: np.ndarray, w: np.ndarray) -> Any:
        mode = self.cfg.calibration
        if mode == "none":
            return None
        try:
            if mode == "isotonic":
                cal = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
                cal.fit(scores, y, sample_weight=w)
                return cal
            cal = LogisticRegression(max_iter=1000)
            cal.fit(scores.reshape(-1, 1), y, sample_weight=w)
            return cal
        except Exception as exc:  # pragma: no cover
            log.warning("Kalibrierung fehlgeschlagen (%s) - Rohwerte werden verwendet", exc)
            return None

    def _honest_calibrated(self, scores: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
        """Kalibrierte Werte, bei denen jeder Punkt von einem fremden Kalibrator stammt.

        Nur so ist der ausgewiesene Kalibrierungsfehler belastbar. Der später
        produktiv genutzte Kalibrator wird anschließend auf allen Daten
        angepasst - das ist zulässig, darf aber nicht sich selbst bewerten.
        """
        if self.cfg.calibration == "none" or len(scores) < 200:
            return np.clip(scores, self.cfg.prob_clip, 1 - self.cfg.prob_clip)
        out = np.empty_like(scores)
        blocks = np.array_split(np.arange(len(scores)), 4)
        for block in blocks:
            mask = np.ones(len(scores), dtype=bool)
            mask[block] = False
            if len(np.unique(y[mask])) < 2:
                out[block] = scores[block]
                continue
            cal = self._fit_calibrator(scores[mask], y[mask], w[mask])
            keeper, self.calibrator = self.calibrator, cal
            out[block] = self._apply_calibration(scores[block])
            self.calibrator = keeper
        return out

    def _apply_calibration(self, scores: np.ndarray) -> np.ndarray:
        if self.calibrator is None:
            out = scores
        elif isinstance(self.calibrator, IsotonicRegression):
            out = self.calibrator.predict(scores)
        else:
            out = self.calibrator.predict_proba(np.asarray(scores).reshape(-1, 1))[:, 1]
        clip = self.cfg.prob_clip
        return np.clip(out, clip, 1.0 - clip)

    def _collect_importance(self, columns: pd.Index) -> pd.Series:
        """Wichtigkeiten über alle Mitglieder mitteln, die welche liefern."""
        frames = []
        for name, model in self.models.items():
            est = model.named_steps["clf"] if hasattr(model, "named_steps") else model
            imp = getattr(est, "feature_importances_", None)
            if imp is None:
                coef = getattr(est, "coef_", None)
                imp = np.abs(coef[0]) if coef is not None else None
            if imp is None or len(imp) != len(columns):
                continue
            s = pd.Series(imp, index=columns, dtype=float)
            total = s.sum()
            if total > 0:
                frames.append(s / total)
        if not frames:
            return pd.Series(dtype=float)
        return pd.concat(frames, axis=1).mean(axis=1).sort_values(ascending=False)

    # ------------------------------------------------------------------ #
    # Vorhersage
    # ------------------------------------------------------------------ #

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Kalibrierte Wahrscheinlichkeit für die positive Klasse."""
        if not self._fitted:
            raise RuntimeError("Das Ensemble wurde noch nicht trainiert")
        Xs = self._prepare(X)
        names = list(self.models)
        matrix = np.column_stack(
            [
                self.models[n].predict_proba(Xs.fillna(0.0) if not _handles_nan(n) else Xs)[:, 1]
                for n in names
            ]
        )
        if self.meta_model is not None and matrix.shape[1] > 1:
            scores = self.meta_model.predict_proba(_logit(matrix))[:, 1]
        else:
            weights = np.array([self.weights.get(n, 1.0 / len(names)) for n in names])
            weights = weights / weights.sum() if weights.sum() > 0 else np.ones(len(names)) / len(names)
            scores = matrix @ weights
        return self._apply_calibration(scores)

    def predict(self, X: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        return (self.predict_proba(X) >= threshold).astype(int)

    def member_probabilities(self, X: pd.DataFrame) -> pd.DataFrame:
        """Einzelmeinungen der Mitglieder - zeigt, wie einig sich das Ensemble ist."""
        Xs = self._prepare(X)
        return pd.DataFrame(
            {
                n: m.predict_proba(Xs.fillna(0.0) if not _handles_nan(n) else Xs)[:, 1]
                for n, m in self.models.items()
            },
            index=X.index,
        )

    def disagreement(self, X: pd.DataFrame) -> np.ndarray:
        """Streuung der Mitgliedsmeinungen - hohe Werte mahnen zur Vorsicht."""
        probs = self.member_probabilities(X)
        return probs.std(axis=1).to_numpy() if probs.shape[1] > 1 else np.zeros(len(X))

    def _prepare(self, X: pd.DataFrame) -> pd.DataFrame:
        X = pd.DataFrame(X).replace([np.inf, -np.inf], np.nan)
        missing = [c for c in self.selected_features if c not in X.columns]
        if missing:
            raise ValueError(
                f"{len(missing)} Merkmale fehlen in den Eingabedaten, z. B.: {missing[:5]}"
            )
        return X[self.selected_features]

    @property
    def feature_importance(self) -> pd.Series:
        return self._importance

    @property
    def fitted(self) -> bool:
        return self._fitted

    # ------------------------------------------------------------------ #
    # Speichern und Laden
    # ------------------------------------------------------------------ #

    def save(self, directory: "str | Path") -> Path:
        if joblib is None:  # pragma: no cover
            raise RuntimeError("joblib fehlt - bitte 'pip install joblib' ausführen")
        if not self._fitted:
            raise RuntimeError("Ein untrainiertes Ensemble lässt sich nicht speichern")
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "models": self.models,
                "meta_model": self.meta_model,
                "calibrator": self.calibrator,
                "weights": self.weights,
                "selected_features": self.selected_features,
                "importance": self._importance,
                "cfg": asdict(self.cfg),
            },
            path / "ensemble.joblib",
            compress=3,
        )
        write_json(path / "report.json", asdict(self.report))
        write_json(
            path / "meta.json",
            {"version": self.version, "features": len(self.selected_features),
             "members": list(self.models), "auc": self.report.auc},
        )
        return path

    @classmethod
    def load(cls, directory: "str | Path") -> "ModelEnsemble":
        if joblib is None:  # pragma: no cover
            raise RuntimeError("joblib fehlt - bitte 'pip install joblib' ausführen")
        path = Path(directory)
        blob = joblib.load(path / "ensemble.joblib")
        cfg = ModelConfig(**blob.get("cfg", {}))
        meta = read_json(path / "meta.json", {}) or {}
        obj = cls(cfg, version=meta.get("version", path.name))
        obj.models = blob["models"]
        obj.meta_model = blob["meta_model"]
        obj.calibrator = blob["calibrator"]
        obj.weights = blob["weights"]
        obj.selected_features = blob["selected_features"]
        obj._importance = blob.get("importance", pd.Series(dtype=float))
        raw_report = read_json(path / "report.json", {}) or {}
        obj.report = FitReport(**{k: v for k, v in raw_report.items() if k in FitReport.__annotations__})
        obj._fitted = True
        return obj


# --------------------------------------------------------------------------- #


def _logit(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    p = np.clip(p, eps, 1 - eps)
    return np.log(p / (1 - p))


def _handles_nan(name: str) -> bool:
    """Welche Verfahren kommen mit fehlenden Werten selbst zurecht?"""
    return name in {"hist_gradient_boosting", "lightgbm", "xgboost", "catboost"}
