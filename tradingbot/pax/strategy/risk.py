"""Risikomanagement.

Der Teil, der über Erfolg entscheidet - und der einzige, den man vollständig
kontrollieren kann. Die Trefferquote ist Verhandlungssache mit dem Markt, die
Positionsgröße nicht.

Drei Ebenen greifen ineinander:

1. **Größe je Trade**: fester Anteil des Kontos, optional nach Kelly angepasst -
   aber nur mit einem Bruchteil des vollen Kelly-Einsatzes. Voller Kelly ist
   mathematisch optimal und praktisch ruinös, weil er 50-Prozent-Rückgänge als
   normal einkalkuliert.
2. **Gleichzeitiges Risiko**: Summe aller offenen Risiken, mit Aufschlag für
   korrelierte Positionen. Drei Longs in EURUSD, GBPUSD und AUDUSD sind ein
   Trade, nicht drei.
3. **Notbremsen**: Tages-, Wochen- und Gesamtverlustgrenzen. Sie greifen ohne
   Diskussion, gerade weil man sie im Verlust am liebsten aufweichen würde.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import numpy as np

from ..config import RiskConfig
from ..types import AccountState, Direction, Position, Signal, SymbolSpec
from ..utils import clamp, get_logger, safe_div

log = get_logger("risk")


@dataclass
class PositionPlan:
    """Der konkrete Vorschlag für eine Position."""

    allowed: bool
    volume: float = 0.0
    risk_amount: float = 0.0
    risk_pct: float = 0.0
    stop_distance: float = 0.0
    stop_points: float = 0.0
    loss_per_lot: float = 0.0
    kelly_raw: float = 0.0
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.allowed:
            return "abgelehnt: " + "; ".join(self.blockers)
        return (
            f"{self.volume:.2f} Lot | Risiko {self.risk_amount:.2f} "
            f"({self.risk_pct * 100:.2f} %) | Stop {self.stop_points:.0f} Punkte"
        )


@dataclass
class RiskState:
    """Laufende Verlustzähler - die Grundlage aller Notbremsen."""

    day: "date | None" = None
    week: "tuple[int, int] | None" = None
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    day_start_balance: float = 0.0
    week_start_balance: float = 0.0
    equity_peak: float = 0.0
    consecutive_losses: int = 0
    halted_until: "datetime | None" = None
    halt_reason: str = ""


class RiskManager:
    """Berechnet Positionsgrößen und wacht über die Verlustgrenzen."""

    def __init__(self, cfg: RiskConfig, correlations: "dict[tuple[str, str], float] | None" = None) -> None:
        self.cfg = cfg
        self.state = RiskState()
        self.correlations = correlations or {}

    # ------------------------------------------------------------------ #
    # Zustandspflege
    # ------------------------------------------------------------------ #

    def update_account(self, account: AccountState, now: "datetime | None" = None) -> None:
        """Tages-/Wochenwechsel erkennen und Höchststand fortschreiben."""
        now = now or datetime.now(timezone.utc)
        today = now.date()
        week = (now.isocalendar().year, now.isocalendar().week)

        if self.state.day != today:
            self.state.day = today
            self.state.daily_pnl = 0.0
            self.state.day_start_balance = account.balance
            if self.state.halted_until and now >= self.state.halted_until:
                log.info("Handelssperre aufgehoben (%s)", self.state.halt_reason)
                self.state.halted_until = None
                self.state.halt_reason = ""
        if self.state.week != week:
            self.state.week = week
            self.state.weekly_pnl = 0.0
            self.state.week_start_balance = account.balance
        self.state.equity_peak = max(self.state.equity_peak, account.equity)

    def record_trade(self, profit: float, r_multiple: float = 0.0) -> None:
        """Ein abgeschlossener Trade fließt in die Verlustzähler ein."""
        self.state.daily_pnl += profit
        self.state.weekly_pnl += profit
        self.state.consecutive_losses = 0 if profit > 0 else self.state.consecutive_losses + 1

    def halt(self, reason: str, until: "datetime | None" = None) -> None:
        """Handel aussetzen - standardmäßig bis zum nächsten Tag."""
        self.state.halted_until = until or (
            datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        )
        self.state.halt_reason = reason
        log.warning("Handel ausgesetzt: %s (%s)", reason, _halt_until(self.state.halted_until))

    # ------------------------------------------------------------------ #
    # Notbremsen
    # ------------------------------------------------------------------ #

    def check_limits(self, account: AccountState, now: "datetime | None" = None) -> list[str]:
        """Alle Verlustgrenzen prüfen. Leere Liste = Handel erlaubt."""
        now = now or datetime.now(timezone.utc)
        self.update_account(account, now)
        cfg = self.cfg
        blockers: list[str] = []

        if self.state.halted_until and now < self.state.halted_until:
            blockers.append(
                f"Handelssperre aktiv ({self.state.halt_reason}; "
                f"{_halt_until(self.state.halted_until)})"
            )

        base_day = self.state.day_start_balance or account.balance
        if base_day > 0 and self.state.daily_pnl < -cfg.max_daily_loss * base_day:
            msg = f"Tagesverlustgrenze erreicht ({self.state.daily_pnl:.2f} von max. {cfg.max_daily_loss * base_day:.2f})"
            blockers.append(msg)
            if not self.state.halted_until:
                self.halt(msg)

        base_week = self.state.week_start_balance or account.balance
        if base_week > 0 and self.state.weekly_pnl < -cfg.max_weekly_loss * base_week:
            blockers.append(f"Wochenverlustgrenze erreicht ({self.state.weekly_pnl:.2f})")

        peak = self.state.equity_peak or account.equity
        if peak > 0:
            drawdown = (peak - account.equity) / peak
            if drawdown > cfg.max_drawdown_stop:
                msg = f"Maximaler Rückgang überschritten ({drawdown * 100:.1f} % vom Höchststand)"
                blockers.append(msg)
                if not self.state.halted_until:
                    self.halt(msg, until=datetime.max.replace(tzinfo=timezone.utc))

        if account.free_margin <= 0 < account.margin:
            blockers.append("keine freie Margin")
        return blockers

    # ------------------------------------------------------------------ #
    # Positionsgröße
    # ------------------------------------------------------------------ #

    def plan(
        self,
        signal: Signal,
        account: AccountState,
        spec: SymbolSpec,
        open_positions: "list[Position] | None" = None,
        now: "datetime | None" = None,
    ) -> PositionPlan:
        """Positionsgröße bestimmen und alle Grenzen prüfen."""
        cfg = self.cfg
        positions = open_positions or []
        plan = PositionPlan(allowed=False)

        blockers = self.check_limits(account, now)
        plan.blockers.extend(blockers)

        if not signal.is_actionable:
            plan.blockers.append("kein handelbares Signal")
            return plan
        if len(positions) >= cfg.max_open_positions:
            plan.blockers.append(f"Positionsobergrenze erreicht ({len(positions)} von {cfg.max_open_positions})")
        same_symbol = [p for p in positions if p.symbol == signal.symbol]
        if len(same_symbol) >= cfg.max_positions_per_symbol:
            plan.blockers.append(f"Symbol bereits im Bestand ({signal.symbol})")
        opposing = [p for p in same_symbol if p.direction is not signal.direction]
        if opposing:
            plan.blockers.append(f"Gegenposition offen ({signal.symbol})")

        stop_distance = signal.risk_per_unit
        if stop_distance <= 0:
            plan.blockers.append("Stopabstand ist null")
            return plan
        min_dist = spec.min_stop_distance()
        if min_dist > 0 and stop_distance < min_dist:
            plan.blockers.append(
                f"Stopabstand unter Broker-Minimum ({stop_distance:.5f} < {min_dist:.5f})"
            )

        # --- Risikoanteil bestimmen ------------------------------------ #
        risk_pct = cfg.risk_per_trade
        reasons = [f"Grundrisiko {cfg.risk_per_trade * 100:.2f} %"]

        if cfg.use_kelly:
            kelly = self._kelly(signal)
            plan.kelly_raw = round(kelly, 4)
            scaled = kelly * cfg.kelly_fraction
            # Entscheidend: Kelly dämpft in erster Linie. Bei dünnem Vorteil geht
            # die Größe deutlich herunter, nach oben ist bei dem 1,5-fachen des
            # konfigurierten Grundrisikos Schluss. Wer `risk_per_trade: 0.5 %`
            # einstellt, soll nicht plötzlich mit 2 % im Markt stehen, nur weil
            # das Modell für dieses Setup optimistisch ist.
            ceiling = min(1.5 * cfg.risk_per_trade, cfg.max_risk_per_trade)
            floor = 0.25 * cfg.risk_per_trade
            risk_pct = clamp(scaled, floor, ceiling)
            reasons.append(
                f"Kelly {kelly:.3f} x {cfg.kelly_fraction} = {scaled * 100:.2f} % "
                f"-> begrenzt auf {risk_pct * 100:.2f} %"
            )

        # Qualitätsabschlag: schwache Signale bekommen weniger Kapital
        quality = clamp((signal.score - cfg.min_signal_score) / max(1e-9, 1.0 - cfg.min_signal_score), 0.0, 1.0)
        factor = 0.6 + 0.4 * quality
        risk_pct *= factor
        reasons.append(f"Qualitätsfaktor {factor:.2f} (Score {signal.score:.2f})")

        # Nach Verlustserien defensiver werden - kein Aberglaube, sondern
        # Schutz gegen Regime, in denen das Modell gerade nicht passt.
        if self.state.consecutive_losses >= 3:
            damp = 0.5 if self.state.consecutive_losses >= 5 else 0.7
            risk_pct *= damp
            reasons.append(f"{self.state.consecutive_losses} Verluste in Folge -> Faktor {damp}")

        risk_pct = min(risk_pct, cfg.max_risk_per_trade)

        # --- Korreliertes Risiko begrenzen ----------------------------- #
        correlated = self._correlated_risk(signal, positions, account)
        if correlated + risk_pct > cfg.max_correlated_risk:
            allowed = max(0.0, cfg.max_correlated_risk - correlated)
            if allowed < cfg.risk_per_trade * 0.25:
                plan.blockers.append(
                    f"korreliertes Risiko ausgeschöpft ({correlated * 100:.2f} % offen)"
                )
            else:
                risk_pct = allowed
                reasons.append(f"wegen Korrelation auf {risk_pct * 100:.2f} % gekürzt")

        # --- In Lot umrechnen ------------------------------------------ #
        risk_amount = risk_pct * account.balance
        stop_points = stop_distance / spec.point if spec.point > 0 else 0.0
        loss_per_lot = stop_points * spec.value_per_point
        if loss_per_lot <= 0:
            plan.blockers.append("Kontraktdaten unbrauchbar (Punktwert null)")
            return plan

        volume = spec.normalize_volume(safe_div(risk_amount, loss_per_lot))
        actual_risk = volume * loss_per_lot

        if volume < spec.volume_min:
            plan.blockers.append(
                f"Volumen unter Mindestlot - Konto zu klein für dieses Risiko "
                f"({safe_div(risk_amount, loss_per_lot):.4f} < {spec.volume_min})"
            )
        elif actual_risk > cfg.max_risk_per_trade * account.balance * 1.05:
            # Aufrunden auf das Mindestlot kann das Risiko sprengen. Dann lieber gar nicht.
            plan.blockers.append(
                f"Mindestlot sprengt die Risikogrenze ({actual_risk / account.balance * 100:.2f} %)"
            )

        plan.volume = volume
        plan.risk_amount = round(actual_risk, 2)
        plan.risk_pct = round(safe_div(actual_risk, account.balance), 5)
        plan.stop_distance = stop_distance
        plan.stop_points = round(stop_points, 1)
        plan.loss_per_lot = round(loss_per_lot, 2)
        plan.reasons = reasons
        plan.allowed = not plan.blockers
        return plan

    # ------------------------------------------------------------------ #

    @staticmethod
    def _kelly(signal: Signal) -> float:
        """Kelly-Anteil aus Trefferwahrscheinlichkeit und Chance-Risiko-Verhältnis."""
        p = clamp(signal.prob_win, 0.01, 0.99)
        b = max(signal.risk_reward, 0.01)
        return float(max(0.0, (p * (b + 1.0) - 1.0) / b))

    def _correlated_risk(
        self, signal: Signal, positions: list[Position], account: AccountState
    ) -> float:
        """Offenes Risiko in Positionen, die mit dem neuen Signal zusammenhängen."""
        if not positions or account.balance <= 0:
            return 0.0
        total = 0.0
        for pos in positions:
            corr = self.correlation(signal.symbol, pos.symbol)
            if abs(corr) < self.cfg.correlation_threshold:
                continue
            # Gleiche Richtung bei positiver Korrelation häuft Risiko an;
            # entgegengesetzte Richtung hebt es teilweise auf.
            aligned = np.sign(corr) * pos.direction.sign * signal.direction.sign
            if aligned <= 0:
                continue
            risk = pos.risk_per_unit * pos.volume
            total += abs(corr) * risk / account.balance if risk > 0 else 0.0
        return float(total)

    def correlation(self, a: str, b: str) -> float:
        """Korrelation zweier Symbole. Ohne Messwert wird sie geschätzt."""
        if a == b:
            return 1.0
        for key in ((a, b), (b, a)):
            if key in self.correlations:
                return float(self.correlations[key])
        return _guess_correlation(a, b)

    def set_correlations(self, matrix: "dict[tuple[str, str], float]") -> None:
        """Gemessene Korrelationen hinterlegen - besser als jede Schätzung."""
        self.correlations = dict(matrix)


def _halt_until(until: "datetime | None") -> str:
    """Sperrfrist lesbar machen.

    Eine dauerhafte Sperre wird intern mit `datetime.max` hinterlegt. Formatiert
    ergab das die verwirrende Angabe "bis 31.12. 23:59" - das liest sich wie
    Jahresende, gemeint ist aber das Jahr 9999, also: nie wieder ohne Neustart.
    """
    if until is None:
        return "unbefristet"
    if until.year >= 9999:
        return "dauerhaft - nur ein Neustart hebt sie auf"
    return f"bis {until:%d.%m.%Y %H:%M} UTC"


def _guess_correlation(a: str, b: str) -> float:
    """Grobe Schätzung über gemeinsame Währungen im Symbolnamen.

    Nur ein Notbehelf, solange keine gemessenen Werte vorliegen - aber weit
    besser als anzunehmen, EURUSD und GBPUSD hätten nichts miteinander zu tun.
    """
    def parts(symbol: str) -> tuple[str, str]:
        s = "".join(ch for ch in symbol.upper() if ch.isalpha())
        return (s[:3], s[3:6]) if len(s) >= 6 else (s[:3], "")

    a_base, a_quote = parts(a)
    b_base, b_quote = parts(b)
    if not a_base or not b_base:
        return 0.0
    if a_base == b_base and a_quote == b_quote:
        return 1.0
    metals = {"XAU", "XAG", "XPT", "XPD"}
    if (a_base in metals) != (b_base in metals):
        return 0.30  # Metall gegen Devisenpaar: real deutlich lockerer gekoppelt
    if a_base == b_base:
        return 0.70  # gleiche Basiswährung, z. B. EURUSD und EURGBP
    if a_quote == b_quote:
        return 0.60  # gleiche Kurswährung, z. B. EURUSD und GBPUSD
    if a_base == b_quote or a_quote == b_base:
        return -0.55  # über Kreuz: gegenläufig
    return 0.15
