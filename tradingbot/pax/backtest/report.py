"""Auswertung eines Backtests in lesbarer Form.

Die Zahlen sollen nicht schmeicheln, sondern brauchbar sein. Deshalb stehen
Kosten, abgelehnte Signale und die Aufschlüsselung nach Ausstiegsgrund
gleichberechtigt neben Gewinn und Trefferquote: Wenn 80 % der Trades über den
Zeitausstieg enden, stimmt etwas mit den Zielen nicht - das sieht man nur, wenn
es jemand hinschreibt.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..types import Direction
from ..utils import fmt_money, fmt_pct


def trade_frame(result: object) -> pd.DataFrame:
    """Alle Trades als Tabelle."""
    trades = getattr(result, "trades", [])
    if not trades:
        return pd.DataFrame()
    return pd.DataFrame([t.to_dict() for t in trades])


def equity_frame(result: object) -> pd.DataFrame:
    """Kapitalkurve mit Rückgang."""
    equity = getattr(result, "equity", pd.Series(dtype=float))
    if equity.empty:
        return pd.DataFrame()
    peak = equity.cummax()
    return pd.DataFrame(
        {
            "equity": equity,
            "balance": getattr(result, "balance", equity),
            "peak": peak,
            "drawdown": (equity - peak) / peak.replace(0, np.nan),
        }
    )


def monthly_table(result: object) -> pd.DataFrame:
    """Ergebnis je Monat - zeigt, ob der Gewinn aus einem Glücksmonat stammt."""
    df = trade_frame(result)
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    # to_period() würde die Zeitzone verwerfen und eine Warnung auslösen
    df["monat"] = df["exit_time"].dt.strftime("%Y-%m")
    grouped = df.groupby("monat").agg(
        trades=("r_multiple", "size"),
        summe_r=("r_multiple", "sum"),
        gewinn=("profit", "sum"),
        gewinnquote=("profit", lambda s: float((s > 0).mean())),
    )
    return grouped.round(3).reset_index()


def exit_breakdown(result: object) -> pd.DataFrame:
    """Wie enden die Trades? Der ehrlichste Blick auf die Ausstiegslogik."""
    df = trade_frame(result)
    if df.empty:
        return pd.DataFrame()
    grouped = df.groupby("exit_reason").agg(
        anzahl=("r_multiple", "size"),
        mittleres_r=("r_multiple", "mean"),
        summe_r=("r_multiple", "sum"),
    )
    grouped["anteil"] = grouped["anzahl"] / grouped["anzahl"].sum()
    return grouped.round(3).sort_values("anzahl", ascending=False).reset_index()


def regime_breakdown(result: object) -> pd.DataFrame:
    """Ergebnis je Volatilitätsregime und Horizont - Grundlage der Lernschleife."""
    df = trade_frame(result)
    if df.empty:
        return pd.DataFrame()
    grouped = df.groupby(["regime", "horizon"]).agg(
        trades=("r_multiple", "size"),
        erwartungswert_r=("r_multiple", "mean"),
        summe_r=("r_multiple", "sum"),
        gewinnquote=("profit", lambda s: float((s > 0).mean())),
    )
    return grouped.round(3).sort_values("trades", ascending=False).reset_index()


def format_report(result: object, currency: str = "EUR", n_trials: int = 1,
                  periods_per_year: float = 252 * 24) -> str:
    """Vollständiger Textbericht."""
    trades = getattr(result, "trades", [])
    lines: list[str] = []
    sep = "=" * 72
    lines.append(sep)
    lines.append(f"  BACKTEST {getattr(result, 'symbol', '')}")
    lines.append(sep)

    if not trades:
        lines.append("\n  Kein einziger Trade zustande gekommen.")
        lines.append(f"  Signale insgesamt: {getattr(result, 'signals_total', 0)}")
        lines.append(f"  davon handelbar:   {getattr(result, 'signals_actionable', 0)}")
        lines.extend(_rejection_lines(result))
        lines.append(
            "\n  Häufigste Ursachen: zu hohe Mindestwerte (min_signal_score, min_risk_reward),\n"
            "  zu enge Handelszeiten oder ein Konto, das für das Mindestlot zu klein ist."
        )
        return "\n".join(lines)

    m = result.metrics(n_trials=n_trials, periods_per_year=periods_per_year)  # type: ignore[attr-defined]
    initial = getattr(result, "initial_balance", 0.0)
    final = getattr(result, "final_balance", 0.0)

    lines.append("\n  ERGEBNIS")
    lines.append(f"    Startkapital        {fmt_money(initial, currency)}")
    lines.append(f"    Endkapital          {fmt_money(final, currency)}")
    lines.append(f"    Nettogewinn         {fmt_money(final - initial, currency)}  "
                 f"({fmt_pct((final / initial - 1) if initial else 0)})")
    lines.append(f"    Summe R             {m.get('total_r', 0):+.2f} R")

    lines.append("\n  TRADES")
    lines.append(f"    Anzahl              {m.get('trades', 0)}")
    lines.append(f"    Trefferquote        {fmt_pct(m.get('win_rate', 0))}")
    lines.append(f"    Erwartungswert      {m.get('expectancy_r', 0):+.3f} R je Trade")
    lines.append(f"    Profitfaktor        {m.get('profit_factor', 0):.2f}")
    lines.append(f"    Ø Gewinn / Verlust  {m.get('avg_win_r', 0):+.2f} R / {m.get('avg_loss_r', 0):+.2f} R")
    lines.append(f"    Payoff-Verhältnis   {m.get('payoff_ratio', 0):.2f}")
    lines.append(f"    längste Verlustserie {m.get('max_consecutive_losses', 0)}")

    lines.append("\n  RISIKO")
    lines.append(f"    max. Rückgang       {fmt_pct(abs(m.get('max_drawdown', 0)))} "
                 f"({m.get('max_drawdown_r', 0):.2f} R)")
    lines.append(f"    Sharpe (annualis.)  {m.get('sharpe', 0):.2f}")
    lines.append(f"    Sortino             {m.get('sortino', 0):.2f}")
    lines.append(f"    Calmar              {m.get('calmar', 0):.2f}")
    lines.append(f"    Ulcer-Index         {m.get('ulcer_index', 0):.4f}")
    lines.append(f"    Erholungsfaktor     {m.get('recovery_factor', 0):.2f}")

    lines.append("\n  EHRLICHKEITSPRÜFUNG")
    lines.append(f"    PSR                 {m.get('psr', 0):.3f}   "
                 "(Wahrscheinlichkeit, dass der Vorteil echt ist)")
    lines.append(f"    Deflated Sharpe     {m.get('deflated_sharpe', 0):.3f}   "
                 f"(bereinigt um {n_trials} ausprobierte Varianten)")
    if m.get("deflated_sharpe", 0) < 0.5 and n_trials > 1:
        lines.append("    -> Der Vorteil ist statistisch nicht gesichert. Nicht live schalten.")

    costs = getattr(result, "costs", {})
    if costs:
        lines.append("\n  KOSTEN")
        for key, value in costs.items():
            lines.append(f"    {key:<20}{fmt_money(value, currency)}")
        gross = (final - initial) + costs.get("gesamt", 0)
        if abs(gross) > 1e-9:
            lines.append(f"    Kostenanteil        {fmt_pct(costs.get('gesamt', 0) / abs(gross))} des Bruttoergebnisses")

    lines.append("\n  SIGNALE")
    lines.append(f"    geprüfte Balken     {getattr(result, 'signals_total', 0)}")
    lines.append(f"    handelbare Signale  {getattr(result, 'signals_actionable', 0)}")
    lines.append(f"    davon gehandelt     {len(trades)}")
    lines.extend(_rejection_lines(result))

    ex = exit_breakdown(result)
    if not ex.empty:
        lines.append("\n  AUSSTIEGSGRÜNDE")
        for _, row in ex.iterrows():
            lines.append(
                f"    {row['exit_reason']:<16}{int(row['anzahl']):>4}  "
                f"({row['anteil'] * 100:4.1f} %)  Ø {row['mittleres_r']:+.2f} R"
            )

    reg = regime_breakdown(result)
    if not reg.empty and len(reg) > 1:
        lines.append("\n  NACH REGIME UND HORIZONT")
        for _, row in reg.head(8).iterrows():
            lines.append(
                f"    {row['regime']:<9} {row['horizon']:<14}{int(row['trades']):>4} Trades  "
                f"Ø {row['erwartungswert_r']:+.3f} R  Quote {row['gewinnquote'] * 100:4.1f} %"
            )

    monthly = monthly_table(result)
    if not monthly.empty and len(monthly) > 1:
        positive = int((monthly["summe_r"] > 0).sum())
        lines.append("\n  MONATE")
        lines.append(f"    positiv             {positive} von {len(monthly)}")
        lines.append(f"    bester / schlechtester {monthly['summe_r'].max():+.2f} R / "
                     f"{monthly['summe_r'].min():+.2f} R")

    lines.append("\n" + sep)
    return "\n".join(lines)


def _rejection_lines(result: object) -> list[str]:
    rejections = getattr(result, "rejections", {})
    if not rejections:
        return []
    out = ["    abgelehnt wegen:"]
    for reason, count in sorted(rejections.items(), key=lambda kv: -kv[1])[:8]:
        text = reason if len(reason) <= 52 else reason[:49] + "..."
        out.append(f"      {count:>6}x  {text}")
    return out
