"""Grundlegende Datentypen des Systems.

Bewusst schlank gehalten: Alles, was mehrere Module gemeinsam nutzen, steht
hier, damit es keine Import-Zyklen zwischen Analyse, Strategie und Ausführung
gibt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class Direction(str, Enum):
    """Handelsrichtung."""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"

    @property
    def sign(self) -> int:
        return {Direction.LONG: 1, Direction.SHORT: -1, Direction.FLAT: 0}[self]

    def opposite(self) -> "Direction":
        if self is Direction.LONG:
            return Direction.SHORT
        if self is Direction.SHORT:
            return Direction.LONG
        return Direction.FLAT


class Timeframe(str, Enum):
    """Zeiteinheiten, wie MT5 sie kennt."""

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"
    MN1 = "MN1"

    @property
    def minutes(self) -> int:
        return {
            "M1": 1,
            "M5": 5,
            "M15": 15,
            "M30": 30,
            "H1": 60,
            "H4": 240,
            "D1": 1440,
            "W1": 10080,
            "MN1": 43200,
        }[self.value]

    @property
    def pandas_freq(self) -> str:
        """Resample-Frequenz für pandas."""
        return {
            "M1": "1min",
            "M5": "5min",
            "M15": "15min",
            "M30": "30min",
            "H1": "1h",
            "H4": "4h",
            "D1": "1D",
            "W1": "1W",
            "MN1": "1MS",
        }[self.value]

    @classmethod
    def parse(cls, value: "str | Timeframe") -> "Timeframe":
        if isinstance(value, cls):
            return value
        key = str(value).strip().upper()
        if key in cls.__members__:
            return cls[key]
        raise ValueError(f"Unbekannte Zeiteinheit: {value!r}")

    def __lt__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, Timeframe):
            return self.minutes < other.minutes
        return NotImplemented


class Horizon(str, Enum):
    """Die drei Analysehorizonte des Systems."""

    SHORT = "kurzfristig"
    MEDIUM = "mittelfristig"
    LONG = "langfristig"


class TrendState(str, Enum):
    """Marktstruktur-Zustand nach Swing-Analyse."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGE = "range"

    @property
    def direction(self) -> Direction:
        return {
            TrendState.BULLISH: Direction.LONG,
            TrendState.BEARISH: Direction.SHORT,
            TrendState.RANGE: Direction.FLAT,
        }[self]


class VolRegime(str, Enum):
    """Volatilitätsregime, aus ATR-Quantilen abgeleitet."""

    LOW = "niedrig"
    NORMAL = "normal"
    HIGH = "hoch"
    EXTREME = "extrem"


class OrderKind(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class ExitReason(str, Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    PARTIAL = "teilgewinn"
    TRAILING = "trailing_stop"
    BREAK_EVEN = "break_even"
    TIME = "zeitlimit"
    SIGNAL_FLIP = "gegensignal"
    MANUAL = "manuell"
    GUARD = "schutzabschaltung"
    END_OF_DATA = "datenende"


# --------------------------------------------------------------------------- #
# Analyse-Ergebnisse
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Swing:
    """Ein bestätigter Swing-Punkt (Hoch oder Tief)."""

    index: int
    time: datetime
    price: float
    is_high: bool
    strength: float = 0.0  # 0..1, wie deutlich der Punkt herausragt

    @property
    def kind(self) -> str:
        return "high" if self.is_high else "low"


@dataclass(frozen=True)
class Zone:
    """Ein Preisbereich mit Bedeutung (Order Block, FVG, S/R-Cluster …)."""

    kind: str  # "order_block" | "fvg" | "support" | "resistance" | "liquidity"
    direction: Direction
    top: float
    bottom: float
    created_index: int
    created_time: datetime
    strength: float = 0.5  # 0..1
    touches: int = 0
    mitigated: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def height(self) -> float:
        return abs(self.top - self.bottom)

    def contains(self, price: float, tolerance: float = 0.0) -> bool:
        return (self.bottom - tolerance) <= price <= (self.top + tolerance)

    def distance(self, price: float) -> float:
        """Abstand des Preises zur Zone (0 wenn innerhalb)."""
        if self.contains(price):
            return 0.0
        return min(abs(price - self.top), abs(price - self.bottom))


@dataclass(frozen=True)
class StructureEvent:
    """Bruch der Marktstruktur: BOS (Fortsetzung) oder CHoCH (Wechsel)."""

    index: int
    time: datetime
    kind: str  # "BOS" | "CHoCH"
    direction: Direction
    level: float
    swing_index: int


@dataclass
class HorizonView:
    """Die Sicht eines einzelnen Horizonts auf den Markt."""

    horizon: Horizon
    timeframe: Timeframe
    trend: TrendState
    prob_up: float = 0.5  # kalibrierte Wahrscheinlichkeit für Aufwärtsbewegung
    confidence: float = 0.0  # 0..1, Modellsicherheit
    rule_score: float = 0.0  # -1..+1, regelbasierte Price-Action-Konfluenz
    atr: float = 0.0
    regime: VolRegime = VolRegime.NORMAL
    reasons: list[str] = field(default_factory=list)
    model_available: bool = False

    @property
    def bias(self) -> float:
        """Zusammengefasster Bias von -1 (short) bis +1 (long).

        Ohne trainiertes Modell entscheidet allein das Regelwerk. Die neutrale
        Wahrscheinlichkeit 0,5 einzumischen würde jede Aussage halbieren und das
        System künstlich stumm schalten.
        """
        if not self.model_available:
            return float(self.rule_score)
        model_bias = (self.prob_up - 0.5) * 2.0
        return float(0.5 * model_bias + 0.5 * self.rule_score)


@dataclass
class Signal:
    """Ein fertiges Handelssignal - das Endprodukt der Analyse."""

    symbol: str
    time: datetime
    direction: Direction
    score: float  # 0..1, Gesamtüberzeugung
    entry: float
    stop_loss: float
    take_profits: list[float] = field(default_factory=list)
    tp_fractions: list[float] = field(default_factory=list)
    horizon: Horizon = Horizon.MEDIUM
    prob_win: float = 0.5
    expected_r: float = 0.0
    risk_reward: float = 0.0
    atr: float = 0.0
    regime: VolRegime = VolRegime.NORMAL
    trend_alignment: float = 0.0  # -1..+1, Übereinstimmung der drei Horizonte
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    views: dict[str, HorizonView] = field(default_factory=dict)
    features: dict[str, float] = field(default_factory=dict)
    model_version: str = ""
    max_hold_bars: int = 0

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop_loss)

    @property
    def is_actionable(self) -> bool:
        return self.direction is not Direction.FLAT and self.risk_per_unit > 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["time"] = self.time.isoformat()
        data["direction"] = self.direction.value
        data["horizon"] = self.horizon.value
        data["regime"] = self.regime.value
        data["views"] = {
            k: {
                "timeframe": v.timeframe.value,
                "trend": v.trend.value,
                "prob_up": v.prob_up,
                "rule_score": v.rule_score,
                "bias": v.bias,
                "reasons": v.reasons,
            }
            for k, v in self.views.items()
        }
        return data

    def summary(self) -> str:
        """Einzeilige, für Menschen lesbare Zusammenfassung."""
        if not self.is_actionable:
            return f"{self.symbol}: kein Setup (Score {self.score:.2f})"
        arrow = "LONG " if self.direction is Direction.LONG else "SHORT"
        tp = self.take_profits[0] if self.take_profits else float("nan")
        return (
            f"{self.symbol} {arrow} | Score {self.score:.2f} | "
            f"Entry {self.entry:.5f} SL {self.stop_loss:.5f} TP {tp:.5f} | "
            f"CRV {self.risk_reward:.2f} | E[R] {self.expected_r:+.2f} | "
            f"{self.horizon.value}"
        )


# --------------------------------------------------------------------------- #
# Handel
# --------------------------------------------------------------------------- #


@dataclass
class Position:
    """Eine offene Position."""

    ticket: int
    symbol: str
    direction: Direction
    volume: float
    entry_price: float
    entry_time: datetime
    stop_loss: float
    take_profit: float
    initial_stop: float = 0.0
    initial_volume: float = 0.0
    magic: int = 0
    comment: str = ""
    signal_score: float = 0.0
    horizon: Horizon = Horizon.MEDIUM
    partials_done: int = 0
    break_even_done: bool = False
    max_favorable: float = 0.0  # in R
    max_adverse: float = 0.0  # in R
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.initial_stop == 0.0:
            self.initial_stop = self.stop_loss
        if self.initial_volume == 0.0:
            self.initial_volume = self.volume

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry_price - self.initial_stop)

    def unrealised_r(self, price: float) -> float:
        """Aktuelles Ergebnis in R-Vielfachen."""
        risk = self.risk_per_unit
        if risk <= 0 or not math.isfinite(price):
            return 0.0
        return (price - self.entry_price) * self.direction.sign / risk

    def unrealised_pnl(self, price: float, value_per_point: float) -> float:
        return (price - self.entry_price) * self.direction.sign * self.volume * value_per_point


@dataclass
class Trade:
    """Ein abgeschlossener Trade - Grundlage für Journal und Lernschleife."""

    symbol: str
    direction: Direction
    volume: float
    entry_price: float
    entry_time: datetime
    exit_price: float
    exit_time: datetime
    profit: float
    r_multiple: float
    exit_reason: ExitReason = ExitReason.MANUAL
    stop_loss: float = 0.0
    take_profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    slippage: float = 0.0
    bars_held: int = 0
    max_favorable_r: float = 0.0
    max_adverse_r: float = 0.0
    signal_score: float = 0.0
    prob_win: float = 0.5
    horizon: Horizon = Horizon.MEDIUM
    regime: VolRegime = VolRegime.NORMAL
    model_version: str = ""
    ticket: int = 0
    features: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def is_winner(self) -> bool:
        return self.profit > 0

    @property
    def duration_hours(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds() / 3600.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entry_time"] = self.entry_time.isoformat()
        data["exit_time"] = self.exit_time.isoformat()
        data["direction"] = self.direction.value
        data["exit_reason"] = self.exit_reason.value
        data["horizon"] = self.horizon.value
        data["regime"] = self.regime.value
        return data


@dataclass
class SymbolSpec:
    """Kontraktspezifikation eines Symbols.

    Wird live aus MT5 gelesen und für Backtests aus der Konfiguration
    rekonstruiert, damit beide Pfade identisch rechnen.
    """

    name: str
    digits: int = 5
    point: float = 0.00001
    tick_size: float = 0.00001
    tick_value: float = 1.0  # Kontowährung pro tick_size und 1.0 Lot
    contract_size: float = 100_000.0
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    stops_level_points: int = 0
    freeze_level_points: int = 0
    spread_points: float = 10.0
    swap_long: float = 0.0
    swap_short: float = 0.0
    currency_profit: str = "USD"
    trade_allowed: bool = True

    @property
    def value_per_point(self) -> float:
        """Kontowährung je 1 Punkt Preisbewegung und 1.0 Lot."""
        if self.tick_size <= 0:
            return self.tick_value
        return self.tick_value * (self.point / self.tick_size)

    @property
    def pip(self) -> float:
        """Ein Pip - bei 3/5 Nachkommastellen das Zehnfache eines Punktes."""
        return self.point * 10 if self.digits in (3, 5) else self.point

    def normalize_price(self, price: float) -> float:
        if self.tick_size > 0:
            price = round(price / self.tick_size) * self.tick_size
        return round(price, self.digits)

    def normalize_volume(self, volume: float) -> float:
        if self.volume_step <= 0:
            return max(self.volume_min, min(self.volume_max, volume))
        steps = math.floor(volume / self.volume_step + 1e-9)
        vol = steps * self.volume_step
        vol = max(self.volume_min, min(self.volume_max, vol))
        # Nachkommastellen des Schritts sauber halten (0.01 -> 2 Stellen)
        decimals = max(0, -int(math.floor(math.log10(self.volume_step))) if self.volume_step < 1 else 0)
        return round(vol, decimals + 1)

    def min_stop_distance(self) -> float:
        return self.stops_level_points * self.point


@dataclass
class AccountState:
    """Momentaufnahme des Kontos."""

    balance: float
    equity: float
    margin: float = 0.0
    free_margin: float = 0.0
    currency: str = "EUR"
    leverage: int = 100
    login: int = 0
    server: str = ""

    @property
    def margin_level(self) -> float:
        return (self.equity / self.margin * 100.0) if self.margin > 0 else float("inf")


def utcnow() -> datetime:
    """Zeitstempel in UTC - MT5 liefert alle Zeiten in UTC."""
    return datetime.now(timezone.utc)
