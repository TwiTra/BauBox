"""Kerzenformationen - aber mit Kontext statt Katalogdenken.

Ein Pin Bar mitten in einer Range ist Rauschen. Derselbe Pin Bar an einem
getesteten Widerstand, nach einem Liquiditätsgriff und gegen den Trend, ist ein
Setup. Deshalb liefert jede Formation hier nicht nur "ja/nein", sondern eine
Qualität zwischen 0 und 1: relative Körpergröße, Dochtverhältnis und
Schlusskursposition fließen mit ein.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def candle_anatomy(df: pd.DataFrame) -> pd.DataFrame:
    """Grundmaße jeder Kerze, normiert auf ihre eigene Spanne."""
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    rng = np.maximum(h - l, 1e-12)
    body = np.abs(c - o)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    return pd.DataFrame(
        {
            "body_ratio": body / rng,
            "upper_wick_ratio": upper / rng,
            "lower_wick_ratio": lower / rng,
            "close_position": (c - l) / rng,  # 0 = am Tief, 1 = am Hoch
            "bull": np.where(c > o, 1.0, np.where(c < o, -1.0, 0.0)),
            "range": rng,
        },
        index=df.index,
    )


def detect(df: pd.DataFrame, atr: "pd.Series | None" = None) -> pd.DataFrame:
    """Alle Formationen als Spalten mit Qualität in [-1, 1].

    Vorzeichen = Richtung (positiv bullisch), Betrag = Qualität. Ein Wert von 0
    heißt: Formation liegt nicht vor.
    """
    from .indicators import atr as atr_fn

    if atr is None:
        atr = atr_fn(df, 14)
    a = atr.to_numpy(dtype=float)
    an = candle_anatomy(df)

    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    rng = an["range"].to_numpy()
    body = np.abs(c - o)
    body_ratio = an["body_ratio"].to_numpy()
    up_w = an["upper_wick_ratio"].to_numpy()
    lo_w = an["lower_wick_ratio"].to_numpy()
    close_pos = an["close_position"].to_numpy()
    bull = an["bull"].to_numpy()

    prev = lambda arr: np.concatenate([[np.nan], arr[:-1]])  # noqa: E731
    o1, c1, h1, l1 = prev(o), prev(c), prev(h), prev(l)
    body1 = prev(body)
    bull1 = prev(bull)
    rng1 = prev(rng)

    # Größenfaktor: nur Kerzen mit relevanter Spanne zählen überhaupt.
    with np.errstate(invalid="ignore", divide="ignore"):
        size = np.clip(rng / np.where(a > 0, a, np.nan), 0, 3.0)
    size_ok = np.nan_to_num(np.clip(size / 1.2, 0.0, 1.0))

    out = pd.DataFrame(index=df.index)

    # --- Pin Bar / Hammer / Shooting Star --------------------------------- #
    # Langer Docht gegen die Bewegung, kleiner Körper, Schluss auf der
    # Gegenseite: ein abgelehnter Preisbereich.
    bull_pin = (lo_w >= 0.55) & (body_ratio <= 0.35) & (close_pos >= 0.55)
    bear_pin = (up_w >= 0.55) & (body_ratio <= 0.35) & (close_pos <= 0.45)
    quality_pin = np.clip((np.maximum(lo_w, up_w) - 0.5) / 0.45, 0, 1) * size_ok
    out["pat_pinbar"] = np.where(bull_pin, quality_pin, np.where(bear_pin, -quality_pin, 0.0))

    # --- Engulfing -------------------------------------------------------- #
    bull_eng = (bull > 0) & (bull1 < 0) & (c >= o1) & (o <= c1) & (body > body1)
    bear_eng = (bull < 0) & (bull1 > 0) & (c <= o1) & (o >= c1) & (body > body1)
    with np.errstate(invalid="ignore", divide="ignore"):
        eng_q = np.clip(body / np.where(body1 > 0, body1, np.nan) - 1.0, 0, 1.5) / 1.5
    eng_q = np.nan_to_num(eng_q) * size_ok
    out["pat_engulfing"] = np.where(bull_eng, eng_q, np.where(bear_eng, -eng_q, 0.0))

    # --- Inside Bar (Kompression) und Outside Bar (Expansion) ------------- #
    inside = (h <= h1) & (l >= l1)
    outside = (h > h1) & (l < l1)
    with np.errstate(invalid="ignore", divide="ignore"):
        compression = np.nan_to_num(1.0 - np.clip(rng / np.where(rng1 > 0, rng1, np.nan), 0, 1))
    out["pat_inside"] = np.where(inside, compression, 0.0)
    out["pat_outside"] = np.where(outside, np.sign(bull) * size_ok, 0.0)

    # --- Momentum-/Marubozu-Kerze ---------------------------------------- #
    marubozu = (body_ratio >= 0.72) & (size >= 1.1)
    out["pat_momentum"] = np.where(marubozu, np.sign(bull) * np.clip(body_ratio, 0, 1) * size_ok, 0.0)

    # --- Doji / Unentschlossenheit ---------------------------------------- #
    out["pat_doji"] = np.where((body_ratio <= 0.1) & (size >= 0.5), 1.0 - body_ratio * 10, 0.0)

    # --- Drei-Kerzen-Umkehr (Morning/Evening Star) ------------------------ #
    o2, c2 = prev(o1), prev(c1)
    body2 = prev(body1)
    small_middle = np.nan_to_num(body1 / np.where(body2 > 0, body2, np.nan)) < 0.5
    morning = (prev(bull1) < 0) & small_middle & (bull > 0) & (c > (o2 + c2) / 2)
    evening = (prev(bull1) > 0) & small_middle & (bull < 0) & (c < (o2 + c2) / 2)
    star_q = np.clip(body_ratio, 0, 1) * size_ok
    out["pat_star"] = np.where(morning, star_q, np.where(evening, -star_q, 0.0))

    # --- Zwei-Balken-Umkehr (Sweep + Rückeroberung) ----------------------- #
    # Der wohl verlässlichste kurzfristige Aufbau: erst unter das Vorbalkentief
    # laufen, dann darüber schließen - eingesammelte Stops, sofort abgelehnt.
    reversal_up = (l < l1) & (c > c1) & (close_pos > 0.6)
    reversal_dn = (h > h1) & (c < c1) & (close_pos < 0.4)
    out["pat_2bar_reversal"] = np.where(
        reversal_up, size_ok, np.where(reversal_dn, -size_ok, 0.0)
    )

    # --- Gesamtwertung ---------------------------------------------------- #
    directional = out[
        ["pat_pinbar", "pat_engulfing", "pat_outside", "pat_momentum", "pat_star", "pat_2bar_reversal"]
    ]
    out["pattern_score"] = directional.sum(axis=1).clip(-2.0, 2.0) / 2.0
    out["pattern_count"] = (directional.abs() > 0.1).sum(axis=1).astype(float)

    # Erste Zeilen enthalten wegen der Vorgänger NaN-Vergleiche - auf 0 setzen.
    return out.fillna(0.0)


def rejection_at(df: pd.DataFrame, level: pd.Series, atr: pd.Series, tolerance: float = 0.3) -> pd.Series:
    """Wurde ein Niveau angetestet und abgelehnt?

    Der Docht muss das Niveau erreicht haben, der Schlusskurs aber wieder auf
    der Ursprungsseite liegen - genau das, was einen Test von einem Bruch
    unterscheidet.
    """
    tol = tolerance * atr
    touched_above = (df["high"] >= level - tol) & (df["close"] < level)
    touched_below = (df["low"] <= level + tol) & (df["close"] > level)
    strength = ((df["high"] - df["close"]) / atr.replace(0, np.nan)).clip(0, 2) / 2
    strength_dn = ((df["close"] - df["low"]) / atr.replace(0, np.nan)).clip(0, 2) / 2
    return pd.Series(
        np.where(touched_above, -strength, np.where(touched_below, strength_dn, 0.0)),
        index=df.index,
        name="rejection",
    ).fillna(0.0)
