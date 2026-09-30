"""Der Wächter - alles, was den Handel sofort stoppen muss.

Ein Handelssystem scheitert selten an einer schlechten Prognose. Es scheitert
an einer abgerissenen Verbindung, an veralteten Kursen, an einer Endlosschleife
aus Fehlversuchen oder daran, dass niemand hinsieht, während ein Konto
leerläuft.

Dieser Wächter prüft vor jedem Handelsschritt und hat Vorrang vor jeder
Strategie: Was er blockiert, wird nicht gehandelt - ohne Diskussion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..config import Config
from ..types import AccountState, utcnow
from ..utils import get_logger

log = get_logger("guard")


@dataclass
class GuardStatus:
    """Ergebnis einer Prüfung."""

    ok: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    kill_switch: bool = False

    def summary(self) -> str:
        if self.kill_switch:
            return "NOTAUS: " + "; ".join(self.blockers)
        if not self.ok:
            return "gesperrt: " + "; ".join(self.blockers)
        return "frei" + (f" (Hinweise: {'; '.join(self.warnings)})" if self.warnings else "")


class Guard:
    """Betriebsüberwachung mit Notaus."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.errors_in_row = 0
        self.kill_switch = False
        self.kill_reason = ""
        self.start_equity = 0.0
        self.equity_peak = 0.0
        self.last_bar_time: "datetime | None" = None
        self.last_success: "datetime | None" = None

    # ------------------------------------------------------------------ #

    def note_error(self, exc: BaseException) -> None:
        self.errors_in_row += 1
        log.error("Fehler im Livebetrieb (%d in Folge): %s", self.errors_in_row, exc)
        if self.errors_in_row >= 10:
            self.trip("10 Fehler in Folge - der Zustand ist nicht mehr vertrauenswürdig")

    def note_success(self) -> None:
        self.errors_in_row = 0
        self.last_success = utcnow()

    def trip(self, reason: str) -> None:
        """Notaus auslösen. Nur ein Neustart hebt das auf - mit Absicht."""
        if not self.kill_switch:
            log.critical("NOTAUS ausgelöst: %s", reason)
        self.kill_switch = True
        self.kill_reason = reason

    def reset(self) -> None:
        self.kill_switch = False
        self.kill_reason = ""
        self.errors_in_row = 0

    # ------------------------------------------------------------------ #

    def check(
        self,
        account: "AccountState | None" = None,
        broker_health: "dict | None" = None,
        bar_time: "datetime | None" = None,
        now: "datetime | None" = None,
    ) -> GuardStatus:
        """Vollständige Prüfung vor dem nächsten Handelsschritt."""
        now = now or utcnow()
        status = GuardStatus(ok=True)

        if self.kill_switch:
            return GuardStatus(False, [f"Notaus aktiv: {self.kill_reason}"], kill_switch=True)

        # --- Verbindung ------------------------------------------------ #
        if broker_health is not None:
            if not broker_health.get("ok", False):
                status.blockers.append(
                    f"Broker nicht bereit: {broker_health.get('grund', 'unbekannt')}"
                )
            if broker_health.get("verbunden") and not broker_health.get("autotrading", True):
                status.blockers.append("Autotrading im Terminal ausgeschaltet")
            ping = broker_health.get("ping_ms", 0)
            if ping and ping > 500:
                status.warnings.append(f"hohe Latenz zum Server ({ping:.0f} ms)")

        # --- Datenaktualität ------------------------------------------ #
        if bar_time is not None:
            age = (now - _aware(bar_time)).total_seconds()
            tf_minutes = self.cfg.data.base_timeframe.minutes
            # Ein Balken darf naturgemäß bis zu einer Periode alt sein; danach
            # stimmt etwas mit dem Datenstrom nicht.
            limit = tf_minutes * 60 + self.cfg.data.max_bar_age_seconds
            if age > limit:
                status.blockers.append(
                    f"Kursdaten veraltet: letzter Balken vor {age / 60:.1f} Minuten"
                )
            self.last_bar_time = bar_time

        # --- Konto ----------------------------------------------------- #
        if account is not None:
            if self.start_equity <= 0:
                self.start_equity = account.equity
            self.equity_peak = max(self.equity_peak, account.equity)

            if account.equity <= 0:
                self.trip("Kontokapital auf oder unter null")
                status.blockers.append("Kontokapital erschöpft")

            if self.equity_peak > 0:
                drawdown = (self.equity_peak - account.equity) / self.equity_peak
                limit = self.cfg.risk.max_drawdown_stop
                if drawdown > limit:
                    reason = f"Rückgang {drawdown * 100:.1f} % über der Grenze von {limit * 100:.0f} %"
                    self.trip(reason)
                    status.blockers.append(reason)
                elif drawdown > limit * 0.7:
                    status.warnings.append(
                        f"Rückgang bei {drawdown * 100:.1f} % - Notaus bei {limit * 100:.0f} %"
                    )

            if account.margin > 0 and account.margin_level < 200:
                status.warnings.append(f"Margin-Niveau nur {account.margin_level:.0f} %")
            if account.margin > 0 and account.margin_level < 120:
                status.blockers.append(f"Margin-Niveau kritisch ({account.margin_level:.0f} %)")

        # --- Fehlerhäufung --------------------------------------------- #
        if self.errors_in_row >= 5:
            status.blockers.append(f"{self.errors_in_row} Fehler in Folge - Pause")

        status.ok = not status.blockers
        status.kill_switch = self.kill_switch
        return status

    def report(self) -> dict:
        return {
            "notaus": self.kill_switch,
            "grund": self.kill_reason,
            "fehler_in_folge": self.errors_in_row,
            "equity_hoechststand": round(self.equity_peak, 2),
            "letzter_balken": self.last_bar_time.isoformat() if self.last_bar_time else None,
            "letzter_erfolg": self.last_success.isoformat() if self.last_success else None,
        }


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
