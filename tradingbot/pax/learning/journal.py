"""Das Handelstagebuch.

Ohne lückenlose Aufzeichnung kann ein System nichts lernen - es kennt seine
eigenen Fehler nicht. Festgehalten wird deshalb nicht nur das Ergebnis, sondern
der gesamte Zustand zum Zeitpunkt der Entscheidung: Merkmale, Regelbegründung,
Modellversion, Regime. Nur so lässt sich später die Frage beantworten, die
zählt: *Unter welchen Umständen liegt dieses System falsch?*

SQLite, weil es zu Python gehört, in einer Datei liegt, Abstürze übersteht und
sich mit jedem beliebigen Werkzeug öffnen lässt.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..types import Direction, ExitReason, Horizon, Signal, Trade, VolRegime, utcnow
from ..utils import ensure_dir, get_logger

log = get_logger("journal")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket         INTEGER,
    symbol         TEXT NOT NULL,
    direction      TEXT NOT NULL,
    volume         REAL,
    entry_price    REAL,
    entry_time     TEXT NOT NULL,
    exit_price     REAL,
    exit_time      TEXT NOT NULL,
    profit         REAL,
    r_multiple     REAL,
    exit_reason    TEXT,
    stop_loss      REAL,
    take_profit    REAL,
    commission     REAL,
    swap           REAL,
    slippage       REAL,
    bars_held      INTEGER,
    max_favorable_r REAL,
    max_adverse_r  REAL,
    signal_score   REAL,
    prob_win       REAL,
    horizon        TEXT,
    regime         TEXT,
    model_version  TEXT,
    source         TEXT DEFAULT 'live',
    reasons        TEXT,
    features       TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_exit  ON trades(exit_time);
CREATE INDEX IF NOT EXISTS idx_trades_sym   ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_src   ON trades(source);

CREATE TABLE IF NOT EXISTS signals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT NOT NULL,
    time           TEXT NOT NULL,
    direction      TEXT,
    score          REAL,
    prob_win       REAL,
    expected_r     REAL,
    risk_reward    REAL,
    entry          REAL,
    stop_loss      REAL,
    take_profit    REAL,
    horizon        TEXT,
    regime         TEXT,
    trend_alignment REAL,
    taken          INTEGER DEFAULT 0,
    reject_reason  TEXT,
    model_version  TEXT,
    reasons        TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(time);
CREATE INDEX IF NOT EXISTS idx_signals_sym  ON signals(symbol);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    time        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    symbol      TEXT,
    message     TEXT,
    payload     TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(time);

CREATE TABLE IF NOT EXISTS training_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    time          TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    version       TEXT NOT NULL,
    auc           REAL,
    n_samples     INTEGER,
    n_features    INTEGER,
    promoted      INTEGER DEFAULT 0,
    reason        TEXT,
    metrics       TEXT
);
"""


class Journal:
    """Handelstagebuch auf SQLite-Basis."""

    def __init__(self, path: "str | Path" = "runtime/journal.sqlite") -> None:
        self.path = Path(path)
        ensure_dir(self.path.parent)
        self._lock = threading.RLock()
        self._init_schema()

    # ------------------------------------------------------------------ #

    @contextmanager
    def _connect(self):
        with self._lock:
            conn = sqlite3.connect(self.path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            try:
                # WAL erlaubt Lesen während geschrieben wird - wichtig, wenn die
                # Auswertung läuft, während der Bot handelt.
                conn.execute("PRAGMA journal_mode=WAL")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------------ #
    # Schreiben
    # ------------------------------------------------------------------ #

    def record_trade(self, trade: Trade, source: str = "live") -> int:
        """Einen abgeschlossenen Trade festhalten."""
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO trades (ticket, symbol, direction, volume, entry_price, entry_time,
                   exit_price, exit_time, profit, r_multiple, exit_reason, stop_loss, take_profit,
                   commission, swap, slippage, bars_held, max_favorable_r, max_adverse_r,
                   signal_score, prob_win, horizon, regime, model_version, source, reasons,
                   features, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    trade.ticket, trade.symbol, trade.direction.value, trade.volume,
                    trade.entry_price, _iso(trade.entry_time), trade.exit_price, _iso(trade.exit_time),
                    trade.profit, trade.r_multiple, trade.exit_reason.value, trade.stop_loss,
                    trade.take_profit, trade.commission, trade.swap, trade.slippage, trade.bars_held,
                    trade.max_favorable_r, trade.max_adverse_r, trade.signal_score, trade.prob_win,
                    trade.horizon.value, trade.regime.value, trade.model_version, source,
                    json.dumps(trade.reasons, ensure_ascii=False),
                    json.dumps(trade.features, ensure_ascii=False),
                    _iso(utcnow()),
                ),
            )
            return int(cur.lastrowid or 0)

    def record_trades(self, trades: list[Trade], source: str = "backtest") -> int:
        for t in trades:
            self.record_trade(t, source)
        return len(trades)

    def record_signal(
        self, signal: Signal, taken: bool = False, reject_reason: str = ""
    ) -> int:
        """Auch nicht gehandelte Signale aufzeichnen.

        Gerade die abgelehnten sind wertvoll: Sie zeigen, ob die Filter zu
        streng sind - und was man liegengelassen hat.
        """
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO signals (symbol, time, direction, score, prob_win, expected_r,
                   risk_reward, entry, stop_loss, take_profit, horizon, regime, trend_alignment,
                   taken, reject_reason, model_version, reasons, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    signal.symbol, _iso(signal.time), signal.direction.value, signal.score,
                    signal.prob_win, signal.expected_r, signal.risk_reward, signal.entry,
                    signal.stop_loss, signal.take_profits[0] if signal.take_profits else 0.0,
                    signal.horizon.value, signal.regime.value, signal.trend_alignment,
                    int(taken), reject_reason, signal.model_version,
                    json.dumps(signal.reasons[:6], ensure_ascii=False), _iso(utcnow()),
                ),
            )
            return int(cur.lastrowid or 0)

    def record_event(self, kind: str, message: str, symbol: str = "", payload: "dict | None" = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO events (time, kind, symbol, message, payload) VALUES (?,?,?,?,?)",
                (_iso(utcnow()), kind, symbol, message,
                 json.dumps(payload or {}, ensure_ascii=False, default=str)),
            )

    def record_training(
        self, symbol: str, version: str, auc: float, n_samples: int, n_features: int,
        promoted: bool = False, reason: str = "", metrics: "dict | None" = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO training_runs (time, symbol, version, auc, n_samples, n_features,
                   promoted, reason, metrics) VALUES (?,?,?,?,?,?,?,?,?)""",
                (_iso(utcnow()), symbol, version, auc, n_samples, n_features,
                 int(promoted), reason, json.dumps(metrics or {}, ensure_ascii=False, default=str)),
            )

    # ------------------------------------------------------------------ #
    # Lesen
    # ------------------------------------------------------------------ #

    def trades(
        self,
        symbol: "str | None" = None,
        since: "datetime | None" = None,
        source: "str | None" = None,
        limit: int = 100_000,
    ) -> pd.DataFrame:
        query = "SELECT * FROM trades WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if since:
            query += " AND exit_time >= ?"
            params.append(_iso(since))
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY exit_time DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        if not df.empty:
            for col in ("entry_time", "exit_time", "created_at"):
                df[col] = pd.to_datetime(df[col], utc=True, format="mixed")
            df = df.sort_values("exit_time").reset_index(drop=True)
        return df

    def signals(self, symbol: "str | None" = None, since: "datetime | None" = None,
                limit: int = 100_000) -> pd.DataFrame:
        query = "SELECT * FROM signals WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if since:
            query += " AND time >= ?"
            params.append(_iso(since))
        query += " ORDER BY time DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        if not df.empty:
            df["time"] = pd.to_datetime(df["time"], utc=True, format="mixed")
        return df

    def training_runs(self, symbol: "str | None" = None) -> pd.DataFrame:
        query = "SELECT * FROM training_runs"
        params: list[Any] = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)
        query += " ORDER BY time DESC"
        with self._connect() as conn:
            return pd.read_sql_query(query, conn, params=params)

    def count_trades(self, symbol: "str | None" = None, since: "datetime | None" = None,
                     source: str = "live") -> int:
        query = "SELECT COUNT(*) AS n FROM trades WHERE source = ?"
        params: list[Any] = [source]
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if since:
            query += " AND exit_time >= ?"
            params.append(_iso(since))
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return int(row["n"]) if row else 0

    def last_training(self, symbol: str) -> "datetime | None":
        with self._connect() as conn:
            row = conn.execute(
                "SELECT time FROM training_runs WHERE symbol = ? ORDER BY time DESC LIMIT 1",
                (symbol,),
            ).fetchone()
        return datetime.fromisoformat(row["time"]) if row else None

    # ------------------------------------------------------------------ #

    def stats(self, symbol: "str | None" = None, days: int = 0, source: str = "live") -> dict[str, Any]:
        """Kennzahlen für die Statusanzeige."""
        since = utcnow() - timedelta(days=days) if days else None
        df = self.trades(symbol, since, source)
        if df.empty:
            return {"trades": 0, "quelle": source}
        wins = df[df["profit"] > 0]
        return {
            "trades": len(df),
            "quelle": source,
            "gewinnquote": round(len(wins) / len(df), 4),
            "erwartungswert_r": round(float(df["r_multiple"].mean()), 4),
            "summe_r": round(float(df["r_multiple"].sum()), 3),
            "gewinn": round(float(df["profit"].sum()), 2),
            "profitfaktor": round(
                float(wins["profit"].sum() / abs(df[df["profit"] < 0]["profit"].sum())), 3
            ) if (df["profit"] < 0).any() else float("inf"),
            "bester": round(float(df["r_multiple"].max()), 2),
            "schlechtester": round(float(df["r_multiple"].min()), 2),
            "von": str(df["exit_time"].min())[:19],
            "bis": str(df["exit_time"].max())[:19],
        }

    def export_csv(self, directory: "str | Path") -> list[Path]:
        """Alles als CSV herausschreiben - für Excel oder eigene Auswertungen."""
        out_dir = ensure_dir(directory)
        written = []
        for name, frame in (
            ("trades", self.trades()),
            ("signale", self.signals()),
            ("trainings", self.training_runs()),
        ):
            path = out_dir / f"{name}.csv"
            frame.to_csv(path, index=False)
            written.append(path)
        return written

    def vacuum(self, keep_days: int = 400) -> int:
        """Alte Signalzeilen entfernen - Trades bleiben immer erhalten."""
        cutoff = _iso(utcnow() - timedelta(days=keep_days))
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM signals WHERE time < ?", (cutoff,))
            deleted = cur.rowcount
            conn.execute("DELETE FROM events WHERE time < ?", (cutoff,))
        return int(deleted)


def _iso(ts: "datetime | None") -> str:
    if ts is None:
        return ""
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()
