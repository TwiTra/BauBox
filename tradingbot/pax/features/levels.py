"""Preisniveaus: Unterstützung/Widerstand, Volumenprofil, Referenzpunkte.

Was der Kurs schon mehrfach abgelehnt hat, lehnt er oft wieder ab. Dieses Modul
sammelt genau solche Niveaus:

* geclusterte Swing-Punkte mit Zähler, wie oft sie getestet wurden
* Volumenprofil mit POC und Value Area - wo tatsächlich Umsatz stattfand
* Referenzpunkte, auf die Handelstische schauen: Vortageshoch/-tief,
  Vorwochenextreme, Tagesöffnung
* runde Zahlen, an denen erfahrungsgemäß Orders liegen
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..types import Swing


@dataclass
class Level:
    """Ein geclustertes Preisniveau."""

    price: float
    touches: int
    first_index: int
    last_index: int
    is_resistance: bool

    @property
    def strength(self) -> float:
        """Mehr Tests = stärkeres Niveau, aber mit abnehmendem Grenznutzen."""
        return float(min(1.0, 0.3 + 0.18 * (self.touches - 1)))


def cluster_levels(
    swings: list[Swing], atr: pd.Series, tolerance_atr: float = 0.35, lookback_confirm: int = 3
) -> list[tuple[int, Level]]:
    """Swings zu Niveaus verdichten - als Zeitstrahl (Bestätigungsindex, Level).

    Zurückgegeben wird jede Änderung mit dem Balken, ab dem sie bekannt ist.
    Der Aufrufer kann daraus einen kausalen Verlauf aufbauen.
    """
    a = atr.to_numpy(dtype=float)
    updates: list[tuple[int, Level]] = []
    levels: list[Level] = []

    for s in sorted(swings, key=lambda x: x.index):
        ref = a[s.index] if s.index < len(a) and np.isfinite(a[s.index]) and a[s.index] > 0 else np.nan
        if not np.isfinite(ref):
            continue
        confirm_at = s.index + lookback_confirm
        tol = tolerance_atr * ref
        match = None
        for lv in levels:
            if abs(lv.price - s.price) <= tol and lv.is_resistance == s.is_high:
                match = lv
                break
        if match is None:
            lv = Level(float(s.price), 1, s.index, s.index, s.is_high)
            levels.append(lv)
        else:
            # Gewichteter Mittelwert: das Niveau wandert leicht zum neuen Test
            match.price = (match.price * match.touches + s.price) / (match.touches + 1)
            match.touches += 1
            match.last_index = s.index
            lv = match
        updates.append((confirm_at, Level(lv.price, lv.touches, lv.first_index, lv.last_index, lv.is_resistance)))
    return updates


def level_features(
    df: pd.DataFrame,
    atr: pd.Series,
    swings: list[Swing],
    tolerance_atr: float = 0.35,
    lookback_confirm: int = 3,
    max_age: int = 500,
) -> pd.DataFrame:
    """Abstand und Stärke des nächsten Niveaus über und unter dem Kurs."""
    n = len(df)
    close = df["close"].to_numpy(dtype=float)
    a = atr.to_numpy(dtype=float)
    updates = cluster_levels(swings, atr, tolerance_atr, lookback_confirm)

    by_index: dict[int, list[Level]] = {}
    for idx, lv in updates:
        by_index.setdefault(idx, []).append(lv)

    res_dist = np.full(n, 20.0)
    sup_dist = np.full(n, 20.0)
    res_strength = np.zeros(n)
    sup_strength = np.zeros(n)
    level_count = np.zeros(n)

    known: dict[tuple[bool, int], Level] = {}
    for i in range(n):
        for lv in by_index.get(i, ()):
            known[(lv.is_resistance, lv.first_index)] = lv  # gleiche Wurzel = Aktualisierung
        ref = a[i]
        if not np.isfinite(ref) or ref <= 0:
            continue
        price = close[i]
        best_res: tuple[float, Level] | None = None
        best_sup: tuple[float, Level] | None = None
        active = 0
        for lv in known.values():
            if i - lv.last_index > max_age:
                continue
            active += 1
            dist = (lv.price - price) / ref
            if dist >= 0:
                if best_res is None or dist < best_res[0]:
                    best_res = (dist, lv)
            else:
                if best_sup is None or -dist < best_sup[0]:
                    best_sup = (-dist, lv)
        level_count[i] = active
        if best_res:
            res_dist[i] = min(best_res[0], 20.0)
            res_strength[i] = best_res[1].strength
        if best_sup:
            sup_dist[i] = min(best_sup[0], 20.0)
            sup_strength[i] = best_sup[1].strength

    return pd.DataFrame(
        {
            "res_dist_atr": res_dist,
            "sup_dist_atr": sup_dist,
            "res_strength": res_strength,
            "sup_strength": sup_strength,
            "level_count": level_count,
            # Positiv, wenn die Unterstützung näher liegt als der Widerstand:
            # dann ist der Weg nach oben freier.
            "level_balance": np.clip((res_dist - sup_dist) / 5.0, -1, 1),
        },
        index=df.index,
    )


# --------------------------------------------------------------------------- #
# Volumenprofil
# --------------------------------------------------------------------------- #


def volume_profile(
    df: pd.DataFrame,
    lookback: int = 240,
    bins: int = 48,
    value_area: float = 0.70,
    step: int = 5,
) -> pd.DataFrame:
    """Rollierendes Volumenprofil mit POC und Value Area.

    Aus Aufwandsgründen wird alle `step` Balken neu gerechnet und dazwischen
    fortgeschrieben. Das bleibt kausal - es benutzt nur ältere Daten - und
    spart auf langen Historien viel Rechenzeit.
    """
    n = len(df)
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    vol = df.get("volume", pd.Series(np.ones(n), index=df.index)).to_numpy(dtype=float)
    typical = (high + low + close) / 3.0

    poc = np.full(n, np.nan)
    vah = np.full(n, np.nan)
    val = np.full(n, np.nan)

    last = (np.nan, np.nan, np.nan)
    for i in range(n):
        if i >= lookback and (i % step == 0 or not np.isfinite(last[0])):
            s = slice(i - lookback + 1, i + 1)
            prices, weights = typical[s], np.maximum(vol[s], 1e-9)
            lo, hi = float(prices.min()), float(prices.max())
            if hi > lo:
                hist, edges = np.histogram(prices, bins=bins, range=(lo, hi), weights=weights)
                centers = (edges[:-1] + edges[1:]) / 2.0
                peak = int(np.argmax(hist))
                # Value Area: vom POC aus nach beiden Seiten wachsen, bis
                # `value_area` des Volumens eingeschlossen ist.
                target = hist.sum() * value_area
                lo_i = hi_i = peak
                acc = hist[peak]
                while acc < target and (lo_i > 0 or hi_i < bins - 1):
                    left = hist[lo_i - 1] if lo_i > 0 else -1.0
                    right = hist[hi_i + 1] if hi_i < bins - 1 else -1.0
                    if right >= left:
                        hi_i += 1
                        acc += hist[hi_i]
                    else:
                        lo_i -= 1
                        acc += hist[lo_i]
                last = (float(centers[peak]), float(centers[hi_i]), float(centers[lo_i]))
        poc[i], vah[i], val[i] = last

    return pd.DataFrame({"poc": poc, "vah": vah, "val": val}, index=df.index)


# --------------------------------------------------------------------------- #
# Referenzpunkte
# --------------------------------------------------------------------------- #


def session_levels(df: pd.DataFrame) -> pd.DataFrame:
    """Vortages- und Vorwochenextreme sowie die Tagesöffnung.

    Alle Werte sind um einen Zeitraum verschoben: das Vortageshoch ist erst am
    Folgetag bekannt, nicht während des Tages, an dem es entsteht.
    """
    day = df.index.normalize()
    week = day - pd.to_timedelta(df.index.dayofweek, unit="D")

    daily = df.groupby(day).agg(dh=("high", "max"), dl=("low", "min"), dc=("close", "last"))
    prev_day = daily.shift(1)
    weekly = df.groupby(week).agg(wh=("high", "max"), wl=("low", "min"))
    prev_week = weekly.shift(1)

    out = pd.DataFrame(index=df.index)
    out["prev_day_high"] = prev_day["dh"].reindex(day).to_numpy()
    out["prev_day_low"] = prev_day["dl"].reindex(day).to_numpy()
    out["prev_day_close"] = prev_day["dc"].reindex(day).to_numpy()
    out["prev_week_high"] = prev_week["wh"].reindex(week).to_numpy()
    out["prev_week_low"] = prev_week["wl"].reindex(week).to_numpy()
    out["day_open"] = df.groupby(day)["open"].transform("first")
    # Laufendes Tageshoch/-tief, ausschließlich aus bereits geschlossenen Balken
    out["day_high_sofar"] = df.groupby(day)["high"].cummax().groupby(day).shift(1)
    out["day_low_sofar"] = df.groupby(day)["low"].cummin().groupby(day).shift(1)
    return out


def reference_features(df: pd.DataFrame, atr: pd.Series) -> pd.DataFrame:
    """Abstände zu den Referenzpunkten, in ATR gemessen."""
    lv = session_levels(df)
    a = atr.replace(0, np.nan)
    close = df["close"]
    out = pd.DataFrame(index=df.index)
    for name in ("prev_day_high", "prev_day_low", "prev_day_close",
                 "prev_week_high", "prev_week_low", "day_open"):
        out[f"dist_{name}_atr"] = ((close - lv[name]) / a).clip(-20, 20)
    rng = (lv["prev_day_high"] - lv["prev_day_low"]).replace(0, np.nan)
    out["prev_day_range_atr"] = (rng / a).clip(0, 30)
    out["pos_in_prev_day"] = ((close - lv["prev_day_low"]) / rng).clip(-2, 3)
    out["day_range_used"] = (
        (lv["day_high_sofar"] - lv["day_low_sofar"]) / rng
    ).clip(0, 5)
    return out.fillna(0.0)


def round_number_distance(close: pd.Series, atr: pd.Series, digits: int = 5) -> pd.DataFrame:
    """Abstand zur nächsten runden Zahl (00er- und 50er-Marken).

    Institutionelle Orders und Optionsbarrieren häufen sich dort - der Kurs
    reagiert an diesen Marken messbar anders.
    """
    a = atr.replace(0, np.nan)
    # Schrittweite: bei 5 Nachkommastellen sind das 50 bzw. 100 Pips
    step_big = 10.0 ** (-(digits - 3)) if digits >= 3 else 1.0
    step_half = step_big / 2.0
    out = pd.DataFrame(index=close.index)
    for name, step in (("big", step_big), ("half", step_half)):
        nearest = (close / step).round() * step
        out[f"round_{name}_dist_atr"] = ((close - nearest) / a).clip(-10, 10)
        out[f"round_{name}_abs_atr"] = (out[f"round_{name}_dist_atr"]).abs()
    return out.fillna(0.0)


def all_level_features(
    df: pd.DataFrame,
    atr: pd.Series,
    swings: list[Swing],
    tolerance_atr: float = 0.35,
    vp_lookback: int = 240,
    vp_bins: int = 48,
    digits: int = 5,
) -> pd.DataFrame:
    """Alle Niveau-Merkmale in einem Rahmen."""
    a = atr.replace(0, np.nan)
    out = level_features(df, atr, swings, tolerance_atr)
    vp = volume_profile(df, vp_lookback, vp_bins)
    out["dist_poc_atr"] = ((df["close"] - vp["poc"]) / a).clip(-20, 20)
    out["dist_vah_atr"] = ((df["close"] - vp["vah"]) / a).clip(-20, 20)
    out["dist_val_atr"] = ((df["close"] - vp["val"]) / a).clip(-20, 20)
    out["in_value_area"] = (
        (df["close"] <= vp["vah"]) & (df["close"] >= vp["val"])
    ).astype(float)
    out = out.join(reference_features(df, atr))
    out = out.join(round_number_distance(df["close"], atr, digits))
    return out.fillna(0.0)
