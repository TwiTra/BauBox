"""Fehleranalyse - der eigentliche Lernmechanismus.

Ein Modell neu zu trainieren ist die einfache Hälfte. Die schwierige ist die
Frage, *wo* das System systematisch danebenliegt: In welchem Regime? In welcher
Handelszeit? Bei welchem Setup? Bei welcher Signalstärke?

Diese Auswertung teilt die Handelshistorie in Scheiben und sucht darin
Bereiche mit dauerhaft negativem Erwartungswert. Wo genug Belege vorliegen,
entsteht daraus eine Sperre - das System hört auf, denselben Fehler zu
wiederholen.

Zwei Schutzmechanismen halten das ehrlich:

* **Mindestanzahl**: Unter einer Mindestzahl von Trades wird nichts gesperrt.
  Fünf Verlusttrades in einer Kategorie sind Zufall, keine Erkenntnis.
* **Ablaufdatum**: Sperren verfallen. Märkte ändern sich, und was drei Monate
  lang nicht funktionierte, kann danach wieder tragen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..config import LearningConfig
from ..types import utcnow
from ..utils import get_logger, read_json, write_json

log = get_logger("feedback")


@dataclass
class PerformanceSlice:
    """Das Abschneiden in einer Teilmenge der Trades."""

    dimension: str
    value: str
    trades: int
    expectancy_r: float
    win_rate: float
    total_r: float
    avg_hold: float = 0.0

    @property
    def is_harmful(self) -> bool:
        return self.expectancy_r < 0 and self.total_r < 0

    def describe(self) -> str:
        return (
            f"{self.dimension}={self.value}: {self.trades} Trades, "
            f"E[R] {self.expectancy_r:+.3f}, Quote {self.win_rate * 100:.0f} %, "
            f"Summe {self.total_r:+.1f} R"
        )


@dataclass
class BlockRule:
    """Eine gelernte Sperre."""

    dimension: str
    value: str
    reason: str
    created_at: str
    expires_at: str
    trades: int
    expectancy_r: float

    def active(self, now: "datetime | None" = None) -> bool:
        now = now or utcnow()
        try:
            return now < datetime.fromisoformat(self.expires_at)
        except (TypeError, ValueError):
            return False


@dataclass
class Blocklist:
    """Alle aktiven Sperren, dauerhaft gespeichert."""

    rules: list[BlockRule] = field(default_factory=list)
    path: "Path | None" = None

    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, path: "str | Path") -> "Blocklist":
        p = Path(path)
        raw = read_json(p, []) or []
        rules = []
        for item in raw:
            try:
                rules.append(BlockRule(**item))
            except TypeError:  # veraltetes Format überspringen
                continue
        return cls(rules=rules, path=p)

    def save(self) -> None:
        if self.path:
            write_json(self.path, [asdict(r) for r in self.rules])

    def active_rules(self, now: "datetime | None" = None) -> list[BlockRule]:
        return [r for r in self.rules if r.active(now)]

    def prune(self) -> int:
        before = len(self.rules)
        self.rules = self.active_rules()
        return before - len(self.rules)

    def add(self, rule: BlockRule) -> bool:
        """Sperre aufnehmen. Bestehende gleiche Sperre wird verlängert."""
        for existing in self.rules:
            if existing.dimension == rule.dimension and existing.value == rule.value:
                existing.expires_at = rule.expires_at
                existing.reason = rule.reason
                existing.trades = rule.trades
                existing.expectancy_r = rule.expectancy_r
                return False
        self.rules.append(rule)
        return True

    def check(self, context: dict[str, Any], now: "datetime | None" = None) -> "str | None":
        """Ist dieser Handelskontext gesperrt? Gibt den Grund zurück."""
        for rule in self.active_rules(now):
            value = context.get(rule.dimension)
            if value is None:
                continue
            if str(value) == rule.value:
                return f"gesperrt ({rule.dimension}={rule.value}): {rule.reason}"
        return None

    def summary(self) -> str:
        active = self.active_rules()
        if not active:
            return "keine aktiven Sperren"
        lines = [f"{len(active)} aktive Sperre(n):"]
        for r in sorted(active, key=lambda x: x.expectancy_r):
            lines.append(
                f"  {r.dimension}={r.value}: E[R] {r.expectancy_r:+.3f} aus {r.trades} Trades, "
                f"bis {r.expires_at[:10]}"
            )
        return "\n".join(lines)


class FeedbackAnalyzer:
    """Zerlegt die Handelshistorie und leitet Sperren ab."""

    #: Nach welchen Merkmalen die Historie zerlegt wird
    DIMENSIONS = ("regime", "horizon", "direction", "exit_reason", "hour_bucket", "score_bucket", "symbol")

    def __init__(self, cfg: LearningConfig) -> None:
        self.cfg = cfg

    # ------------------------------------------------------------------ #

    @staticmethod
    def enrich(trades: pd.DataFrame) -> pd.DataFrame:
        """Zusätzliche Auswertungsspalten anlegen."""
        if trades.empty:
            return trades
        df = trades.copy()
        entry = pd.to_datetime(df["entry_time"], utc=True, format="mixed")
        df["hour_bucket"] = pd.cut(
            entry.dt.hour,
            bins=[-1, 6, 11, 15, 20, 24],
            labels=["asien", "london_vormittag", "ueberschneidung", "newyork", "spaet"],
        ).astype(str)
        df["score_bucket"] = pd.cut(
            df["signal_score"].fillna(0.0),
            bins=[-0.01, 0.5, 0.6, 0.7, 1.01],
            labels=["knapp", "mittel", "gut", "sehr_gut"],
        ).astype(str)
        return df

    def slices(self, trades: pd.DataFrame, min_trades: int = 10) -> list[PerformanceSlice]:
        """Alle Teilmengen auswerten, die genug Trades haben."""
        if trades.empty:
            return []
        df = self.enrich(trades)
        out: list[PerformanceSlice] = []
        for dim in self.DIMENSIONS:
            if dim not in df.columns:
                continue
            for value, group in df.groupby(dim, dropna=True):
                if len(group) < min_trades:
                    continue
                out.append(
                    PerformanceSlice(
                        dimension=dim,
                        value=str(value),
                        trades=len(group),
                        expectancy_r=round(float(group["r_multiple"].mean()), 4),
                        win_rate=round(float((group["profit"] > 0).mean()), 4),
                        total_r=round(float(group["r_multiple"].sum()), 3),
                        avg_hold=round(float(group["bars_held"].mean()), 1) if "bars_held" in group else 0.0,
                    )
                )
        return sorted(out, key=lambda s: s.expectancy_r)

    def update_blocklist(
        self, trades: pd.DataFrame, blocklist: Blocklist, expire_days: int = 60
    ) -> list[BlockRule]:
        """Neue Sperren aus der Historie ableiten."""
        blocklist.prune()
        added: list[BlockRule] = []
        if len(trades) < self.cfg.min_trades_for_feedback:
            log.info(
                "Fehleranalyse übersprungen: %d Trades, mindestens %d nötig",
                len(trades), self.cfg.min_trades_for_feedback,
            )
            return added

        now = utcnow()
        for sl in self.slices(trades, self.cfg.blocklist_min_trades):
            if sl.expectancy_r > self.cfg.blocklist_max_expectancy:
                continue
            # Die Richtung komplett zu sperren wäre zu grob - dann handelt das
            # System nur noch eine Seite und wird von Regimewechseln überrollt.
            if sl.dimension in ("direction", "exit_reason"):
                continue
            rule = BlockRule(
                dimension=sl.dimension,
                value=sl.value,
                reason=(
                    f"E[R] {sl.expectancy_r:+.3f} über {sl.trades} Trades "
                    f"(Summe {sl.total_r:+.1f} R)"
                ),
                created_at=now.isoformat(),
                expires_at=(now + timedelta(days=expire_days)).isoformat(),
                trades=sl.trades,
                expectancy_r=sl.expectancy_r,
            )
            if blocklist.add(rule):
                added.append(rule)
                log.info("Neue Sperre: %s", rule.reason)
        blocklist.save()
        return added

    # ------------------------------------------------------------------ #

    def report(self, trades: pd.DataFrame, top: int = 6) -> str:
        """Textbericht: wo verdient das System, wo verliert es?"""
        if trades.empty:
            return "Keine Trades für eine Auswertung vorhanden."
        slices = self.slices(trades, max(5, self.cfg.blocklist_min_trades // 2))
        if not slices:
            return f"{len(trades)} Trades, aber keine Teilmenge mit genug Fällen für eine Aussage."

        df = self.enrich(trades)
        lines = ["FEHLERANALYSE", "=" * 60]
        lines.append(
            f"  {len(df)} Trades | E[R] {df['r_multiple'].mean():+.3f} | "
            f"Summe {df['r_multiple'].sum():+.1f} R | Quote {(df['profit'] > 0).mean() * 100:.1f} %"
        )
        lines.append("\n  SCHWÄCHSTE BEREICHE")
        for sl in slices[:top]:
            marker = "  !" if sl.is_harmful else "   "
            lines.append(f"  {marker} {sl.describe()}")
        lines.append("\n  STÄRKSTE BEREICHE")
        for sl in sorted(slices, key=lambda s: -s.expectancy_r)[:top]:
            lines.append(f"      {sl.describe()}")

        # Kalibrierungsprüfung: hält das Modell, was es verspricht?
        if "prob_win" in df.columns and df["prob_win"].notna().any():
            lines.append("\n  VERSPROCHEN GEGEN EINGETRETEN")
            bins = pd.cut(df["prob_win"], bins=[0, 0.5, 0.55, 0.6, 0.7, 1.0])
            for interval, group in df.groupby(bins, observed=True):
                if len(group) < 5:
                    continue
                actual = float((group["r_multiple"] > 0).mean())
                promised = float(group["prob_win"].mean())
                flag = "  <-- überschätzt" if promised - actual > 0.1 else ""
                lines.append(
                    f"      {str(interval):<14} {len(group):>4} Trades  "
                    f"versprochen {promised:.2f}  eingetreten {actual:.2f}{flag}"
                )

        mae = df["max_adverse_r"].dropna()
        if len(mae) > 10:
            winners = df[df["profit"] > 0]["max_adverse_r"].dropna()
            if len(winners) > 5:
                lines.append("\n  STOPPLATZIERUNG")
                lines.append(
                    f"      Gewinner liefen im Mittel {winners.mean():.2f} R ins Minus "
                    f"(90 % blieben unter {winners.quantile(0.9):.2f} R)"
                )
                if winners.quantile(0.9) < 0.55:
                    lines.append("      -> Der Stop könnte enger sitzen, das erhöht das CRV.")
        return "\n".join(lines)
