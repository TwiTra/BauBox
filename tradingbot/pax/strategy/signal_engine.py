"""Die Signalbildung - hier wird aus Analyse eine Handelsentscheidung.

Zwei Quellen fließen zusammen:

* das **Modell**, das eine kalibrierte Wahrscheinlichkeit liefert, aber nicht
  begründen kann, warum
* das **Regelwerk**, das begründet, aber nicht rechnet

Beide werden gewichtet verschmolzen und mit der Übereinstimmung der drei
Zeithorizonte multipliziert. Widersprechen sich die Ebenen, fällt der Wert
stark - dann entsteht bewusst kein Signal.

Stop und Ziel kommen anschließend nicht aus einer Formel, sondern aus der
Struktur: Der Stop liegt hinter dem letzten Swing, das Ziel vor dem nächsten
ernstzunehmenden Hindernis. Erst danach entscheidet das Chance-Risiko-Verhältnis,
ob der Trade überhaupt zustande kommt.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import Config
from ..features.builder import FeatureSet
from ..features.regime import RegimeDetector
from ..types import Direction, Horizon, HorizonView, Signal, SymbolSpec, Timeframe, TrendState, VolRegime
from ..utils import clamp, get_logger
from .rules import RuleEngine, RuleResult

log = get_logger("signal")


#: Steilheit der Überzeugungskennlinie. Bei diesem Rohwert liegt die
#: Überzeugung bei rund 0,76 - das ist die Größenordnung eines Setups, bei dem
#: Trendausrichtung, Struktur und Einstiegsort gleichzeitig stimmen.
CONVICTION_GAIN = 4.0


# Ein gerichteter Vorteil wird in Log-Odds gerechnet. Dort ist "kein Vorteil"
# exakt die Null, und Vorteile aus verschiedenen Quellen addieren sich sauber.
RULE_EDGE_GAIN = 0.65  # bewusst zurückhaltend: volle Regelstärke ~ Log-Odds 0.65


def _logit(p: float) -> float:
    p = float(min(max(p, 1e-6), 1.0 - 1e-6))
    return float(np.log(p / (1.0 - p)))


def _sigmoid(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-float(x))))


def _win_probability(edge_logodds: float, reward_risk: float) -> float:
    """Gewinnwahrscheinlichkeit eines Trades mit gegebenem CRV.

    Ausgangspunkt ist der faire Wert: Ein driftloser Zufallspfad trifft ein
    Ziel im Abstand `reward_risk` vor einem Stop im Abstand 1 mit der
    Wahrscheinlichkeit 1/(1+CRV). Genau dort ist der Erwartungswert null.
    Der gerichtete Vorteil verschiebt diesen Anker in Log-Odds.

    Das ist der Unterschied, auf den es ankommt: Eine Richtungswahrschein-
    lichkeit von 0.5 bedeutet "keine Meinung" und muss zu einem Erwartungswert
    von exakt 0 führen - nicht zu einem geschenkten Gewinn, nur weil das Ziel
    weiter entfernt liegt als der Stop.
    """
    fair = 1.0 / (1.0 + max(float(reward_risk), 1e-9))
    return _sigmoid(_logit(fair) + float(edge_logodds))


def _conviction(raw: float) -> float:
    """Rohen Bias-Betrag auf eine Überzeugung in [0, 1] abbilden."""
    return float(2.0 / (1.0 + np.exp(-CONVICTION_GAIN * abs(raw))) - 1.0)


def raw_bias_for(conviction: float) -> float:
    """Umkehrung von `_conviction` - welcher Rohwert steckt hinter einem Score?

    Praktisch, um eine Schwelle wie `min_signal_score: 0.58` einordnen zu können.
    """
    c = float(np.clip(conviction, 1e-6, 1 - 1e-6))
    return float(-np.log(2.0 / (1.0 + c) - 1.0) / CONVICTION_GAIN)


@dataclass
class HorizonModels:
    """Ein Modell je Horizont - oder ein gemeinsames für alle."""

    short: object = None
    medium: object = None
    long: object = None

    def get(self, horizon: Horizon) -> object:
        return {Horizon.SHORT: self.short, Horizon.MEDIUM: self.medium, Horizon.LONG: self.long}[horizon]

    @property
    def any_available(self) -> bool:
        return any(m is not None for m in (self.short, self.medium, self.long))

    @property
    def skill(self) -> float:
        """Nachgewiesene Güte in [0, 1], aus der Out-of-Fold-AUC.

        AUC 0.50 ist Münzwurf und ergibt 0; ab AUC 0.75 zählt das Modell voll.
        Ohne belastbare Kennzahl gilt ein Modell als ahnungslos - das ist die
        vorsichtige Annahme, nicht die bequeme.
        """
        aucs = [
            float(getattr(getattr(m, "report", None), "auc", 0.5))
            for m in (self.short, self.medium, self.long)
            if m is not None
        ]
        if not aucs:
            return 0.0
        return float(min(max(4.0 * (max(aucs) - 0.5), 0.0), 1.0))


class SignalEngine:
    """Erzeugt Signale aus Merkmalen, Modell und Regelwerk."""

    # Gewichtung Modell gegen Regelwerk. Ohne trainiertes Modell entscheidet
    # allein das Regelwerk - das System ist damit vom ersten Tag an handlungsfähig.
    MODEL_WEIGHT = 0.55
    RULE_WEIGHT = 0.45

    def __init__(
        self,
        cfg: Config,
        models: "HorizonModels | object | None" = None,
        rule_engine: "RuleEngine | None" = None,
        blocklist: object = None,
    ) -> None:
        self.cfg = cfg
        self.rules = rule_engine or RuleEngine()
        # Hier schließt sich die Lernschleife: Was die Fehleranalyse als
        # dauerhaft verlustbringend erkannt hat, kommt gar nicht erst durch.
        self.blocklist = blocklist
        if models is None:
            self.models = HorizonModels()
        elif isinstance(models, HorizonModels):
            self.models = models
        else:  # ein einzelnes Ensemble für alle Horizonte
            self.models = HorizonModels(models, models, models)

    # ------------------------------------------------------------------ #
    # Einzelsignal
    # ------------------------------------------------------------------ #

    def generate(
        self,
        fs: FeatureSet,
        index: int = -1,
        spec: "SymbolSpec | None" = None,
        proba: "float | None" = None,
    ) -> Signal:
        """Signal für einen Balken. `proba` erspart im Backtest den Modellaufruf."""
        if len(fs.frame) == 0:
            raise ValueError("Leere Merkmalsmatrix")
        i = index if index >= 0 else len(fs.frame) + index
        row = fs.frame.iloc[i]
        bar = fs.base.iloc[i]
        atr = float(fs.atr.iloc[i])
        time = fs.frame.index[i]

        rule = self.rules.evaluate(row)
        if proba is None and self.models.any_available:
            proba = self._model_proba(fs, i)

        views = self._horizon_views(fs, i, row, rule, proba)
        combined, alignment = self._fuse(rule, proba, views)

        direction = (
            Direction.LONG if combined > 0 else Direction.SHORT if combined < 0 else Direction.FLAT
        )
        score = abs(combined)

        signal = Signal(
            symbol=fs.symbol,
            time=time.to_pydatetime() if hasattr(time, "to_pydatetime") else time,
            direction=direction,
            score=round(float(score), 4),
            entry=float(bar["close"]),
            stop_loss=0.0,
            atr=atr,
            regime=RegimeDetector.to_enum(row.get("vol_regime", 1.0)),
            trend_alignment=round(float(alignment), 4),
            reasons=list(rule.reasons),
            warnings=list(rule.warnings),
            views=views,
            prob_win=float(proba) if proba is not None else 0.5,
            horizon=self._pick_horizon(views),
            model_version=getattr(self.models.get(Horizon.MEDIUM), "version", ""),
            max_hold_bars=int(self.cfg.labels.max_horizon_bars * self.cfg.risk.max_hold_bars_factor),
        )

        if direction is Direction.FLAT or atr <= 0:
            signal.reasons = ["kein ausreichender Vorteil erkennbar"] + signal.reasons[:2]
            return signal

        self._set_levels(signal, fs, i, row, spec)
        self._score_expectancy(signal, proba, rule)
        self._apply_filters(signal, row)
        return signal

    # ------------------------------------------------------------------ #

    def _model_proba(self, fs: FeatureSet, i: int) -> float:
        model = self.models.get(Horizon.MEDIUM) or self.models.get(Horizon.SHORT)
        if model is None:
            return 0.5
        try:
            return float(model.predict_proba(fs.frame.iloc[[i]])[0])
        except Exception as exc:
            log.warning("Modellabfrage fehlgeschlagen (%s) - es entscheidet das Regelwerk", exc)
            return 0.5

    def _horizon_views(
        self, fs: FeatureSet, i: int, row: pd.Series, rule: RuleResult, proba: "float | None"
    ) -> dict[str, HorizonView]:
        """Für jeden Horizont eine eigene Sicht auf den Markt."""
        views: dict[str, HorizonView] = {}
        base_tf = fs.timeframe
        for horizon in Horizon:
            tf = self.cfg.data.tf(horizon)
            prefix = "" if tf == base_tf else f"{tf.value.lower()}_"
            trend_value = row.get(f"{prefix}struct_trend", row.get("struct_trend", 0.0))
            trend = (
                TrendState.BULLISH if trend_value > 0.5
                else TrendState.BEARISH if trend_value < -0.5
                else TrendState.RANGE
            )
            # Regelanteil dieses Horizonts: Struktur und Ort auf seiner Ebene
            local = self._local_rule_score(row, prefix, rule)
            reasons = []
            if trend is not TrendState.RANGE:
                reasons.append(f"{tf.value}: {'Aufwärts' if trend is TrendState.BULLISH else 'Abwärts'}struktur")
            views[horizon.value] = HorizonView(
                horizon=horizon,
                timeframe=tf,
                trend=trend,
                prob_up=float(proba) if proba is not None else 0.5,
                confidence=abs(local),
                rule_score=float(local),
                atr=float(fs.atr.iloc[i]),
                regime=RegimeDetector.to_enum(row.get(f"{prefix}vol_regime", row.get("vol_regime", 1.0))),
                reasons=reasons,
                model_available=proba is not None,
            )
        return views

    @staticmethod
    def _local_rule_score(row: pd.Series, prefix: str, rule: RuleResult) -> float:
        """Regelbewertung, auf die Merkmale einer Zeitebene eingeengt."""
        trend = float(row.get(f"{prefix}struct_trend", 0.0) or 0.0)
        location = -float(row.get(f"{prefix}premium_discount", 0.0) or 0.0)
        smc = float(row.get(f"{prefix}smc_score", 0.0) or 0.0)
        regime = float(row.get(f"{prefix}regime_score", 0.0) or 0.0)
        local = 0.40 * trend + 0.25 * clamp(location, -1, 1) + 0.20 * smc + 0.15 * clamp(regime, -1, 1)
        if not prefix:  # auf der Basisebene zählt die volle Regelbewertung mit
            local = 0.6 * local + 0.4 * rule.score
        return float(clamp(local, -1.0, 1.0))

    def _fuse(
        self, rule: RuleResult, proba: "float | None", views: dict[str, HorizonView]
    ) -> tuple[float, float]:
        """Modell und Regelwerk zusammenführen, gedämpft durch die Zeitebenen-Einigkeit."""
        from ..features.mtf import alignment_score

        biases = {v.horizon: v.bias for v in views.values()}
        alignment = alignment_score(biases)

        if proba is None:
            combined = rule.score
        else:
            # Das Modell bekommt nur so viel Gewicht, wie es nachgewiesen hat.
            # Mit festen Gewichten löscht ein ahnungsloses Modell (proba ~ 0.5,
            # also Bias ~ 0) die Regelmeinung rechnerisch aus: Der Regelanteil
            # schrumpft auf 45 %, und kein noch so gutes Setup erreicht dann
            # die Mindestschwelle. Ein Modell ohne Wissen muss neutral sein,
            # nicht vetoberechtigt.
            model_bias = (float(proba) - 0.5) * 2.0
            w_model = self.MODEL_WEIGHT * self.models.skill
            w_rule = 1.0 - w_model
            combined = w_model * model_bias + w_rule * rule.score

        # Widersprechen sich Zeitebenen und Gesamtbild, wird der Wert gestaucht.
        if combined != 0 and alignment != 0 and np.sign(alignment) != np.sign(combined):
            combined *= 0.35
        else:
            combined *= 0.55 + 0.45 * abs(alignment)

        # Der Rohwert ist eine gewichtete Summe: selbst ein sehr gutes Setup
        # erreicht selten mehr als 0,4, weil nie alle Regelblöcke gleichzeitig
        # ausschlagen. Damit `min_signal_score` eine verständliche Bedeutung
        # bekommt, wird der Rohwert über eine sättigende Kennlinie auf eine
        # Überzeugungsskala von 0 bis 1 gebracht. Die Rangfolge bleibt dabei
        # unverändert - es ist eine Umrechnung, keine Verstärkung.
        conviction = _conviction(abs(combined))
        return float(np.sign(combined) * conviction), float(alignment)

    @staticmethod
    def _pick_horizon(views: dict[str, HorizonView]) -> Horizon:
        """Der Horizont mit der deutlichsten Meinung gibt dem Signal seinen Charakter."""
        best = max(views.values(), key=lambda v: abs(v.bias), default=None)
        return best.horizon if best else Horizon.MEDIUM

    # ------------------------------------------------------------------ #
    # Stop, Ziel, Erwartungswert
    # ------------------------------------------------------------------ #

    def _set_levels(
        self, signal: Signal, fs: FeatureSet, i: int, row: pd.Series, spec: "SymbolSpec | None"
    ) -> None:
        """Stop hinter die Struktur, Ziel vor das nächste Hindernis."""
        risk_cfg = self.cfg.risk
        atr = signal.atr
        entry = signal.entry
        is_long = signal.direction is Direction.LONG

        # --- Stop: hinter dem letzten bestätigten Swing ---------------- #
        structure = fs.structures.get(fs.timeframe.value)
        swing_price = np.nan
        if structure is not None and not structure.frame.empty:
            key = "swing_low" if is_long else "swing_high"
            if key in structure.frame.columns:
                swing_price = float(structure.frame[key].iloc[i])

        buffer = 0.25 * atr  # Puffer gegen Dochte, die den Stop streifen
        if np.isfinite(swing_price):
            raw_stop = swing_price - buffer if is_long else swing_price + buffer
            distance = abs(entry - raw_stop)
        else:
            distance = 1.2 * atr

        # Der Stop darf weder im Rauschen liegen noch das Risiko sprengen.
        distance = clamp(distance, risk_cfg.min_stop_atr * atr, risk_cfg.max_stop_atr * atr)
        stop = entry - distance if is_long else entry + distance

        # --- Ziel: bis zum nächsten Hindernis -------------------------- #
        # Das Ziel orientiert sich am Horizont, für den das Modell trainiert wurde;
        # die Struktur moduliert es nur. Andersherum - Struktur schlägt Horizont -
        # würde ein einzelnes Nebenlevel jeden Trade unwirtschaftlich machen.
        rr_label = self.cfg.labels.tp_atr / max(self.cfg.labels.sl_atr, 1e-9)
        obstacle_atr = self._next_obstacle(row, is_long)
        if obstacle_atr > 0 and distance > 0:
            rr_structural = obstacle_atr * atr / distance
            rr = clamp(rr_structural, 0.75 * rr_label, 1.5 * rr_label)
        else:
            rr = rr_label
        rr = clamp(rr, 0.5, 5.0)

        sign = 1 if is_long else -1
        targets = [entry + sign * r * distance for r in risk_cfg.partial_take_r if r < rr]
        targets.append(entry + sign * rr * distance)

        if spec is not None:
            stop = spec.normalize_price(stop)
            targets = [spec.normalize_price(t) for t in targets]
            entry = spec.normalize_price(entry)
            signal.entry = entry

        signal.stop_loss = float(stop)
        signal.take_profits = [float(t) for t in targets]
        fractions = list(risk_cfg.partial_fractions[: len(targets) - 1])
        fractions.append(round(1.0 - sum(fractions), 4))
        signal.tp_fractions = fractions
        signal.risk_reward = round(float(rr), 3)

    #: Hindernisse näher als dieser ATR-Abstand begrenzen kein Ziel. Ein Level
    #: eine halbe ATR über dem Kurs hält den Markt nicht auf - der handelt
    #: routinemäßig hindurch. Wer solche Nahziele als Deckel nimmt, erzeugt
    #: lauter 0,5er-CRVs und damit ein System, das nie handelt.
    MIN_OBSTACLE_ATR = 1.0

    @staticmethod
    def _next_obstacle(row: pd.Series, is_long: bool) -> float:
        """Abstand zum nächsten *ernstzunehmenden* Hindernis in ATR.

        Für einen Long sind das Widerstände, bärische Order Blocks und
        Liquiditätsansammlungen darüber. Zu nahe Hindernisse werden übergangen,
        weil der Kurs sie erfahrungsgemäß mitnimmt.
        """
        keys = (
            ("res_dist_atr", "ob_bear_dist_atr", "fvg_bear_dist_atr", "liq_above_dist_atr")
            if is_long
            else ("sup_dist_atr", "ob_bull_dist_atr", "fvg_bull_dist_atr", "liq_below_dist_atr")
        )
        candidates = [
            value
            for key in keys
            if SignalEngine.MIN_OBSTACLE_ATR < (value := float(row.get(key, 20.0) or 20.0)) < 19.9
        ]
        if not candidates:
            return 0.0
        # Der Kurs schießt typischerweise etwas über das Hindernis hinaus.
        return float(min(candidates) * 1.15)

    def _score_expectancy(self, signal: Signal, proba: "float | None", rule: RuleResult) -> None:
        """Erwartungswert in R - die Zahl, die am Ende zählt."""
        # Teilgewinne senken das mittlere Gewinn-R gegenüber dem vollen Ziel.
        # Der Anker muss auf demselben CRV sitzen, gegen das am Ende gerechnet
        # wird - sonst ist der Erwartungswert bei fehlendem Vorteil nicht null.
        avg_rr = signal.risk_reward
        if len(signal.take_profits) > 1 and signal.tp_fractions:
            r_levels = [
                abs(tp - signal.entry) / max(signal.risk_per_unit, 1e-12)
                for tp in signal.take_profits
            ]
            avg_rr = float(np.dot(r_levels, signal.tp_fractions))

        if proba is not None:
            # Das Modell ist auf symmetrische Barrieren trainiert: 0.5 heißt
            # "keine Richtungsmeinung". Für einen Short zählt die Gegenwahr-
            # scheinlichkeit - bei symmetrischen Barrieren ist das zulässig.
            p_dir = float(proba) if signal.direction is Direction.LONG else 1.0 - float(proba)
            edge = _logit(p_dir)  # logit(0.5) = 0, der Nullpunkt stimmt also
        else:
            edge = RULE_EDGE_GAIN * abs(float(rule.score))

        p = clamp(_win_probability(edge, avg_rr), 0.05, 0.95)
        signal.prob_win = round(p, 4)
        signal.expected_r = round(float(p * avg_rr - (1.0 - p) * 1.0), 4)

    def _apply_filters(self, signal: Signal, row: pd.Series) -> None:
        """Harte Ausschlusskriterien. Ein Signal, das hier hängenbleibt, wird flach."""
        r = self.cfg.risk
        # Der Text vor der Klammer ist die Kategorie - der Backtest zählt danach.
        # Stünde der Zahlenwert davor, ergäbe jede Ablehnung eine eigene Zeile im
        # Bericht und man sähe vor lauter Einzelfällen das Muster nicht mehr.
        blockers = []
        if signal.score < r.min_signal_score:
            blockers.append(f"Score unter Mindestwert ({signal.score:.2f} < {r.min_signal_score})")
        if signal.risk_reward < r.min_risk_reward:
            blockers.append(f"CRV unter Mindestwert ({signal.risk_reward:.2f} < {r.min_risk_reward})")
        if signal.expected_r <= 0:
            blockers.append(f"negativer Erwartungswert ({signal.expected_r:+.2f} R)")
        if signal.risk_per_unit <= 0:
            blockers.append("kein gültiger Stop")

        spread_atr = float(row.get("spread_atr", 0.0) or 0.0)
        if spread_atr > r.max_spread_atr:
            blockers.append(f"Spread zu hoch ({spread_atr:.2f} ATR)")

        if self.blocklist is not None:
            blocked = self.blocklist.check(self.block_context(signal))  # type: ignore[attr-defined]
            if blocked:
                blockers.append(blocked)

        if blockers:
            signal.direction = Direction.FLAT
            signal.warnings = blockers + signal.warnings

    @staticmethod
    def block_context(signal: Signal) -> dict[str, str]:
        """Kategorien des Signals für die Sperrprüfung.

        Muss zu `FeedbackAnalyzer.enrich` passen - sonst greift keine Sperre,
        weil beide Seiten unterschiedliche Namen verwenden.
        """
        hour = signal.time.hour
        bucket = (
            "asien" if hour <= 6
            else "london_vormittag" if hour <= 11
            else "ueberschneidung" if hour <= 15
            else "newyork" if hour <= 20
            else "spaet"
        )
        score = signal.score
        score_bucket = (
            "knapp" if score <= 0.5
            else "mittel" if score <= 0.6
            else "gut" if score <= 0.7
            else "sehr_gut"
        )
        return {
            "symbol": signal.symbol,
            "regime": signal.regime.value,
            "horizon": signal.horizon.value,
            "direction": signal.direction.value,
            "hour_bucket": bucket,
            "score_bucket": score_bucket,
        }

    # ------------------------------------------------------------------ #
    # Serienbetrieb für den Backtest
    # ------------------------------------------------------------------ #

    def generate_series(
        self, fs: FeatureSet, spec: "SymbolSpec | None" = None, start: int = 0
    ) -> list[Signal]:
        """Signale für jeden Balken - im Backtest deutlich schneller.

        Die Modellabfrage läuft einmal für alle Zeilen als Block statt Zeile für
        Zeile; das spart bei 20 000 Balken Minuten.
        """
        probas: "np.ndarray | None" = None
        model = self.models.get(Horizon.MEDIUM) or self.models.get(Horizon.SHORT)
        if model is not None:
            try:
                probas = model.predict_proba(fs.frame)
            except Exception as exc:
                log.warning("Modellabfrage im Block fehlgeschlagen (%s) - nur Regelwerk", exc)

        out: list[Signal] = []
        for i in range(start, len(fs.frame)):
            p = float(probas[i]) if probas is not None else None
            out.append(self.generate(fs, i, spec, proba=p))
        return out
