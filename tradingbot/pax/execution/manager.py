"""Positionsführung im Livebetrieb.

Bewusst dieselben Regeln wie im Backtest: Stop auf Einstand ziehen, Teilgewinne
mitnehmen, Stop nachziehen, Zeitausstieg. Wenn Backtest und Livebetrieb
Positionen unterschiedlich führen, ist jeder Backtest wertlos - deshalb liegen
die Schwellen in derselben Konfiguration und werden hier nur ein zweites Mal
angewandt, nicht neu erfunden.

Der Unterschied zum Backtest: Hier gibt es keine bekannte Kerze, sondern einen
laufenden Kurs, und jede Änderung kostet einen Serveraufruf. Deshalb wird nur
geändert, was sich nennenswert bewegt hat.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone

from ..config import RiskConfig
from ..types import Direction, ExitReason, Position, SymbolSpec, utcnow
from ..utils import get_logger

log = get_logger("manager")


@dataclass
class ManagementAction:
    """Eine durchgeführte oder vorgeschlagene Maßnahme."""

    ticket: int
    kind: str  # "break_even" | "trail" | "partial" | "close"
    detail: str = ""
    ok: bool = True
    value: float = 0.0


@dataclass
class ManagedState:
    """Was der Manager je Position mitführt - MT5 speichert das nicht."""

    initial_stop: float = 0.0
    initial_volume: float = 0.0
    targets: list[float] = field(default_factory=list)
    fractions: list[float] = field(default_factory=list)
    partials_done: int = 0
    break_even_done: bool = False
    max_favorable_r: float = 0.0
    max_adverse_r: float = 0.0
    opened_at: "datetime | None" = None
    max_hold_minutes: int = 0
    signal_score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["opened_at"] = self.opened_at.isoformat() if self.opened_at else None
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ManagedState":
        """Zustand aus der Ablage zurücklesen.

        Jeder Wert wird auf seinen erwarteten Typ gebracht; was sich nicht
        umwandeln lässt, fällt auf den Standard zurück. Die Ablage ist eine
        Datei, die jederzeit beschädigt oder von Hand verändert sein kann - ein
        falscher Typ darf nicht die Live-Schleife anhalten.
        """
        if not isinstance(data, dict):
            return cls()
        kwargs: dict = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            wert = data[f.name]
            try:
                if f.name == "opened_at":
                    kwargs[f.name] = (
                        datetime.fromisoformat(wert) if isinstance(wert, str) else wert
                    )
                elif f.name in ("partials_done", "max_hold_minutes"):
                    kwargs[f.name] = int(wert)
                elif f.name == "break_even_done":
                    kwargs[f.name] = bool(wert)
                elif f.name in ("targets", "fractions"):
                    kwargs[f.name] = [float(x) for x in wert]
                elif f.name == "reasons":
                    kwargs[f.name] = [str(x) for x in wert]
                else:
                    kwargs[f.name] = float(wert)
            except (TypeError, ValueError):
                log.warning(
                    "Feld '%s' im gesicherten Zustand unbrauchbar (%r) - Standard wird benutzt",
                    f.name, wert,
                )
        return cls(**kwargs)


class TradeManager:
    """Führt offene Positionen nach den Regeln der Konfiguration."""

    def __init__(self, broker: object, risk_cfg: RiskConfig, store: object = None) -> None:
        self.broker = broker
        self.cfg = risk_cfg
        self.state: dict[int, ManagedState] = {}
        # Ablage (üblicherweise das Journal). Ohne sie beginnt der Bot nach
        # jedem Neustart bei null: Teilgewinne würden ein zweites Mal genommen,
        # das Risiko falsch gerechnet und der Zeitausstieg stillschweigend
        # abgeschaltet.
        self.store = store
        self._saved: dict[int, ManagedState] = {}
        self._load_saved()

    def _load_saved(self) -> None:
        if self.store is None:
            return
        try:
            raw = self.store.load_position_states()  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - defekte Ablage darf nicht stoppen
            log.warning("Gesicherte Positionszustände nicht lesbar: %s", exc)
            return
        for ticket, data in raw.items():
            try:
                self._saved[int(ticket)] = ManagedState.from_dict(data)
            except Exception as exc:  # pragma: no cover
                log.warning("Zustand für Ticket %s unbrauchbar: %s", ticket, exc)
        if self._saved:
            log.info("%d gesicherte Positionszustände geladen", len(self._saved))

    def _persist(self, ticket: int, symbol: str = "") -> None:
        if self.store is None:
            return
        state = self.state.get(ticket)
        if state is None:
            return
        try:
            self.store.save_position_state(ticket, symbol, state.to_dict())  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover
            log.warning("Positionszustand %s nicht speicherbar: %s", ticket, exc)

    # ------------------------------------------------------------------ #

    def register(
        self,
        position: Position,
        targets: "list[float] | None" = None,
        fractions: "list[float] | None" = None,
        max_hold_minutes: int = 0,
        signal_score: float = 0.0,
        reasons: "list[str] | None" = None,
    ) -> None:
        """Eine neu eröffnete Position in die Führung aufnehmen."""
        self.state[position.ticket] = ManagedState(
            initial_stop=position.stop_loss,
            initial_volume=position.volume,
            targets=list(targets or ([position.take_profit] if position.take_profit else [])),
            fractions=list(fractions or self.cfg.partial_fractions),
            opened_at=position.entry_time,
            max_hold_minutes=max_hold_minutes,
            signal_score=signal_score,
            reasons=list(reasons or []),
        )
        self._persist(position.ticket, position.symbol)

    def forget(self, ticket: int) -> None:
        self.state.pop(ticket, None)
        self._saved.pop(ticket, None)
        if self.store is not None:
            try:
                self.store.delete_position_state(ticket)  # type: ignore[attr-defined]
            except Exception as exc:  # pragma: no cover
                log.warning("Positionszustand %s nicht löschbar: %s", ticket, exc)

    def sync(self, positions: list[Position]) -> None:
        """Zustand mit dem Terminal abgleichen.

        Positionen, die manuell im Terminal geschlossen wurden, fallen hier
        heraus; von Hand eröffnete werden mit Notzustand aufgenommen, damit sie
        wenigstens einen Zeitausstieg bekommen.
        """
        live = {p.ticket for p in positions}
        for ticket in list(self.state):
            if ticket not in live:
                self.forget(ticket)
        for p in positions:
            if p.ticket in self.state:
                continue
            saved = self._saved.pop(p.ticket, None)
            if saved is not None:
                # Nach einem Neustart zählt der gesicherte Zustand, nicht der
                # aktuelle Stop: Der ist womöglich längst nachgezogen, und mit
                # ihm als "initial_stop" wäre jede R-Rechnung falsch.
                self.state[p.ticket] = saved
                log.info(
                    "Position %s aus der Ablage wiederhergestellt (%s, %d Teilgewinn(e) bereits "
                    "genommen, Ausgangsstop %.5f)",
                    p.ticket, p.symbol, saved.partials_done, saved.initial_stop,
                )
                continue
            log.info("Unbekannte Position %s übernommen (%s %s)", p.ticket, p.symbol, p.direction.value)
            self.register(p)

    # ------------------------------------------------------------------ #

    def manage(self, positions: "list[Position] | None" = None, now: "datetime | None" = None) -> list[ManagementAction]:
        """Alle offenen Positionen einmal durchgehen."""
        now = now or utcnow()
        positions = positions if positions is not None else self.broker.positions()  # type: ignore[attr-defined]
        self.sync(positions)
        actions: list[ManagementAction] = []

        for pos in positions:
            state = self.state.get(pos.ticket)
            if state is None:
                continue
            try:
                spec = self.broker.symbol_spec(pos.symbol)  # type: ignore[attr-defined]
                tick = self.broker.tick(pos.symbol)  # type: ignore[attr-defined]
            except Exception as exc:
                log.warning("Kurs für %s nicht abrufbar: %s", pos.symbol, exc)
                continue

            # Statt jede einzelne Änderungsstelle zu bestücken (und irgendwann
            # eine zu vergessen) wird der Zustand vorher und nachher verglichen.
            before = state.to_dict()

            is_long = pos.direction is Direction.LONG
            # Bewertungskurs ist immer der Kurs, zu dem geschlossen würde
            price = tick["bid"] if is_long else tick["ask"]
            risk = abs(pos.entry_price - state.initial_stop)
            if risk <= 0:
                continue
            r_now = (price - pos.entry_price) * pos.direction.sign / risk
            state.max_favorable_r = max(state.max_favorable_r, r_now)
            state.max_adverse_r = max(state.max_adverse_r, -r_now)

            actions.extend(self._partials(pos, state, price, spec))
            if pos.ticket not in self.state:
                continue
            action = self._break_even(pos, state, spec)
            if action:
                actions.append(action)
            action = self._trail(pos, state, price, spec)
            if action:
                actions.append(action)
            action = self._time_exit(pos, state, now)
            if action:
                actions.append(action)

            if pos.ticket in self.state and state.to_dict() != before:
                self._persist(pos.ticket, pos.symbol)
        return actions

    # ------------------------------------------------------------------ #

    def _partials(
        self, pos: Position, state: ManagedState, price: float, spec: SymbolSpec
    ) -> list[ManagementAction]:
        """Teilgewinne an den vorgesehenen Zielen mitnehmen."""
        out: list[ManagementAction] = []
        is_long = pos.direction is Direction.LONG
        while state.partials_done < len(state.targets) - 1 and state.partials_done < len(state.fractions):
            level = state.targets[state.partials_done]
            reached = (price >= level) if is_long else (price <= level)
            if not reached:
                break
            fraction = state.fractions[state.partials_done]
            volume = spec.normalize_volume(state.initial_volume * fraction)
            state.partials_done += 1
            remaining = round(pos.volume - volume, 6)
            if volume < spec.volume_min or remaining < spec.volume_min:
                out.append(ManagementAction(pos.ticket, "partial",
                                            "Teilgewinn übersprungen - Restvolumen zu klein", ok=False))
                continue
            result = self.broker.close_position(pos.ticket, volume)  # type: ignore[attr-defined]
            out.append(ManagementAction(
                pos.ticket, "partial",
                f"Teilgewinn {volume:.2f} Lot bei {level:.5f} ({state.partials_done}. Ziel)",
                ok=result.ok, value=volume,
            ))
            if result.ok:
                pos.volume = remaining
            else:
                break
        return out

    def _break_even(self, pos: Position, state: ManagedState, spec: SymbolSpec) -> "ManagementAction | None":
        """Stop auf Einstand ziehen, sobald der Trade genug im Plus liegt."""
        if state.break_even_done or state.max_favorable_r < self.cfg.break_even_at_r:
            return None
        risk = abs(pos.entry_price - state.initial_stop)
        offset = self.cfg.break_even_offset_r * risk
        is_long = pos.direction is Direction.LONG
        new_stop = spec.normalize_price(pos.entry_price + (offset if is_long else -offset))
        if (is_long and new_stop <= pos.stop_loss) or (not is_long and new_stop >= pos.stop_loss):
            state.break_even_done = True
            return None
        result = self.broker.modify_position(pos.ticket, stop_loss=new_stop)  # type: ignore[attr-defined]
        if result.ok:
            pos.stop_loss = new_stop
            state.break_even_done = True
        return ManagementAction(
            pos.ticket, "break_even",
            f"Stop auf Einstand gezogen ({new_stop:.5f}, {state.max_favorable_r:.2f} R erreicht)",
            ok=result.ok, value=new_stop,
        )

    def _trail(
        self, pos: Position, state: ManagedState, price: float, spec: SymbolSpec, atr: float = 0.0
    ) -> "ManagementAction | None":
        """Stop nachziehen, sobald der Trade deutlich läuft."""
        if state.max_favorable_r < self.cfg.trail_start_r:
            return None
        risk = abs(pos.entry_price - state.initial_stop)
        distance = self.cfg.trail_atr * (atr if atr > 0 else risk)
        is_long = pos.direction is Direction.LONG
        candidate = spec.normalize_price(price - distance if is_long else price + distance)
        # Nur bei spürbarer Verbesserung anfassen - jeder Aufruf kostet Zeit
        # und kann bei schnellem Markt abgelehnt werden.
        threshold = max(spec.point * 10, 0.05 * risk)
        if is_long and candidate <= pos.stop_loss + threshold:
            return None
        if not is_long and candidate >= pos.stop_loss - threshold:
            return None
        result = self.broker.modify_position(pos.ticket, stop_loss=candidate)  # type: ignore[attr-defined]
        if result.ok:
            pos.stop_loss = candidate
        return ManagementAction(
            pos.ticket, "trail", f"Stop nachgezogen auf {candidate:.5f}", ok=result.ok, value=candidate
        )

    def _time_exit(self, pos: Position, state: ManagedState, now: datetime) -> "ManagementAction | None":
        """Position schließen, wenn der geplante Horizont abgelaufen ist.

        Ein Trade, der nach seinem Horizont weder Ziel noch Stop erreicht hat,
        funktioniert nicht - die Begründung ist verfallen. Kapital, das dort
        gebunden bleibt, fehlt beim nächsten Setup.
        """
        if not state.max_hold_minutes or state.opened_at is None:
            return None
        opened = state.opened_at
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        held = (now - opened).total_seconds() / 60.0
        if held < state.max_hold_minutes:
            return None
        result = self.broker.close_position(pos.ticket)  # type: ignore[attr-defined]
        if result.ok:
            self.forget(pos.ticket)
        return ManagementAction(
            pos.ticket, "close",
            f"Zeitausstieg nach {held / 60:.1f} Stunden ({ExitReason.TIME.value})",
            ok=result.ok,
        )

    # ------------------------------------------------------------------ #

    def close_all(self, reason: str = "") -> list[ManagementAction]:
        """Not-Aus: alles glattstellen."""
        out = []
        for pos in self.broker.positions():  # type: ignore[attr-defined]
            result = self.broker.close_position(pos.ticket)  # type: ignore[attr-defined]
            if result.ok:
                self.forget(pos.ticket)
            out.append(ManagementAction(pos.ticket, "close", reason or "Not-Aus", ok=result.ok))
        return out
