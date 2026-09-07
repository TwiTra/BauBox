"""Marktregime erkennen.

Dieselbe Strategie, die im Trend Geld verdient, verbrennt es in der Range. Wer
das Regime nicht kennt, handelt blind. Hier werden drei Achsen bestimmt:

* **Volatilität** aus dem Perzentilrang des ATR
* **Trendhaftigkeit** aus ADX, Effizienzquotient, Hurst und Regressionsgüte
* **Liquidität** aus Tageszeit und Handelsvolumen

Alle Grenzen sind rollierende Quantile, keine festen Zahlen: 20 ATR-Pips sind
im Gold etwas völlig anderes als im EURUSD.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..types import VolRegime
from . import indicators as ind


class RegimeDetector:
    """Bestimmt Volatilitäts- und Trendregime je Balken."""

    def __init__(self, lookback: int = 250, atr_period: int = 14, adx_period: int = 14) -> None:
        self.lookback = int(lookback)
        self.atr_period = int(atr_period)
        self.adx_period = int(adx_period)

    def analyze(self, df: pd.DataFrame, atr: "pd.Series | None" = None) -> pd.DataFrame:
        if atr is None:
            atr = ind.atr(df, self.atr_period)
        close = df["close"]
        lb = self.lookback

        # --- Volatilität ---------------------------------------------- #
        atr_pct = (atr / close.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
        vol_rank = atr_pct.rolling(lb, min_periods=max(30, lb // 5)).rank(pct=True)
        vol_regime = pd.Series(
            np.select(
                [vol_rank < 0.25, vol_rank < 0.70, vol_rank < 0.92],
                [0.0, 1.0, 2.0],
                default=3.0,
            ),
            index=df.index,
        ).where(vol_rank.notna(), 1.0)

        # Volatilitätsausdehnung: schnelle gegen langsame Volatilität.
        # Ein Wert deutlich über 1 heißt: die Bewegung nimmt gerade Fahrt auf.
        vol_expansion = (
            atr / atr.rolling(50, min_periods=20).mean().replace(0, np.nan)
        ).clip(0, 4)

        # --- Trendhaftigkeit ------------------------------------------ #
        dm = ind.directional_movement(df, self.adx_period)
        adx = dm["adx"]
        er = ind.efficiency_ratio(close, 20)
        h = ind.hurst(close, 120)
        r2 = ind.linreg_r2(close, 20)

        # Vier unabhängige Belege, jeder auf [0, 1] gebracht und gemittelt.
        # Einzeln ist jeder angreifbar, zusammen sind sie erstaunlich stabil.
        trendiness = (
            0.30 * ((adx - 15.0) / 25.0).clip(0, 1)
            + 0.30 * (er / 0.45).clip(0, 1)
            + 0.20 * ((h - 0.45) / 0.25).clip(0, 1)
            + 0.20 * r2.clip(0, 1)
        )
        direction = np.sign(dm["plus_di"] - dm["minus_di"])
        trend_regime = pd.Series(
            np.select([trendiness > 0.55, trendiness < 0.30], [1.0, -1.0], default=0.0),
            index=df.index,
        )  # 1 = Trend, -1 = Range, 0 = Übergang

        # --- Liquidität ----------------------------------------------- #
        hour = df.index.hour + df.index.minute / 60.0
        # London 07-16 UTC, New York 12-21 UTC, Überschneidung 12-16 am dichtesten
        liquidity = pd.Series(
            np.clip(
                0.35
                + 0.45 * ((hour >= 7) & (hour < 16)).astype(float)
                + 0.35 * ((hour >= 12) & (hour < 21)).astype(float),
                0,
                1,
            ),
            index=df.index,
        )
        vol_z = ind.volume_zscore(df, 50).fillna(0.0)

        out = pd.DataFrame(
            {
                "vol_rank": vol_rank,
                "vol_regime": vol_regime,
                "vol_expansion": vol_expansion,
                "trendiness": trendiness,
                "trend_regime": trend_regime,
                "trend_direction": direction,
                "regime_score": trendiness * direction,
                "liquidity_score": liquidity,
                "volume_z": vol_z.clip(-4, 4),
                "hour_sin": np.sin(2 * np.pi * hour / 24.0),
                "hour_cos": np.cos(2 * np.pi * hour / 24.0),
                "dow": df.index.dayofweek.astype(float),
            },
            index=df.index,
        )
        return out.fillna({"vol_rank": 0.5, "trendiness": 0.35, "vol_expansion": 1.0}).fillna(0.0)

    @staticmethod
    def to_enum(value: float) -> VolRegime:
        return {0.0: VolRegime.LOW, 1.0: VolRegime.NORMAL, 2.0: VolRegime.HIGH}.get(
            float(value), VolRegime.EXTREME
        )

    @staticmethod
    def label(row: pd.Series) -> str:
        """Regime in einem Satz - für Protokoll und Signalbegründung."""
        vol = {0.0: "ruhig", 1.0: "normal", 2.0: "volatil", 3.0: "extrem"}.get(
            float(row.get("vol_regime", 1.0)), "normal"
        )
        tr = float(row.get("trend_regime", 0.0))
        dirn = float(row.get("trend_direction", 0.0))
        if tr > 0:
            trend = "Aufwärtstrend" if dirn > 0 else "Abwärtstrend"
        elif tr < 0:
            trend = "Seitwärtsphase"
        else:
            trend = "Übergang"
        return f"{trend}, {vol}e Volatilität"
