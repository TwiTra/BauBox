"""Anbindung an das MetaTrader-5-Terminal.

Das Paket `MetaTrader5` läuft nur unter Windows und nur mit installiertem
Terminal. Deshalb wird es weich importiert: Analyse, Backtest und Training
funktionieren vollständig ohne MT5, nur Live-Daten und Orderausführung nicht.

MT5 liefert alle Zeiten in UTC. Dieser Client gibt konsequent UTC-behaftete
Zeitstempel zurück, damit es keine stillen Zeitzonenfehler gibt.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from ..types import AccountState, Direction, Position, SymbolSpec, Timeframe
from ..utils import get_logger

log = get_logger("mt5")

try:  # pragma: no cover - abhängig von der Plattform
    import MetaTrader5 as mt5  # type: ignore

    MT5_AVAILABLE = True
except Exception:  # ImportError unter Linux/macOS, OSError bei kaputter DLL
    mt5 = None  # type: ignore[assignment]
    MT5_AVAILABLE = False


class MT5Unavailable(RuntimeError):
    """Das Paket MetaTrader5 ist nicht installiert oder nicht ladbar."""


class MT5Error(RuntimeError):
    """Das Terminal hat einen Fehler gemeldet."""

    def __init__(self, message: str, code: int = 0, detail: str = "") -> None:
        super().__init__(f"{message} (Code {code}: {detail})" if code else message)
        self.code = code
        self.detail = detail


# Rückgabecodes, die einen erneuten Versuch rechtfertigen (Preis lief weg o.ä.).
RETRYABLE_RETCODES = {
    10004,  # REQUOTE
    10006,  # REJECT
    10008,  # PLACED, aber ohne Deal
    10021,  # PRICE_OFF
    10024,  # TOO_MANY_REQUESTS
    10030,  # INVALID_FILL - wird zusätzlich per Fallback behandelt
    10031,  # CONNECTION
}

RETCODE_TEXT = {
    10004: "Requote",
    10006: "Order abgelehnt",
    10007: "Vom Händler storniert",
    10008: "Order platziert",
    10009: "Anfrage vollständig ausgeführt",
    10010: "Anfrage nur teilweise ausgeführt",
    10011: "Anfrageverarbeitung fehlgeschlagen",
    10013: "Ungültige Anfrage",
    10014: "Ungültiges Volumen",
    10015: "Ungültiger Preis",
    10016: "Ungültige Stops (SL/TP zu nah am Markt)",
    10017: "Handel deaktiviert",
    10018: "Markt geschlossen",
    10019: "Nicht genug Geld",
    10021: "Kein Preis verfügbar",
    10024: "Zu viele Anfragen",
    10027: "Autotrading im Terminal deaktiviert",
    10030: "Nicht unterstützter Ausführungsmodus (Filling)",
    10031: "Keine Verbindung zum Handelsserver",
    10036: "Position bereits geschlossen",
}


def _to_utc(ts: "int | float | datetime") -> datetime:
    """Sekunden seit Epoche (wie MT5 sie liefert) in aware UTC umwandeln."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


class MT5Client:
    """Dünne, aber robuste Hülle um die MetaTrader5-Python-API.

    Alle Aufrufe laufen unter einer Sperre, weil die MT5-Bibliothek einen
    globalen Terminalzustand hat und nicht threadsicher ist.
    """

    def __init__(self, terminal_config: Any = None, magic: int = 0) -> None:
        self.cfg = terminal_config
        self.magic = magic
        self._connected = False
        self._lock = threading.RLock()
        self._spec_cache: dict[str, SymbolSpec] = {}
        self._tf_map: dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    # Verbindung
    # ------------------------------------------------------------------ #

    @staticmethod
    def available() -> bool:
        """Ist das MetaTrader5-Paket importierbar?"""
        return MT5_AVAILABLE

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> "MT5Client":
        """Terminal starten bzw. sich anhängen und - falls angegeben - einloggen."""
        if not MT5_AVAILABLE:
            raise MT5Unavailable(
                "Das Paket 'MetaTrader5' ist nicht verfügbar. Es läuft nur unter Windows "
                "mit installiertem MT5-Terminal. Backtest und Training laufen auch ohne."
            )
        with self._lock:
            if self._connected:
                return self

            cfg = self.cfg.from_env() if hasattr(self.cfg, "from_env") else self.cfg
            kwargs: dict[str, Any] = {}
            if cfg is not None:
                if getattr(cfg, "path", ""):
                    kwargs["path"] = cfg.path
                if getattr(cfg, "login", 0):
                    kwargs["login"] = int(cfg.login)
                if getattr(cfg, "password", ""):
                    kwargs["password"] = cfg.password
                if getattr(cfg, "server", ""):
                    kwargs["server"] = cfg.server
                if getattr(cfg, "timeout_ms", 0):
                    kwargs["timeout"] = int(cfg.timeout_ms)
                if getattr(cfg, "portable", False):
                    kwargs["portable"] = True

            if not mt5.initialize(**kwargs):
                code, detail = mt5.last_error()
                raise MT5Error("Verbindung zum MT5-Terminal fehlgeschlagen", code, detail)

            info = mt5.terminal_info()
            if info is not None and not info.trade_allowed:
                log.warning(
                    "Autotrading ist im Terminal deaktiviert - Orders werden abgelehnt. "
                    "Im MT5 den Knopf 'Algo Trading' einschalten."
                )
            acc = mt5.account_info()
            if acc is not None:
                log.info(
                    "Verbunden: Konto %s auf %s (%s), Guthaben %.2f %s",
                    acc.login, acc.server, acc.company, acc.balance, acc.currency,
                )
            self._connected = True
            self._build_timeframe_map()
            return self

    def disconnect(self) -> None:
        with self._lock:
            if self._connected and mt5 is not None:
                mt5.shutdown()
            self._connected = False

    def __enter__(self) -> "MT5Client":
        return self.connect()

    def __exit__(self, *exc: Any) -> None:
        self.disconnect()

    def _require(self) -> None:
        if not self._connected:
            self.connect()

    def _build_timeframe_map(self) -> None:
        self._tf_map = {
            tf.value: getattr(mt5, f"TIMEFRAME_{tf.value}")
            for tf in Timeframe
            if hasattr(mt5, f"TIMEFRAME_{tf.value}")
        }

    def _mt5_timeframe(self, timeframe: "str | Timeframe") -> Any:
        tf = Timeframe.parse(timeframe)
        if not self._tf_map:
            self._build_timeframe_map()
        value = self._tf_map.get(tf.value)
        if value is None:
            raise MT5Error(f"Zeiteinheit {tf.value} wird vom Terminal nicht unterstützt")
        return value

    def health(self) -> dict[str, Any]:
        """Zustandsbericht für den Wächter im Live-Betrieb."""
        if not MT5_AVAILABLE:
            return {"ok": False, "grund": "MetaTrader5-Paket nicht verfügbar"}
        if not self._connected:
            return {"ok": False, "grund": "nicht verbunden"}
        with self._lock:
            term = mt5.terminal_info()
            acc = mt5.account_info()
        if term is None or acc is None:
            return {"ok": False, "grund": "Terminal antwortet nicht"}
        return {
            "ok": bool(term.connected and term.trade_allowed),
            "verbunden": bool(term.connected),
            "autotrading": bool(term.trade_allowed),
            "ping_ms": getattr(term, "ping_last", 0) / 1000.0,
            "konto": acc.login,
            "server": acc.server,
            "guthaben": acc.balance,
            "equity": acc.equity,
        }

    # ------------------------------------------------------------------ #
    # Stammdaten
    # ------------------------------------------------------------------ #

    def account(self) -> AccountState:
        self._require()
        with self._lock:
            info = mt5.account_info()
        if info is None:
            code, detail = mt5.last_error()
            raise MT5Error("Kontoinformationen nicht abrufbar", code, detail)
        return AccountState(
            balance=float(info.balance),
            equity=float(info.equity),
            margin=float(info.margin),
            free_margin=float(info.margin_free),
            currency=info.currency,
            leverage=int(info.leverage),
            login=int(info.login),
            server=info.server,
        )

    def ensure_symbol(self, symbol: str) -> None:
        """Symbol in die Marktübersicht holen - sonst liefert MT5 keine Daten."""
        self._require()
        with self._lock:
            info = mt5.symbol_info(symbol)
            if info is None:
                raise MT5Error(f"Symbol {symbol} beim Broker unbekannt")
            if not info.visible and not mt5.symbol_select(symbol, True):
                code, detail = mt5.last_error()
                raise MT5Error(f"Symbol {symbol} konnte nicht aktiviert werden", code, detail)

    def symbol_spec(self, symbol: str, refresh: bool = False) -> SymbolSpec:
        """Kontraktspezifikation lesen (zwischengespeichert)."""
        if not refresh and symbol in self._spec_cache:
            return self._spec_cache[symbol]
        self.ensure_symbol(symbol)
        with self._lock:
            i = mt5.symbol_info(symbol)
        if i is None:
            raise MT5Error(f"Symbol {symbol} beim Broker unbekannt")
        spec = SymbolSpec(
            name=i.name,
            digits=int(i.digits),
            point=float(i.point),
            tick_size=float(i.trade_tick_size or i.point),
            tick_value=float(i.trade_tick_value or 1.0),
            contract_size=float(i.trade_contract_size or 1.0),
            volume_min=float(i.volume_min),
            volume_max=float(i.volume_max),
            volume_step=float(i.volume_step),
            stops_level_points=int(i.trade_stops_level),
            freeze_level_points=int(i.trade_freeze_level),
            spread_points=float(i.spread),
            swap_long=float(i.swap_long),
            swap_short=float(i.swap_short),
            currency_profit=i.currency_profit,
            trade_allowed=i.trade_mode != getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", -1),
        )
        self._spec_cache[symbol] = spec
        return spec

    def tick(self, symbol: str) -> dict[str, Any]:
        """Letzter Tick mit Bid/Ask/Spread."""
        self.ensure_symbol(symbol)
        with self._lock:
            t = mt5.symbol_info_tick(symbol)
        if t is None:
            code, detail = mt5.last_error()
            raise MT5Error(f"Kein Tick für {symbol}", code, detail)
        spec = self.symbol_spec(symbol)
        bid, ask = float(t.bid), float(t.ask)
        return {
            "time": _to_utc(t.time),
            "bid": bid,
            "ask": ask,
            "last": float(t.last) if t.last else (bid + ask) / 2,
            "spread": ask - bid,
            "spread_points": (ask - bid) / spec.point if spec.point else 0.0,
            "volume": float(t.volume),
        }

    # ------------------------------------------------------------------ #
    # Kursdaten
    # ------------------------------------------------------------------ #

    def rates(
        self,
        symbol: str,
        timeframe: "str | Timeframe",
        count: int = 5_000,
        start_pos: int = 0,
        drop_unclosed: bool = True,
    ) -> pd.DataFrame:
        """Die letzten `count` Balken als DataFrame mit UTC-Index.

        `drop_unclosed` entfernt den laufenden, noch offenen Balken. Das ist der
        wichtigste Schutz gegen Lookahead im Livebetrieb: Signale dürfen nur auf
        abgeschlossenen Balken beruhen.
        """
        self.ensure_symbol(symbol)
        tf = Timeframe.parse(timeframe)
        with self._lock:
            raw = mt5.copy_rates_from_pos(symbol, self._mt5_timeframe(tf), int(start_pos), int(count))
        if raw is None or len(raw) == 0:
            code, detail = mt5.last_error()
            raise MT5Error(f"Keine Kursdaten für {symbol} {tf.value}", code, detail)
        df = self._frame_from_rates(raw)
        if drop_unclosed and start_pos == 0 and len(df) > 1:
            df = self._drop_unclosed_bar(df, tf)
        return df

    def rates_range(
        self,
        symbol: str,
        timeframe: "str | Timeframe",
        start: datetime,
        end: "datetime | None" = None,
        drop_unclosed: bool = True,
    ) -> pd.DataFrame:
        """Balken in einem Zeitraum. Zeiten werden als UTC interpretiert."""
        self.ensure_symbol(symbol)
        tf = Timeframe.parse(timeframe)
        end = end or datetime.now(timezone.utc)
        start_utc = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        end_utc = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        with self._lock:
            raw = mt5.copy_rates_range(
                symbol, self._mt5_timeframe(tf), start_utc, end_utc
            )
        if raw is None or len(raw) == 0:
            code, detail = mt5.last_error()
            raise MT5Error(f"Keine Kursdaten für {symbol} {tf.value} im Zeitraum", code, detail)
        df = self._frame_from_rates(raw)
        if drop_unclosed and len(df) > 1:
            df = self._drop_unclosed_bar(df, tf)
        return df

    @staticmethod
    def _frame_from_rates(raw: np.ndarray) -> pd.DataFrame:
        df = pd.DataFrame(raw)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time").sort_index()
        df = df.rename(columns={"tick_volume": "volume"})
        keep = ["open", "high", "low", "close", "volume", "spread", "real_volume"]
        df = df[[c for c in keep if c in df.columns]]
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype("float64")
        if "volume" in df:
            df["volume"] = df["volume"].astype("float64")
        df = df[~df.index.duplicated(keep="last")]
        return df

    @staticmethod
    def _drop_unclosed_bar(df: pd.DataFrame, tf: Timeframe) -> pd.DataFrame:
        """Letzten Balken verwerfen, falls seine Periode noch läuft."""
        last_open = df.index[-1]
        bar_end = last_open + timedelta(minutes=tf.minutes)
        if datetime.now(timezone.utc) < bar_end:
            return df.iloc[:-1]
        return df

    def last_closed_bar_time(self, symbol: str, timeframe: "str | Timeframe") -> datetime:
        """Öffnungszeit des zuletzt abgeschlossenen Balkens."""
        df = self.rates(symbol, timeframe, count=3, drop_unclosed=True)
        return df.index[-1].to_pydatetime()

    # ------------------------------------------------------------------ #
    # Positionen
    # ------------------------------------------------------------------ #

    def positions(self, symbol: "str | None" = None, only_own: bool = True) -> list[Position]:
        """Offene Positionen, standardmäßig nur die mit eigener Magic Number."""
        self._require()
        with self._lock:
            raw = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if raw is None:
            return []
        out: list[Position] = []
        for p in raw:
            if only_own and self.magic and int(p.magic) != int(self.magic):
                continue
            out.append(
                Position(
                    ticket=int(p.ticket),
                    symbol=p.symbol,
                    direction=Direction.LONG if p.type == mt5.POSITION_TYPE_BUY else Direction.SHORT,
                    volume=float(p.volume),
                    entry_price=float(p.price_open),
                    entry_time=_to_utc(p.time),
                    stop_loss=float(p.sl),
                    take_profit=float(p.tp),
                    magic=int(p.magic),
                    comment=p.comment,
                    meta={
                        "profit": float(p.profit),
                        "swap": float(p.swap),
                        "price_current": float(p.price_current),
                    },
                )
            )
        return out

    def total_exposure(self, symbol: "str | None" = None) -> float:
        return sum(p.volume for p in self.positions(symbol=symbol))

    # ------------------------------------------------------------------ #
    # Orderausführung
    # ------------------------------------------------------------------ #

    def _filling_modes(self, symbol: str, preferred: str = "auto") -> list[Any]:
        """Erlaubte Ausführungsmodi des Symbols, bester zuerst.

        MT5 meldet die erlaubten Modi als Bitmaske. Wer den falschen Modus
        schickt, bekommt 10030 - deshalb probieren wir der Reihe nach durch.
        """
        named = {
            "IOC": mt5.ORDER_FILLING_IOC,
            "FOK": mt5.ORDER_FILLING_FOK,
            "RETURN": mt5.ORDER_FILLING_RETURN,
        }
        if preferred.upper() in named:
            first = named[preferred.upper()]
            return [first] + [v for v in named.values() if v != first]

        with self._lock:
            info = mt5.symbol_info(symbol)
        mask = int(getattr(info, "filling_mode", 0)) if info else 0
        modes: list[Any] = []
        if mask & 2:  # SYMBOL_FILLING_IOC
            modes.append(mt5.ORDER_FILLING_IOC)
        if mask & 1:  # SYMBOL_FILLING_FOK
            modes.append(mt5.ORDER_FILLING_FOK)
        modes.append(mt5.ORDER_FILLING_RETURN)
        return modes

    def _send(self, request: dict[str, Any], attempts: int = 3, delay: float = 1.0) -> Any:
        """Order senden, mit Wiederholung bei flüchtigen Fehlern."""
        self._require()
        last_result = None
        wait = delay
        for attempt in range(1, attempts + 1):
            with self._lock:
                result = mt5.order_send(request)
            if result is None:
                code, detail = mt5.last_error()
                raise MT5Error("order_send lieferte kein Ergebnis", code, detail)
            last_result = result
            if result.retcode in (mt5.TRADE_RETCODE_DONE, 10009, 10008):
                return result
            if result.retcode not in RETRYABLE_RETCODES or attempt == attempts:
                break
            log.warning(
                "Order abgelehnt (%s: %s) - Versuch %d/%d",
                result.retcode, RETCODE_TEXT.get(result.retcode, "?"), attempt, attempts,
            )
            time.sleep(wait)
            wait *= 2
            # Preis auffrischen, sonst wiederholt sich der Requote endlos
            if "price" in request and request.get("action") == mt5.TRADE_ACTION_DEAL:
                t = self.tick(request["symbol"])
                request["price"] = t["ask"] if request["type"] == mt5.ORDER_TYPE_BUY else t["bid"]
        raise MT5Error(
            "Order fehlgeschlagen",
            getattr(last_result, "retcode", 0),
            RETCODE_TEXT.get(getattr(last_result, "retcode", 0), getattr(last_result, "comment", "")),
        )

    def open_position(
        self,
        symbol: str,
        direction: Direction,
        volume: float,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        deviation: int = 20,
        comment: str = "PAX",
        filling: str = "auto",
    ) -> dict[str, Any]:
        """Marktposition eröffnen. Preise und Volumen werden normalisiert."""
        self.ensure_symbol(symbol)
        spec = self.symbol_spec(symbol, refresh=True)
        if not spec.trade_allowed:
            raise MT5Error(f"Handel in {symbol} ist beim Broker gesperrt")

        volume = spec.normalize_volume(volume)
        if volume < spec.volume_min:
            raise MT5Error(
                f"Volumen {volume} liegt unter dem Minimum {spec.volume_min} für {symbol}"
            )
        tick = self.tick(symbol)
        is_long = direction is Direction.LONG
        price = tick["ask"] if is_long else tick["bid"]
        sl, tp = self._sanitize_stops(spec, direction, price, stop_loss, take_profit, tick)

        base = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL,
            "price": float(spec.normalize_price(price)),
            "deviation": int(deviation),
            "magic": int(self.magic),
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
        }
        if sl:
            base["sl"] = float(sl)
        if tp:
            base["tp"] = float(tp)

        last_error: MT5Error | None = None
        for mode in self._filling_modes(symbol, filling):
            request = dict(base, type_filling=mode)
            try:
                result = self._send(request)
            except MT5Error as exc:
                last_error = exc
                if exc.code == 10030:  # unsupported filling -> nächsten Modus testen
                    continue
                raise
            return {
                "ticket": int(result.order),
                "deal": int(result.deal),
                "price": float(result.price),
                "volume": float(result.volume),
                "retcode": int(result.retcode),
                "symbol": symbol,
                "direction": direction.value,
                "sl": sl,
                "tp": tp,
                "slippage": abs(float(result.price) - price),
            }
        raise last_error or MT5Error("Kein unterstützter Ausführungsmodus gefunden")

    def _sanitize_stops(
        self,
        spec: SymbolSpec,
        direction: Direction,
        price: float,
        sl: float,
        tp: float,
        tick: dict[str, Any],
    ) -> tuple[float, float]:
        """SL/TP auf die Broker-Mindestabstände schieben und normalisieren.

        Ein zu enger Stop führt sonst zu Rückgabecode 10016 und die Position
        bliebe ungeschützt offen.
        """
        min_dist = max(spec.min_stop_distance(), spec.point)
        is_long = direction is Direction.LONG
        ref_sl = tick["bid"] if is_long else tick["ask"]
        ref_tp = tick["bid"] if is_long else tick["ask"]

        if sl:
            if is_long:
                sl = min(sl, ref_sl - min_dist)
            else:
                sl = max(sl, ref_sl + min_dist)
            sl = spec.normalize_price(sl)
        if tp:
            if is_long:
                tp = max(tp, ref_tp + min_dist)
            else:
                tp = min(tp, ref_tp - min_dist)
            tp = spec.normalize_price(tp)
        return float(sl or 0.0), float(tp or 0.0)

    def modify_position(
        self, ticket: int, stop_loss: "float | None" = None, take_profit: "float | None" = None
    ) -> bool:
        """SL/TP einer offenen Position ändern (z. B. Nachziehen des Stops)."""
        self._require()
        with self._lock:
            found = mt5.positions_get(ticket=ticket)
        if not found:
            raise MT5Error(f"Position {ticket} nicht gefunden")
        pos = found[0]
        spec = self.symbol_spec(pos.symbol)
        direction = Direction.LONG if pos.type == mt5.POSITION_TYPE_BUY else Direction.SHORT
        tick = self.tick(pos.symbol)
        sl = float(pos.sl) if stop_loss is None else float(stop_loss)
        tp = float(pos.tp) if take_profit is None else float(take_profit)
        sl, tp = self._sanitize_stops(spec, direction, float(pos.price_current), sl, tp, tick)
        if abs(sl - float(pos.sl)) < spec.point / 2 and abs(tp - float(pos.tp)) < spec.point / 2:
            return False  # nichts zu tun
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": int(ticket),
            "sl": sl,
            "tp": tp,
            "magic": int(self.magic),
        }
        self._send(request)
        return True

    def close_position(
        self, ticket: int, volume: "float | None" = None, deviation: int = 20, comment: str = "PAX close"
    ) -> dict[str, Any]:
        """Position ganz oder teilweise glattstellen."""
        self._require()
        with self._lock:
            found = mt5.positions_get(ticket=ticket)
        if not found:
            raise MT5Error(f"Position {ticket} nicht gefunden")
        pos = found[0]
        spec = self.symbol_spec(pos.symbol)
        close_volume = spec.normalize_volume(volume if volume else float(pos.volume))
        close_volume = min(close_volume, float(pos.volume))
        is_long = pos.type == mt5.POSITION_TYPE_BUY
        tick = self.tick(pos.symbol)
        price = tick["bid"] if is_long else tick["ask"]

        base = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": float(close_volume),
            "type": mt5.ORDER_TYPE_SELL if is_long else mt5.ORDER_TYPE_BUY,
            "position": int(ticket),
            "price": float(spec.normalize_price(price)),
            "deviation": int(deviation),
            "magic": int(self.magic),
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
        }
        last_error: MT5Error | None = None
        for mode in self._filling_modes(pos.symbol):
            try:
                result = self._send(dict(base, type_filling=mode))
            except MT5Error as exc:
                last_error = exc
                if exc.code == 10030:
                    continue
                raise
            return {
                "ticket": int(ticket),
                "closed_volume": float(result.volume),
                "price": float(result.price),
                "retcode": int(result.retcode),
            }
        raise last_error or MT5Error("Schließen fehlgeschlagen")

    def close_all(self, symbol: "str | None" = None) -> list[dict[str, Any]]:
        """Alle eigenen Positionen schließen - der Not-Aus-Knopf."""
        results = []
        for pos in self.positions(symbol=symbol):
            try:
                results.append(self.close_position(pos.ticket))
            except MT5Error as exc:
                log.error("Position %s konnte nicht geschlossen werden: %s", pos.ticket, exc)
                results.append({"ticket": pos.ticket, "error": str(exc)})
        return results

    def deals_since(self, since: datetime) -> pd.DataFrame:
        """Abgeschlossene Deals seit einem Zeitpunkt - Grundlage der Lernschleife."""
        self._require()
        start = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        with self._lock:
            deals = mt5.history_deals_get(start, datetime.now(timezone.utc))
        if not deals:
            return pd.DataFrame()
        df = pd.DataFrame([d._asdict() for d in deals])
        if self.magic:
            df = df[df["magic"] == self.magic]
        if "time" in df:
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df.reset_index(drop=True)
