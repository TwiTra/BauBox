"""Handelszeiten- und Nachrichtenfilter.

Price-Action-Handel lebt von Liquidität. Der beste Aufbau in einer toten
Asien-Session ist keiner. Und fünf Minuten vor einem Zinsentscheid gilt keine
Chartlehre - deshalb blockt dieses Modul solche Fenster aus.
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

import pandas as pd

from ..config import SessionConfig
from ..utils import get_logger

log = get_logger("sessions")

_IMPACT_RANK = {"low": 1, "niedrig": 1, "medium": 2, "mittel": 2, "high": 3, "hoch": 3}


class SessionFilter:
    """Entscheidet, ob zu einem Zeitpunkt gehandelt werden darf."""

    def __init__(self, cfg: SessionConfig, symbol_currencies: "dict[str, set[str]] | None" = None) -> None:
        self.cfg = cfg
        self.symbol_currencies = symbol_currencies or {}
        self._windows = self._parse_windows(cfg.trade_sessions)
        self._news = self._load_news(cfg.news_file, cfg.news_min_impact)

    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_windows(raw: list[list[str]]) -> list[tuple[dtime, dtime]]:
        windows: list[tuple[dtime, dtime]] = []
        for pair in raw:
            if len(pair) != 2:
                log.warning("Ungültiges Sessionfenster übersprungen: %r", pair)
                continue
            try:
                start = dtime.fromisoformat(pair[0])
                end = dtime.fromisoformat(pair[1])
            except ValueError:
                log.warning("Ungültige Uhrzeit im Sessionfenster: %r", pair)
                continue
            windows.append((start, end))
        return windows

    @staticmethod
    def _load_news(path: str, min_impact: str) -> pd.DataFrame:
        """Optionale Nachrichtendatei laden: Spalten time, impact, currency."""
        if not path:
            return pd.DataFrame(columns=["time", "impact", "currency"])
        p = Path(path)
        if not p.exists():
            return pd.DataFrame(columns=["time", "impact", "currency"])
        try:
            df = pd.read_csv(p)
        except Exception as exc:  # pragma: no cover - defekte Datei darf nicht stoppen
            log.warning("Nachrichtendatei %s nicht lesbar: %s", p, exc)
            return pd.DataFrame(columns=["time", "impact", "currency"])
        if "time" not in df.columns:
            log.warning("Nachrichtendatei %s ohne Spalte 'time' - wird ignoriert", p)
            return pd.DataFrame(columns=["time", "impact", "currency"])
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        df = df.dropna(subset=["time"])
        if "impact" not in df.columns:
            df["impact"] = "high"
        if "currency" not in df.columns:
            df["currency"] = ""
        threshold = _IMPACT_RANK.get(str(min_impact).lower(), 3)
        df["_rank"] = df["impact"].astype(str).str.lower().map(_IMPACT_RANK).fillna(3)
        df = df[df["_rank"] >= threshold]
        log.info("%d Nachrichtentermine geladen aus %s", len(df), p)
        return df.sort_values("time").reset_index(drop=True)

    # ------------------------------------------------------------------ #

    def in_session(self, ts: datetime) -> bool:
        """Liegt der Zeitpunkt in einem konfigurierten Handelsfenster?"""
        ts = self._as_utc(ts)
        if ts.weekday() not in self.cfg.trade_weekdays:
            return False
        if ts.weekday() == 4 and ts.hour >= self.cfg.friday_close_hour_utc:
            return False
        if self.cfg.avoid_first_minutes_of_day:
            if ts.hour == 0 and ts.minute < self.cfg.avoid_first_minutes_of_day:
                return False
        if not self._windows:
            return True
        t = ts.timetz().replace(tzinfo=None)
        for start, end in self._windows:
            if start <= end:
                if start <= t < end:
                    return True
            else:  # Fenster über Mitternacht
                if t >= start or t < end:
                    return True
        return False

    def news_block(self, ts: datetime, symbol: str = "") -> "str | None":
        """Grund, falls ein Nachrichtenfenster den Handel sperrt, sonst None."""
        if self._news.empty:
            return None
        ts = self._as_utc(ts)
        before = timedelta(minutes=self.cfg.news_block_minutes_before)
        after = timedelta(minutes=self.cfg.news_block_minutes_after)
        window = self._news[
            (self._news["time"] >= ts - after) & (self._news["time"] <= ts + before)
        ]
        if window.empty:
            return None
        currencies = self.symbol_currencies.get(symbol) or self._infer_currencies(symbol)
        for _, row in window.iterrows():
            cur = str(row.get("currency", "")).upper().strip()
            if cur and currencies and cur not in currencies:
                continue
            when = row["time"].to_pydatetime()
            return f"Nachricht {row.get('impact', '?')} {cur or '(alle)'} um {when:%H:%M} UTC"
        return None

    @staticmethod
    def _infer_currencies(symbol: str) -> set[str]:
        """Aus dem Symbolnamen die beteiligten Währungen raten."""
        s = "".join(ch for ch in symbol.upper() if ch.isalpha())
        if len(s) >= 6:
            return {s[:3], s[3:6]}
        if s.startswith("XAU") or s.startswith("GOLD"):
            return {"XAU", "USD"}
        return set()

    def check(self, ts: datetime, symbol: str = "") -> tuple[bool, str]:
        """(darf gehandelt werden, Begründung)."""
        if not self.in_session(ts):
            return False, "außerhalb der Handelszeiten"
        news = self.news_block(ts, symbol)
        if news:
            return False, news
        return True, "Handelszeit"

    @staticmethod
    def _as_utc(ts: datetime) -> datetime:
        if isinstance(ts, pd.Timestamp):
            ts = ts.to_pydatetime()
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    def mask(self, index: pd.DatetimeIndex, symbol: str = "") -> pd.Series:
        """Boolean-Maske über einen ganzen Index - für Backtests."""
        return pd.Series(
            [self.check(ts, symbol)[0] for ts in index], index=index, name="tradable"
        )
