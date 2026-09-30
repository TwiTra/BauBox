"""Das Regelwerk - Price Action in nachvollziehbaren Punkten.

Das Modell liefert eine Wahrscheinlichkeit, aber keine Begründung. Für den
Handel ist beides nötig: eine Zahl zum Rechnen und ein Satz zum Verstehen. Wer
nicht sagen kann, *warum* eine Position offen ist, kann auch nicht beurteilen,
wann die Begründung wegfällt.

Jede Regel gibt einen Beitrag zwischen -1 und +1 sowie einen Klartextgrund
zurück. Die Gewichte spiegeln das, was sich über Jahre als tragfähig erwiesen
hat: Trendausrichtung und Einstiegsort schlagen jedes Kerzenmuster.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..types import Direction, Horizon
from ..utils import clamp


@dataclass
class RuleResult:
    """Ergebnis der Regelprüfung für einen Balken."""

    score: float = 0.0  # -1 (klar short) bis +1 (klar long)
    direction: Direction = Direction.FLAT
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    contributions: dict[str, float] = field(default_factory=dict)

    @property
    def strength(self) -> float:
        return abs(self.score)

    def top_reasons(self, n: int = 4) -> list[str]:
        return self.reasons[:n]


# Gewichte der Regelblöcke. Summe = 1,0. Wer hier schraubt, ändert den Charakter
# des Systems - deshalb stehen sie zentral und nicht verstreut im Code.
WEIGHTS = {
    "trend_alignment": 0.22,
    "structure": 0.18,
    "location": 0.16,
    "zones": 0.13,
    "liquidity": 0.11,
    "momentum": 0.08,
    "candles": 0.07,
    "levels": 0.05,
}


class RuleEngine:
    """Bewertet einen Balken nach klassischen Price-Action-Kriterien."""

    def __init__(self, weights: "dict[str, float] | None" = None) -> None:
        self.weights = dict(weights or WEIGHTS)
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}

    # ------------------------------------------------------------------ #

    def evaluate(self, row: pd.Series, tf_prefixes: "list[str] | None" = None) -> RuleResult:
        """Alle Regeln auf eine Merkmalszeile anwenden."""
        res = RuleResult()
        prefixes = tf_prefixes or _detect_prefixes(row)
        parts: dict[str, tuple[float, list[str]]] = {
            "trend_alignment": self._trend_alignment(row, prefixes),
            "structure": self._structure(row),
            "location": self._location(row, prefixes),
            "zones": self._zones(row),
            "liquidity": self._liquidity(row),
            "momentum": self._momentum(row),
            "candles": self._candles(row),
            "levels": self._levels(row),
        }

        score = 0.0
        for name, (value, reasons) in parts.items():
            weight = self.weights.get(name, 0.0)
            contribution = clamp(value, -1.0, 1.0) * weight
            res.contributions[name] = round(contribution, 4)
            score += contribution
            res.reasons.extend(reasons)

        res.score = float(clamp(score, -1.0, 1.0))
        res.direction = (
            Direction.LONG if res.score > 0.12
            else Direction.SHORT if res.score < -0.12
            else Direction.FLAT
        )
        # Beiträge, die dem Gesamtergebnis widersprechen, als Warnung ausweisen
        if res.direction is not Direction.FLAT:
            sign = res.direction.sign
            for name, contribution in res.contributions.items():
                if contribution * sign < -0.03:
                    res.warnings.append(f"{name} spricht dagegen ({contribution:+.2f})")
        res.reasons.sort(key=lambda r: -_reason_weight(r))
        res.warnings.extend(self._regime_warnings(row))
        return res

    # ------------------------------------------------------------------ #
    # Einzelne Regelblöcke
    # ------------------------------------------------------------------ #

    def _trend_alignment(self, row: pd.Series, prefixes: list[str]) -> tuple[float, list[str]]:
        """Zeigen alle Zeitebenen in dieselbe Richtung?

        Die wirksamste Einzelregel im gesamten System. Gegen den übergeordneten
        Trend zu handeln kostet über die Jahre mehr als jeder Spread.
        """
        trends = []
        labels = []
        for prefix in [""] + prefixes:
            key = f"{prefix}struct_trend"
            if key in row and np.isfinite(row[key]):
                trends.append(float(row[key]))
                labels.append(prefix.rstrip("_").upper() or "Basis")
        if not trends:
            return 0.0, []

        weights = np.linspace(1.0, 1.8, len(trends))  # höhere Ebenen zählen mehr
        raw = float(np.average(trends, weights=weights))
        signs = [np.sign(t) for t in trends if t != 0]
        agreement = abs(sum(signs)) / len(signs) if signs else 0.0
        value = raw * (0.4 + 0.6 * agreement)

        reasons = []
        if agreement >= 0.99 and len(trends) >= 2 and abs(raw) > 0.5:
            word = "Aufwärts" if raw > 0 else "Abwärts"
            reasons.append(f"[stark] {word}struktur auf allen Zeitebenen ({', '.join(labels)})")
        elif agreement < 0.5 and len(trends) >= 2:
            reasons.append("Zeitebenen widersprechen sich")

        # Zusätzlich der gleitende Durchschnitt als grober Trendfilter
        stack = row.get("ema_stack", np.nan)
        if np.isfinite(stack) and stack != 0:
            value = 0.85 * value + 0.15 * float(stack)
        return value, reasons

    def _structure(self, row: pd.Series) -> tuple[float, list[str]]:
        """Frischer Strukturbruch in Handelsrichtung?"""
        event = float(row.get("struct_event", 0.0) or 0.0)
        direction = float(row.get("struct_event_dir", 0.0) or 0.0)
        age = float(row.get("bars_since_struct_event", 999.0) or 999.0)
        sequence = float(row.get("swing_sequence", 0.0) or 0.0)

        if direction == 0 or age > 30:
            return 0.6 * sequence, (
                ["Swing-Folge stützt die Richtung"] if abs(sequence) > 0.6 else []
            )

        # Frische Ereignisse zählen deutlich mehr als alte
        freshness = float(np.exp(-age / 12.0))
        kind_weight = 1.0 if event > 0 else 0.85  # BOS etwas stärker als CHoCH
        value = direction * freshness * kind_weight
        value = 0.75 * value + 0.25 * sequence

        reasons = []
        if freshness > 0.5:
            name = "BOS" if event > 0 else "CHoCH"
            word = "aufwärts" if direction > 0 else "abwärts"
            reasons.append(f"[stark] frischer {name} {word} vor {int(age)} Balken")
        return value, reasons

    def _location(self, row: pd.Series, prefixes: list[str]) -> tuple[float, list[str]]:
        """Wird an der richtigen Stelle eingestiegen?

        Der klassische Fehler: im Aufwärtstrend am Hoch kaufen. Richtig ist der
        Rücksetzer in die untere Hälfte der Spanne - dort ist der Stop nah und
        das Ziel weit.
        """
        pos = row.get("premium_discount", np.nan)
        higher_key = next(
            (f"{p}premium_discount" for p in reversed(prefixes) if f"{p}premium_discount" in row),
            None,
        )
        higher_pos = row.get(higher_key, np.nan) if higher_key else np.nan
        trend = float(row.get("struct_trend", 0.0) or 0.0)
        if not np.isfinite(pos):
            return 0.0, []

        # Im Discount (pos < 0) sind Käufe günstig, im Premium Verkäufe.
        base = float(-clamp(pos, -1.0, 1.0))
        if np.isfinite(higher_pos):
            base = 0.6 * base + 0.4 * float(-clamp(higher_pos, -1.0, 1.0))

        reasons = []
        if trend > 0 and base > 0.35:
            reasons.append("[stark] Rücksetzer in die Discount-Zone eines Aufwärtstrends")
        elif trend < 0 and base < -0.35:
            reasons.append("[stark] Anstieg in die Premium-Zone eines Abwärtstrends")
        elif trend != 0 and base * trend < -0.4:
            reasons.append("ungünstiger Einstiegsort - dem Trend hinterhergelaufen")

        # Nur bei vorhandenem Trend zählt der Ort voll; in der Range weniger.
        weight = 1.0 if trend != 0 else 0.5
        return base * weight, reasons

    def _zones(self, row: pd.Series) -> tuple[float, list[str]]:
        """Steht der Kurs in einem Order Block oder einer Imbalance?"""
        value = 0.0
        reasons = []
        in_ob = float(row.get("ob_in_bull", 0)) - float(row.get("ob_in_bear", 0))
        in_fvg = float(row.get("fvg_in_bull", 0)) - float(row.get("fvg_in_bear", 0))
        confluence = float(row.get("zone_confluence", 0.0) or 0.0)

        if in_ob != 0:
            value += 0.55 * np.sign(in_ob)
            reasons.append(f"[stark] Kurs im {'bullischen' if in_ob > 0 else 'bärischen'} Order Block")
        if in_fvg != 0:
            value += 0.3 * np.sign(in_fvg)
            reasons.append(f"Kurs in einer {'bullischen' if in_fvg > 0 else 'bärischen'} Imbalance")
        value += 0.4 * clamp(confluence, -1, 1)

        # Nähe zu einer noch nicht erreichten Zone
        for key, sign, text in (
            ("ob_bull_dist_atr", 1, "bullischer Order Block in Reichweite"),
            ("ob_bear_dist_atr", -1, "bärischer Order Block in Reichweite"),
        ):
            d = float(row.get(key, 20.0) or 20.0)
            if 0 < d < 0.6:
                value += 0.2 * sign
                reasons.append(text)
        return clamp(value, -1, 1), reasons

    def _liquidity(self, row: pd.Series) -> tuple[float, list[str]]:
        """Wurde Liquidität abgeholt und der Kurs sofort zurückgewiesen?

        Das Muster, an dem sich professionelles von naivem Handeln unterscheidet:
        Der Ausbruch, der scheitert, ist verlässlicher als der, der gelingt.
        """
        sweep = float(row.get("sweep_signal", 0.0) or 0.0)
        age = float(row.get("bars_since_sweep", 200.0) or 200.0)
        value = sweep
        reasons = []
        if abs(sweep) > 0.35 and age <= 5:
            word = "unter" if sweep > 0 else "über"
            side = "Tiefs" if sweep > 0 else "Hochs"
            reasons.append(f"[stark] Liquiditätsgriff {word} die {side} und Rückeroberung")

        # Ungeräumte Liquidität voraus wirkt wie ein Magnet
        above = float(row.get("liq_above_dist_atr", 20.0) or 20.0)
        below = float(row.get("liq_below_dist_atr", 20.0) or 20.0)
        if above < 1.2 and above < below:
            value += 0.2
            reasons.append("Liquidität knapp über dem Kurs zieht an")
        elif below < 1.2 and below < above:
            value -= 0.2
            reasons.append("Liquidität knapp unter dem Kurs zieht an")
        return clamp(value, -1, 1), reasons

    def _momentum(self, row: pd.Series) -> tuple[float, list[str]]:
        """Trägt das Momentum die Bewegung noch?"""
        di = float(row.get("di_diff", 0.0) or 0.0)
        adx = float(row.get("adx", 0.0) or 0.0)
        rsi = float(row.get("rsi", 50.0) or 50.0)
        macd_h = float(row.get("macd_hist_atr", 0.0) or 0.0)

        value = 0.0
        value += 0.4 * clamp(di / 25.0, -1, 1) * clamp(adx / 30.0, 0, 1)
        value += 0.3 * clamp(macd_h / 0.5, -1, 1)
        # RSI wird bewusst NICHT als Umkehrsignal benutzt: "überkauft" ist im
        # Trend der Normalzustand, nicht die Ausnahme.
        value += 0.3 * clamp((rsi - 50.0) / 25.0, -1, 1)

        reasons = []
        if adx > 28 and abs(di) > 12:
            reasons.append(f"kräftiger Trend (ADX {adx:.0f}, DI-Differenz {di:+.0f})")
        elif adx < 16:
            reasons.append("kein Trendmomentum (ADX unter 16)")
        return clamp(value, -1, 1), reasons

    def _candles(self, row: pd.Series) -> tuple[float, list[str]]:
        """Bestätigt die letzte Kerze den Einstieg?"""
        score = float(row.get("pattern_score", 0.0) or 0.0)
        reasons = []
        for key, label in (
            ("pat_pinbar", "Pin Bar"),
            ("pat_engulfing", "Engulfing"),
            ("pat_2bar_reversal", "Zwei-Balken-Umkehr"),
            ("pat_momentum", "Momentumkerze"),
        ):
            v = float(row.get(key, 0.0) or 0.0)
            if abs(v) > 0.45:
                reasons.append(f"{label} {'bullisch' if v > 0 else 'bärisch'}")
        return clamp(score, -1, 1), reasons

    def _levels(self, row: pd.Series) -> tuple[float, list[str]]:
        """Ist der Weg frei oder steht ein starkes Niveau im Weg?"""
        res_d = float(row.get("res_dist_atr", 20.0) or 20.0)
        sup_d = float(row.get("sup_dist_atr", 20.0) or 20.0)
        res_s = float(row.get("res_strength", 0.0) or 0.0)
        sup_s = float(row.get("sup_strength", 0.0) or 0.0)

        value = 0.0
        reasons = []
        if sup_d < 0.5 and sup_s > 0.4:
            value += 0.6 * sup_s
            reasons.append("Kurs an bestätigter Unterstützung")
        if res_d < 0.5 and res_s > 0.4:
            value -= 0.6 * res_s
            reasons.append("Kurs an bestätigtem Widerstand")
        # Ein naher Widerstand deckelt das Gewinnziel eines Longs
        if 0.5 <= res_d < 1.5 and res_s > 0.5:
            value -= 0.3
            reasons.append("Widerstand begrenzt das Aufwärtspotenzial")
        if 0.5 <= sup_d < 1.5 and sup_s > 0.5:
            value += 0.3
            reasons.append("Unterstützung begrenzt das Abwärtspotenzial")
        return clamp(value, -1, 1), reasons

    @staticmethod
    def _regime_warnings(row: pd.Series) -> list[str]:
        """Umstände, die jedes Setup schlechter machen, egal wie schön es aussieht."""
        out = []
        vol = float(row.get("vol_regime", 1.0) or 1.0)
        if vol >= 3:
            out.append("extreme Volatilität - Stops werden leicht ausgelöst")
        trendiness = float(row.get("trendiness", 0.4) or 0.4)
        if trendiness < 0.22:
            out.append("ausgeprägte Seitwärtsphase - Ausbrüche scheitern häufig")
        liquidity = float(row.get("liquidity_score", 1.0) or 1.0)
        if liquidity < 0.45:
            out.append("dünne Handelszeit - erhöhte Spreads und Schlupf")
        expansion = float(row.get("vol_expansion", 1.0) or 1.0)
        if expansion > 2.2:
            out.append("Volatilität explodiert - womöglich Nachrichtenlage")
        return out


# --------------------------------------------------------------------------- #


def _detect_prefixes(row: pd.Series) -> list[str]:
    """Welche Zeitebenen-Präfixe kommen in der Zeile vor? (z. B. h1_, h4_)

    Es wird nicht geraten, sondern gegen die bekannten Zeiteinheiten geprüft.
    Der frühere Namensheuristik fiel unter anderem `r2_20` (Regressionsgüte)
    zum Opfer, was eine Zeitebene vortäuschte, die es gar nicht gibt.
    """
    from ..types import Timeframe

    known = {tf.value.lower() for tf in Timeframe}
    # Series wie einfache Abbildungen zulassen - die Massenauswertung reicht
    # Wörterbücher durch, weil pandas-Zeilenzugriff dafür zu langsam ist.
    namen = row.index if hasattr(row, "index") else row.keys()
    prefixes = {
        f"{name.split('_', 1)[0]}_"
        for name in namen
        if "_" in name and name.split("_", 1)[0] in known
    }
    order = {"m": 0, "h": 1, "d": 2, "w": 3}
    return sorted(
        prefixes,
        key=lambda p: (order.get(p[0], 9), int("".join(ch for ch in p if ch.isdigit()) or 0)),
    )


def _reason_weight(reason: str) -> float:
    """Begründungen mit [stark]-Markierung nach oben sortieren."""
    return 1.0 if reason.startswith("[stark]") else 0.0
