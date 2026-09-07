"""Die Hauptschleife des Livebetriebs.

Der Takt ist der abgeschlossene Balken der feinsten Zeiteinheit. Erst wenn eine
Kerze wirklich zu Ende ist, wird analysiert - alles andere wäre Handeln auf
unfertigen Daten.

Ablauf je Takt:

1. Wächter fragen. Bei Sperre passiert nichts weiter.
2. Offene Positionen führen (Teilgewinne, Einstand, Trailing, Zeitausstieg).
   Das geschieht *zuerst*: Bestehendes Risiko zu senken ist wichtiger, als ein
   neues Setup zu erwischen.
3. Für jedes Symbol: Daten nachladen, Merkmale bauen, Signal bilden.
4. Risikoprüfung, dann Ausführung.
5. Alles ins Journal - auch das, was nicht gehandelt wurde.
6. In größeren Abständen: Lernschleife anstoßen.
"""

from __future__ import annotations

import signal as signal_module
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import Config
from ..data.mt5_client import MT5Client, MT5Error
from ..data.sessions import SessionFilter
from ..data.store import BarStore
from ..execution.broker import Broker, MT5Broker, OrderResult
from ..execution.manager import TradeManager
from ..features.builder import FeatureBuilder
from ..learning.evolve import Evolver
from ..learning.feedback import Blocklist
from ..learning.journal import Journal
from ..models.registry import ModelRegistry
from ..strategy.risk import RiskManager
from ..strategy.signal_engine import SignalEngine
from ..types import Direction, Position, Signal, SymbolSpec, Timeframe, utcnow
from ..utils import ensure_dir, get_logger
from .guard import Guard, GuardStatus

log = get_logger("runner")


@dataclass
class RunnerStatus:
    """Momentaufnahme des Betriebs."""

    running: bool = False
    started_at: "datetime | None" = None
    iterations: int = 0
    signals_seen: int = 0
    orders_sent: int = 0
    errors: int = 0
    last_bar: dict[str, str] = field(default_factory=dict)
    last_signal: dict[str, str] = field(default_factory=dict)
    guard: str = ""
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "läuft": self.running,
            "gestartet": self.started_at.isoformat() if self.started_at else None,
            "takte": self.iterations,
            "signale": self.signals_seen,
            "orders": self.orders_sent,
            "fehler": self.errors,
            "letzte_balken": self.last_bar,
            "letzte_signale": self.last_signal,
            "waechter": self.guard,
            "trockenlauf": self.dry_run,
        }


class LiveRunner:
    """Betreibt die Strategie am laufenden Markt."""

    def __init__(
        self,
        cfg: Config,
        client: "MT5Client | None" = None,
        broker: "Broker | None" = None,
        journal: "Journal | None" = None,
    ) -> None:
        self.cfg = cfg
        self.client = client or MT5Client(cfg.terminal, cfg.execution.magic)
        self.broker = broker or MT5Broker(self.client, cfg.execution)
        self.journal = journal or Journal(cfg.learning.journal_path)
        self.store = BarStore(cfg.data.cache_dir, self.client)
        self.builder = FeatureBuilder(cfg)
        self.registry = ModelRegistry(cfg.learning.model_dir, cfg.learning.keep_model_versions)
        self.blocklist = Blocklist.load(Path(cfg.learning.model_dir).parent / "blocklist.json")
        self.risk = RiskManager(cfg.risk)
        self.manager = TradeManager(self.broker, cfg.risk)
        self.guard = Guard(cfg)
        self.sessions = SessionFilter(cfg.sessions)
        self.evolver = Evolver(cfg, self.registry, self.journal, self.builder)

        self.engines: dict[str, SignalEngine] = {}
        self.specs: dict[str, SymbolSpec] = {}
        self._last_bar: dict[str, datetime] = {}
        self._last_evolve = utcnow()
        self._stop_requested = False
        self.status = RunnerStatus(dry_run=getattr(self.broker, "dry_run", True))

    # ------------------------------------------------------------------ #
    # Vorbereitung
    # ------------------------------------------------------------------ #

    def prepare(self) -> None:
        """Verbinden, Symbole prüfen, Modelle laden."""
        problems = self.cfg.validate()
        if problems:
            raise ValueError("Konfigurationsfehler:\n  - " + "\n  - ".join(problems))

        if isinstance(self.broker, MT5Broker):
            self.client.connect()

        for symbol in self.cfg.data.symbols:
            try:
                self.specs[symbol] = self.broker.symbol_spec(symbol)
            except Exception as exc:
                log.error("Symbol %s nicht verfügbar: %s", symbol, exc)
                continue
            model = self.registry.load(symbol)
            if model is None:
                log.warning(
                    "Für %s ist kein Modell hinterlegt - es entscheidet allein das Regelwerk. "
                    "Mit 'train' lässt sich eines anlernen.", symbol,
                )
            else:
                log.info("Modell %s für %s geladen (OOF-AUC %.4f)",
                         model.version, symbol, model.report.auc)
            self.engines[symbol] = SignalEngine(self.cfg, model, blocklist=self.blocklist)

        if not self.specs:
            raise RuntimeError("Kein einziges handelbares Symbol - Abbruch")

        active = self.blocklist.active_rules()
        if active:
            log.info("Aktive Sperren aus der Fehleranalyse: %d", len(active))
        self.journal.record_event(
            "start", f"Livebetrieb gestartet ({len(self.specs)} Symbole)",
            payload={"trockenlauf": self.status.dry_run, "symbole": list(self.specs)},
        )

    # ------------------------------------------------------------------ #
    # Takt
    # ------------------------------------------------------------------ #

    def run_once(self, force: bool = False) -> dict[str, Any]:
        """Ein Durchlauf. `force` ignoriert die Prüfung auf neue Balken."""
        outcome: dict[str, Any] = {"handled": [], "skipped": [], "orders": []}
        self.status.iterations += 1

        try:
            account = self.broker.account()
        except Exception as exc:
            self.guard.note_error(exc)
            self.status.errors += 1
            return {"error": str(exc)}

        status = self.guard.check(account, self.broker.health())
        self.status.guard = status.summary()
        if not status.ok:
            outcome["guard"] = status.summary()
            if status.kill_switch:
                self.manager.close_all("Notaus")
            return outcome

        # Bestehende Positionen zuerst - Risiko senken schlägt Risiko aufnehmen
        try:
            actions = self.manager.manage()
            for a in actions:
                log.info("Positionsführung %s: %s", a.ticket, a.detail)
                self.journal.record_event("manage", a.detail, payload={"ticket": a.ticket, "art": a.kind})
            outcome["management"] = [a.detail for a in actions]
        except Exception as exc:
            self.guard.note_error(exc)
            outcome["management_error"] = str(exc)

        for symbol in list(self.specs):
            try:
                handled = self._process_symbol(symbol, account, force, outcome)
                outcome["handled" if handled else "skipped"].append(symbol)
            except MT5Error as exc:
                self.guard.note_error(exc)
                self.status.errors += 1
                outcome.setdefault("errors", {})[symbol] = str(exc)
            except Exception as exc:
                self.guard.note_error(exc)
                self.status.errors += 1
                log.exception("Unerwarteter Fehler bei %s", symbol)
                outcome.setdefault("errors", {})[symbol] = str(exc)

        self.guard.note_success()
        self._maybe_evolve()
        return outcome

    def _process_symbol(
        self, symbol: str, account: Any, force: bool, outcome: dict[str, Any]
    ) -> bool:
        """Ein Symbol analysieren und gegebenenfalls handeln."""
        base_tf = self.cfg.data.base_timeframe
        frames = self.store.load_multi(
            symbol, self.cfg.data.all_timeframes, self.cfg.data.history_bars, update=True
        )
        base = frames[base_tf.value]
        if base.empty:
            return False

        bar_time = base.index[-1].to_pydatetime()
        self.status.last_bar[symbol] = bar_time.isoformat()
        if not force and self._last_bar.get(symbol) == bar_time:
            return False  # kein neuer abgeschlossener Balken
        self._last_bar[symbol] = bar_time

        bar_status = self.guard.check(bar_time=bar_time)
        if not bar_status.ok:
            outcome["skipped"].append(f"{symbol}: {bar_status.summary()}")
            return False

        fs = self.builder.build(frames, symbol=symbol, digits=self.specs[symbol].digits)
        engine = self.engines[symbol]
        sig = engine.generate(fs, -1, self.specs[symbol])
        self.status.signals_seen += 1
        self.status.last_signal[symbol] = sig.summary()

        # Aktuellen Spread einbeziehen - der ist im Merkmalsrahmen nicht enthalten
        try:
            tick = self.broker.tick(symbol)
            if sig.atr > 0 and tick["spread"] / sig.atr > self.cfg.risk.max_spread_atr:
                sig.direction = Direction.FLAT
                sig.warnings.insert(0, f"Spread zu hoch ({tick['spread'] / sig.atr:.2f} ATR)")
        except Exception as exc:
            log.debug("Spread für %s nicht prüfbar: %s", symbol, exc)

        if not sig.is_actionable:
            self.journal.record_signal(sig, False, sig.warnings[0] if sig.warnings else "kein Setup")
            return True

        ok, reason = self.sessions.check(sig.time, symbol)
        if not ok:
            self.journal.record_signal(sig, False, reason)
            return True

        positions = self.broker.positions()
        plan = self.risk.plan(sig, account, self.specs[symbol], positions)
        if not plan.allowed:
            self.journal.record_signal(sig, False, plan.blockers[0] if plan.blockers else "Risikoprüfung")
            log.info("%s: %s", symbol, plan.summary())
            return True

        result = self._execute(sig, plan, symbol)
        outcome["orders"].append(
            {"symbol": symbol, "richtung": sig.direction.value, "volumen": plan.volume, "ok": result.ok}
        )
        self.journal.record_signal(sig, result.ok, "" if result.ok else result.message)
        return True

    def _execute(self, sig: Signal, plan: Any, symbol: str) -> OrderResult:
        """Order senden und die Position in die Führung übernehmen."""
        log.info("SIGNAL %s | %s", sig.summary(), "; ".join(sig.reasons[:3]))
        result = self.broker.open_position(
            symbol=symbol,
            direction=sig.direction,
            volume=plan.volume,
            stop_loss=sig.stop_loss,
            # Als Serverziel das letzte Ziel setzen: Es greift auch dann, wenn
            # dieser Prozess nicht läuft. Teilgewinne holt der Manager davor ab.
            take_profit=sig.take_profits[-1] if sig.take_profits else 0.0,
            comment=f"{self.cfg.execution.comment} {sig.horizon.value[:4]}",
        )
        if not result.ok:
            log.error("Order für %s abgelehnt: %s", symbol, result.message)
            self.journal.record_event("order_error", result.message, symbol)
            return result

        self.status.orders_sent += 1
        if result.ticket:
            position = Position(
                ticket=result.ticket, symbol=symbol, direction=sig.direction,
                volume=result.volume or plan.volume, entry_price=result.price or sig.entry,
                entry_time=utcnow(), stop_loss=sig.stop_loss,
                take_profit=sig.take_profits[-1] if sig.take_profits else 0.0,
                signal_score=sig.score, horizon=sig.horizon,
            )
            base_minutes = self.cfg.data.base_timeframe.minutes
            self.manager.register(
                position, sig.take_profits, sig.tp_fractions,
                max_hold_minutes=int(sig.max_hold_bars * base_minutes),
                signal_score=sig.score, reasons=sig.reasons[:5],
            )
        self.journal.record_event(
            "order", f"{sig.direction.value} {plan.volume} Lot", symbol,
            payload={"ticket": result.ticket, "preis": result.price,
                     "sl": sig.stop_loss, "tp": sig.take_profits, "score": sig.score},
        )
        return result

    # ------------------------------------------------------------------ #
    # Lernschleife
    # ------------------------------------------------------------------ #

    def _maybe_evolve(self) -> None:
        """In größeren Abständen nachtrainieren und die Sperren auffrischen."""
        hours = (utcnow() - self._last_evolve).total_seconds() / 3600.0
        if hours < max(1.0, self.cfg.learning.retrain_every_hours / 4.0):
            return
        self._last_evolve = utcnow()

        from ..learning.feedback import FeedbackAnalyzer

        analyzer = FeedbackAnalyzer(self.cfg.learning)
        try:
            trades = self.journal.trades(source="live")
            if len(trades) >= self.cfg.learning.min_trades_for_feedback:
                added = analyzer.update_blocklist(trades, self.blocklist)
                for rule in added:
                    self.journal.record_event(
                        "blocklist", f"{rule.dimension}={rule.value}: {rule.reason}"
                    )
        except Exception as exc:
            log.warning("Fehleranalyse fehlgeschlagen: %s", exc)

        for symbol in list(self.specs):
            try:
                needed, reason = self.evolver.should_retrain(symbol)
                if not needed:
                    continue
                frames = self.store.load_multi(
                    symbol, self.cfg.data.all_timeframes, self.cfg.data.history_bars, update=False
                )
                decision = self.evolver.evolve(frames, symbol)
                log.info(decision.summary())
                self.journal.record_event("evolve", decision.summary(), symbol)
                if decision.promoted:
                    model = self.registry.load(symbol)
                    self.engines[symbol] = SignalEngine(self.cfg, model, blocklist=self.blocklist)
                    log.info("%s handelt ab jetzt mit Modell %s", symbol, decision.challenger_version)
            except Exception as exc:
                log.error("Lernschleife für %s fehlgeschlagen: %s", symbol, exc)

    # ------------------------------------------------------------------ #
    # Schleife
    # ------------------------------------------------------------------ #

    def run(self, poll_seconds: int = 20, max_iterations: "int | None" = None) -> RunnerStatus:
        """Dauerbetrieb bis Strg+C oder Notaus."""
        self.prepare()
        self.status.running = True
        self.status.started_at = utcnow()
        self._install_signal_handlers()

        log.info(
            "Livebetrieb läuft. Takt: %s | Symbole: %s | Modus: %s",
            self.cfg.data.base_timeframe.value, ", ".join(self.specs),
            "TROCKENLAUF" if self.status.dry_run else "ECHTGELD",
        )
        try:
            while not self._stop_requested:
                if max_iterations is not None and self.status.iterations >= max_iterations:
                    break
                started = time.monotonic()
                self.run_once()
                if self.guard.kill_switch:
                    log.critical("Notaus - die Schleife wird beendet")
                    break
                elapsed = time.monotonic() - started
                time.sleep(max(1.0, poll_seconds - elapsed))
        except KeyboardInterrupt:  # pragma: no cover - interaktiver Abbruch
            log.info("Abbruch durch Benutzer")
        finally:
            self.shutdown()
        return self.status

    def shutdown(self, close_positions: bool = False) -> None:
        """Sauber beenden. Positionen bleiben standardmäßig offen.

        Bewusst so: Sie tragen serverseitige Stops und Ziele, die auch ohne
        laufenden Bot greifen. Sie beim Beenden zu schließen würde bedeuten,
        jeden Neustart mit einem realisierten Verlust zu bezahlen.
        """
        self.status.running = False
        if close_positions:
            self.manager.close_all("Beenden")
        try:
            self.journal.record_event("stop", "Livebetrieb beendet", payload=self.status.to_dict())
        except Exception:  # pragma: no cover
            pass
        if isinstance(self.broker, MT5Broker):
            self.client.disconnect()
        log.info(
            "Beendet nach %d Takten, %d Signalen, %d Orders, %d Fehlern",
            self.status.iterations, self.status.signals_seen,
            self.status.orders_sent, self.status.errors,
        )

    def request_stop(self) -> None:
        self._stop_requested = True

    def _install_signal_handlers(self) -> None:
        def handler(signum, frame):  # pragma: no cover - nur interaktiv
            log.info("Signal %s empfangen - Betrieb wird geordnet beendet", signum)
            self._stop_requested = True

        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal_module, sig_name, None)
            if sig is not None:
                try:
                    signal_module.signal(sig, handler)
                except (ValueError, OSError):  # pragma: no cover - z. B. in Threads
                    pass
