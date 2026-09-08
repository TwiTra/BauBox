"""Weiterentwicklung: Nachtrainieren, prüfen, ablösen.

"Entwickelt sich selbständig weiter" heißt hier nicht, dass sich das System
unkontrolliert verändert. Es heißt: Es trainiert regelmäßig einen Herausforderer,
misst ihn gegen den amtierenden Champion - und übernimmt ihn nur, wenn er
*nachweislich* besser ist.

Der Ablauf:

1. **Auslöser prüfen**: genug neue Trades, genug Zeit vergangen, oder die
   Merkmalsverteilung hat sich verschoben (Drift).
2. **Herausforderer trainieren** auf der aktuellen Historie.
3. **Vorwärtstest** beider Modelle auf denselben Zeitfenstern.
4. **Ablösen nur bei klarem Vorsprung.** Ein Modell, das um 0,3 Prozentpunkte
   AUC besser ist, ist nicht besser - es ist Rauschen.

Ohne Schritt 4 verwandelt sich jede Lernschleife binnen Wochen in einen
Zufallsgenerator, der dem letzten Rauschen hinterherläuft.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from ..config import Config
from ..features.builder import FeatureBuilder, FeatureSet
from ..labeling import direction_labels, sample_weights
from ..models.ensemble import ModelEnsemble
from ..models.registry import ModelRegistry
from ..types import utcnow
from ..utils import get_logger
from ..validation.metrics import classification_metrics, roc_auc
from ..validation.splits import walk_forward_windows

log = get_logger("evolve")


@dataclass
class EvolutionDecision:
    """Was bei einem Entwicklungszyklus herauskam."""

    symbol: str
    trained: bool = False
    promoted: bool = False
    reason: str = ""
    champion_version: str = ""
    challenger_version: str = ""
    champion_score: float = 0.0
    challenger_score: float = 0.0
    improvement: float = 0.0
    walk_forward: dict[str, Any] = field(default_factory=dict)
    drift: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.trained:
            return f"{self.symbol}: kein Training nötig ({self.reason})"
        verdict = "ÜBERNOMMEN" if self.promoted else "verworfen"
        return (
            f"{self.symbol}: Herausforderer {self.challenger_version} {verdict} - "
            f"{self.challenger_score:.4f} gegen Champion {self.champion_score:.4f} "
            f"({self.improvement:+.4f}). {self.reason}"
        )


class Evolver:
    """Steuert Nachtraining und Modellablösung."""

    def __init__(
        self,
        cfg: Config,
        registry: "ModelRegistry | None" = None,
        journal: object = None,
        builder: "FeatureBuilder | None" = None,
    ) -> None:
        self.cfg = cfg
        self.registry = registry or ModelRegistry(cfg.learning.model_dir, cfg.learning.keep_model_versions)
        self.journal = journal
        self.builder = builder or FeatureBuilder(cfg)

    # ------------------------------------------------------------------ #
    # Auslöser
    # ------------------------------------------------------------------ #

    def should_retrain(self, symbol: str, drift: "dict[str, float] | None" = None) -> tuple[bool, str]:
        """Ist ein Nachtraining fällig?"""
        lc = self.cfg.learning
        if self.registry.champion(symbol) is None:
            return True, "noch kein Modell vorhanden"

        if drift:
            worst = max(drift.values()) if drift else 0.0
            if worst >= lc.drift_psi_threshold:
                worst_feature = max(drift, key=drift.get)
                return True, f"Verteilungsdrift erkannt (PSI {worst:.2f} bei '{worst_feature}')"

        if self.journal is None:
            return False, "kein Journal - Auslöser nicht prüfbar"

        last = self.journal.last_training(symbol)  # type: ignore[attr-defined]
        if last is None:
            return True, "kein Trainingslauf verzeichnet"
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)

        hours = (utcnow() - last).total_seconds() / 3600.0
        new_trades = self.journal.count_trades(symbol, since=last, source="live")  # type: ignore[attr-defined]
        if new_trades >= lc.retrain_every_trades:
            return True, f"{new_trades} neue Trades seit dem letzten Training"
        if hours >= lc.retrain_every_hours:
            return True, f"letztes Training vor {hours:.0f} Stunden"
        return False, (
            f"erst {new_trades} neue Trades und {hours:.0f} Stunden seit dem letzten Training"
        )

    # ------------------------------------------------------------------ #
    # Zyklus
    # ------------------------------------------------------------------ #

    def prepare(self, frames: dict[str, pd.DataFrame], symbol: str) -> tuple[FeatureSet, pd.DataFrame]:
        """Merkmale und Zielvariable aufbereiten."""
        fs = self.builder.build(frames, symbol=symbol)
        lb = self.cfg.labels
        y, usable, res = direction_labels(
            fs.base, fs.atr, lb.direction_atr, lb.max_horizon_bars, lb.min_return_atr
        )
        w = sample_weights(res, lb.sample_weight_decay, lb.apply_uniqueness_weights)
        mask = usable.to_numpy(dtype=bool)

        # Die Ausstiegsindizes beziehen sich auf den ungefilterten Rahmen und
        # müssen für das Purging auf die gefilterten Positionen umgerechnet werden.
        original = np.arange(len(fs.frame))[mask]
        exits = np.searchsorted(original, res.exit_index[mask].to_numpy(), side="left").astype(float)

        data = pd.DataFrame(
            {"y": y[mask].to_numpy(), "w": w[mask].to_numpy(), "exit": exits},
            index=fs.frame.index[mask],
        )
        return fs, data

    def train_challenger(
        self, frames: dict[str, pd.DataFrame], symbol: str
    ) -> tuple[ModelEnsemble, FeatureSet, pd.DataFrame]:
        """Ein neues Modell auf der aktuellen Historie anlernen."""
        fs, data = self.prepare(frames, symbol)
        X = fs.frame.loc[data.index]
        ensemble = ModelEnsemble(self.cfg.model)
        ensemble.fit(X, data["y"], data["w"], data["exit"])
        return ensemble, fs, data

    def evolve(
        self, frames: dict[str, pd.DataFrame], symbol: str, force: bool = False
    ) -> EvolutionDecision:
        """Vollständiger Entwicklungszyklus für ein Symbol."""
        decision = EvolutionDecision(symbol=symbol)
        champion_version = self.registry.champion(symbol) or ""
        decision.champion_version = champion_version

        # --- Drift messen und Training entscheiden --------------------- #
        champion = self.registry.load(symbol) if champion_version else None
        drift: dict[str, float] = {}
        if champion is not None:
            try:
                fs_probe = self.builder.build(frames, symbol=symbol)
                drift = self.measure_drift(fs_probe.frame, champion)
                decision.drift = {k: round(v, 3) for k, v in sorted(
                    drift.items(), key=lambda kv: -kv[1])[:8]}
            except Exception as exc:
                decision.warnings.append(f"Drift nicht messbar: {exc}")

        needed, reason = (True, "erzwungen") if force else self.should_retrain(symbol, drift)
        if not needed:
            decision.reason = reason
            return decision

        # --- Herausforderer trainieren --------------------------------- #
        try:
            challenger, fs, data = self.train_challenger(frames, symbol)
        except Exception as exc:
            decision.reason = f"Training fehlgeschlagen: {exc}"
            decision.warnings.append(str(exc))
            log.error("Training für %s fehlgeschlagen: %s", symbol, exc)
            return decision

        decision.trained = True
        decision.challenger_version = challenger.version
        decision.challenger_score = challenger.report.auc
        self.registry.save(challenger, symbol, {"trigger": reason})

        # --- Vergleich ------------------------------------------------- #
        if champion is None:
            self.registry.promote(symbol, challenger.version, "erstes Modell",
                                  {"auc": challenger.report.auc})
            decision.promoted = True
            decision.reason = f"{reason}; erstes Modell übernommen"
            self._log_training(symbol, challenger, True, decision.reason)
            return decision

        X = fs.frame.loc[data.index]
        comparison = self.compare(champion, challenger, X, data)
        decision.walk_forward = comparison
        decision.champion_score = comparison["champion_auc"]
        decision.challenger_score = comparison["challenger_auc"]
        decision.improvement = round(comparison["challenger_auc"] - comparison["champion_auc"], 4)

        promoted, verdict = self._decide(comparison, len(data))
        decision.promoted = promoted
        decision.reason = f"{reason}; {verdict}"
        if promoted:
            self.registry.promote(symbol, challenger.version, verdict, comparison)
        self._log_training(symbol, challenger, promoted, decision.reason, comparison)
        log.info(decision.summary())
        return decision

    # ------------------------------------------------------------------ #

    def compare(
        self, champion: ModelEnsemble, challenger: ModelEnsemble, X: pd.DataFrame, data: pd.DataFrame
    ) -> dict[str, Any]:
        """Beide Modelle auf denselben Vorwärtsfenstern messen.

        Der Champion wird dabei *nicht* neu trainiert - genau das ist der Punkt:
        Er muss zeigen, dass sein altes Wissen noch trägt.
        """
        lc = self.cfg.learning
        y = data["y"].to_numpy()
        w = data["w"].to_numpy()
        try:
            windows = walk_forward_windows(
                len(X), lc.walk_forward_folds, 0.6, True, self.cfg.model.embargo_frac, data["exit"]
            )
        except ValueError as exc:
            return {"error": str(exc), "champion_auc": 0.5, "challenger_auc": 0.5, "folds": 0}

        champ_scores, chall_scores, folds = [], [], 0
        for _, test_idx in windows:
            if len(test_idx) < 30 or len(np.unique(y[test_idx])) < 2:
                continue
            X_test = X.iloc[test_idx]
            try:
                p_champ = champion.predict_proba(X_test)
                p_chall = challenger.predict_proba(X_test)
            except Exception as exc:
                log.warning("Vergleichsfenster übersprungen: %s", exc)
                continue
            champ_scores.append(roc_auc(y[test_idx], p_champ, w[test_idx]))
            chall_scores.append(roc_auc(y[test_idx], p_chall, w[test_idx]))
            folds += 1

        if folds == 0:
            return {"error": "kein auswertbares Fenster", "champion_auc": 0.5,
                    "challenger_auc": 0.5, "folds": 0}

        champ_auc = float(np.mean(champ_scores))
        chall_auc = float(np.mean(chall_scores))
        # Der Vorsprung muss auch in den einzelnen Fenstern sichtbar sein, nicht
        # nur im Mittel - sonst stammt er aus einem einzigen Glücksabschnitt.
        wins = int(sum(1 for a, b in zip(chall_scores, champ_scores) if b > a))
        return {
            "champion_auc": round(champ_auc, 4),
            "challenger_auc": round(chall_auc, 4),
            "folds": folds,
            "challenger_wins": wins,
            "win_ratio": round(wins / folds, 3),
            "champion_per_fold": [round(s, 4) for s in champ_scores],
            "challenger_per_fold": [round(s, 4) for s in chall_scores],
            "samples": len(X),
        }

    def _decide(self, comparison: dict[str, Any], n_samples: int) -> tuple[bool, str]:
        """Die Ablösungsregel - bewusst streng."""
        lc = self.cfg.learning
        if comparison.get("error"):
            return False, f"Vergleich nicht möglich ({comparison['error']}) - Champion bleibt"
        if n_samples < lc.challenger_min_trades:
            return False, f"zu wenige Beispiele ({n_samples} < {lc.challenger_min_trades})"

        improvement = comparison["challenger_auc"] - comparison["champion_auc"]
        if improvement < lc.challenger_min_improvement:
            return False, (
                f"Vorsprung {improvement:+.4f} unter der Mindestverbesserung "
                f"{lc.challenger_min_improvement} - Champion bleibt"
            )
        if comparison.get("win_ratio", 0) < 0.6:
            return False, (
                f"nur in {comparison.get('challenger_wins', 0)} von {comparison['folds']} "
                "Fenstern besser - zu unbeständig"
            )
        if comparison["challenger_auc"] < 0.5:
            return False, "Herausforderer liegt unter Zufallsniveau"
        return True, (
            f"in {comparison['challenger_wins']}/{comparison['folds']} Fenstern besser, "
            f"Vorsprung {improvement:+.4f}"
        )

    def _log_training(
        self, symbol: str, ensemble: ModelEnsemble, promoted: bool, reason: str,
        metrics: "dict | None" = None,
    ) -> None:
        if self.journal is None:
            return
        try:
            self.journal.record_training(  # type: ignore[attr-defined]
                symbol, ensemble.version, ensemble.report.auc, ensemble.report.n_samples,
                ensemble.report.n_features, promoted, reason, metrics or {},
            )
        except Exception as exc:  # pragma: no cover
            log.warning("Trainingslauf konnte nicht protokolliert werden: %s", exc)

    # ------------------------------------------------------------------ #
    # Drift
    # ------------------------------------------------------------------ #

    def measure_drift(
        self, current: pd.DataFrame, model: ModelEnsemble, reference_frac: float = 0.5
    ) -> dict[str, float]:
        """Verschiebt sich die Merkmalsverteilung gegenüber früher?

        Verglichen werden die ältere und die jüngere Hälfte der vorliegenden
        Daten. Ein hoher PSI heißt: Der Markt sieht heute anders aus als in dem
        Zeitraum, aus dem das Modell sein Wissen hat.
        """
        features = [f for f in model.selected_features if f in current.columns]
        if not features or len(current) < 400:
            return {}
        split = int(len(current) * reference_frac)
        reference, recent = current.iloc[:split], current.iloc[split:]
        out: dict[str, float] = {}
        for name in features[:60]:  # die wichtigsten reichen, das spart Zeit
            try:
                out[name] = population_stability_index(
                    reference[name].to_numpy(), recent[name].to_numpy()
                )
            except Exception:  # pragma: no cover
                continue
        return out


# --------------------------------------------------------------------------- #


def population_stability_index(
    expected: np.ndarray, actual: np.ndarray, bins: int = 10
) -> float:
    """Population Stability Index zwischen zwei Verteilungen.

    Als Faustregel gilt: unter 0,1 stabil, 0,1 bis 0,25 auffällig, darüber ist
    die Verteilung deutlich verschoben und das Modell arbeitet außerhalb
    dessen, was es gesehen hat.
    """
    expected = np.asarray(expected, dtype=float)
    actual = np.asarray(actual, dtype=float)
    expected = expected[np.isfinite(expected)]
    actual = actual[np.isfinite(actual)]
    if len(expected) < 20 or len(actual) < 20:
        return 0.0

    quantiles = np.linspace(0, 100, bins + 1)
    edges = np.unique(np.percentile(expected, quantiles))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf

    exp_counts, _ = np.histogram(expected, bins=edges)
    act_counts, _ = np.histogram(actual, bins=edges)
    # Kleine Untergrenze, damit leere Klassen den Logarithmus nicht sprengen
    exp_share = np.maximum(exp_counts / max(len(expected), 1), 1e-4)
    act_share = np.maximum(act_counts / max(len(actual), 1), 1e-4)
    return float(np.sum((act_share - exp_share) * np.log(act_share / exp_share)))
