"""Dauerhafte Ablage in SQLite: Verlauf, Vorlagen und KI-Cache.

Der Cache ist Teil der Kostenbremse: derselbe Auftrag auf derselben Seite
kostet beim zweiten Mal nichts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from typing import Any

from .config import DB_FILE, ensure_dirs
from .models import JobResult, ScrapeOptions, Template

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    started_at  REAL NOT NULL,
    finished_at REAL,
    options     TEXT NOT NULL,
    summary     TEXT,
    rows_json   TEXT,
    ledger      TEXT,
    usage       TEXT,
    row_count   INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS templates (
    name       TEXT PRIMARY KEY,
    options    TEXT NOT NULL,
    note       TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_cache (
    key        TEXT PRIMARY KEY,
    model      TEXT,
    response   TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_cache_created ON ai_cache(created_at);
"""


class Storage:
    """Alle Datenbankzugriffe. Thread-sicher über ein Lock."""

    def __init__(self, path: str | None = None) -> None:
        ensure_dirs()
        self.path = str(path or DB_FILE)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- Verlauf -------------------------------------------------------
    def save_job(self, job: JobResult) -> None:
        rows = job.rows
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO jobs "
                "(id, name, started_at, finished_at, options, summary, rows_json, "
                " ledger, usage, row_count) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    job.id,
                    job.name,
                    job.started_at,
                    job.finished_at,
                    json.dumps(job.options.to_dict(), ensure_ascii=False),
                    job.summary_text,
                    json.dumps(rows, ensure_ascii=False),
                    json.dumps([t.to_dict() for t in job.ledger], ensure_ascii=False),
                    json.dumps(job.usage.to_dict()),
                    len(rows),
                ),
            )
            self._conn.commit()

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, name, started_at, finished_at, row_count, summary, usage "
                "FROM jobs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def load_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            cursor = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
        if not row:
            return None
        data = dict(row)
        data["options"] = json.loads(data["options"] or "{}")
        data["rows"] = json.loads(data["rows_json"] or "[]")
        data["ledger"] = json.loads(data["ledger"] or "[]")
        data["usage"] = json.loads(data["usage"] or "{}")
        return data

    def delete_job(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self._conn.commit()

    def clear_jobs(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM jobs")
            self._conn.commit()

    # -- Vorlagen ------------------------------------------------------
    def save_template(self, template: Template) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO templates (name, options, note, created_at) "
                "VALUES (?,?,?,?)",
                (
                    template.name,
                    json.dumps(template.options.to_dict(), ensure_ascii=False),
                    template.note,
                    template.created_at,
                ),
            )
            self._conn.commit()

    def list_templates(self) -> list[Template]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM templates ORDER BY created_at DESC"
            )
            rows = cursor.fetchall()
        return [
            Template(
                name=row["name"],
                options=ScrapeOptions.from_dict(json.loads(row["options"])),
                note=row["note"] or "",
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def delete_template(self, name: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM templates WHERE name = ?", (name,))
            self._conn.commit()

    # -- KI-Cache ------------------------------------------------------
    @staticmethod
    def _cache_key(model: str, system: str, prompt: str) -> str:
        digest = hashlib.sha256()
        digest.update(model.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(system.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(prompt.encode("utf-8"))
        return digest.hexdigest()

    def get(self, model: str, system: str, prompt: str, ttl_hours: int = 168) -> str | None:
        key = self._cache_key(model, system, prompt)
        cutoff = time.time() - ttl_hours * 3600
        with self._lock:
            cursor = self._conn.execute(
                "SELECT response FROM ai_cache WHERE key = ? AND created_at > ?",
                (key, cutoff),
            )
            row = cursor.fetchone()
        return row["response"] if row else None

    def put(self, model: str, system: str, prompt: str, response: str) -> None:
        key = self._cache_key(model, system, prompt)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO ai_cache (key, model, response, created_at) "
                "VALUES (?,?,?,?)",
                (key, model, response, time.time()),
            )
            self._conn.commit()

    def clear_cache(self) -> int:
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) AS n FROM ai_cache")
            count = cursor.fetchone()["n"]
            self._conn.execute("DELETE FROM ai_cache")
            self._conn.commit()
        return count

    def cache_stats(self) -> dict[str, Any]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT COUNT(*) AS eintraege, "
                "COALESCE(SUM(LENGTH(response)), 0) AS zeichen FROM ai_cache"
            )
            return dict(cursor.fetchone())
