"""End-to-End-Test gegen einen echten lokalen Webserver.

Deckt ab: Abruf, Link-Verfolgung, robots.txt, alle drei Modi und - der
eigentliche Punkt - dass im Agenten-Modus genau EIN Selektor-Aufruf
stattfindet, egal wie viele Seiten geholt werden.

Das Modell wird durch eine Attrappe ersetzt; es geht kein Aufruf ins Netz.
"""

from __future__ import annotations

import http.server
import socketserver
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrapestudio.agents.base import BudgetGuard, LLMClient  # noqa: E402
from scrapestudio.agents.orchestrator import Orchestrator  # noqa: E402
from scrapestudio.config import Settings  # noqa: E402
from scrapestudio.models import AgentResult, ScrapeOptions, Usage  # noqa: E402

_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  OK   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        _failures.append(name)


# --------------------------------------------------------------------------
# Testserver: eine Übersicht mit Links auf fünf gleich gebaute Detailseiten
# --------------------------------------------------------------------------
def _liste() -> str:
    karten = "".join(
        f'<article class="karte"><h2 class="name">Artikel {i}</h2>'
        f'<span class="preis">{i}0,00 €</span>'
        f'<a class="mehr" href="/detail/{i}">Details</a></article>'
        for i in range(1, 6)
    )
    # Viele Links, damit der Abbruch-Test etwas zu tun hat, das er
    # zuverlässig unterbrechen kann.
    links = "".join(f'<a href="/detail/{i}">Detail {i}</a> ' for i in range(1, 61))
    return f"""<!doctype html><html><head><title>Übersicht</title>
<script>var x=1;</script></head><body><h1>Alle Artikel</h1>
<div class="liste">{karten}</div><nav>{links}</nav></body></html>"""


def _detail(nummer: str) -> str:
    return f"""<!doctype html><html><head><title>Artikel {nummer}</title></head>
<body><article class="karte"><h2 class="name">Artikel {nummer}</h2>
<span class="preis">{nummer}0,00 €</span>
<a class="mehr" href="/detail/{nummer}">Details</a></article>
<p>Beschreibung von Artikel {nummer}.</p></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/robots.txt":
            body, typ = "User-agent: *\nDisallow: /geheim\n", "text/plain"
        elif self.path == "/geheim":
            body, typ = "<html><body>Nicht erlaubt</body></html>", "text/html"
        elif self.path.startswith("/detail/"):
            body, typ = _detail(self.path.rsplit("/", 1)[-1]), "text/html"
        elif self.path == "/kaputt":
            self.send_error(500)
            return
        else:
            body, typ = _liste(), "text/html"

        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", f"{typ}; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args) -> None:
        pass  # keine Konsolenausgabe


class Server:
    def __enter__(self) -> str:
        socketserver.TCPServer.allow_reuse_address = True
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.15)
        return f"http://127.0.0.1:{self.port}"

    def __exit__(self, *args) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# --------------------------------------------------------------------------
# Modell-Attrappe: zählt Aufrufe, antwortet mit festen Texten
# --------------------------------------------------------------------------
class FakeLLM(LLMClient):
    """Ersetzt echte API-Aufrufe. Zählt, wer wie oft gefragt wurde."""

    def __init__(self, settings: Settings, budget: BudgetGuard,
                 selector_answer: str | None = None) -> None:
        super().__init__(api_key="test", settings=settings, budget=budget, cache=None)
        self.calls: list[str] = []
        self.selector_answer = selector_answer or (
            '{"container": "article.karte", '
            '"felder": {"name": "h2.name", "preis": ".preis", "link": "a.mehr@href"}, '
            '"begruendung": "Karten wiederholen sich."}'
        )

    def available(self) -> bool:
        return True

    def call(self, tier, system, prompt, max_tokens=2000, temperature=0.0,
             cache_key_extra="") -> AgentResult:
        self.budget.check()

        if "CSS-Selektoren" in system or "HTML-Struktur" in system:
            kind, text = "selector", self.selector_answer
        elif "prüfst das Ergebnis" in system:
            kind, text = "verify", '{"verdikt": "PASS", "grund": "Passt.", "vorschlag": ""}'
        elif "fasst gescrapte Daten" in system:
            kind, text = "summary", "Fünf Artikel mit Preisen zwischen 10 und 50 Euro."
        elif "liest strukturierte Daten" in system:
            kind, text = "extract", '[{"name": "Direkt gelesen"}]'
        else:
            kind, text = "other", "[]"

        self.calls.append(kind)
        usage = Usage(input_tokens=1000, output_tokens=100, calls=1, cost_usd=0.0015)
        self.budget.record(usage)
        return AgentResult(ok=True, text=text, usage=usage)


def _settings() -> Settings:
    settings = Settings()
    settings.use_cache = False
    settings.budget_usd = 5.0
    settings.budget_calls = 50
    return settings


# --------------------------------------------------------------------------
def test_preset_mode(base: str) -> None:
    print("\n[Modus Presets - ohne KI]")
    settings = _settings()
    budget = BudgetGuard(5.0, 50)
    llm = FakeLLM(settings, budget)

    options = ScrapeOptions(urls=[base], mode="preset", presets=["headings", "links"],
                            delay=0, respect_robots=False)
    job = Orchestrator(llm, settings, cancel=threading.Event()).run(options)

    check("eine Seite geholt", len(job.pages) == 1, f"-> {len(job.pages)}")
    check("Überschrift gefunden",
          any(r.get("text") == "Alle Artikel" for r in job.rows))
    check("Links gefunden", any(r.get("typ") == "link" for r in job.rows))
    check("kein Modellaufruf", llm.calls == [], f"-> {llm.calls}")
    check("keine Kosten", job.usage.cost_usd == 0.0)


def test_selector_mode(base: str) -> None:
    print("\n[Modus eigene Selektoren - ohne KI]")
    settings = _settings()
    llm = FakeLLM(settings, BudgetGuard(5.0, 50))

    options = ScrapeOptions(
        urls=[base], mode="selectors",
        selectors={"titel": "h1", "erster_preis": ".preis"},
        delay=0, respect_robots=False,
    )
    job = Orchestrator(llm, settings, cancel=threading.Event()).run(options)

    check("Datensatz erzeugt", len(job.rows) == 1, f"-> {len(job.rows)}")
    check("Titel gelesen", job.rows[0].get("titel") == "Alle Artikel")
    check("kein Modellaufruf", llm.calls == [])


def test_crawl(base: str) -> None:
    print("\n[Links verfolgen]")
    settings = _settings()
    llm = FakeLLM(settings, BudgetGuard(5.0, 50))

    options = ScrapeOptions(
        urls=[base], mode="preset", presets=["headings"],
        follow_links=True, max_depth=1, max_pages=6, delay=0,
        respect_robots=False, workers=3,
    )
    job = Orchestrator(llm, settings, cancel=threading.Event()).run(options)

    check("mehrere Seiten geholt", len(job.pages) >= 5, f"-> {len(job.pages)}")
    check("Seitengrenze eingehalten", len(job.pages) <= 6, f"-> {len(job.pages)}")
    titles = {p.title for p in job.pages}
    check("Detailseiten dabei", any("Artikel" in t for t in titles), f"-> {titles}")


def test_robots(base: str) -> None:
    print("\n[robots.txt]")
    settings = _settings()
    llm = FakeLLM(settings, BudgetGuard(5.0, 50))

    options = ScrapeOptions(urls=[f"{base}/geheim"], mode="preset",
                            delay=0, respect_robots=True)
    job = Orchestrator(llm, settings, cancel=threading.Event()).run(options)
    check("gesperrte Seite abgelehnt",
          any("robots" in p.error.lower() for p in job.pages),
          f"-> {[p.error for p in job.pages]}")

    options.respect_robots = False
    job2 = Orchestrator(FakeLLM(settings, BudgetGuard(5.0, 50)), settings,
                        cancel=threading.Event()).run(options)
    check("ohne robots-Prüfung erreichbar", job2.pages[0].ok)


def test_errors(base: str) -> None:
    print("\n[Fehlerbehandlung]")
    settings = _settings()
    llm = FakeLLM(settings, BudgetGuard(5.0, 50))

    options = ScrapeOptions(
        urls=[f"{base}/kaputt", base, "http://127.0.0.1:1/weg"],
        mode="preset", presets=["headings"], delay=0, retries=0,
        respect_robots=False, timeout=3,
    )
    job = Orchestrator(llm, settings, cancel=threading.Event()).run(options)

    check("Fehler gezählt", len(job.errors) == 2, f"-> {len(job.errors)}")
    check("gute Seite trotzdem gelesen", len(job.rows) >= 1)
    check("Lauf nicht abgestürzt", job.finished_at > 0)


def test_agent_mode_learns_once(base: str) -> None:
    print("\n[Modus KI-Agenten - der Token-Sparer]")
    settings = _settings()
    budget = BudgetGuard(5.0, 50)
    llm = FakeLLM(settings, budget)

    options = ScrapeOptions(
        urls=[base], mode="agent", instruction="Name und Preis jedes Artikels",
        follow_links=True, max_depth=1, max_pages=6, delay=0,
        respect_robots=False, workers=3,
    )
    job = Orchestrator(llm, settings, cancel=threading.Event()).run(options)

    check("mehrere Seiten geholt", len(job.pages) >= 5, f"-> {len(job.pages)}")
    check("Datensätze gefunden", len(job.rows) >= 5, f"-> {len(job.rows)}")

    # Der Kern: EIN Selektor-Aufruf, egal wie viele Seiten.
    selector_calls = llm.calls.count("selector")
    check("genau EIN Selektor-Aufruf", selector_calls == 1, f"-> {selector_calls}")
    check("genau EIN Prüf-Aufruf", llm.calls.count("verify") == 1, f"-> {llm.calls}")
    check("genau EIN Zusammenfassungs-Aufruf", llm.calls.count("summary") == 1)
    check("kein Direkt-Leser nötig", llm.calls.count("extract") == 0)
    check("insgesamt 3 Aufrufe für 6 Seiten", len(llm.calls) == 3, f"-> {llm.calls}")

    check("Ersparnis gezählt", job.usage.saved_calls >= 4,
          f"-> {job.usage.saved_calls}")
    check("Selektoren gemerkt", "name" in job.learned_selectors,
          f"-> {job.learned_selectors}")
    check("Zusammenfassung da", "Artikel" in job.summary_text, f"-> {job.summary_text}")

    # Datensätze inhaltlich korrekt
    namen = {r.get("name") for r in job.rows}
    check("Namen korrekt extrahiert", "Artikel 3" in namen, f"-> {sorted(namen)[:6]}")
    preise = {r.get("preis") for r in job.rows}
    check("Preise korrekt extrahiert", "30,00 €" in preise, f"-> {sorted(preise)[:6]}")

    # Status-Board
    states = {t.id: t.state for t in job.ledger}
    check("Board führt Lernaufgabe", "L1" in states and states["L1"] == "PASS",
          f"-> {states}")
    check("Board führt Anwendung", states.get("A1") == "PASS")
    check("Board führt Prüfung", states.get("P1") == "PASS")


def test_agent_retries_on_fix(base: str) -> None:
    print("\n[Prüfer lehnt ab - zweiter Versuch]")
    settings = _settings()
    budget = BudgetGuard(5.0, 50)

    class RejectingLLM(FakeLLM):
        """Prüfer sagt beim ersten Mal FIX, danach PASS."""

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.verify_count = 0

        def call(self, tier, system, prompt, max_tokens=2000, temperature=0.0,
                 cache_key_extra="") -> AgentResult:
            if "prüfst das Ergebnis" in system:
                self.verify_count += 1
                self.calls.append("verify")
                usage = Usage(input_tokens=500, output_tokens=50, calls=1, cost_usd=0.001)
                self.budget.record(usage)
                if self.verify_count == 1:
                    return AgentResult(ok=True, usage=usage, text=(
                        '{"verdikt": "FIX", "grund": "Preisspalte leer.", '
                        '"vorschlag": "Anderen Selektor für den Preis nehmen."}'
                    ))
                return AgentResult(ok=True, usage=usage,
                                   text='{"verdikt": "PASS", "grund": "Jetzt gut."}')
            return super().call(tier, system, prompt, max_tokens, temperature,
                                cache_key_extra)

    llm = RejectingLLM(settings, budget)
    options = ScrapeOptions(urls=[base], mode="agent", instruction="Name und Preis",
                            delay=0, respect_robots=False, max_pages=1)
    job = Orchestrator(llm, settings, cancel=threading.Event()).run(options)

    check("zweimal gelernt", llm.calls.count("selector") == 2, f"-> {llm.calls}")
    check("zweimal geprüft", llm.calls.count("verify") == 2)
    check("am Ende Datensätze da", len(job.rows) >= 1)

    states = {t.id: t.state for t in job.ledger}
    check("erster Prüfdurchgang als FIX vermerkt", states.get("P1") == "FIX",
          f"-> {states}")
    check("zweiter Versuch als PASS", states.get("L2") == "PASS")

    ledger_l2 = next(t for t in job.ledger if t.id == "L2")
    check("Wiederholung gezählt", ledger_l2.retries == 1, f"-> {ledger_l2.retries}")


def test_budget_stops(base: str) -> None:
    print("\n[Kostenbremse greift]")
    settings = _settings()
    budget = BudgetGuard(max_usd=0.002, max_calls=1, stop=True)
    llm = FakeLLM(settings, budget)

    options = ScrapeOptions(urls=[base], mode="agent", instruction="Alles",
                            delay=0, respect_robots=False, max_pages=1)
    job = Orchestrator(llm, settings, cancel=threading.Event()).run(options)

    check("höchstens ein Aufruf", len(llm.calls) <= 1, f"-> {llm.calls}")
    check("Lauf beendet sich sauber", job.finished_at > 0)
    check("Rückfall auf Presets lieferte Daten", len(job.rows) >= 1,
          f"-> {len(job.rows)}")


def test_agent_without_key(base: str) -> None:
    print("\n[Agentenmodus ohne Schlüssel fällt zurück]")
    settings = _settings()
    llm = LLMClient(api_key="", settings=settings, budget=BudgetGuard(5.0, 50))

    options = ScrapeOptions(urls=[base], mode="agent", instruction="Alles",
                            presets=["headings"], delay=0, respect_robots=False)
    job = Orchestrator(llm, settings, cancel=threading.Event()).run(options)

    check("läuft trotzdem durch", job.finished_at > 0)
    check("Presets lieferten Daten", len(job.rows) >= 1, f"-> {len(job.rows)}")


def test_cancel(base: str) -> None:
    print("\n[Abbruch]")
    settings = _settings()
    llm = FakeLLM(settings, BudgetGuard(5.0, 50))
    cancel = threading.Event()
    orchestrator = Orchestrator(llm, settings, cancel=cancel)

    # 60 verlinkte Seiten mit Pause dazwischen: der Lauf braucht deutlich
    # länger als die Wartezeit bis zum Abbruch.
    options = ScrapeOptions(urls=[base], mode="preset", follow_links=True,
                            max_depth=2, max_pages=55, delay=0.08,
                            workers=2, respect_robots=False)

    result: dict = {}

    def work() -> None:
        result["job"] = orchestrator.run(options)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    time.sleep(0.4)
    orchestrator.stop()
    thread.join(timeout=15)

    check("Lauf beendet sich nach Abbruch", not thread.is_alive())
    check("als abgebrochen markiert",
          bool(result.get("job")) and result["job"].cancelled)
    check("weniger als das Limit geholt", len(result["job"].pages) < 55,
          f"-> {len(result['job'].pages)}")


if __name__ == "__main__":
    with Server() as base_url:
        print(f"Testserver: {base_url}")
        for test in (test_preset_mode, test_selector_mode, test_crawl, test_robots,
                     test_errors, test_agent_mode_learns_once,
                     test_agent_retries_on_fix, test_budget_stops,
                     test_agent_without_key, test_cancel):
            test(base_url)

    print("\n" + "=" * 58)
    if _failures:
        print(f"{len(_failures)} Prüfung(en) fehlgeschlagen: {', '.join(_failures)}")
        sys.exit(1)
    print("Orchestrator: alle Prüfungen bestanden.")
