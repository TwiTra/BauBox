"""Portfolioverwaltung: was ist offen, wie viel Risiko steht im Feuer.

Bewusst schlank: Buchhaltung, keine Optimierung. Die Wahrheit über offene
Positionen steht im Livebetrieb im Terminal, im Backtest in der Engine - diese
Klasse hält beides in derselben Form, damit Strategie- und Risikologik nicht
zwischen zwei Welten unterscheiden müssen.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from ..types import Direction, Position, Trade


@dataclass
class Portfolio:
    """Offene Positionen und abgeschlossene Trades."""

    positions: dict[int, Position] = field(default_factory=dict)
    closed: list[Trade] = field(default_factory=list)
    balance: float = 0.0
    equity: float = 0.0

    # ------------------------------------------------------------------ #

    def add(self, position: Position) -> None:
        self.positions[position.ticket] = position

    def remove(self, ticket: int) -> "Position | None":
        return self.positions.pop(ticket, None)

    def get(self, ticket: int) -> "Position | None":
        return self.positions.get(ticket)

    def close(self, trade: Trade) -> None:
        self.positions.pop(trade.ticket, None)
        self.closed.append(trade)
        self.balance += trade.profit

    @property
    def open_list(self) -> list[Position]:
        return list(self.positions.values())

    def for_symbol(self, symbol: str) -> list[Position]:
        return [p for p in self.positions.values() if p.symbol == symbol]

    def has(self, symbol: str, direction: "Direction | None" = None) -> bool:
        return any(
            p.symbol == symbol and (direction is None or p.direction is direction)
            for p in self.positions.values()
        )

    # ------------------------------------------------------------------ #

    def open_risk(self, balance: "float | None" = None) -> float:
        """Summe des noch offenen Risikos als Anteil des Kontos.

        Nachgezogene Stops senken das Risiko - Positionen im Gewinn mit Stop
        über dem Einstieg zählen gar nicht mehr mit.
        """
        base = balance if balance is not None else (self.balance or 1.0)
        if base <= 0:
            return 0.0
        total = 0.0
        for p in self.positions.values():
            if p.stop_loss <= 0:
                distance = p.risk_per_unit  # ohne Stop das ursprüngliche Risiko annehmen
            else:
                distance = (p.entry_price - p.stop_loss) * p.direction.sign
            if distance > 0:
                total += distance * p.volume
        return total / base

    def exposure(self) -> dict[str, float]:
        """Nettovolumen je Symbol (positiv = long)."""
        out: dict[str, float] = defaultdict(float)
        for p in self.positions.values():
            out[p.symbol] += p.volume * p.direction.sign
        return dict(out)

    def unrealised(self, prices: dict[str, float], value_per_point: dict[str, float]) -> float:
        total = 0.0
        for p in self.positions.values():
            price = prices.get(p.symbol)
            if price is None:
                continue
            total += p.unrealised_pnl(price, value_per_point.get(p.symbol, 1.0))
        return total

    # ------------------------------------------------------------------ #

    def stats(self) -> dict[str, float]:
        """Kurzstatistik der abgeschlossenen Trades."""
        if not self.closed:
            return {"trades": 0, "offen": len(self.positions)}
        wins = [t for t in self.closed if t.profit > 0]
        r_values = [t.r_multiple for t in self.closed]
        return {
            "trades": len(self.closed),
            "offen": len(self.positions),
            "gewinnquote": round(len(wins) / len(self.closed), 4),
            "summe_r": round(sum(r_values), 3),
            "erwartungswert_r": round(sum(r_values) / len(r_values), 4),
            "gewinn": round(sum(t.profit for t in self.closed), 2),
        }

    def trades_since(self, since: datetime) -> list[Trade]:
        return [t for t in self.closed if t.exit_time >= since]

    def reset(self, balance: float = 0.0) -> None:
        self.positions.clear()
        self.closed.clear()
        self.balance = balance
        self.equity = balance
