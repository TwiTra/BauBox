"""Triple-Barrier-Labeling.

Die naive Zielvariable "Kurs in 10 Balken höher als heute?" ist für den Handel
wertlos: sie ignoriert, dass eine Position vorher ausgestoppt worden wäre.

Das Triple-Barrier-Verfahren (López de Prado) fragt stattdessen das, was ein
Trader wirklich wissen will: *Wird zuerst mein Ziel oder zuerst mein Stop
getroffen?* Drei Barrieren begrenzen jedes Beispiel - Gewinnziel, Verlustgrenze
und Zeitlimit. Die Barrieren skalieren mit dem ATR, damit ruhige und volatile
Phasen vergleichbar bleiben.

Dazu kommen zwei Feinheiten, die in der Praxis über Sinn und Unsinn eines
Modells entscheiden:

* **Meta-Labeling**: Ein erstes, einfaches Regelwerk bestimmt die Richtung. Das
  Modell entscheidet dann nur noch, ob dieser Vorschlag angenommen wird. Diese
  Zerlegung ist deutlich lernbarer als "rate die Richtung".
* **Stichprobengewichte**: Überlappende Beispiele enthalten dieselbe
  Kursinformation mehrfach. Ohne Korrektur überschätzt jedes Modell seine
  Sicherheit dramatisch.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BarrierResult:
    """Ergebnis der Barriereprüfung für eine ganze Zeitreihe."""

    label: pd.Series  # +1 obere Barriere zuerst, -1 untere, 0 Zeitlimit
    exit_index: pd.Series  # Positionsindex des Ausstiegs
    exit_price: pd.Series
    bars_held: pd.Series
    ret_atr: pd.Series  # Ergebnis in ATR-Einheiten
    r_multiple: pd.Series  # Ergebnis in R (Risiko = untere Barriere)
    touch_time: pd.Series

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "label": self.label,
                "exit_index": self.exit_index,
                "exit_price": self.exit_price,
                "bars_held": self.bars_held,
                "ret_atr": self.ret_atr,
                "r_multiple": self.r_multiple,
                "touch_time": self.touch_time,
            }
        )


def barrier_outcome(
    df: pd.DataFrame,
    atr: pd.Series,
    up_atr: float = 2.0,
    dn_atr: float = 1.0,
    max_bars: int = 48,
    side: "int | pd.Series" = 1,
    pessimistic: bool = True,
) -> BarrierResult:
    """Erste berührte Barriere je Balken bestimmen.

    `side` = +1 rechnet eine Longposition, -1 eine Shortposition; als Serie
    lässt sich für jeden Balken eine eigene Richtung vorgeben (für
    Meta-Labeling).

    `pessimistic` entscheidet den Grenzfall, dass beide Barrieren im selben
    Balken liegen. Ohne Tickdaten ist nicht feststellbar, welche zuerst kam -
    dann wird der Verlust angenommen. Alles andere schönt die Ergebnisse.
    """
    n = len(df)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    a = atr.to_numpy(dtype=float)
    sides = (
        np.full(n, float(side))
        if np.isscalar(side)
        else np.asarray(pd.Series(side).reindex(df.index).fillna(0.0), dtype=float)
    )

    label = np.zeros(n)
    exit_idx = np.full(n, -1, dtype=float)
    exit_price = np.full(n, np.nan)
    bars = np.zeros(n)
    ret_atr = np.full(n, np.nan)
    r_mult = np.full(n, np.nan)

    for i in range(n):
        s = sides[i]
        ref = a[i]
        if s == 0 or not np.isfinite(ref) or ref <= 0 or i + 1 >= n:
            continue
        entry = close[i]
        # Bei einer Shortposition liegt das Ziel unten und der Stop oben.
        target = entry + s * up_atr * ref
        stop = entry - s * dn_atr * ref
        last = min(i + max_bars, n - 1)

        hit = 0
        j_exit = last
        px_exit = close[last]
        for j in range(i + 1, last + 1):
            hi, lo = high[j], low[j]
            hit_target = (hi >= target) if s > 0 else (lo <= target)
            hit_stop = (lo <= stop) if s > 0 else (hi >= stop)
            if hit_target and hit_stop:
                hit = -1 if pessimistic else 1
                j_exit = j
                px_exit = stop if pessimistic else target
                break
            if hit_target:
                hit, j_exit, px_exit = 1, j, target
                break
            if hit_stop:
                hit, j_exit, px_exit = -1, j, stop
                break

        label[i] = hit
        exit_idx[i] = j_exit
        exit_price[i] = px_exit
        bars[i] = j_exit - i
        move = (px_exit - entry) * s
        ret_atr[i] = move / ref
        r_mult[i] = move / (dn_atr * ref) if dn_atr > 0 else np.nan

    idx = df.index
    return BarrierResult(
        label=pd.Series(label, index=idx, name="label"),
        exit_index=pd.Series(exit_idx, index=idx, name="exit_index"),
        exit_price=pd.Series(exit_price, index=idx, name="exit_price"),
        bars_held=pd.Series(bars, index=idx, name="bars_held"),
        ret_atr=pd.Series(ret_atr, index=idx, name="ret_atr"),
        r_multiple=pd.Series(r_mult, index=idx, name="r_multiple"),
        touch_time=pd.Series(
            [idx[int(k)] if k >= 0 else pd.NaT for k in exit_idx], index=idx, name="touch_time"
        ),
    )


def direction_labels(
    df: pd.DataFrame,
    atr: pd.Series,
    barrier_atr: float = 1.5,
    max_bars: int = 48,
    min_return_atr: float = 0.25,
) -> tuple[pd.Series, pd.Series, BarrierResult]:
    """Richtungslabel für das Basismodell.

    Es gibt bewusst nur **einen** Barriereabstand, keine zwei. Die Frage muss
    symmetrisch gestellt sein - "geht es zuerst hinreichend hoch oder zuerst
    hinreichend runter?" -, sonst ist die Antwort keine Richtungsaussage mehr.

    Warum das eine eigene Signatur wert ist: Bei einem Barriereverhältnis von
    2:1 trifft schon ein driftloser Zufallspfad die obere Barriere nur in einem
    Drittel der Fälle. Ein sauber kalibriertes Modell gibt dann im Mittel 0.33
    aus. Wer diesen Wert gegen 0.5 als neutralen Punkt liest, bekommt auf jedem
    einzelnen Balken eine Short-Neigung geschenkt, die nichts über den Markt
    aussagt, sondern nur über die Barrierewahl. Ein Parameterpaar hier hat
    genau diesen Fehler möglich gemacht; ein einzelner Abstand macht ihn
    unmöglich. Das Verhältnis 2:1 gehört zum Trade (siehe `meta_labels`),
    nicht zur Richtungsfrage.

    Rückgabe: (y in {0,1}, verwertbar-Maske, vollständiges Barriereergebnis).
    Zeitlimit-Fälle mit nennenswerter Bewegung werden nach der Bewegungsrichtung
    zugeordnet; alles darunter ist Rauschen und wird vom Training ausgeschlossen.
    """
    res = barrier_outcome(df, atr, barrier_atr, barrier_atr, max_bars, side=1, pessimistic=True)
    y = pd.Series(np.nan, index=df.index, name="y")
    y[res.label > 0] = 1.0
    y[res.label < 0] = 0.0

    timeout = res.label == 0
    drift = res.ret_atr.where(timeout)
    y[timeout & (drift >= min_return_atr)] = 1.0
    y[timeout & (drift <= -min_return_atr)] = 0.0

    usable = y.notna()
    # Das Ende der Reihe hat keine Zukunft mehr - diese Beispiele sind ungültig.
    usable.iloc[-max_bars:] = False
    return y.fillna(0.0), usable, res


def meta_labels(
    df: pd.DataFrame,
    atr: pd.Series,
    side: pd.Series,
    tp_atr: float = 2.0,
    sl_atr: float = 1.0,
    max_bars: int = 48,
) -> tuple[pd.Series, pd.Series, BarrierResult]:
    """Meta-Label: Hätte der vorgeschlagene Trade funktioniert?

    `side` kommt vom Regelwerk (+1 long, -1 short, 0 kein Vorschlag). Trainiert
    wird nur auf den Balken, an denen tatsächlich ein Vorschlag vorlag - genau
    die Verteilung, auf der das Modell später auch entscheidet.
    """
    res = barrier_outcome(df, atr, tp_atr, sl_atr, max_bars, side=side, pessimistic=True)
    y = (res.label > 0).astype(float)
    usable = (pd.Series(side).reindex(df.index).fillna(0.0) != 0) & (res.label != 0)
    usable.iloc[-max_bars:] = False
    return y, usable, res


# --------------------------------------------------------------------------- #
# Stichprobengewichte
# --------------------------------------------------------------------------- #


def concurrency(exit_index: pd.Series, n: "int | None" = None) -> np.ndarray:
    """Wie viele Beispiele beanspruchen denselben Balken?"""
    n = n or len(exit_index)
    counts = np.zeros(n + 1)
    ends = exit_index.to_numpy(dtype=float)
    for i, end in enumerate(ends):
        if end < 0 or not np.isfinite(end):
            continue
        counts[i] += 1
        counts[int(end) + 1] -= 1
    return np.cumsum(counts)[:n]


def uniqueness_weights(exit_index: pd.Series, n: "int | None" = None) -> np.ndarray:
    """Durchschnittliche Einzigartigkeit je Beispiel.

    Ein Beispiel, dessen Zeitraum sich mit zehn anderen überlappt, enthält kaum
    neue Information und bekommt entsprechend ein Zehntel Gewicht. Ohne diese
    Korrektur hält sich jedes Modell für zehnmal sicherer, als es ist.
    """
    n = n or len(exit_index)
    conc = np.maximum(concurrency(exit_index, n), 1.0)
    inv = 1.0 / conc
    ends = exit_index.to_numpy(dtype=float)
    out = np.zeros(n)
    cumulative = np.concatenate([[0.0], np.cumsum(inv)])
    for i, end in enumerate(ends):
        if end < 0 or not np.isfinite(end):
            out[i] = 0.0
            continue
        j = min(int(end), n - 1)
        span = j - i + 1
        out[i] = (cumulative[j + 1] - cumulative[i]) / span if span > 0 else 0.0
    return out


def time_decay_weights(n: int, decay: float = 0.5) -> np.ndarray:
    """Ältere Beispiele leichter gewichten.

    `decay` = 0 schaltet die Zeitgewichtung ab, 1 lässt das älteste Beispiel
    gegen null gehen. Märkte ändern sich - was 2015 galt, gilt heute selten noch.
    """
    if decay <= 0:
        return np.ones(n)
    x = np.linspace(0.0, 1.0, n)
    return np.clip((1.0 - decay) + decay * x, 1e-3, None)


def sample_weights(
    result: BarrierResult,
    decay: float = 0.5,
    apply_uniqueness: bool = True,
    by_return: bool = True,
    normalize: bool = True,
) -> pd.Series:
    """Gesamtgewicht je Beispiel aus Einzigartigkeit, Alter und Bewegungsgröße."""
    n = len(result.label)
    w = np.ones(n)
    if apply_uniqueness:
        w *= np.maximum(uniqueness_weights(result.exit_index, n), 1e-4)
    w *= time_decay_weights(n, decay)
    if by_return:
        # Große Bewegungen sind aussagekräftiger als Zufallszappeln.
        magnitude = result.ret_atr.abs().fillna(0.0).to_numpy()
        w *= 0.5 + np.clip(magnitude / 2.0, 0.0, 1.5)
    if normalize and w.sum() > 0:
        w = w * (n / w.sum())
    return pd.Series(w, index=result.label.index, name="weight")


def label_report(y: pd.Series, usable: pd.Series, result: BarrierResult) -> dict[str, float]:
    """Kurzbericht zur Güte der Zielvariablen - vor jedem Training zu prüfen."""
    sel = usable.to_numpy(dtype=bool)
    y_sel = y[sel]
    total = int(sel.sum())
    if total == 0:
        return {"verwertbar": 0}
    return {
        "verwertbar": total,
        "anteil_verwertbar": round(total / len(y), 4),
        "anteil_aufwaerts": round(float(y_sel.mean()), 4),
        "klassenbalance": round(float(min(y_sel.mean(), 1 - y_sel.mean()) * 2), 4),
        "ziel_zuerst": int((result.label[sel] > 0).sum()),
        "stop_zuerst": int((result.label[sel] < 0).sum()),
        "zeitlimit": int((result.label[sel] == 0).sum()),
        "median_haltedauer": float(result.bars_held[sel].median()),
        "mittleres_r": round(float(result.r_multiple[sel].mean()), 4),
    }
