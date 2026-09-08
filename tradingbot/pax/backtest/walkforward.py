"""Vorwärts-Backtest - die einzige Auswertung, der man glauben darf.

Der gewöhnliche Backtest hat einen stillen Fehler: Er lässt den Champion über
die gesamte Historie laufen, obwohl der genau auf dieser Historie trainiert
wurde. Das Modell kennt die Antworten. Das Ergebnis sieht gut aus und bedeutet
nichts.

Hier läuft es so, wie es im Betrieb tatsächlich abliefe:

1. Die Historie wird in aufeinanderfolgende Fenster geteilt.
2. Für jedes Fenster entsteht ein *eigenes* Modell, trainiert ausschließlich auf
   Daten, die vor dem Fenster liegen - mit Sperrzone dazwischen.
3. Gehandelt wird nur im Fenster selbst.
4. Alle Fenster ergeben eine durchgehende Kapitalkurve.

Kein Balken wird also je mit einem Modell gehandelt, das ihn kannte. Das kostet
Rechenzeit - für jedes Fenster ein vollständiges Training - und liefert dafür
eine Zahl, auf die man eine Entscheidung stützen kann.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from ..config import Config
from ..features.builder import FeatureSet
from ..labeling import build_labels, sample_weights
from ..models.ensemble import ModelEnsemble
from ..strategy.signal_engine import ModelProfile, SignalEngine, skill_from_auc
from ..types import Direction, Signal, SymbolSpec, Trade
from ..utils import get_logger
from ..validation.metrics import roc_auc, summarize
from ..validation.splits import walk_forward_windows
from .engine import BacktestEngine, BacktestResult

log = get_logger("walkforward")


@dataclass
class WindowResult:
    """Was ein einzelnes Vorwärtsfenster ergeben hat."""

    number: int
    train_rows: int
    test_rows: int
    test_from: "datetime | None" = None
    test_to: "datetime | None" = None
    auc: float = 0.5
    trades: int = 0
    total_r: float = 0.0
    expectancy_r: float = 0.0
    win_rate: float = 0.0
    model_features: int = 0
    members: int = 0
    note: str = ""

    def line(self) -> str:
        span = (
            f"{self.test_from:%Y-%m-%d}..{self.test_to:%Y-%m-%d}"
            if self.test_from and self.test_to else "-"
        )
        return (
            f"  {self.number:<4}{self.train_rows:>8}{self.test_rows:>8}  {span:<24}"
            f"{self.auc:>7.4f}{self.trades:>8}{self.expectancy_r:>+9.3f}{self.total_r:>+9.2f}"
            + (f"   {self.note}" if self.note else "")
        )


@dataclass
class WalkForwardResult:
    """Ergebnis über alle Fenster - inklusive der durchgehenden Kapitalkurve."""

    windows: list[WindowResult] = field(default_factory=list)
    backtest: "BacktestResult | None" = None
    skipped: Counter = field(default_factory=Counter)
    duration_s: float = 0.0
    symbol: str = ""
    traded_bars: int = 0
    total_bars: int = 0

    @property
    def trades(self) -> list[Trade]:
        return self.backtest.trades if self.backtest else []

    @property
    def trained_windows(self) -> int:
        return len(self.windows)

    def metrics(self, n_trials: int = 1, periods_per_year: float = 252 * 24) -> dict[str, float]:
        if self.backtest is None:
            return {"trades": 0}
        return self.backtest.metrics(n_trials, periods_per_year)

    def consistency(self) -> dict[str, float]:
        """Wie beständig ist das Ergebnis über die Fenster?

        Ein Gesamtgewinn aus einem einzigen guten Fenster ist kein Vorteil,
        sondern Glück. Diese Kennzahlen machen den Unterschied sichtbar.
        """
        with_trades = [w for w in self.windows if w.trades > 0]
        if not with_trades:
            return {"fenster_mit_trades": 0}
        r = np.array([w.total_r for w in with_trades], dtype=float)
        aucs = np.array([w.auc for w in self.windows], dtype=float)
        return {
            "fenster_mit_trades": len(with_trades),
            "davon_positiv": int((r > 0).sum()),
            "anteil_positiv": round(float((r > 0).mean()), 3),
            "bestes_fenster_r": round(float(r.max()), 2),
            "schlechtestes_fenster_r": round(float(r.min()), 2),
            "anteil_bestes_fenster": round(
                float(r.max() / r.sum()) if r.sum() > 0 else float("nan"), 3
            ),
            "auc_mittel": round(float(aucs.mean()), 4),
            "auc_streuung": round(float(aucs.std()), 4),
            "auc_ueber_zufall": int((aucs > 0.5).sum()),
        }


# --------------------------------------------------------------------------- #


def walk_forward_backtest(
    cfg: Config,
    fs: FeatureSet,
    spec: SymbolSpec,
    folds: int = 5,
    train_frac: float = 0.6,
    anchored: bool = True,
    session_filter: object = None,
    blocklist: object = None,
    verbose: bool = True,
) -> WalkForwardResult:
    """Backtest, bei dem jedes Fenster von einem eigenen, blinden Modell gehandelt wird."""
    start = time.perf_counter()
    result = WalkForwardResult(symbol=fs.symbol, total_bars=len(fs.frame))

    # --- Zielvariable und Gewichte über die gesamte Reihe ------------------ #
    lb = cfg.labels
    y_all, usable, barriers, label_kind = build_labels(cfg, fs)
    w_all = sample_weights(barriers, lb.sample_weight_decay, lb.apply_uniqueness_weights)
    mask = usable.to_numpy(dtype=bool)
    positions = np.arange(len(fs.frame))[mask]  # absolute Zeilen der lernbaren Beispiele
    if len(positions) < cfg.model.min_train_samples * 2:
        raise ValueError(
            f"Zu wenige verwertbare Beispiele für einen Vorwärtstest: {len(positions)}. "
            "Mehr Historie laden oder weniger Fenster wählen."
        )

    X = fs.frame.iloc[positions]
    y = y_all.to_numpy()[positions]
    w = w_all.to_numpy()[positions]
    # Ausstiegsindizes auf die Positionen im gefilterten Rahmen umrechnen
    exits = np.searchsorted(
        positions, barriers.exit_index.to_numpy()[positions], side="left"
    ).astype(float)

    windows = walk_forward_windows(
        len(positions), folds, train_frac, anchored, cfg.model.embargo_frac, exits
    )
    if not windows:
        raise ValueError("Die Aufteilung ergab kein nutzbares Fenster - weniger folds versuchen.")

    # --- Je Fenster ein eigenes Modell ------------------------------------ #
    probas = np.full(len(fs.frame), np.nan)  # NaN = kein Modell zuständig = nicht handeln
    # Güte und Basisrate gehören zum Modell des jeweiligen Fensters. Ohne sie
    # läse die Engine die Wahrscheinlichkeiten als blosse Zahlen - ein
    # Meta-Modell als Richtungsmodell und mit Gewicht null.
    skills = np.zeros(len(fs.frame))
    base_rates = np.full(len(fs.frame), 0.5)
    times = fs.frame.index

    for number, (train_idx, test_idx) in enumerate(windows, 1):
        train_rows, test_rows = len(train_idx), len(test_idx)
        if len(np.unique(y[train_idx])) < 2:
            result.skipped["nur eine Klasse im Training"] += 1
            continue

        # Gehandelt wird der volle Zeitraum des Fensters, nicht nur die Balken
        # mit auswertbarem Label - im Betrieb liegt an jedem Balken eine
        # Entscheidung an, nicht nur an den nachträglich eindeutigen.
        lo, hi = int(positions[test_idx[0]]), int(positions[test_idx[-1]])
        test_slice = slice(lo, hi + 1)

        ensemble = ModelEnsemble(cfg.model, version=f"wf{number:02d}")
        try:
            # Purging arbeitet relativ zum übergebenen Ausschnitt, deshalb die
            # Ausstiegsindizes um den Fensteranfang verschieben.
            rel_exits = exits[train_idx] - int(train_idx[0])
            ensemble.fit(X.iloc[train_idx], y[train_idx], w[train_idx], rel_exits,
                         label_kind=label_kind)
            window_proba = ensemble.predict_proba(fs.frame.iloc[test_slice])
        except Exception as exc:
            log.warning("Fenster %d übersprungen: %s", number, exc)
            result.skipped[f"Trainingsfehler: {type(exc).__name__}"] += 1
            continue

        probas[test_slice] = window_proba
        # Bewusst die Out-of-Fold-AUC aus dem Training dieses Fensters, nicht
        # die AUC auf dem Testabschnitt: Letztere kennt das Modell nicht, wenn
        # es entscheidet.
        skills[test_slice] = skill_from_auc(ensemble.report.auc)
        base_rates[test_slice] = ensemble.report.base_rate

        # Ehrliche AUC: nur auf den Testzeilen, die ein Label haben
        label_rows = test_idx
        auc = 0.5
        if len(np.unique(y[label_rows])) >= 2:
            offsets = positions[label_rows] - lo
            auc = roc_auc(y[label_rows], window_proba[offsets], w[label_rows])

        result.windows.append(
            WindowResult(
                number=number,
                train_rows=train_rows,
                test_rows=hi - lo + 1,
                test_from=times[lo].to_pydatetime(),
                test_to=times[hi].to_pydatetime(),
                auc=round(float(auc), 4),
                model_features=ensemble.report.n_features,
                members=len(ensemble.models),
                note="; ".join(ensemble.report.warnings[:1]),
            )
        )
        if verbose:
            log.info(
                "Fenster %d/%d: %d Trainingszeilen -> %s..%s, AUC %.4f",
                number, len(windows), train_rows,
                f"{times[lo]:%Y-%m-%d}", f"{times[hi]:%Y-%m-%d}", auc,
            )

    if not result.windows:
        raise RuntimeError(
            "Kein einziges Fenster ließ sich trainieren: "
            + ", ".join(f"{v}x {k}" for k, v in result.skipped.items())
        )

    # --- Signale bilden: außerhalb der Fenster wird nicht gehandelt -------- #
    profile = ModelProfile(label_kind=label_kind)
    engine = SignalEngine(cfg, models=None, blocklist=blocklist, profile=profile)
    signals: list[Signal] = []
    for i in range(len(fs.frame)):
        p = probas[i]
        if not np.isfinite(p):
            signals.append(_flat(fs, i))
            continue
        # Das Profil wandert mit dem Fenster mit, in dem dieser Balken liegt.
        profile.skill = float(skills[i])
        profile.base_rate = float(base_rates[i])
        signals.append(engine.generate(fs, i, spec, proba=float(p)))
    result.traded_bars = int(np.isfinite(probas).sum())

    # --- Ein durchgehender Backtest über alle Fenster ---------------------- #
    result.backtest = BacktestEngine(cfg, spec).run(fs, signals, session_filter)
    _attribute_trades(result)
    result.duration_s = round(time.perf_counter() - start, 1)
    return result


# --------------------------------------------------------------------------- #


def _flat(fs: FeatureSet, i: int) -> Signal:
    """Platzhaltersignal für Balken, für die kein blindes Modell zuständig ist."""
    ts = fs.frame.index[i]
    return Signal(
        symbol=fs.symbol,
        time=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
        direction=Direction.FLAT,
        score=0.0,
        entry=float(fs.base["close"].iloc[i]),
        stop_loss=0.0,
        warnings=["außerhalb der Vorwärtsfenster"],
    )


def _attribute_trades(result: WalkForwardResult) -> None:
    """Trades ihrem Fenster zuordnen und je Fenster auswerten."""
    if result.backtest is None:
        return
    for window in result.windows:
        if window.test_from is None or window.test_to is None:
            continue
        eigene = [
            t for t in result.backtest.trades
            if window.test_from <= t.entry_time <= window.test_to
        ]
        window.trades = len(eigene)
        if not eigene:
            continue
        r = np.array([t.r_multiple for t in eigene], dtype=float)
        window.total_r = round(float(r.sum()), 3)
        window.expectancy_r = round(float(r.mean()), 4)
        window.win_rate = round(float((r > 0).mean()), 4)


def format_walkforward_report(
    result: WalkForwardResult, currency: str = "EUR", n_trials: int = 1,
    periods_per_year: float = 252 * 24,
) -> str:
    """Textbericht des Vorwärtstests."""
    from ..utils import fmt_money, fmt_pct
    from .report import format_report

    lines = ["", "=" * 88]
    lines.append(f"  VORWÄRTS-BACKTEST {result.symbol}")
    lines.append("  Jedes Fenster wird von einem Modell gehandelt, das nur frühere Daten kannte.")
    lines.append("=" * 88)

    lines.append(
        f"\n  {result.trained_windows} Fenster trainiert in {result.duration_s:.0f}s | "
        f"gehandelt auf {result.traded_bars} von {result.total_bars} Balken "
        f"({result.traded_bars / max(result.total_bars, 1) * 100:.0f} %)"
    )
    if result.skipped:
        lines.append("  übersprungen: " + ", ".join(f"{v}x {k}" for k, v in result.skipped.items()))

    lines.append("\n  FENSTER")
    lines.append(
        f"  {'Nr':<4}{'Train':>8}{'Test':>8}  {'Zeitraum':<24}{'AUC':>7}{'Trades':>8}{'E[R]':>9}{'Summe R':>9}"
    )
    lines.append("  " + "-" * 80)
    for window in result.windows:
        lines.append(window.line())

    c = result.consistency()
    if c.get("fenster_mit_trades"):
        lines.append("\n  BESTÄNDIGKEIT")
        lines.append(
            f"    Fenster mit Trades   {c['fenster_mit_trades']}, davon positiv "
            f"{c['davon_positiv']} ({c['anteil_positiv'] * 100:.0f} %)"
        )
        lines.append(
            f"    bestes / schlechtestes {c['bestes_fenster_r']:+.2f} R / "
            f"{c['schlechtestes_fenster_r']:+.2f} R"
        )
        anteil = c.get("anteil_bestes_fenster")
        if anteil == anteil:  # NaN-sicherer Vergleich
            if anteil > 1.0:
                # Das beste Fenster trägt mehr als das Gesamtergebnis - alle
                # übrigen zusammen sind also negativ. "182 %" wäre hier eine
                # sinnlose Zahl; die Aussage dahinter ist die eigentliche Warnung.
                lines.append(
                    "    ACHTUNG: Ein einziges Fenster trägt mehr als das Gesamtergebnis - "
                    "alle übrigen zusammen sind negativ."
                )
                lines.append(
                    "    Ohne dieses eine Fenster wäre der Test ein Verlust. Das ist Glück, "
                    "kein Vorteil."
                )
            elif anteil > 0.6:
                lines.append(
                    f"    ACHTUNG: {anteil * 100:.0f} % des Gesamtergebnisses stammen aus einem "
                    "einzigen Fenster - das ist Glück, kein Vorteil."
                )
        lines.append(
            f"    AUC {c['auc_mittel']:.4f} ± {c['auc_streuung']:.4f}, "
            f"über Zufallsniveau in {c['auc_ueber_zufall']} von {result.trained_windows} Fenstern"
        )
        if c["auc_mittel"] < 0.52:
            lines.append(
                "    Kein belastbarer Vorteil. Parameter nachzujustieren erzeugt nur einen "
                "Vorteil aus dem Optimieren, der live sofort verschwindet."
            )

    if result.backtest is not None:
        lines.append(format_report(result.backtest, currency, n_trials, periods_per_year))
    return "\n".join(lines)
