"""Marktstruktur: Swings, Bruchereignisse und Trendzustand.

Das ist das Fundament klassischer Price Action. Nicht ein Indikator entscheidet
über den Trend, sondern die Abfolge der Hoch- und Tiefpunkte:

* Höhere Hochs und höhere Tiefs -> Aufwärtsstruktur
* Tiefere Hochs und tiefere Tiefs -> Abwärtsstruktur
* BOS (Break of Structure): der Trend bestätigt sich, indem er sein letztes
  Extrem in Trendrichtung überwindet.
* CHoCH (Change of Character): der erste Bruch *gegen* die Struktur - das
  früheste ernstzunehmende Umkehrsignal.

Der wichtigste Punkt der ganzen Datei: ein Swing-Punkt bei Balken i ist erst bei
Balken i + lookback *bekannt*. Diese Verzögerung wird konsequent eingehalten -
sonst entsteht Lookahead und jedes Backtest-Ergebnis wird wertlos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from ..types import Direction, StructureEvent, Swing, TrendState
from .indicators import atr as atr_fn


@dataclass
class MarketStructure:
    """Ergebnis der Strukturanalyse für eine Zeitreihe."""

    swings: list[Swing] = field(default_factory=list)
    events: list[StructureEvent] = field(default_factory=list)
    frame: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def last_event(self) -> "StructureEvent | None":
        return self.events[-1] if self.events else None

    def trend_at(self, index: int) -> TrendState:
        if self.frame.empty or index >= len(self.frame):
            return TrendState.RANGE
        value = float(self.frame["struct_trend"].iloc[index])
        if value > 0.5:
            return TrendState.BULLISH
        if value < -0.5:
            return TrendState.BEARISH
        return TrendState.RANGE

    @property
    def current_trend(self) -> TrendState:
        return self.trend_at(len(self.frame) - 1)

    def swings_before(self, index: int, kind: "str | None" = None) -> list[Swing]:
        """Alle Swings, die bei `index` bereits bestätigt waren."""
        out = []
        for s in self.swings:
            if s.index + getattr(self, "_lookback", 0) > index:
                continue
            if kind and s.kind != kind:
                continue
            out.append(s)
        return out


class StructureAnalyzer:
    """Erkennt Swings, Struktur und Bruchereignisse - streng kausal."""

    def __init__(self, lookback: int = 3, atr_filter: float = 0.5, atr_period: int = 14) -> None:
        self.lookback = max(1, int(lookback))
        self.atr_filter = float(atr_filter)
        self.atr_period = int(atr_period)

    # ------------------------------------------------------------------ #
    # Swings
    # ------------------------------------------------------------------ #

    def find_swings(
        self, df: pd.DataFrame, atr: "pd.Series | None" = None, alternate: bool = False
    ) -> list[Swing]:
        """Fraktale Wendepunkte finden und per ATR-Filter entrauschen.

        Ein Punkt zählt nur, wenn er das Extrem seines Fensters ist *und* sich
        deutlich genug (in ATR gemessen) von der Gegenseite abhebt.

        `alternate` erzwingt eine abwechselnde Hoch-/Tief-Folge, **ist aber nicht
        kausal** und darf deshalb niemals für Merkmale verwendet werden: Die
        Regel "von zwei aufeinanderfolgenden Hochs überlebt das höhere" löscht
        rückwirkend einen Swing, der zu seiner Zeit längst bestätigt war und auf
        den bereits reagiert wurde. Genau daran verrutschen Backtests still und
        leise ins Schöne. Für die Analyse bleibt die Abwechslung deshalb aus -
        `analyze` bildet sie im Vorwärtslauf nach, wo jeder Ersatz erst ab
        seinem Bestätigungsbalken gilt. Nur zum Zeichnen eines fertigen Charts
        ist die globale Variante brauchbar.
        """
        n = len(df)
        L = self.lookback
        if n < 2 * L + 2:
            return []

        if atr is None:
            atr = atr_fn(df, self.atr_period)
        atr_v = atr.to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        times = df.index.to_pydatetime()

        window = 2 * L + 1
        roll_max = df["high"].rolling(window, center=True, min_periods=window).max().to_numpy()
        roll_min = df["low"].rolling(window, center=True, min_periods=window).min().to_numpy()

        candidates: list[Swing] = []
        for i in range(L, n - L):
            ref_atr = atr_v[i]
            if not np.isfinite(ref_atr) or ref_atr <= 0:
                continue
            if highs[i] >= roll_max[i]:
                prominence = highs[i] - lows[i - L : i + L + 1].min()
                if prominence >= self.atr_filter * ref_atr:
                    candidates.append(
                        Swing(i, times[i], float(highs[i]), True, _strength(prominence, ref_atr))
                    )
            if lows[i] <= roll_min[i]:
                prominence = highs[i - L : i + L + 1].max() - lows[i]
                if prominence >= self.atr_filter * ref_atr:
                    candidates.append(
                        Swing(i, times[i], float(lows[i]), False, _strength(prominence, ref_atr))
                    )

        candidates.sort(key=lambda s: (s.index, not s.is_high))
        return _alternate(candidates) if alternate else candidates

    # ------------------------------------------------------------------ #
    # Struktur je Balken
    # ------------------------------------------------------------------ #

    def analyze(self, df: pd.DataFrame, atr: "pd.Series | None" = None) -> MarketStructure:
        """Vollständige Strukturanalyse mit Zeitreihe je Balken."""
        n = len(df)
        if atr is None:
            atr = atr_fn(df, self.atr_period)
        swings = self.find_swings(df, atr)

        close = df["close"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        atr_v = atr.to_numpy(dtype=float)
        times = df.index.to_pydatetime()
        L = self.lookback

        # Swings nach Bestätigungsbalken einsortieren: erst dort sind sie bekannt.
        by_confirm: dict[int, list[Swing]] = {}
        for s in swings:
            by_confirm.setdefault(s.index + L, []).append(s)

        trend = np.zeros(n)
        active_high = np.full(n, np.nan)
        active_low = np.full(n, np.nan)
        prev_high = np.full(n, np.nan)
        prev_low = np.full(n, np.nan)
        bars_since_event = np.full(n, np.nan)
        last_event_kind = np.zeros(n)  # +1 BOS, -1 CHoCH, 0 keins
        last_event_dir = np.zeros(n)
        swing_seq_score = np.zeros(n)
        events: list[StructureEvent] = []

        state = TrendState.RANGE
        confirmed_highs: list[Swing] = []
        confirmed_lows: list[Swing] = []
        cur_high: Swing | None = None  # letztes unverletztes Hoch
        cur_low: Swing | None = None
        last_event_idx: int | None = None
        cur_event_kind = 0.0
        cur_event_dir = 0.0
        last_confirmed_is_high: "bool | None" = None

        for i in range(n):
            for s in by_confirm.get(i, ()):
                # Abwechslung kausal nachbilden: Ein neues Hoch verdrängt das
                # vorherige nur dann aus der Folge, wenn es höher liegt UND
                # zwischenzeitlich kein Tief bestätigt wurde. Der Ersatz gilt
                # ab genau diesem Balken - nicht rückwirkend.
                if s.is_high:
                    if (
                        confirmed_highs
                        and last_confirmed_is_high
                        and s.price > confirmed_highs[-1].price
                    ):
                        confirmed_highs[-1] = s
                    elif not (confirmed_highs and last_confirmed_is_high and s.price <= confirmed_highs[-1].price):
                        confirmed_highs.append(s)
                    last_confirmed_is_high = True
                    cur_high = s
                else:
                    if (
                        confirmed_lows
                        and last_confirmed_is_high is False
                        and s.price < confirmed_lows[-1].price
                    ):
                        confirmed_lows[-1] = s
                    elif not (confirmed_lows and last_confirmed_is_high is False and s.price >= confirmed_lows[-1].price):
                        confirmed_lows.append(s)
                    last_confirmed_is_high = False
                    cur_low = s

            # --- Bruchprüfung auf Schlusskursbasis ---------------------- #
            # Schlusskurs statt Docht: ein Stop-Hunt-Docht ist kein Strukturbruch.
            if cur_high is not None and close[i] > cur_high.price:
                kind = "BOS" if state is TrendState.BULLISH else "CHoCH"
                events.append(
                    StructureEvent(i, times[i], kind, Direction.LONG, cur_high.price, cur_high.index)
                )
                state = TrendState.BULLISH
                last_event_idx = i
                cur_event_kind = 1.0 if kind == "BOS" else -1.0
                cur_event_dir = 1.0
                # Das gebrochene Hoch ist verbraucht; bis zum nächsten
                # bestätigten Hoch gibt es kein aktives Widerstandsniveau.
                cur_high = None

            if cur_low is not None and close[i] < cur_low.price:
                kind = "BOS" if state is TrendState.BEARISH else "CHoCH"
                events.append(
                    StructureEvent(i, times[i], kind, Direction.SHORT, cur_low.price, cur_low.index)
                )
                state = TrendState.BEARISH
                last_event_idx = i
                cur_event_kind = 1.0 if kind == "BOS" else -1.0
                cur_event_dir = -1.0
                cur_low = None

            last_event_kind[i] = cur_event_kind
            last_event_dir[i] = cur_event_dir
            trend[i] = {TrendState.BULLISH: 1.0, TrendState.BEARISH: -1.0, TrendState.RANGE: 0.0}[state]
            active_high[i] = cur_high.price if cur_high else (confirmed_highs[-1].price if confirmed_highs else np.nan)
            active_low[i] = cur_low.price if cur_low else (confirmed_lows[-1].price if confirmed_lows else np.nan)
            prev_high[i] = confirmed_highs[-2].price if len(confirmed_highs) >= 2 else np.nan
            prev_low[i] = confirmed_lows[-2].price if len(confirmed_lows) >= 2 else np.nan
            bars_since_event[i] = (i - last_event_idx) if last_event_idx is not None else np.nan
            swing_seq_score[i] = _sequence_score(confirmed_highs, confirmed_lows)

        rng = active_high - active_low
        with np.errstate(invalid="ignore", divide="ignore"):
            range_position = np.where(rng > 0, (close - active_low) / rng, np.nan)
            frame = pd.DataFrame(
                {
                    "struct_trend": trend,
                    "struct_event": last_event_kind,
                    "struct_event_dir": last_event_dir,
                    "bars_since_struct_event": bars_since_event,
                    "swing_high": active_high,
                    "swing_low": active_low,
                    "prev_swing_high": prev_high,
                    "prev_swing_low": prev_low,
                    "swing_range_atr": rng / atr_v,
                    # 0 = am Tief (Discount), 1 = am Hoch (Premium), 0,5 = Gleichgewicht
                    "range_position": range_position,
                    "dist_swing_high_atr": (active_high - close) / atr_v,
                    "dist_swing_low_atr": (close - active_low) / atr_v,
                    "swing_sequence": swing_seq_score,
                    "struct_alignment": trend * np.sign(np.nan_to_num(swing_seq_score)),
                },
                index=df.index,
            )
        frame["bars_since_struct_event"] = frame["bars_since_struct_event"].fillna(999.0).clip(upper=999.0)
        # Nach einem Bruch liegt der Kurs außerhalb der alten Spanne; ohne Deckel
        # explodiert die Kennzahl und dominiert später jede Skalierung.
        frame["range_position"] = frame["range_position"].clip(-1.0, 2.0)
        frame["premium_discount"] = (frame["range_position"] - 0.5) * 2.0  # -1 = Discount, +1 = Premium

        result = MarketStructure(swings=swings, events=events, frame=frame)
        result._lookback = L  # type: ignore[attr-defined]
        return result


# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #


def _strength(prominence: float, ref_atr: float) -> float:
    """Wie deutlich ragt der Punkt heraus? Auf [0, 1] gestaucht."""
    if ref_atr <= 0:
        return 0.0
    return float(min(1.0, prominence / (3.0 * ref_atr)))


def _alternate(candidates: list[Swing]) -> list[Swing]:
    """Abwechselnde Hoch-/Tief-Folge erzwingen - NICHT kausal.

    Folgen zwei Hochs aufeinander, überlebt das höhere; bei zwei Tiefs das
    tiefere. Das ergibt einen aufgeräumten Chart, benutzt dafür aber Wissen aus
    der Zukunft: Der zweite Punkt bestimmt rückwirkend, ob der erste je
    existiert hat. Ausschließlich für die Darstellung verwenden, niemals für
    Merkmale oder Signale.
    """
    out: list[Swing] = []
    for s in candidates:
        if not out:
            out.append(s)
            continue
        last = out[-1]
        if last.is_high == s.is_high:
            keep_new = (s.price > last.price) if s.is_high else (s.price < last.price)
            if keep_new:
                out[-1] = s
        else:
            out.append(s)
    return out


def _sequence_score(highs: list[Swing], lows: list[Swing], depth: int = 3) -> float:
    """Bewertet die jüngste Swing-Folge von -1 (klar bärisch) bis +1 (klar bullisch).

    Zählt höhere Hochs und höhere Tiefs gegen tiefere Hochs und tiefere Tiefs -
    also genau das, was ein Chartleser auf einen Blick beurteilt.
    """
    score = 0.0
    total = 0
    for series in (highs, lows):
        recent = series[-(depth + 1) :]
        for a, b in zip(recent, recent[1:]):
            total += 1
            score += 1.0 if b.price > a.price else -1.0
    return score / total if total else 0.0


def swings_to_frame(swings: list[Swing]) -> pd.DataFrame:
    """Swings als Tabelle - praktisch zum Prüfen und Zeichnen."""
    if not swings:
        return pd.DataFrame(columns=["time", "index", "price", "kind", "strength"])
    return pd.DataFrame(
        [
            {"time": s.time, "index": s.index, "price": s.price, "kind": s.kind, "strength": s.strength}
            for s in swings
        ]
    )
