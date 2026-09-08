"""Broker-Abstraktion.

Eine gemeinsame Schnittstelle für drei Betriebsarten:

* **MT5Broker** - echte Orders im Terminal
* **MT5Broker mit `dry_run`** - liest echte Kurse, sendet aber nichts. Der
  richtige Modus für die ersten Wochen: man sieht, was das System *täte*, ohne
  dass ein Fehler Geld kostet.
* **PaperBroker** - simuliert alles, auch die Kurse. Für Tests ohne Terminal.

Weil alle drei dieselbe Schnittstelle haben, laufen Strategie, Risiko und
Positionsführung überall unverändert. Fehler im Live-Pfad, die im Test nicht
auftauchen, sind so weitgehend ausgeschlossen.
"""

from __future__ import annotations

import numpy as np

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..types import AccountState, Direction, Position, SymbolSpec, utcnow
from ..utils import get_logger

log = get_logger("broker")


@dataclass
class OrderResult:
    """Ergebnis eines Orderversuchs."""

    ok: bool
    ticket: int = 0
    price: float = 0.0
    volume: float = 0.0
    message: str = ""
    dry_run: bool = False
    raw: dict = field(default_factory=dict)


class Broker(ABC):
    """Was die Strategie von einem Broker braucht - mehr nicht."""

    @abstractmethod
    def account(self) -> AccountState: ...

    @abstractmethod
    def symbol_spec(self, symbol: str) -> SymbolSpec: ...

    @abstractmethod
    def tick(self, symbol: str) -> dict: ...

    @abstractmethod
    def positions(self, symbol: "str | None" = None) -> list[Position]: ...

    @abstractmethod
    def open_position(
        self, symbol: str, direction: Direction, volume: float,
        stop_loss: float = 0.0, take_profit: float = 0.0, comment: str = "",
    ) -> OrderResult: ...

    @abstractmethod
    def modify_position(
        self, ticket: int, stop_loss: "float | None" = None, take_profit: "float | None" = None
    ) -> OrderResult: ...

    @abstractmethod
    def close_position(self, ticket: int, volume: "float | None" = None) -> OrderResult: ...

    def close_all(self, symbol: "str | None" = None) -> list[OrderResult]:
        return [self.close_position(p.ticket) for p in self.positions(symbol)]

    def health(self) -> dict:
        return {"ok": True}


# --------------------------------------------------------------------------- #


class MT5Broker(Broker):
    """Orderausführung über das MetaTrader-5-Terminal."""

    def __init__(self, client: object, execution_cfg: object) -> None:
        self.client = client
        self.cfg = execution_cfg
        self.dry_run = bool(getattr(execution_cfg, "dry_run", True))
        if self.dry_run:
            log.warning(
                "TROCKENLAUF aktiv - es werden KEINE echten Orders gesendet. "
                "Zum Scharfschalten in der Konfiguration execution.dry_run auf false setzen."
            )

    # ------------------------------------------------------------------ #

    def account(self) -> AccountState:
        return self.client.account()  # type: ignore[attr-defined]

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        return self.client.symbol_spec(symbol)  # type: ignore[attr-defined]

    def tick(self, symbol: str) -> dict:
        return self.client.tick(symbol)  # type: ignore[attr-defined]

    def positions(self, symbol: "str | None" = None) -> list[Position]:
        return self.client.positions(symbol=symbol)  # type: ignore[attr-defined]

    def health(self) -> dict:
        return self.client.health()  # type: ignore[attr-defined]

    def open_position(
        self, symbol: str, direction: Direction, volume: float,
        stop_loss: float = 0.0, take_profit: float = 0.0, comment: str = "",
    ) -> OrderResult:
        if self.dry_run:
            tick = self.tick(symbol)
            price = tick["ask"] if direction is Direction.LONG else tick["bid"]
            log.info(
                "[TROCKEN] %s %s %.2f Lot zu %.5f, SL %.5f, TP %.5f",
                direction.value.upper(), symbol, volume, price, stop_loss, take_profit,
            )
            return OrderResult(True, ticket=0, price=price, volume=volume,
                               message="Trockenlauf - nicht gesendet", dry_run=True)
        try:
            raw = self.client.open_position(  # type: ignore[attr-defined]
                symbol, direction, volume, stop_loss, take_profit,
                deviation=getattr(self.cfg, "deviation_points", 20),
                comment=comment or getattr(self.cfg, "comment", "PAX"),
                filling=getattr(self.cfg, "filling", "auto"),
            )
        except Exception as exc:
            log.error("Order fehlgeschlagen: %s", exc)
            return OrderResult(False, message=str(exc))
        log.info(
            "Position eröffnet: %s %s %.2f Lot zu %.5f (Ticket %s, Schlupf %.1f Punkte)",
            direction.value.upper(), symbol, raw["volume"], raw["price"], raw["ticket"],
            raw.get("slippage", 0.0) / max(self.symbol_spec(symbol).point, 1e-12),
        )
        return OrderResult(True, raw["ticket"], raw["price"], raw["volume"], raw=raw)

    def modify_position(
        self, ticket: int, stop_loss: "float | None" = None, take_profit: "float | None" = None
    ) -> OrderResult:
        if self.dry_run:
            log.info("[TROCKEN] Position %s: SL -> %s, TP -> %s", ticket, stop_loss, take_profit)
            return OrderResult(True, ticket=ticket, message="Trockenlauf", dry_run=True)
        try:
            changed = self.client.modify_position(ticket, stop_loss, take_profit)  # type: ignore[attr-defined]
        except Exception as exc:
            log.error("Anpassung von Position %s fehlgeschlagen: %s", ticket, exc)
            return OrderResult(False, ticket=ticket, message=str(exc))
        return OrderResult(True, ticket=ticket, message="geändert" if changed else "unverändert")

    def close_position(self, ticket: int, volume: "float | None" = None) -> OrderResult:
        if self.dry_run:
            log.info("[TROCKEN] Position %s geschlossen (Volumen %s)", ticket, volume or "gesamt")
            return OrderResult(True, ticket=ticket, message="Trockenlauf", dry_run=True)
        try:
            raw = self.client.close_position(ticket, volume)  # type: ignore[attr-defined]
        except Exception as exc:
            log.error("Schließen von Position %s fehlgeschlagen: %s", ticket, exc)
            return OrderResult(False, ticket=ticket, message=str(exc))
        log.info("Position %s geschlossen zu %.5f", ticket, raw["price"])
        return OrderResult(True, ticket, raw["price"], raw["closed_volume"], raw=raw)


# --------------------------------------------------------------------------- #


def _volumen_fehler(volume: float, spec: "SymbolSpec | None") -> str:
    """Grund, warum ein Volumen unzulässig ist - oder ein leerer Text."""
    try:
        v = float(volume)
    except (TypeError, ValueError):
        return f"Volumen ist keine Zahl: {volume!r}"
    if not np.isfinite(v) or v <= 0:
        return f"Volumen muss positiv sein, war {v}"
    if spec is None:
        return ""
    if v < spec.volume_min - 1e-9:
        return f"Volumen {v} unter dem Mindestlot {spec.volume_min}"
    maximum = getattr(spec, "volume_max", 0.0) or 0.0
    if maximum > 0 and v > maximum + 1e-9:
        return f"Volumen {v} über dem Höchstlot {maximum}"
    schritt = getattr(spec, "volume_step", 0.0) or 0.0
    if schritt > 0:
        rest = abs((v / schritt) - round(v / schritt))
        if rest > 1e-6:
            return f"Volumen {v} ist kein Vielfaches der Schrittweite {schritt}"
    return ""


class PaperBroker(Broker):
    """Vollständig simulierter Broker - für Tests des Live-Ablaufs ohne Terminal."""

    def __init__(
        self, balance: float = 10_000.0, spec: "SymbolSpec | None" = None, currency: str = "EUR"
    ) -> None:
        self.balance = float(balance)
        self.spec_default = spec or SymbolSpec("PAPER")
        self.currency = currency
        self._positions: dict[int, Position] = {}
        self._prices: dict[str, float] = {}
        self._ticket = 1000
        self.closed: list[dict] = []

    # ------------------------------------------------------------------ #

    def set_price(self, symbol: str, price: float) -> None:
        """Aktuellen Kurs setzen - der Testtreiber schiebt den Markt weiter."""
        self._prices[symbol] = float(price)

    def account(self) -> AccountState:
        unrealised = sum(
            p.unrealised_pnl(self._prices.get(p.symbol, p.entry_price), self.spec_default.value_per_point)
            for p in self._positions.values()
        )
        return AccountState(
            balance=self.balance,
            equity=self.balance + unrealised,
            margin=0.0,
            free_margin=self.balance,
            currency=self.currency,
        )

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        spec = self.spec_default
        return spec if spec.name == symbol else SymbolSpec(
            name=symbol, digits=spec.digits, point=spec.point, tick_size=spec.tick_size,
            tick_value=spec.tick_value, contract_size=spec.contract_size,
            volume_min=spec.volume_min, volume_max=spec.volume_max,
            volume_step=spec.volume_step, spread_points=spec.spread_points,
        )

    def tick(self, symbol: str) -> dict:
        price = self._prices.get(symbol, 1.0)
        spread = self.spec_default.spread_points * self.spec_default.point
        return {
            "time": utcnow(), "bid": price, "ask": price + spread,
            "last": price, "spread": spread,
            "spread_points": self.spec_default.spread_points, "volume": 0.0,
        }

    def positions(self, symbol: "str | None" = None) -> list[Position]:
        return [p for p in self._positions.values() if symbol is None or p.symbol == symbol]

    def open_position(
        self, symbol: str, direction: Direction, volume: float,
        stop_loss: float = 0.0, take_profit: float = 0.0, comment: str = "",
    ) -> OrderResult:
        # Wie ein echter Broker prüfen. Ohne das nimmt der Papierbetrieb
        # Aufträge an, die MT5 ablehnen würde - der Trockenlauf sähe dann
        # sauber aus und live schlüge derselbe Auftrag fehl.
        spec = self.symbol_spec(symbol)
        fehler = _volumen_fehler(volume, spec)
        if fehler:
            return OrderResult(False, message=fehler)
        tick = self.tick(symbol)
        price = tick["ask"] if direction is Direction.LONG else tick["bid"]
        if not np.isfinite(price) or price <= 0:
            return OrderResult(False, message=f"kein gültiger Kurs für {symbol}")
        self._ticket += 1
        self._positions[self._ticket] = Position(
            ticket=self._ticket, symbol=symbol, direction=direction, volume=volume,
            entry_price=price, entry_time=utcnow(), stop_loss=stop_loss,
            take_profit=take_profit, comment=comment,
        )
        return OrderResult(True, self._ticket, price, volume)

    def modify_position(
        self, ticket: int, stop_loss: "float | None" = None, take_profit: "float | None" = None
    ) -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(False, ticket, message="Position nicht gefunden")
        if stop_loss is not None:
            pos.stop_loss = float(stop_loss)
        if take_profit is not None:
            pos.take_profit = float(take_profit)
        return OrderResult(True, ticket, message="geändert")

    def close_position(self, ticket: int, volume: "float | None" = None) -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(False, ticket, message="Position nicht gefunden")
        spec = self.symbol_spec(pos.symbol)
        price = self._prices.get(pos.symbol, pos.entry_price)
        close_volume = min(volume or pos.volume, pos.volume)
        profit = (
            (price - pos.entry_price) * pos.direction.sign * close_volume
            * spec.value_per_point / spec.point
        )
        self.balance += profit
        self.closed.append(
            {"ticket": ticket, "symbol": pos.symbol, "volume": close_volume,
             "price": price, "profit": profit, "time": utcnow()}
        )
        pos.volume = round(pos.volume - close_volume, 6)
        if pos.volume < spec.volume_min:
            self._positions.pop(ticket, None)
        return OrderResult(True, ticket, price, close_volume, raw={"profit": profit})
