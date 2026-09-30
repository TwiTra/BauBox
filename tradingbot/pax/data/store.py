"""Lokaler Kursdatenspeicher.

Historie einmal holen, danach nur noch die neuen Balken nachladen. Das spart im
Livebetrieb Zeit und macht Backtests reproduzierbar, weil sie auf einer
festgehaltenen Datei laufen statt auf dem, was der Broker gerade liefert.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from ..types import Timeframe
from ..utils import ensure_dir, get_logger

log = get_logger("store")

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


class BarStore:
    """Balken auf Platte halten und inkrementell aktualisieren."""

    def __init__(self, cache_dir: "str | Path" = "data_cache", client: object = None) -> None:
        self.dir = ensure_dir(cache_dir)
        self.client = client
        self._format = "parquet" if _parquet_available() else "csv"

    # ------------------------------------------------------------------ #

    def path(self, symbol: str, timeframe: "str | Timeframe") -> Path:
        tf = Timeframe.parse(timeframe)
        safe = "".join(ch for ch in symbol if ch.isalnum() or ch in "._-")
        return self.dir / f"{safe}_{tf.value}.{self._format}"

    def has(self, symbol: str, timeframe: "str | Timeframe") -> bool:
        return self.path(symbol, timeframe).exists()

    def read(self, symbol: str, timeframe: "str | Timeframe") -> pd.DataFrame:
        """Gespeicherte Balken laden. Fehlt die Datei, kommt ein leerer Rahmen."""
        p = self.path(symbol, timeframe)
        if not p.exists():
            return _empty_frame()
        try:
            if self._format == "parquet":
                df = pd.read_parquet(p)
            else:
                df = pd.read_csv(p, index_col=0, parse_dates=True)
        except Exception as exc:  # pragma: no cover - beschädigter Cache
            log.warning("Cache %s nicht lesbar (%s) - wird neu aufgebaut", p, exc)
            return _empty_frame()
        return _normalize(df)

    def write(self, symbol: str, timeframe: "str | Timeframe", df: pd.DataFrame) -> Path:
        p = self.path(symbol, timeframe)
        df = _normalize(df)
        tmp = p.with_suffix(p.suffix + ".tmp")
        if self._format == "parquet":
            df.to_parquet(tmp)
        else:
            df.to_csv(tmp)
        tmp.replace(p)  # atomar: ein Absturz hinterlässt keinen halben Cache
        return p

    def append(self, symbol: str, timeframe: "str | Timeframe", new: pd.DataFrame) -> pd.DataFrame:
        """Neue Balken einfügen; Überschneidungen gewinnt die neue Lieferung."""
        old = self.read(symbol, timeframe)
        merged = _merge(old, new)
        self.write(symbol, timeframe, merged)
        return merged

    # ------------------------------------------------------------------ #

    def load(
        self,
        symbol: str,
        timeframe: "str | Timeframe",
        bars: int = 20_000,
        update: bool = True,
        max_age: timedelta = timedelta(minutes=5),
    ) -> pd.DataFrame:
        """Balken liefern - aus dem Cache, bei Bedarf frisch aus MT5 ergänzt."""
        tf = Timeframe.parse(timeframe)
        cached = self.read(symbol, tf)

        if not update or self.client is None:
            return cached.tail(bars) if len(cached) else cached

        need_full = len(cached) < bars
        if not need_full and len(cached):
            age = datetime.now(timezone.utc) - cached.index[-1].to_pydatetime()
            if age < max_age:
                return cached.tail(bars)

        try:
            if need_full:
                fresh = self.client.rates(symbol, tf, count=bars)  # type: ignore[attr-defined]
            else:
                # Nur die Lücke seit dem letzten gespeicherten Balken holen,
                # mit etwas Überlappung gegen Randfälle.
                since = cached.index[-1].to_pydatetime() - timedelta(minutes=tf.minutes * 5)
                fresh = self.client.rates_range(symbol, tf, since)  # type: ignore[attr-defined]
        except Exception as exc:
            if len(cached):
                log.warning(
                    "Aktualisierung von %s %s fehlgeschlagen (%s) - nutze Cache-Stand %s",
                    symbol, tf.value, exc, cached.index[-1],
                )
                return cached.tail(bars)
            raise

        merged = _merge(cached, fresh)
        self.write(symbol, tf, merged)
        return merged.tail(bars)

    def load_multi(
        self,
        symbol: str,
        timeframes: "list[str | Timeframe]",
        bars: int = 20_000,
        update: bool = True,
    ) -> dict[str, pd.DataFrame]:
        """Mehrere Zeiteinheiten auf einmal laden."""
        out: dict[str, pd.DataFrame] = {}
        for tf in timeframes:
            key = Timeframe.parse(tf).value
            out[key] = self.load(symbol, tf, bars=bars, update=update)
        return out

    def coverage(self) -> pd.DataFrame:
        """Übersicht, was im Cache liegt - für die Statusanzeige der CLI."""
        rows = []
        for p in sorted(self.dir.glob(f"*.{self._format}")):
            stem = p.stem
            symbol, _, tf = stem.rpartition("_")
            try:
                df = self.read(symbol, tf)
            except Exception:  # pragma: no cover
                continue
            if df.empty:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": tf,
                    "bars": len(df),
                    "von": df.index[0],
                    "bis": df.index[-1],
                    "MB": round(p.stat().st_size / 1e6, 2),
                }
            )
        return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=OHLCV_COLUMNS,
        index=pd.DatetimeIndex([], tz="UTC", name="time"),
    ).astype("float64")


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Index als UTC, Spalten kleingeschrieben, Duplikate weg, sortiert."""
    if df is None or len(df) == 0:
        return _empty_frame()
    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    if not isinstance(df.index, pd.DatetimeIndex):
        for candidate in ("time", "date", "datetime"):
            if candidate in df.columns:
                df = df.set_index(candidate)
                break
        df.index = pd.to_datetime(df.index, utc=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df.index.name = "time"
    missing = [c for c in ("open", "high", "low", "close") if c not in df.columns]
    if missing:
        raise ValueError(f"Kursdaten unvollständig, es fehlen: {missing}")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _merge(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    if old is None or old.empty:
        return _normalize(new)
    if new is None or new.empty:
        return _normalize(old)
    old, new = _normalize(old), _normalize(new)
    combined = pd.concat([old, new])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    return combined


def _parquet_available() -> bool:
    try:
        import pyarrow  # noqa: F401

        return True
    except ImportError:
        try:
            import fastparquet  # noqa: F401

            return True
        except ImportError:
            return False
