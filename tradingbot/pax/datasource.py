"""Woher die Kursdaten kommen - eine Entscheidung, drei Quellen.

Reihenfolge: MT5-Terminal, sonst lokaler Zwischenspeicher, sonst synthetische
Daten. Der letzte Fall wird immer deutlich gemeldet: Ergebnisse auf erzeugten
Daten sagen etwas über die Software aus, nichts über den Markt.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import Config
from .data.mt5_client import MT5Client, MT5Unavailable
from .data.store import BarStore
from .data.synthetic import SyntheticMarket
from .types import SymbolSpec, Timeframe
from .utils import get_logger

log = get_logger("daten")


@dataclass
class DataBundle:
    """Kursdaten eines Symbols über alle Zeitebenen, samt Herkunft."""

    symbol: str
    frames: dict[str, pd.DataFrame]
    spec: SymbolSpec
    source: str  # "mt5" | "cache" | "synthetisch"

    @property
    def is_synthetic(self) -> bool:
        return self.source == "synthetisch"

    def describe(self) -> str:
        base = min(self.frames, key=lambda k: Timeframe.parse(k).minutes)
        df = self.frames[base]
        span = f"{df.index[0]:%Y-%m-%d} bis {df.index[-1]:%Y-%m-%d}" if len(df) else "leer"
        sizes = ", ".join(f"{k}:{len(v)}" for k, v in sorted(
            self.frames.items(), key=lambda kv: Timeframe.parse(kv[0]).minutes))
        return f"{self.symbol} [{self.source}] {span} | {sizes}"


def load_data(
    cfg: Config,
    symbol: str,
    bars: "int | None" = None,
    allow_synthetic: bool = True,
    update: bool = True,
    seed: int = 7,
) -> DataBundle:
    """Kursdaten beschaffen - aus der besten verfügbaren Quelle."""
    bars = bars or cfg.data.history_bars
    timeframes = cfg.data.all_timeframes

    client: MT5Client | None = None
    if MT5Client.available():
        try:
            client = MT5Client(cfg.terminal, cfg.execution.magic).connect()
        except Exception as exc:
            log.warning("MT5-Verbindung nicht möglich (%s) - es wird der Zwischenspeicher genutzt", exc)
            client = None

    store = BarStore(cfg.data.cache_dir, client)

    if client is not None:
        try:
            frames = store.load_multi(symbol, timeframes, bars, update=update)
            spec = client.symbol_spec(symbol)
            return DataBundle(symbol, frames, spec, "mt5")
        except Exception as exc:
            log.warning("Daten für %s nicht vom Terminal ladbar: %s", symbol, exc)

    cached = {}
    for tf in timeframes:
        df = store.read(symbol, tf)
        if len(df) >= 200:
            cached[Timeframe.parse(tf).value] = df.tail(bars)
    if len(cached) == len(timeframes):
        log.info("%s aus dem Zwischenspeicher geladen", symbol)
        return DataBundle(symbol, cached, _default_spec(symbol), "cache")

    if not allow_synthetic:
        raise MT5Unavailable(
            f"Für {symbol} liegen weder ein MT5-Terminal noch ausreichend zwischengespeicherte "
            f"Daten vor. Mit dem Befehl 'fetch' lassen sich Daten herunterladen."
        )

    log.warning(
        "ACHTUNG: %s wird mit SYNTHETISCHEN Daten geladen. Die Ergebnisse prüfen die "
        "Software, nicht den Markt.", symbol,
    )
    market = SyntheticMarket(symbol, start_price=_default_price(symbol), seed=seed,
                             digits=_default_digits(symbol))
    frames = market.generate_multi(max(600, bars // 8), timeframes)
    return DataBundle(symbol, frames, market.spec(), "synthetisch")


def _default_digits(symbol: str) -> int:
    s = symbol.upper()
    if "JPY" in s:
        return 3
    if s.startswith(("XAU", "GOLD", "XAG")):
        return 2
    return 5


def _default_price(symbol: str) -> float:
    s = symbol.upper()
    known = {
        "EURUSD": 1.09, "GBPUSD": 1.27, "AUDUSD": 0.66, "NZDUSD": 0.60,
        "USDCHF": 0.88, "USDCAD": 1.36, "USDJPY": 152.0, "EURJPY": 165.0,
        "EURGBP": 0.855, "XAUUSD": 2350.0, "XAGUSD": 28.0,
    }
    return known.get(s, 1.10)


def _default_spec(symbol: str) -> SymbolSpec:
    """Kontraktdaten schätzen, wenn kein Terminal erreichbar ist.

    Für Backtests auf zwischengespeicherten Daten brauchbar - im Livebetrieb
    kommen die echten Werte immer vom Broker.
    """
    digits = _default_digits(symbol)
    point = 10.0 ** (-digits)
    is_metal = symbol.upper().startswith(("XAU", "XAG", "GOLD"))
    return SymbolSpec(
        name=symbol,
        digits=digits,
        point=point,
        tick_size=point,
        tick_value=1.0 if not is_metal else 1.0,
        contract_size=100.0 if is_metal else 100_000.0,
        volume_min=0.01,
        volume_step=0.01,
        spread_points=20.0 if is_metal else 12.0,
    )
