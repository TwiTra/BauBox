"""Mehrfach-Zeitebenen-Analyse.

Der klassische Aufbau: der große Rahmen gibt die Richtung vor, der mittlere den
Aufbau, der kleine den Einstieg. Handeln nur, wenn alle drei in dieselbe
Richtung zeigen - das ist die simpelste und wirksamste Filterregel im
Price-Action-Handel.

Die technische Falle dabei ist die Zeitverzögerung: ein H4-Balken, der um 12:00
öffnet, ist erst um 16:00 abgeschlossen. Wer seinen Wert schon um 12:15 auf die
M15-Ebene legt, kennt die Zukunft. `align_to_base` verschiebt deshalb jeden
Wert der höheren Ebene auf den Zeitpunkt, an dem der Balken tatsächlich
geschlossen hat.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..types import Horizon, Timeframe


def align_to_base(
    higher: pd.DataFrame,
    base_index: pd.DatetimeIndex,
    higher_tf: "str | Timeframe",
    prefix: str = "",
) -> pd.DataFrame:
    """Werte einer höheren Zeiteinheit auf den Basisindex legen - ohne Lookahead.

    Der Wert eines höheren Balkens wird erst ab seinem Schlusszeitpunkt
    sichtbar, also ab Öffnungszeit plus Balkendauer.
    """
    tf = Timeframe.parse(higher_tf)
    if higher.empty or len(base_index) == 0:
        return pd.DataFrame(index=base_index)

    shifted = higher.copy()
    shifted.index = shifted.index + pd.Timedelta(minutes=tf.minutes)
    shifted = shifted.sort_index()
    if prefix:
        shifted.columns = [f"{prefix}{c}" for c in shifted.columns]

    left = pd.DataFrame(index=pd.DatetimeIndex(base_index, name="time")).reset_index()
    right = shifted.reset_index(names="time")
    merged = pd.merge_asof(
        left.sort_values("time"),
        right.sort_values("time"),
        on="time",
        direction="backward",
        allow_exact_matches=True,
    )
    return merged.set_index("time").reindex(base_index)


def resample_ohlcv(df: pd.DataFrame, timeframe: "str | Timeframe") -> pd.DataFrame:
    """OHLCV verdichten; die letzte, unvollständige Periode fällt weg."""
    tf = Timeframe.parse(timeframe)
    agg: dict[str, str] = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    out = df.resample(tf.pandas_freq, label="left", closed="left").agg(agg)
    out = out.dropna(subset=["open"])
    if len(out) and len(df):
        # Letzte Periode nur behalten, wenn sie durch die Daten vollständig gedeckt ist
        last_start = out.index[-1]
        last_end = last_start + pd.Timedelta(minutes=tf.minutes)
        if df.index[-1] + pd.Timedelta(minutes=1) < last_end:
            out = out.iloc[:-1]
    return out


def alignment_score(biases: "dict[Horizon, float]", weights: "dict[Horizon, float] | None" = None) -> float:
    """Einigkeit der Zeitebenen von -1 (alle short) bis +1 (alle long).

    Bewusst multiplikativ gedämpft: widersprechen sich die Ebenen, fällt das
    Ergebnis stark ab statt sich nur wegzumitteln. Ein starker H4-Long und ein
    starker M15-Short ergeben eben kein "neutral halb so gutes Setup", sondern
    gar keins.
    """
    if not biases:
        return 0.0
    weights = weights or {Horizon.SHORT: 0.25, Horizon.MEDIUM: 0.35, Horizon.LONG: 0.40}
    total_w = sum(weights.get(h, 0.0) for h in biases) or 1.0
    weighted = sum(biases[h] * weights.get(h, 0.0) for h in biases) / total_w

    signs = [np.sign(v) for v in biases.values() if abs(v) > 0.08]
    if len(signs) <= 1:
        agreement = 1.0
    else:
        positive = sum(1 for s in signs if s > 0)
        negative = len(signs) - positive
        # 1.0 bei Einigkeit, 0.0 bei genau geteilter Meinung
        agreement = abs(positive - negative) / len(signs)

    return float(np.clip(weighted * (0.35 + 0.65 * agreement), -1.0, 1.0))


def build_mtf_frame(
    frames: "dict[str, pd.DataFrame]",
    base_index: pd.DatetimeIndex,
    columns: "list[str] | None" = None,
) -> pd.DataFrame:
    """Ausgewählte Spalten mehrerer Zeitebenen auf den Basisindex bringen."""
    out = pd.DataFrame(index=base_index)
    for tf_name, frame in frames.items():
        if frame is None or frame.empty:
            continue
        sub = frame[columns] if columns else frame
        sub = sub[[c for c in sub.columns if c in frame.columns]]
        aligned = align_to_base(sub, base_index, tf_name, prefix=f"{tf_name.lower()}_")
        out = out.join(aligned)
    return out


def confirm_lag_bars(base_tf: "str | Timeframe", higher_tf: "str | Timeframe") -> int:
    """Wie viele Basisbalken vergehen, bis ein höherer Balken geschlossen ist."""
    b = Timeframe.parse(base_tf).minutes
    h = Timeframe.parse(higher_tf).minutes
    return max(1, h // b)
