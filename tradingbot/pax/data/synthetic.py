"""Synthetischer Markt für Tests und Trockenläufe.

Kein Ersatz für echte Kursdaten, aber deutlich näher an der Realität als
weißes Rauschen: Regimewechsel zwischen Trend und Range, Volatilitätsclusterung
im Stil eines GARCH-Prozesses, Tagesrhythmus der Volatilität, Wochenendlücken
und Ausreißer-Kerzen. Damit lassen sich Pipeline, Backtest und Lernschleife
vollständig prüfen, ohne dass ein MT5-Terminal läuft.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ..types import SymbolSpec, Timeframe


class SyntheticMarket:
    """Erzeugt reproduzierbare OHLCV-Reihen mit marktähnlichen Eigenschaften."""

    def __init__(
        self,
        symbol: str = "EURUSD",
        start_price: float = 1.1000,
        seed: int = 7,
        base_vol: float = 0.0006,
        digits: int = 5,
    ) -> None:
        self.symbol = symbol
        self.start_price = start_price
        self.base_vol = base_vol
        self.digits = digits
        self.rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------ #

    def spec(self) -> SymbolSpec:
        point = 10.0 ** (-self.digits)
        return SymbolSpec(
            name=self.symbol,
            digits=self.digits,
            point=point,
            tick_size=point,
            tick_value=1.0 if self.digits == 5 else 1.0,
            contract_size=100_000.0,
            spread_points=12.0,
        )

    def generate(
        self,
        bars: int = 20_000,
        timeframe: "str | Timeframe" = Timeframe.M15,
        end: "datetime | None" = None,
    ) -> pd.DataFrame:
        """OHLCV-DataFrame mit UTC-Index erzeugen."""
        tf = Timeframe.parse(timeframe)
        rng = self.rng
        n = int(bars)

        # 1) Regime-Kette: 0 = Range, 1 = Aufwärtstrend, 2 = Abwärtstrend.
        #    Persistente Zustände, damit Trends lange genug für Struktur halten.
        regimes = self._markov_regimes(n, rng)
        drift_map = np.array([0.0, 0.55, -0.55])
        drift = drift_map[regimes] * self.base_vol * 0.35

        # 2) Volatilitätsclusterung (GARCH(1,1)-artig).
        vol = self._garch_vol(n, rng)

        # 3) Tagesrhythmus: London/New-York-Überschneidung ist am lebhaftesten.
        times = self._bar_times(n, tf, end)
        hour = np.array([t.hour + t.minute / 60.0 for t in times])
        seasonal = 0.55 + 0.9 * np.exp(-0.5 * ((hour - 9.0) / 3.0) ** 2) \
            + 1.0 * np.exp(-0.5 * ((hour - 14.5) / 2.5) ** 2)
        vol = vol * seasonal

        # 4) Rendite je Balken, mit fetten Rändern (Student-t statt Normal).
        shocks = rng.standard_t(df=4.0, size=n) / np.sqrt(2.0)
        returns = drift + vol * shocks

        # 5) Gelegentliche Sprünge (Nachrichten).
        jump_mask = rng.random(n) < 0.0015
        returns[jump_mask] += rng.normal(0, 8.0 * self.base_vol, jump_mask.sum())

        # 6) Mittelwertrückkehr innerhalb von Range-Phasen: die Struktur, an der
        #    Price-Action-Handel überhaupt Halt findet.
        close = np.empty(n, dtype=float)
        level = float(self.start_price)
        anchor = level
        for i in range(n):
            if regimes[i] == 0:
                pull = -0.02 * (level - anchor) / max(level, 1e-9)
                returns[i] += pull
            else:
                anchor = 0.995 * anchor + 0.005 * level
            level *= float(np.exp(returns[i]))
            close[i] = level

        open_ = np.empty(n, dtype=float)
        open_[0] = self.start_price
        open_[1:] = close[:-1]

        # 7) Dochte: proportional zur Balkenvolatilität, asymmetrisch verteilt.
        span = np.abs(close - open_)
        wick_scale = vol * close * rng.uniform(0.4, 1.9, n)
        up_wick = wick_scale * rng.random(n)
        dn_wick = wick_scale * rng.random(n)
        high = np.maximum(open_, close) + up_wick + 0.15 * span
        low = np.minimum(open_, close) - dn_wick - 0.15 * span

        # 8) Wochenendlücken zwischen Freitagsschluss und Sonntagsöffnung.
        gaps = self._weekend_gaps(times, rng)
        if gaps.any():
            shift = np.cumsum(np.where(gaps, rng.normal(0, 3.0 * self.base_vol, n), 0.0))
            factor = np.exp(shift)
            open_, high, low, close = open_ * factor, high * factor, low * factor, close * factor

        volume = np.round(
            rng.gamma(shape=3.0, scale=250.0, size=n) * seasonal * (1 + 3 * np.abs(shocks) / 4)
        )

        df = pd.DataFrame(
            {
                "open": np.round(open_, self.digits),
                "high": np.round(high, self.digits),
                "low": np.round(low, self.digits),
                "close": np.round(close, self.digits),
                "volume": volume,
                "spread": np.round(10 + 6 * rng.random(n) / np.maximum(seasonal, 0.3)),
                "regime_true": regimes,  # nur zur Auswertung, nie als Feature
            },
            index=pd.DatetimeIndex(times, name="time"),
        )
        # Konsistenz erzwingen: High/Low müssen Open/Close umschließen.
        df["high"] = df[["high", "open", "close"]].max(axis=1)
        df["low"] = df[["low", "open", "close"]].min(axis=1)
        return df

    # ------------------------------------------------------------------ #

    @staticmethod
    def _markov_regimes(n: int, rng: np.random.Generator) -> np.ndarray:
        """Persistente Regimekette - Trends dauern im Mittel ~150 Balken."""
        stay, to_trend = 0.985, 0.0075
        trans = np.array(
            [
                [stay, to_trend, to_trend],
                [0.012, 0.985, 0.003],
                [0.012, 0.003, 0.985],
            ]
        )
        out = np.zeros(n, dtype=int)
        state = 0
        for i in range(n):
            state = int(rng.choice(3, p=trans[state]))
            out[i] = state
        return out

    def _garch_vol(self, n: int, rng: np.random.Generator) -> np.ndarray:
        """GARCH(1,1): omega + alpha * eps² + beta * sigma²."""
        omega, alpha, beta = self.base_vol**2 * 0.05, 0.09, 0.88
        var = np.empty(n)
        var[0] = self.base_vol**2
        eps = rng.standard_normal(n) * self.base_vol
        for i in range(1, n):
            var[i] = omega + alpha * eps[i - 1] ** 2 + beta * var[i - 1]
            eps[i] = rng.standard_normal() * np.sqrt(var[i])
        return np.sqrt(var)

    @staticmethod
    def _bar_times(n: int, tf: Timeframe, end: "datetime | None") -> list[datetime]:
        """Balkenzeiten rückwärts vom Ende, Wochenenden werden übersprungen."""
        end = end or datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        step = timedelta(minutes=tf.minutes)
        times: list[datetime] = []
        t = end
        while len(times) < n:
            # Forex: Samstag ganz, Freitag ab 22:00 und Sonntag bis 22:00 UTC frei
            wd = t.weekday()
            closed = wd == 5 or (wd == 4 and t.hour >= 22) or (wd == 6 and t.hour < 22)
            if not closed:
                times.append(t)
            t -= step
        return list(reversed(times))

    @staticmethod
    def _weekend_gaps(times: list[datetime], rng: np.random.Generator) -> np.ndarray:
        gaps = np.zeros(len(times), dtype=bool)
        for i in range(1, len(times)):
            if times[i].weekday() < times[i - 1].weekday():
                gaps[i] = True
        return gaps

    def generate_multi(
        self, bars: int, timeframes: "list[str | Timeframe]", end: "datetime | None" = None
    ) -> dict[str, pd.DataFrame]:
        """Mehrere Zeiteinheiten, konsistent aus der feinsten aggregiert.

        Wichtig für Tests der Mehrfach-Zeitebenen-Analyse: die groben Rahmen
        müssen echte Aggregate der feinen sein, sonst widersprechen sie sich.
        """
        tfs = sorted((Timeframe.parse(t) for t in timeframes), key=lambda t: t.minutes)
        base = tfs[0]
        factor = max(t.minutes for t in tfs) // base.minutes
        fine = self.generate(bars=bars * max(1, factor), timeframe=base, end=end)
        out = {base.value: fine}
        for tf in tfs[1:]:
            out[tf.value] = resample_ohlcv(fine, tf).tail(bars)
        out[base.value] = fine.tail(bars * max(1, factor))
        return out


def resample_ohlcv(df: pd.DataFrame, timeframe: "str | Timeframe") -> pd.DataFrame:
    """OHLCV auf eine gröbere Zeiteinheit verdichten.

    Nur abgeschlossene Perioden bleiben erhalten; die letzte, möglicherweise
    unvollständige Periode wird verworfen.
    """
    tf = Timeframe.parse(timeframe)
    agg: dict[str, str] = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    if "spread" in df.columns:
        agg["spread"] = "mean"
    out = df.resample(tf.pandas_freq, label="left", closed="left").agg(agg).dropna(subset=["open"])
    return out
