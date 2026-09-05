"""Der Orchestrator - er verteilt, prüft und führt zusammen.

Ablauf eines Auftrags:

1. **Sammeln** - Seiten holen (regelbasiert, keine Token).
2. **Lernen** - EIN Arbeiter sieht EINE Beispielseite und leitet Selektoren ab.
3. **Anwenden** - diese Selektoren laufen über alle übrigen Seiten. Kostenlos.
4. **Prüfen** - der Prüfer sieht eine Stichprobe und sagt PASS oder FIX.
5. **Nachbessern** - bei FIX neu lernen mit konkreter Rückmeldung; erst als
   letzte Stufe liest der Direkt-Leser einzelne Seiten selbst.
6. **Verdichten** - der Zusammenfasser beantwortet den Auftrag.

Der teure Berater wird nur gerufen, wenn zwei Lernversuche scheitern.
Damit kostet ein Lauf über 100 Seiten ungefähr so viel wie einer über 3.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from ..compress import to_readable_text
from ..engine import Crawler, Fetched, to_page_result
from ..extractors import dedupe_rows, extract_presets
from ..models import (
    DISPATCHED, ESCALATED, FIX, PASS, PENDING,
    AgentResult, JobResult, ScrapeOptions, TaskRecord, Usage,
)
from .base import Agent, AgentContext, BudgetExceeded, BudgetGuard, LLMClient
from .workers import (
    ExtractAgent, ScoutAgent, SelectorAgent, SummarizerAgent, VerifierAgent,
    apply_selectors,
)

ProgressFn = Callable[[str, dict], None]
MAX_LEARN_ATTEMPTS = 2


class Orchestrator:
    """Führt einen Auftrag vom Rohbefehl bis zum geprüften Ergebnis."""

    def __init__(
        self,
        llm: LLMClient,
        settings: Any,
        progress: ProgressFn | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        self.llm = llm
        self.settings = settings
        self.progress = progress or (lambda event, data: None)
        self.cancel = cancel or threading.Event()
        self.ctx = AgentContext(
            llm=llm,
            settings=settings,
            log=lambda level, msg: self.progress("log", {"level": level, "text": msg}),
            cancel=self.cancel,
        )
        self.ledger: list[TaskRecord] = []
        self._crawler: Crawler | None = None

    # ------------------------------------------------------------------
    # Status-Board
    # ------------------------------------------------------------------
    def _task(self, task_id: str, agent: str, goal: str, model: str = "") -> TaskRecord:
        record = TaskRecord(id=task_id, agent=agent, goal=goal, model=model)
        self.ledger.append(record)
        self._emit(record)
        return record

    def _update(self, record: TaskRecord, state: str, note: str = "",
                usage: Usage | None = None) -> None:
        record.state = state
        if note:
            record.note = note
        if usage:
            record.usage.add(usage)
        if state in (PASS, FIX, ESCALATED):
            record.finished_at = time.time()
        self._emit(record)

    def _emit(self, record: TaskRecord) -> None:
        self.progress("task", {"record": record, "board": record.board_line()})

    def _log(self, text: str, level: str = "info") -> None:
        self.progress("log", {"level": level, "text": text})

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self.cancel.set()
        if self._crawler:
            self._crawler.cancel()

    @property
    def cancelled(self) -> bool:
        return self.cancel.is_set()

    # ------------------------------------------------------------------
    # Hauptlauf
    # ------------------------------------------------------------------
    def run(self, options: ScrapeOptions, name: str = "") -> JobResult:
        job = JobResult(name=name or (options.urls[0] if options.urls else "Auftrag"),
                        options=options)
        budget: BudgetGuard = self.llm.budget

        # -- 1. Sammeln ------------------------------------------------
        collect = self._task("S1", "Sammler", "Seiten abrufen", model="regelbasiert")
        self._update(collect, DISPATCHED)
        self._crawler = Crawler(options, progress=self.progress)
        fetched = self._crawler.run()
        good = [f for f in fetched if f.ok and f.html]
        self._update(
            collect,
            PASS if good else FIX,
            f"{len(good)} von {len(fetched)} Seiten geladen",
        )
        self._log(f"{len(good)} Seiten geladen, {len(fetched) - len(good)} Fehler.")

        if self.cancelled:
            job.cancelled = True
            return self._finish(job, fetched, [])

        if not good:
            job.pages = [to_page_result(f) for f in fetched]
            job.ledger = self.ledger
            job.finished_at = time.time()
            return job

        # -- Regelbasierte Modi brauchen kein Modell -------------------
        if options.mode != "agent" or not self.llm.available():
            if options.mode == "agent":
                self._log(
                    "Agenten-Team nicht verfügbar (Schlüssel oder Paket fehlt) - "
                    "es laufen die Presets.", "warn",
                )
            return self._run_rule_based(job, fetched, good, options)

        # -- 2./3. Lernen und anwenden ---------------------------------
        try:
            rows, learned = self._learn_and_apply(good, options)
        except BudgetExceeded as exc:
            self._log(f"Kostenbremse: {exc}", "warn")
            return self._run_rule_based(job, fetched, good, options)

        job.learned_selectors = learned.get("felder", {}) if learned else {}

        # -- 6. Verdichten ---------------------------------------------
        if rows and not self.cancelled:
            job.summary_text = self._summarize(options.instruction, rows)

        return self._finish(job, fetched, rows, learned)

    # ------------------------------------------------------------------
    def _run_rule_based(
        self, job: JobResult, fetched: list[Fetched], good: list[Fetched],
        options: ScrapeOptions,
    ) -> JobResult:
        """Presets oder Selektoren von Hand - ohne jeden Modellaufruf."""
        record = self._task("R1", "Extraktor", "Regelbasiert auslesen",
                            model="regelbasiert")
        self._update(record, DISPATCHED)

        rows: list[dict[str, Any]] = []
        by_url: dict[str, list[dict[str, Any]]] = {}
        for page in good:
            if options.mode == "selectors" and options.selectors:
                page_rows = apply_selectors(
                    page.html, page.url,
                    {"felder": options.selectors, "container": ""},
                    options.strip_whitespace,
                )
            else:
                page_rows = extract_presets(
                    page.html, page.url, options.presets or ["text"],
                    options.strip_whitespace, options.min_text_length,
                )
            by_url[page.url] = page_rows
            rows.extend(page_rows)

        if options.dedupe:
            rows = dedupe_rows(rows)
        self._update(record, PASS, f"{len(rows)} Datensätze")
        return self._finish(job, fetched, rows, page_rows_by_url=by_url)

    # ------------------------------------------------------------------
    def _learn_and_apply(
        self, pages: list[Fetched], options: ScrapeOptions,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Selektoren lernen, anwenden, prüfen, notfalls nachbessern."""
        selector_agent = SelectorAgent(self.ctx)
        verifier = VerifierAgent(self.ctx)
        instruction = options.instruction or "Alle wesentlichen Inhalte der Seite"

        sample_page = pages[0]
        learned: dict[str, Any] = {}
        rows: list[dict[str, Any]] = []
        feedback = ""

        for attempt in range(1, MAX_LEARN_ATTEMPTS + 1):
            if self.cancelled:
                break

            learn = self._task(
                f"L{attempt}", selector_agent.name,
                f"Selektoren ableiten (Versuch {attempt})", selector_agent.model,
            )
            learn.retries = attempt - 1
            self._update(learn, DISPATCHED)

            goal = instruction if not feedback else (
                f"{instruction}\n\nVORHERIGER VERSUCH WURDE ABGELEHNT: {feedback}\n"
                "Leite andere Selektoren ab, die diesen Mangel beheben."
            )
            result = selector_agent.run(sample_page.html, sample_page.url, goal)

            if not result.ok:
                self._update(learn, FIX, result.error, result.usage)
                self._log(f"Selektoren fehlgeschlagen: {result.error}", "warn")
                feedback = result.error
                continue

            learned = result.data
            self._update(
                learn, PASS,
                f"{len(learned['felder'])} Felder" + (" (Cache)" if result.from_cache else ""),
                result.usage,
            )
            self._log(
                "Gelernt: " + ", ".join(learned["felder"]) +
                (f" | Container: {learned['container']}" if learned["container"] else "")
            )

            # -- Anwenden: ab hier kostenlos --------------------------
            apply_task = self._task(
                "A1", "Anwender", f"Selektoren auf {len(pages)} Seiten anwenden",
                "regelbasiert",
            )
            self._update(apply_task, DISPATCHED)
            rows = []
            for page in pages:
                if self.cancelled:
                    break
                rows.extend(apply_selectors(page.html, page.url, learned,
                                            options.strip_whitespace))
            if options.dedupe:
                rows = dedupe_rows(rows)
            self.llm.budget.record_saved(max(0, len(pages) - 1))
            self._update(apply_task, PASS if rows else FIX,
                         f"{len(rows)} Datensätze ohne Modellaufruf")

            # -- Prüfen -----------------------------------------------
            check = self._task(f"P{attempt}", verifier.name, "Stichprobe prüfen",
                               verifier.model)
            self._update(check, DISPATCHED)
            verdict = verifier.run(instruction, rows, self.settings.verify_sample)

            if not verdict.ok:
                self._update(check, PASS, f"Prüfung übersprungen: {verdict.error}",
                             verdict.usage)
                break

            data = verdict.data or {}
            if data.get("verdikt") == "PASS":
                self._update(check, PASS, data.get("grund", "") or "In Ordnung",
                             verdict.usage)
                return rows, learned

            self._update(check, FIX, data.get("grund", ""), verdict.usage)
            feedback = f"{data.get('grund', '')} {data.get('vorschlag', '')}".strip()
            self._log(f"Prüfer lehnt ab: {feedback}", "warn")

        # -- Letzte Stufe: Direkt-Leser auf wenigen Seiten -------------
        if not rows and not self.cancelled:
            rows = self._direct_read(pages, instruction)

        if not rows:
            escalate = self._task("E1", "Berater", "Kein Weg führte zum Ziel",
                                  self.llm.model_for("advisor"))
            self._update(escalate, ESCALATED,
                         "Selektoren und Direkt-Leser ohne Ergebnis - bitte Auftrag schärfen.")
            self._log(
                "Weder Selektoren noch Direkt-Leser lieferten Daten. Formuliere den "
                "Auftrag konkreter oder prüfe, ob die Seite Inhalte per JavaScript "
                "nachlädt.", "warn",
            )

        return rows, learned

    # ------------------------------------------------------------------
    def _direct_read(self, pages: list[Fetched], instruction: str) -> list[dict[str, Any]]:
        """Rückfall: einzelne Seiten direkt vom Modell lesen lassen.

        Bewusst gedeckelt - das ist der teure Weg.
        """
        reader = ExtractAgent(self.ctx)
        limit = min(len(pages), max(1, self.settings.parallel_agents))
        self._log(f"Rückfall auf Direkt-Leser für {limit} Seiten.", "warn")

        rows: list[dict[str, Any]] = []
        for index, page in enumerate(pages[:limit], 1):
            if self.cancelled:
                break
            record = self._task(f"D{index}", reader.name,
                                f"Seite direkt lesen: {page.url[:50]}", reader.model)
            self._update(record, DISPATCHED)
            try:
                result = reader.run(page.html, page.url, instruction)
            except BudgetExceeded as exc:
                self._update(record, ESCALATED, str(exc))
                break
            if result.ok and result.data:
                rows.extend(result.data)
                self._update(record, PASS, f"{len(result.data)} Datensätze", result.usage)
            else:
                self._update(record, FIX, result.error or "nichts gefunden", result.usage)
        return rows

    # ------------------------------------------------------------------
    def _summarize(self, instruction: str, rows: list[dict[str, Any]]) -> str:
        summarizer = SummarizerAgent(self.ctx)
        record = self._task("Z1", summarizer.name, "Ergebnis zusammenfassen",
                            summarizer.model)
        self._update(record, DISPATCHED)
        try:
            result = summarizer.run(instruction or "Fasse die Daten zusammen", rows)
        except BudgetExceeded as exc:
            self._update(record, ESCALATED, str(exc))
            return ""
        if result.ok:
            self._update(record, PASS, "fertig", result.usage)
            return result.text.strip()
        self._update(record, FIX, result.error, result.usage)
        return ""

    # ------------------------------------------------------------------
    def scout(self, instruction: str, links: list[dict[str, str]], limit: int = 20) -> list[dict]:
        """Öffentlicher Helfer: Links vom Kundschafter vorsortieren lassen."""
        agent = ScoutAgent(self.ctx)
        record = self._task("K1", agent.name, "Relevante Links auswählen", agent.model)
        self._update(record, DISPATCHED)
        try:
            result = agent.run(instruction, links, limit)
        except BudgetExceeded as exc:
            self._update(record, ESCALATED, str(exc))
            return links[:limit]
        if result.ok:
            self._update(record, PASS, f"{len(result.data)} von {len(links)} gewählt",
                         result.usage)
            return result.data
        self._update(record, FIX, result.error, result.usage)
        return links[:limit]

    # ------------------------------------------------------------------
    def _finish(
        self,
        job: JobResult,
        fetched: list[Fetched],
        rows: list[dict[str, Any]],
        learned: dict[str, Any] | None = None,
        page_rows_by_url: dict[str, list[dict[str, Any]]] | None = None,
    ) -> JobResult:
        """Ergebnisse den Seiten zuordnen und den Auftrag abschliessen."""
        if page_rows_by_url is None:
            page_rows_by_url = {}
            for row in rows:
                page_rows_by_url.setdefault(str(row.get("quelle", "")), []).append(row)

        job.pages = [to_page_result(f, page_rows_by_url.get(f.url, [])) for f in fetched]
        # Zeilen ohne passende Quelle hängen wir an die erste Seite,
        # damit sie im Export nicht verloren gehen.
        known = {r.get("quelle") for r in rows if r.get("quelle")}
        orphans = [r for r in rows if str(r.get("quelle", "")) not in
                   {p.url for p in job.pages}]
        if orphans and job.pages:
            job.pages[0].rows.extend(orphans)

        job.ledger = self.ledger
        job.usage = self.llm.budget.usage
        job.cancelled = self.cancelled
        job.finished_at = time.time()
        return job
