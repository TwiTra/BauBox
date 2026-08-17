#!/usr/bin/env python3
"""Urlaubsplaner-Server – speichert den Plan auf diesem Rechner.

Der Plan liegt in einer SQLite-Datenbank (data/plan.db). Alle Geräte, die den
Server erreichen, arbeiten auf demselben Stand: Änderungen werden sofort
gespeichert und den anderen Geräten innerhalb weniger Sekunden zugestellt.

    python server.py                    Server starten (http://localhost:8000)
    python server.py --tunnel           zusätzlich öffentlichen HTTPS-Link erzeugen
    python server.py --port 8080        anderer Port
    python server.py --set-password     Passwort ändern
    python server.py --show-password    aktuelles Passwort anzeigen (nur lokal)
    python server.py --no-auth          ohne Anmeldung (nur im eigenen Netz!)

Es werden ausschließlich Module der Python-Standardbibliothek verwendet.
Benötigt Python 3.8 oder neuer.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB_PATH = DATA / "plan.db"
CONFIG_PATH = DATA / "config.json"
BACKUP_DIR = DATA / "backups"

MAX_BODY = 32 * 1024 * 1024        # 32 MB – reicht für sehr viele Jahre
SESSION_DAYS = 30
HISTORY_KEEP = 300                 # so viele Fassungen bleiben erhalten
LONGPOLL_MAX = 25                  # Sekunden, die eine Abfrage warten darf
PBKDF2_ROUNDS = 240_000

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
}

# Nur diese Verzeichnisse und Dateien werden ausgeliefert – der Rest des
# Ordners (Datenbank, Sicherungen, Skripte) bleibt unerreichbar.
STATIC_ALLOW = ("index.html", "css/", "js/", "docs/", "favicon.ico")


# ══ Datenbank ═══════════════════════════════════════════════════════════════

def connect() -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS doc (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                rev        INTEGER NOT NULL,
                data       TEXT    NOT NULL,
                updated_at TEXT    NOT NULL,
                client     TEXT
            );
            CREATE TABLE IF NOT EXISTS history (
                rev        INTEGER PRIMARY KEY,
                data       TEXT NOT NULL,
                created_at TEXT NOT NULL,
                client     TEXT,
                note       TEXT
            );
            """
        )
        row = con.execute("SELECT rev FROM doc WHERE id = 1").fetchone()
        if row is None:
            empty = json.dumps({"settings": {}, "years": {}}, ensure_ascii=False)
            con.execute(
                "INSERT INTO doc (id, rev, data, updated_at, client) VALUES (1, 0, ?, ?, ?)",
                (empty, now_iso(), "init"),
            )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_doc() -> tuple[int, str, str]:
    with connect() as con:
        rev, data, updated = con.execute(
            "SELECT rev, data, updated_at FROM doc WHERE id = 1"
        ).fetchone()
    return rev, data, updated


def write_doc(data: str, client: str, note: str = "") -> int:
    """Speichert eine neue Fassung und gibt die neue Revisionsnummer zurück."""
    with connect() as con:
        cur = con.execute("SELECT rev FROM doc WHERE id = 1")
        rev = cur.fetchone()[0] + 1
        stamp = now_iso()
        con.execute(
            "UPDATE doc SET rev = ?, data = ?, updated_at = ?, client = ? WHERE id = 1",
            (rev, data, stamp, client),
        )
        con.execute(
            "INSERT INTO history (rev, data, created_at, client, note) VALUES (?, ?, ?, ?, ?)",
            (rev, data, stamp, client, note),
        )
        con.execute(
            "DELETE FROM history WHERE rev <= (SELECT MAX(rev) FROM history) - ?",
            (HISTORY_KEEP,),
        )
    daily_backup(data)
    return rev


def daily_backup(data: str) -> None:
    """Einmal pro Tag eine Kopie als lesbare JSON-Datei ablegen."""
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        target = BACKUP_DIR / f"plan-{datetime.now().strftime('%Y-%m-%d')}.json"
        if not target.exists():
            target.write_text(data, encoding="utf-8")
            # ältere Sicherungen ausdünnen: die letzten 60 Tage genügen
            files = sorted(BACKUP_DIR.glob("plan-*.json"))
            for old in files[:-60]:
                old.unlink(missing_ok=True)
    except OSError as exc:
        log(f"Sicherung konnte nicht geschrieben werden: {exc}")


# ══ Konfiguration und Anmeldung ═════════════════════════════════════════════

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log("config.json unlesbar – es wird eine neue angelegt.")
    return {}


def save_config(cfg: dict) -> None:
    DATA.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS).hex()


def set_password(password: str) -> None:
    cfg = load_config()
    salt = secrets.token_bytes(16)
    cfg["salt"] = salt.hex()
    cfg["hash"] = hash_password(password, salt)
    cfg.setdefault("secret", secrets.token_hex(32))
    # Ein Passwortwechsel macht alle bestehenden Anmeldungen ungültig.
    cfg["secret"] = secrets.token_hex(32)
    cfg["plain"] = password if cfg.get("keep_plain") else None
    save_config(cfg)


def ensure_config(no_auth: bool) -> dict:
    cfg = load_config()
    if "secret" not in cfg:
        cfg["secret"] = secrets.token_hex(32)
        save_config(cfg)
    if no_auth or cfg.get("hash"):
        return cfg
    # Erststart: Passwort erzeugen und anzeigen.
    password = secrets.token_urlsafe(9)
    cfg["keep_plain"] = True
    save_config(cfg)
    set_password(password)
    cfg = load_config()
    box(["Zugangspasswort für den Urlaubsplaner", "", f"    {password}", "",
         "Notiere es. Ändern lässt es sich mit:", "    python server.py --set-password"])
    return cfg


def check_password(cfg: dict, password: str) -> bool:
    if not cfg.get("hash"):
        return False
    salt = bytes.fromhex(cfg["salt"])
    return hmac.compare_digest(hash_password(password, salt), cfg["hash"])


def make_token(secret: str, days: int = SESSION_DAYS) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": int(time.time()) + days * 86400}).encode()
    ).decode().rstrip("=")
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:40]
    return f"{payload}.{sig}"


def token_valid(secret: str, token: str) -> bool:
    if not token or "." not in token:
        return False
    payload, sig = token.rsplit(".", 1)
    want = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:40]
    if not hmac.compare_digest(sig, want):
        return False
    try:
        pad = "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload + pad))
        return int(data.get("exp", 0)) > time.time()
    except (ValueError, TypeError):
        return False


class Throttle:
    """Bremst wiederholte Fehlversuche pro Absender aus."""

    def __init__(self, limit: int = 8, window: int = 600, block: int = 600):
        self.limit, self.window, self.block = limit, window, block
        self.hits: dict[str, list] = {}
        self.lock = threading.Lock()

    def blocked(self, key: str) -> int:
        with self.lock:
            entry = self.hits.get(key)
            if not entry:
                return 0
            count, first, until = entry
            if until > time.time():
                return int(until - time.time())
            if time.time() - first > self.window:
                self.hits.pop(key, None)
            return 0

    def fail(self, key: str) -> None:
        with self.lock:
            count, first, until = self.hits.get(key, (0, time.time(), 0))
            if time.time() - first > self.window:
                count, first = 0, time.time()
            count += 1
            if count >= self.limit:
                until = time.time() + self.block
            self.hits[key] = (count, first, until)

    def reset(self, key: str) -> None:
        with self.lock:
            self.hits.pop(key, None)


# ══ Benachrichtigung wartender Geräte ═══════════════════════════════════════

class Hub:
    """Weckt Geräte, die per Long-Polling auf Änderungen warten."""

    def __init__(self, rev: int = 0):
        self.cond = threading.Condition()
        self.rev = rev

    def publish(self, rev: int) -> None:
        with self.cond:
            self.rev = rev
            self.cond.notify_all()

    def wait_for_change(self, since: int, timeout: float) -> int:
        deadline = time.time() + timeout
        with self.cond:
            while self.rev == since:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self.cond.wait(remaining)
            return self.rev


# ══ HTTP ════════════════════════════════════════════════════════════════════

def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def box(lines: list[str]) -> None:
    """Rahmen um mehrere Zeilen – die Breite richtet sich nach dem Inhalt."""
    width = max(len(x) for x in lines) + 4
    print()
    print("  ╭" + "─" * width + "╮")
    for line in lines:
        print(f"  │  {line.ljust(width - 4)}  │")
    print("  ╰" + "─" * width + "╯")
    print(flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "Urlaubsplaner"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # von main() gesetzt
    config: dict = {}
    hub: Hub
    throttle: Throttle
    require_auth: bool = True

    # ── Hilfen ──────────────────────────────────────────────────────────────

    def log_message(self, fmt, *args):  # eigene, ruhigere Ausgabe
        pass

    def client_key(self) -> str:
        fwd = self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For", "")
        return (fwd.split(",")[0].strip() or self.client_address[0])[:64]

    def is_https(self) -> bool:
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def send_json(self, obj, status: int = 200, extra: dict | None = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.security_headers()
        self.end_headers()
        self.wfile.write(body)

    def security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("Anfrage zu groß")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def cookies(self) -> dict:
        raw = self.headers.get("Cookie", "")
        out = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def authed(self) -> bool:
        if not self.require_auth:
            return True
        return token_valid(self.config["secret"], self.cookies().get("up_session", ""))

    def set_session_cookie(self, token: str, clear: bool = False) -> str:
        bits = [
            f"up_session={'' if clear else token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            "Max-Age=0" if clear else f"Max-Age={SESSION_DAYS * 86400}",
        ]
        if self.is_https():
            bits.append("Secure")
        return "; ".join(bits)

    # ── Routen ──────────────────────────────────────────────────────────────

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            return self.api_get(path)
        if path in ("/login", "/login/"):
            return self.serve_login()
        if path in ("/", ""):
            if not self.authed():
                return self.redirect("/login")
            return self.serve_static("index.html")
        if not self.authed() and not path.startswith("/css/"):
            return self.redirect("/login")
        return self.serve_static(path.lstrip("/"))

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/login":
                return self.api_login()
            if path == "/api/logout":
                return self.send_json(
                    {"ok": True}, extra={"Set-Cookie": self.set_session_cookie("", clear=True)}
                )
            if not self.authed():
                return self.send_json({"error": "unauthorized"}, 401)
            if path == "/api/restore":
                return self.api_restore()
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)
        self.send_json({"error": "not found"}, 404)

    def do_PUT(self):
        path = urllib.parse.urlparse(self.path).path
        if not self.authed():
            return self.send_json({"error": "unauthorized"}, 401)
        try:
            if path == "/api/state":
                return self.api_put_state()
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)
        self.send_json({"error": "not found"}, 404)

    def redirect(self, target: str) -> None:
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.security_headers()
        self.end_headers()

    # ── API ─────────────────────────────────────────────────────────────────

    def api_get(self, path: str):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if path == "/api/ping":
            return self.send_json(
                {"sync": True, "auth": self.authed(), "authRequired": self.require_auth}
            )

        if not self.authed():
            return self.send_json({"error": "unauthorized"}, 401)

        if path == "/api/state":
            rev, data, updated = read_doc()
            body = f'{{"rev":{rev},"updatedAt":"{updated}","doc":{data}}}'.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.security_headers()
            self.end_headers()
            return self.wfile.write(body)

        if path == "/api/rev":
            since = int((query.get("since") or ["-1"])[0])
            wait = min(LONGPOLL_MAX, max(0, float((query.get("wait") or ["0"])[0])))
            rev = read_doc()[0]
            if wait and rev == since:
                rev = self.hub.wait_for_change(since, wait)
            return self.send_json({"rev": rev})

        if path == "/api/history":
            with connect() as con:
                rows = con.execute(
                    "SELECT rev, created_at, client, LENGTH(data) FROM history "
                    "ORDER BY rev DESC LIMIT 60"
                ).fetchall()
            return self.send_json({
                "entries": [
                    {"rev": r, "createdAt": c, "client": cl or "", "bytes": n}
                    for r, c, cl, n in rows
                ]
            })

        m = re.fullmatch(r"/api/history/(\d+)", path)
        if m:
            with connect() as con:
                row = con.execute(
                    "SELECT rev, data, created_at FROM history WHERE rev = ?", (int(m.group(1)),)
                ).fetchone()
            if not row:
                return self.send_json({"error": "not found"}, 404)
            return self.send_json({"rev": row[0], "createdAt": row[2], "doc": json.loads(row[1])})

        if path == "/api/info":
            rev, data, updated = read_doc()
            backups = sorted(p.name for p in BACKUP_DIR.glob("plan-*.json")) if BACKUP_DIR.exists() else []
            return self.send_json({
                "rev": rev,
                "updatedAt": updated,
                "bytes": len(data.encode("utf-8")),
                "database": str(DB_PATH),
                "backupDir": str(BACKUP_DIR),
                "backups": backups[-5:],
                "authRequired": self.require_auth,
                "host": self.headers.get("Host", ""),
            })

        if path == "/api/export":
            _, data, _ = read_doc()
            body = data.encode("utf-8")
            stamp = datetime.now().strftime("%Y-%m-%d")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition",
                             f'attachment; filename="Urlaubsplaner_Sicherung_{stamp}.json"')
            self.send_header("Content-Length", str(len(body)))
            self.security_headers()
            self.end_headers()
            return self.wfile.write(body)

        self.send_json({"error": "not found"}, 404)

    def api_login(self):
        key = self.client_key()
        wait = self.throttle.blocked(key)
        if wait:
            return self.send_json(
                {"error": "throttled", "retryAfter": wait}, 429, {"Retry-After": str(wait)}
            )
        try:
            body = self.read_body()
        except ValueError:
            body = {}
        password = str(body.get("password", ""))
        time.sleep(0.35)  # verlangsamt automatisiertes Durchprobieren
        if not check_password(self.config, password):
            self.throttle.fail(key)
            log(f"Fehlgeschlagene Anmeldung von {key}")
            return self.send_json({"error": "invalid"}, 401)
        self.throttle.reset(key)
        token = make_token(self.config["secret"])
        log(f"Anmeldung von {key}")
        return self.send_json({"ok": True}, extra={"Set-Cookie": self.set_session_cookie(token)})

    def api_put_state(self):
        body = self.read_body()
        doc = body.get("doc")
        if not isinstance(doc, dict) or "years" not in doc:
            raise ValueError("Ungültiger Plan im Anfragekörper")
        base_rev = int(body.get("baseRev", -1))
        client = str(body.get("client", ""))[:40]

        rev, data, updated = read_doc()
        if base_rev != rev:
            # Ein anderes Gerät war schneller. Der aktuelle Stand geht zurück,
            # der Client führt zusammen und schickt erneut.
            body_out = f'{{"conflict":true,"rev":{rev},"updatedAt":"{updated}","doc":{data}}}'
            raw = body_out.encode("utf-8")
            self.send_response(409)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.security_headers()
            self.end_headers()
            return self.wfile.write(raw)

        payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
        new_rev = write_doc(payload, client)
        self.hub.publish(new_rev)
        return self.send_json({"rev": new_rev, "updatedAt": now_iso()})

    def api_restore(self):
        body = self.read_body()
        target = int(body.get("rev", 0))
        with connect() as con:
            row = con.execute("SELECT data FROM history WHERE rev = ?", (target,)).fetchone()
        if not row:
            return self.send_json({"error": "not found"}, 404)
        new_rev = write_doc(row[0], "restore", note=f"wiederhergestellt aus {target}")
        self.hub.publish(new_rev)
        log(f"Fassung {target} wiederhergestellt als {new_rev}")
        return self.send_json({"rev": new_rev, "doc": json.loads(row[0])})

    # ── Statische Dateien ───────────────────────────────────────────────────

    def serve_static(self, rel: str):
        rel = urllib.parse.unquote(rel)
        if not rel or rel.endswith("/"):
            rel += "index.html"
        if not any(rel == a or rel.startswith(a) for a in STATIC_ALLOW):
            return self.send_json({"error": "not found"}, 404)
        target = (ROOT / rel).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            return self.send_json({"error": "not found"}, 404)
        if not target.is_file():
            return self.send_json({"error": "not found"}, 404)

        data = target.read_bytes()
        ctype = STATIC_TYPES.get(target.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # Der Plan selbst kommt über die API; die Programmdateien dürfen
        # kurz zwischengespeichert werden, müssen aber revalidieren.
        self.send_header("Cache-Control", "no-cache")
        self.security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def serve_login(self):
        html = LOGIN_HTML.replace("{{ERROR}}", "")
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


LOGIN_HTML = """<!DOCTYPE html>
<html lang="de"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Anmelden · Urlaubsplaner</title>
<link rel="stylesheet" href="/css/app.css">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🏖️</text></svg>">
<style>
  body { display: grid; place-items: center; padding: 24px; overflow: auto; }
  .login { width: 100%; max-width: 370px; }
  .login .brand { justify-content: center; margin-bottom: 20px; }
  .login .brand-mark { width: 44px; height: 44px; border-radius: 13px; }
  /* Die Kopfleisten-Regel blendet den Schriftzug auf schmalen Fenstern aus –
     auf der Anmeldeseite soll er immer stehen bleiben. */
  .login .brand-text { display: inline !important; font-size: 19px; }
  .card-body { padding: 22px; }
  h1 { font-size: 16px; font-weight: 650; margin-bottom: 4px; }
  .lead { font-size: 13px; color: var(--muted); margin-bottom: 18px; line-height: 1.5; }
  #msg { margin-top: 14px; }
  .foot { text-align: center; font-size: 12px; color: var(--faint); margin-top: 16px; line-height: 1.6; }
</style>
</head><body>
<div class="login">
  <div class="brand">
    <span class="brand-mark">
      <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="4" width="18" height="17" rx="3"></rect>
        <path d="M3 9h18M8 2v4M16 2v4"></path><path d="M8 14h3M13.5 14h2.5M8 17.5h5"></path>
      </svg>
    </span>
    <span class="brand-text">Urlaubs<b>planer</b></span>
  </div>
  <div class="card">
    <div class="card-body">
      <h1>Anmelden</h1>
      <p class="lead">Dieser Plan liegt auf einem privaten Rechner. Bitte das Zugangspasswort eingeben.</p>
      <form id="f" autocomplete="on">
        <div class="field">
          <label for="pw">Passwort</label>
          <input type="password" id="pw" name="password" autocomplete="current-password" required autofocus>
        </div>
        <button class="primary-btn" type="submit" style="width:100%;height:38px" id="go">Anmelden</button>
      </form>
      <div id="msg"></div>
    </div>
  </div>
  <p class="foot">Passwort vergessen?<br>Auf dem Rechner, der den Planer bereitstellt:<br>
    <span class="mono">python server.py --set-password</span></p>
</div>
<script>
const f = document.getElementById('f'), msg = document.getElementById('msg'), go = document.getElementById('go');
f.addEventListener('submit', async (e) => {
  e.preventDefault();
  go.disabled = true; go.textContent = 'Moment …'; msg.innerHTML = '';
  try {
    const r = await fetch('/api/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: document.getElementById('pw').value })
    });
    if (r.ok) { location.href = '/'; return; }
    const d = await r.json().catch(() => ({}));
    msg.innerHTML = '<div class="note-box danger">' + (
      r.status === 429
        ? 'Zu viele Fehlversuche. Bitte ' + Math.ceil((d.retryAfter || 600) / 60) + ' Minuten warten.'
        : 'Passwort stimmt nicht.') + '</div>';
  } catch (err) {
    msg.innerHTML = '<div class="note-box danger">Der Server ist nicht erreichbar.</div>';
  }
  go.disabled = false; go.textContent = 'Anmelden';
  document.getElementById('pw').select();
});
</script>
</body></html>
"""


# ══ Cloudflare-Tunnel ═══════════════════════════════════════════════════════

def start_tunnel(port: int) -> subprocess.Popen | None:
    """Startet `cloudflared` und gibt die öffentliche Adresse aus."""
    exe = shutil.which("cloudflared")
    if not exe:
        print()
        print("  cloudflared wurde nicht gefunden.")
        print("  Installation:")
        print("    Windows : winget install --id Cloudflare.cloudflared")
        print("    macOS   : brew install cloudflared")
        print("    Linux   : siehe https://developers.cloudflare.com/cloudflare-one/"
              "connections/connect-networks/downloads/")
        print()
        return None

    proc = subprocess.Popen(
        [exe, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, encoding="utf-8", errors="replace",
    )

    def watch():
        pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
        for line in proc.stdout:
            found = pattern.search(line)
            if found:
                box(["Von überall erreichbar unter:", "", f"    {found.group(0)}", "",
                     "Die Adresse gilt, solange dieses Fenster offen bleibt.",
                     "Eine feste Adresse gibt es mit einem Cloudflare-Konto,",
                     "siehe README (Abschnitt „Feste Adresse“)."])

    threading.Thread(target=watch, daemon=True).start()
    return proc


# ══ Start ═══════════════════════════════════════════════════════════════════

def local_ip() -> str:
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> int:
    ap = argparse.ArgumentParser(description="Urlaubsplaner-Server", add_help=True)
    ap.add_argument("--port", type=int, default=8000, help="Port (Standard 8000)")
    ap.add_argument("--host", default="0.0.0.0",
                    help="Adresse zum Lauschen (Standard 0.0.0.0 = auch im lokalen Netz)")
    ap.add_argument("--tunnel", action="store_true", help="öffentlichen HTTPS-Link über cloudflared erzeugen")
    ap.add_argument("--no-auth", action="store_true", help="ohne Anmeldung – nur im eigenen Netz benutzen")
    ap.add_argument("--set-password", action="store_true", help="Zugangspasswort ändern")
    ap.add_argument("--show-password", action="store_true", help="hinterlegtes Passwort anzeigen")
    args = ap.parse_args()

    init_db()

    if args.set_password:
        pw = getpass.getpass("Neues Passwort: ")
        if len(pw) < 6:
            print("Zu kurz – bitte mindestens 6 Zeichen.")
            return 1
        if pw != getpass.getpass("Wiederholen:   "):
            print("Die Eingaben stimmen nicht überein.")
            return 1
        cfg = load_config()
        cfg["keep_plain"] = False
        save_config(cfg)
        set_password(pw)
        print("Passwort gespeichert. Alle Geräte müssen sich neu anmelden.")
        return 0

    if args.show_password:
        cfg = load_config()
        if cfg.get("plain"):
            print(f"Passwort: {cfg['plain']}")
        else:
            print("Das Passwort ist nur als Prüfsumme gespeichert und lässt sich nicht anzeigen.")
            print("Neu setzen mit: python server.py --set-password")
        return 0

    if args.no_auth and args.tunnel:
        print("--no-auth zusammen mit --tunnel wäre ein offener Plan im Internet. Abgebrochen.")
        return 1

    cfg = ensure_config(args.no_auth)

    Handler.config = cfg
    Handler.hub = Hub(read_doc()[0])
    Handler.throttle = Throttle()
    Handler.require_auth = not args.no_auth

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True

    rev, data, updated = read_doc()
    print()
    print("  Urlaubsplaner-Server läuft")
    print(f"    Auf diesem Rechner : http://localhost:{args.port}")
    if args.host == "0.0.0.0":
        print(f"    Im eigenen Netz    : http://{local_ip()}:{args.port}")
    print(f"    Datenbank          : {DB_PATH}")
    print(f"    Sicherungen        : {BACKUP_DIR}")
    print(f"    Stand              : Fassung {rev}, {len(data.encode()) // 1024} kB, {updated}")
    if not Handler.require_auth:
        print("    Anmeldung          : AUS – nicht ins Internet stellen!")
    print("  Beenden mit Strg+C")

    tunnel = start_tunnel(args.port) if args.tunnel else None

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Beendet. Der Plan bleibt gespeichert.")
    finally:
        httpd.server_close()
        if tunnel:
            tunnel.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
