"""Institutionelle Price-Action-Konzepte: Order Blocks, Imbalances, Liquidität.

Die Kernidee hinter allen dreien ist dieselbe: große Orders lassen Spuren im
Chart, und der Kurs kehrt überdurchschnittlich oft dorthin zurück.

* **Fair Value Gap (FVG)**: drei Kerzen, bei denen sich Kerze 1 und 3 nicht
  überlappen. In der Lücke gab es keinen fairen Handel - sie wird oft
  nachgeholt.
* **Order Block (OB)**: die letzte Gegenkerze vor einer Impulsbewegung, die die
  Struktur bricht. Dort wurde die Position aufgebaut.
* **Liquidität**: gleiche Hochs oder Tiefs. Dort liegen die Stops - und genau
  dorthin läuft der Kurs, bevor er dreht.

Zeitliche Sauberkeit ist hier besonders heikel: ein Order Block wird erst
*rückwirkend* erkennbar, wenn der Impuls gelaufen ist. Jede Zone trägt deshalb
einen Bestätigungsindex, und die Merkmale je Balken nutzen ausschließlich
Zonen, die zu diesem Zeitpunkt bereits bekannt waren.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..types import Direction, StructureEvent, Swing, Zone


@dataclass
class SMCResult:
    zones: list[Zone] = field(default_factory=list)
    frame: pd.DataFrame = field(default_factory=pd.DataFrame)

    def active_zones(self, kind: str = "", direction: "Direction | None" = None) -> list[Zone]:
        return [
            z
            for z in self.zones
            if not z.mitigated and (not kind or z.kind == kind) and (direction is None or z.direction is direction)
        ]


class SMCAnalyzer:
    """Findet Zonen und verdichtet sie zu Merkmalen je Balken."""

    def __init__(
        self,
        fvg_min_atr: float = 0.15,
        ob_lookback: int = 40,
        max_zones: int = 12,
        zone_max_age: int = 300,
        equal_level_atr: float = 0.15,
    ) -> None:
        self.fvg_min_atr = float(fvg_min_atr)
        self.ob_lookback = int(ob_lookback)
        self.max_zones = int(max_zones)
        self.zone_max_age = int(zone_max_age)
        self.equal_level_atr = float(equal_level_atr)

    # ------------------------------------------------------------------ #
    # Zonenfindung
    # ------------------------------------------------------------------ #

    def find_fvgs(self, df: pd.DataFrame, atr: pd.Series) -> list[Zone]:
        """Drei-Kerzen-Imbalances. Bekannt ab der dritten Kerze."""
        h = df["high"].to_numpy(dtype=float)
        l = df["low"].to_numpy(dtype=float)
        a = atr.to_numpy(dtype=float)
        times = df.index.to_pydatetime()
        zones: list[Zone] = []

        for i in range(2, len(df)):
            ref = a[i]
            if not np.isfinite(ref) or ref <= 0:
                continue
            # Bullische Lücke: Hoch von Kerze i-2 liegt unter dem Tief von Kerze i
            gap_up = l[i] - h[i - 2]
            if gap_up >= self.fvg_min_atr * ref:
                zones.append(
                    Zone(
                        kind="fvg",
                        direction=Direction.LONG,
                        top=float(l[i]),
                        bottom=float(h[i - 2]),
                        created_index=i,
                        created_time=times[i],
                        strength=float(min(1.0, gap_up / (1.5 * ref))),
                        meta={"confirmed_index": i},
                    )
                )
            gap_dn = l[i - 2] - h[i]
            if gap_dn >= self.fvg_min_atr * ref:
                zones.append(
                    Zone(
                        kind="fvg",
                        direction=Direction.SHORT,
                        top=float(l[i - 2]),
                        bottom=float(h[i]),
                        created_index=i,
                        created_time=times[i],
                        strength=float(min(1.0, gap_dn / (1.5 * ref))),
                        meta={"confirmed_index": i},
                    )
                )
        return zones

    def find_order_blocks(
        self, df: pd.DataFrame, atr: pd.Series, events: list[StructureEvent]
    ) -> list[Zone]:
        """Letzte Gegenkerze vor dem Impuls, der die Struktur gebrochen hat.

        Der Order Block gilt erst ab dem Bruchbalken als bekannt - vorher weiß
        niemand, dass aus dieser Kerze ein Impuls wurde.
        """
        o = df["open"].to_numpy(dtype=float)
        h = df["high"].to_numpy(dtype=float)
        l = df["low"].to_numpy(dtype=float)
        c = df["close"].to_numpy(dtype=float)
        a = atr.to_numpy(dtype=float)
        times = df.index.to_pydatetime()
        zones: list[Zone] = []

        for ev in events:
            i = ev.index
            ref = a[i] if np.isfinite(a[i]) and a[i] > 0 else np.nan
            if not np.isfinite(ref):
                continue
            bullish = ev.direction is Direction.LONG
            start = max(0, i - self.ob_lookback)
            found = None
            # Rückwärts bis zur letzten Kerze, die gegen die Bruchrichtung schloss
            for j in range(i - 1, start - 1, -1):
                is_opposing = (c[j] < o[j]) if bullish else (c[j] > o[j])
                if is_opposing:
                    found = j
                    break
            if found is None:
                continue
            # Die Bewegung vom Order Block bis zum Bruch muss ein echter Impuls
            # sein, sonst ist es nur eine beliebige Gegenkerze.
            impulse = abs(c[i] - c[found]) / ref
            if impulse < 1.0:
                continue
            zones.append(
                Zone(
                    kind="order_block",
                    direction=Direction.LONG if bullish else Direction.SHORT,
                    top=float(max(o[found], c[found], h[found] if bullish else max(o[found], c[found]))),
                    bottom=float(min(o[found], c[found], l[found] if not bullish else min(o[found], c[found]))),
                    created_index=found,
                    created_time=times[found],
                    strength=float(min(1.0, impulse / 4.0)),
                    meta={"confirmed_index": i, "impulse_atr": float(impulse), "event": ev.kind},
                )
            )
        return zones

    def find_liquidity_pools(
        self, swings: list[Swing], atr: pd.Series, lookback: int = 3
    ) -> list[Zone]:
        """Gleiche Hochs/Tiefs - Stop-Ansammlungen, auf die der Markt zusteuert."""
        a = atr.to_numpy(dtype=float)
        zones: list[Zone] = []
        highs = [s for s in swings if s.is_high]
        lows = [s for s in swings if not s.is_high]

        for group, is_high in ((highs, True), (lows, False)):
            for pos, swing in enumerate(group):
                ref = a[swing.index] if np.isfinite(a[swing.index]) and a[swing.index] > 0 else np.nan
                if not np.isfinite(ref):
                    continue
                peers = [
                    other
                    for other in group[max(0, pos - lookback) : pos]
                    if abs(other.price - swing.price) <= self.equal_level_atr * ref
                ]
                if not peers:
                    continue
                prices = [swing.price] + [p.price for p in peers]
                # Der spätere der beiden Punkte bestimmt, ab wann die Zone bekannt ist.
                zones.append(
                    Zone(
                        kind="liquidity",
                        direction=Direction.SHORT if is_high else Direction.LONG,
                        top=float(max(prices) + 0.05 * ref),
                        bottom=float(min(prices) - 0.05 * ref),
                        created_index=swing.index,
                        created_time=swing.time,
                        strength=float(min(1.0, 0.4 + 0.2 * len(prices))),
                        meta={"confirmed_index": swing.index, "count": len(prices), "equal": True},
                    )
                )
        return zones

    # ------------------------------------------------------------------ #
    # Merkmale je Balken
    # ------------------------------------------------------------------ #

    def analyze(
        self,
        df: pd.DataFrame,
        atr: pd.Series,
        events: list[StructureEvent],
        swings: list[Swing],
        structure_frame: "pd.DataFrame | None" = None,
        lookback_confirm: int = 3,
    ) -> SMCResult:
        """Zonen finden und je Balken zu Kennzahlen verdichten."""
        n = len(df)
        zones = (
            self.find_fvgs(df, atr)
            + self.find_order_blocks(df, atr, events)
            + self.find_liquidity_pools(swings, atr)
        )
        # Liquiditätszonen werden erst mit dem Swing bestätigt, der sie erzeugt.
        for z in zones:
            if z.kind == "liquidity":
                z.meta["confirmed_index"] = z.meta.get("confirmed_index", z.created_index) + lookback_confirm

        by_confirm: dict[int, list[Zone]] = {}
        for z in zones:
            by_confirm.setdefault(int(z.meta.get("confirmed_index", z.created_index)), []).append(z)

        h = df["high"].to_numpy(dtype=float)
        l = df["low"].to_numpy(dtype=float)
        c = df["close"].to_numpy(dtype=float)
        a = atr.to_numpy(dtype=float)

        cols = {
            name: np.full(n, np.nan)
            for name in (
                "fvg_bull_dist_atr", "fvg_bear_dist_atr", "ob_bull_dist_atr", "ob_bear_dist_atr",
                "liq_above_dist_atr", "liq_below_dist_atr",
            )
        }
        for name in (
            "fvg_in_bull", "fvg_in_bear", "ob_in_bull", "ob_in_bear",
            "fvg_count_bull", "fvg_count_bear", "ob_count_bull", "ob_count_bear",
            "zone_confluence", "smc_score",
        ):
            cols[name] = np.zeros(n)

        active: list[Zone] = []
        for i in range(n):
            for z in by_confirm.get(i, ()):
                active.append(z)
            ref = a[i]
            if not np.isfinite(ref) or ref <= 0:
                continue

            # Zonen aussortieren: durchhandelt (mitigiert) oder zu alt
            still: list[Zone] = []
            for z in active:
                if i - z.created_index > self.zone_max_age:
                    continue
                if z.kind in ("fvg", "order_block"):
                    # Vollständig durchhandelt heißt: der Kurs hat die Zone
                    # von der Gegenseite verlassen - dann ist sie verbraucht.
                    if z.direction is Direction.LONG and c[i] < z.bottom:
                        continue
                    if z.direction is Direction.SHORT and c[i] > z.top:
                        continue
                still.append(z)
            active = still[-400:]  # Sicherheitsdeckel gegen unbegrenztes Wachstum

            price = c[i]
            best = {
                "fvg_bull": None, "fvg_bear": None,
                "ob_bull": None, "ob_bear": None,
                "liq_above": None, "liq_below": None,
            }
            counts = {"fvg_bull": 0, "fvg_bear": 0, "ob_bull": 0, "ob_bear": 0}
            confluence = 0.0

            for z in active:
                dist = z.distance(price) / ref
                is_long = z.direction is Direction.LONG
                if z.kind == "fvg":
                    key = "fvg_bull" if is_long else "fvg_bear"
                elif z.kind == "order_block":
                    key = "ob_bull" if is_long else "ob_bear"
                else:  # Liquidität: über oder unter dem Kurs
                    key = "liq_below" if z.top < price else ("liq_above" if z.bottom > price else None)
                    if key is None:
                        continue
                    if best[key] is None or dist < best[key][0]:
                        best[key] = (dist, z)
                    continue
                counts[key] += 1
                if best[key] is None or dist < best[key][0]:
                    best[key] = (dist, z)
                if dist < 0.25:  # Kurs steht praktisch in der Zone
                    confluence += z.strength * (1 if is_long else -1)

            for key, target in (
                ("fvg_bull", "fvg_bull_dist_atr"), ("fvg_bear", "fvg_bear_dist_atr"),
                ("ob_bull", "ob_bull_dist_atr"), ("ob_bear", "ob_bear_dist_atr"),
                ("liq_above", "liq_above_dist_atr"), ("liq_below", "liq_below_dist_atr"),
            ):
                if best[key] is not None:
                    cols[target][i] = min(best[key][0], 20.0)

            cols["fvg_in_bull"][i] = 1.0 if best["fvg_bull"] and best["fvg_bull"][0] == 0 else 0.0
            cols["fvg_in_bear"][i] = 1.0 if best["fvg_bear"] and best["fvg_bear"][0] == 0 else 0.0
            cols["ob_in_bull"][i] = 1.0 if best["ob_bull"] and best["ob_bull"][0] == 0 else 0.0
            cols["ob_in_bear"][i] = 1.0 if best["ob_bear"] and best["ob_bear"][0] == 0 else 0.0
            cols["fvg_count_bull"][i] = counts["fvg_bull"]
            cols["fvg_count_bear"][i] = counts["fvg_bear"]
            cols["ob_count_bull"][i] = counts["ob_bull"]
            cols["ob_count_bear"][i] = counts["ob_bear"]
            cols["zone_confluence"][i] = float(np.clip(confluence, -3, 3))

        frame = pd.DataFrame(cols, index=df.index)
        frame = frame.fillna(20.0)  # "keine Zone in Reichweite" = weit entfernt

        sweeps = detect_sweeps(df, atr, structure_frame)
        frame = frame.join(sweeps)
        frame["smc_score"] = (
            0.35 * np.clip(frame["zone_confluence"], -1, 1)
            + 0.30 * frame["sweep_signal"]
            + 0.20 * (frame["ob_in_bull"] - frame["ob_in_bear"])
            + 0.15 * (frame["fvg_in_bull"] - frame["fvg_in_bear"])
        ).clip(-1, 1)
        return SMCResult(zones=zones, frame=frame)


# --------------------------------------------------------------------------- #


def detect_sweeps(
    df: pd.DataFrame, atr: pd.Series, structure_frame: "pd.DataFrame | None" = None, decay: int = 5
) -> pd.DataFrame:
    """Liquiditätsgriffe: über ein Niveau laufen und darunter zurückschließen.

    Ohne Strukturrahmen wird auf das rollierende Extrem der letzten 20 Balken
    zurückgegriffen. Mit Strukturrahmen sind es die bestätigten Swing-Niveaus,
    also genau die Stellen, an denen tatsächlich Stops liegen.
    """
    a = atr.replace(0, np.nan)
    if structure_frame is not None and "swing_high" in structure_frame.columns:
        level_high = structure_frame["swing_high"]
        level_low = structure_frame["swing_low"]
    else:
        level_high = df["high"].shift(1).rolling(20, min_periods=5).max()
        level_low = df["low"].shift(1).rolling(20, min_periods=5).min()

    # Bärischer Sweep: Hoch über dem Niveau, Schluss wieder darunter.
    swept_high = (df["high"] > level_high) & (df["close"] < level_high)
    swept_low = (df["low"] < level_low) & (df["close"] > level_low)
    depth_high = ((df["high"] - level_high) / a).clip(0, 2).fillna(0.0)
    depth_low = ((level_low - df["low"]) / a).clip(0, 2).fillna(0.0)

    raw = pd.Series(
        np.where(swept_low, np.clip(depth_low / 1.0, 0.2, 1.0),
                 np.where(swept_high, -np.clip(depth_high / 1.0, 0.2, 1.0), 0.0)),
        index=df.index,
    ).fillna(0.0)

    # Ein Sweep wirkt über mehrere Balken nach - exponentiell abklingend.
    signal = raw.copy()
    for k in range(1, decay + 1):
        shifted = raw.shift(k) * (0.65**k)
        signal = signal.where(signal.abs() >= shifted.abs(), shifted)

    return pd.DataFrame(
        {
            "sweep_raw": raw,
            "sweep_signal": signal.fillna(0.0),
            "bars_since_sweep": _bars_since(raw.abs() > 0.01),
        }
    )


def _bars_since(flags: pd.Series, cap: float = 200.0) -> pd.Series:
    """Balken seit dem letzten True - kausal, ohne Blick nach vorn."""
    idx = np.arange(len(flags))
    last = np.where(flags.to_numpy(), idx, -1)
    last = pd.Series(last, index=flags.index).cummax().to_numpy()
    out = np.where(last >= 0, idx - last, cap)
    return pd.Series(np.minimum(out, cap).astype(float), index=flags.index, name="bars_since_sweep")
