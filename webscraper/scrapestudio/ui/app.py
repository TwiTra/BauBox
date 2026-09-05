"""Hauptfenster: Navigation, Auftragssteuerung, Verdrahtung."""

from __future__ import annotations

import queue
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import customtkinter as ctk
from tkinter import messagebox, simpledialog

from .. import APP_NAME, __version__, exporters
from ..agents.base import BudgetGuard, LLMClient
from ..agents.orchestrator import Orchestrator
from ..config import (
    Settings, load_api_key, load_settings, save_settings,
)
from ..models import JobResult, ScrapeOptions, Template, Usage
from ..storage import Storage
from .components import Toast, ghost_button
from .theme import C, PAD, PAD_SM, RADIUS_SM, Fonts, apply_mode
from .view_history import HistoryView
from .view_results import ResultsView
from .view_scrape import ScrapeView
from .view_settings import SettingsView
from .view_team import TeamView

NAV = [
    ("scrape", "Auftrag", "Adressen, Modus und Start"),
    ("results", "Ergebnisse", "Tabelle, Filter und Export"),
    ("team", "Team", "Agenten, Kosten und Ersparnis"),
    ("history", "Verlauf", "Frühere Läufe und Vorlagen"),
    ("settings", "Einstellungen", "Schlüssel, Modelle, Budget"),
]


class ScrapeStudio(ctk.CTk):
    """Das Programm."""

    def __init__(self) -> None:
        super().__init__()

        self.settings: Settings = load_settings()
        apply_mode(self.settings.theme)
        Fonts.build()

        self.title(f"{APP_NAME} {__version__}")
        self.geometry("1360x870")
        self.minsize(1120, 700)
        self.configure(fg_color=C["bg"])

        self.storage = Storage()
        self.current_job: JobResult | None = None
        self._orchestrator: Orchestrator | None = None
        self._thread: threading.Thread | None = None
        self._events: queue.Queue = queue.Queue()
        self._page_count = 0

        self.rebuild_llm()
        self._build_layout()
        self._bind_keys()
        self.show("scrape")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._pump)
        self.log(f"{APP_NAME} {__version__} bereit.", "ok")
        if not self.agents_ready():
            self.log("Kein API-Schlüssel: Presets und eigene Selektoren laufen "
                     "normal, der Modus 'KI-Agenten' ist gesperrt.", "warn")

    # ==================================================================
    # Aufbau
    # ==================================================================
    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # -- Seitenleiste ----------------------------------------------
        sidebar = ctk.CTkFrame(self, width=232, corner_radius=0, fg_color=C["surface"])
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD + 4, PAD))
        ctk.CTkLabel(brand, text=APP_NAME, font=Fonts.h1,
                     text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(brand, text="Webscraper mit Agenten-Team", font=Fonts.small,
                     text_color=C["text_muted"]).pack(anchor="w")

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=PAD_SM)
        nav.grid_columnconfigure(0, weight=1)

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for index, (key, label, hint) in enumerate(NAV):
            button = ctk.CTkButton(
                nav, text=f"  {label}", anchor="w", height=40, font=Fonts.body,
                corner_radius=RADIUS_SM, fg_color="transparent",
                hover_color=C["surface_2"], text_color=C["text_muted"],
                command=lambda k=key: self.show(k),
            )
            button.grid(row=index, column=0, sticky="ew", pady=1)
            self.nav_buttons[key] = button

        # -- Fuss der Seitenleiste -------------------------------------
        foot = ctk.CTkFrame(sidebar, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", padx=PAD_SM, pady=PAD_SM)

        self.agent_badge = ctk.CTkLabel(
            foot, text="", font=Fonts.small, text_color=C["text_muted"],
            anchor="w", justify="left", wraplength=200,
        )
        self.agent_badge.pack(fill="x", pady=(0, PAD_SM))

        ctk.CTkLabel(foot, text="Strg+Enter starten  ·  Esc abbrechen",
                     font=Fonts.small, text_color=C["text_faint"],
                     anchor="w").pack(fill="x")

        # -- Inhaltsbereich --------------------------------------------
        header = ctk.CTkFrame(self, fg_color="transparent", height=54)
        header.grid(row=0, column=1, sticky="new", padx=PAD, pady=(PAD, 0))
        header.grid_columnconfigure(0, weight=1)

        self.view_title = ctk.CTkLabel(header, text="", font=Fonts.h2,
                                       text_color=C["text"], anchor="w")
        self.view_title.grid(row=0, column=0, sticky="w")
        self.view_hint = ctk.CTkLabel(header, text="", font=Fonts.small,
                                      text_color=C["text_muted"], anchor="w")
        self.view_hint.grid(row=1, column=0, sticky="w")

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.grid(row=1, column=1, sticky="nsew", padx=PAD, pady=(PAD_SM, PAD))
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        self.scrape_view = ScrapeView(container, self)
        self.results_view = ResultsView(container, self)
        self.team_view = TeamView(container, self)
        self.history_view = HistoryView(container, self)
        self.settings_view = SettingsView(container, self)

        self.views = {
            "scrape": self.scrape_view,
            "results": self.results_view,
            "team": self.team_view,
            "history": self.history_view,
            "settings": self.settings_view,
        }
        self._refresh_agent_badge()

    def _bind_keys(self) -> None:
        self.bind("<Control-Return>", lambda _e: self.start_job())
        self.bind("<Escape>", lambda _e: self.stop_job())
        self.bind("<Control-s>", lambda _e: self._quick_save())
        self.bind("<Control-f>", lambda _e: self._focus_search())
        self.bind("<Control-e>", lambda _e: self.show("results"))
        for index, (key, _label, _hint) in enumerate(NAV, 1):
            self.bind(f"<Control-Key-{index}>", lambda _e, k=key: self.show(k))

    # ==================================================================
    # Navigation
    # ==================================================================
    def show(self, key: str) -> None:
        for view in self.views.values():
            view.grid_forget()
        self.views[key].grid(row=0, column=0, sticky="nsew")

        for nav_key, button in self.nav_buttons.items():
            active = nav_key == key
            button.configure(
                fg_color=C["accent_soft"] if active else "transparent",
                text_color=C["accent"] if active else C["text_muted"],
                font=Fonts.body_bold if active else Fonts.body,
            )

        label, hint = next((l, h) for k, l, h in NAV if k == key)
        self.view_title.configure(text=label)
        self.view_hint.configure(text=hint)

        if key == "history":
            self.history_view.refresh()
        elif key == "settings":
            self.settings_view._refresh_cache_info()

    def _focus_search(self) -> None:
        self.show("results")
        self.results_view.focus_search()

    def _quick_save(self) -> None:
        self.show("results")
        self.results_view._quick_export()

    # ==================================================================
    # Agenten-Anbindung
    # ==================================================================
    def rebuild_llm(self) -> None:
        """Modell-Anbindung neu aufbauen (nach Schlüssel- oder Modellwechsel)."""
        self.budget = BudgetGuard(
            self.settings.budget_usd, self.settings.budget_calls,
            self.settings.stop_on_budget,
        )
        self.llm = LLMClient(
            api_key=load_api_key(),
            settings=self.settings,
            budget=self.budget,
            cache=self.storage if self.settings.use_cache else None,
            log=lambda level, msg: self._events.put(("log", {"level": level, "text": msg})),
        )
        if hasattr(self, "agent_badge"):
            self._refresh_agent_badge()

    def agents_ready(self) -> bool:
        return self.llm.available()

    def model_for(self, tier: str) -> str:
        return self.llm.model_for(tier)

    def settings_mode_default(self) -> str:
        return "agent" if self.agents_ready() else "preset"

    def _refresh_agent_badge(self) -> None:
        if self.agents_ready():
            self.agent_badge.configure(
                text=f"Team bereit\nArbeiter: {self.settings.worker_model.replace('claude-', '')}",
                text_color=C["ok"],
            )
        elif not LLMClient.library_available():
            self.agent_badge.configure(
                text="Paket 'anthropic' fehlt\nOhne Team, sonst voll nutzbar",
                text_color=C["warn"],
            )
        else:
            self.agent_badge.configure(
                text="Kein Schlüssel\nPresets laufen trotzdem",
                text_color=C["text_muted"],
            )

    # ==================================================================
    # Auftrag ausführen
    # ==================================================================
    def start_job(self, options: ScrapeOptions | None = None) -> None:
        if self._thread and self._thread.is_alive():
            Toast.show(self, "Es läuft bereits ein Auftrag.", "warn")
            return

        options = options or self.scrape_view.options()

        if not options.urls:
            Toast.show(self, "Bitte mindestens eine Adresse eintragen.", "warn")
            self.show("scrape")
            return

        if options.mode == "agent":
            if not self.agents_ready():
                Toast.show(self, "Für den Modus 'KI-Agenten' fehlt der Schlüssel.",
                           "error", 5000)
                self.show("settings")
                return
            if not options.instruction.strip():
                Toast.show(self, "Bitte einen Auftrag für das Team formulieren.", "warn")
                return

        # Frischer Zähler und frisches Board je Lauf
        self.rebuild_llm()
        self.team_view.clear()
        self.scrape_view.log.clear()
        self.scrape_view.set_running(True)
        self.scrape_view.update_stats(0, 0, 0, 0.0)
        self._page_count = 0

        name = options.instruction.strip()[:60] or (options.urls[0] if options.urls else "Auftrag")
        self.log(f"Start: {len(options.urls)} Adresse(n), Modus '{options.mode}'.", "info")

        self._orchestrator = Orchestrator(
            llm=self.llm,
            settings=self.settings,
            progress=lambda event, data: self._events.put((event, data)),
        )

        def work() -> None:
            try:
                job = self._orchestrator.run(options, name=name)
                self._events.put(("done", {"job": job}))
            except Exception as exc:
                self._events.put(("crash", {
                    "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(),
                }))

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def stop_job(self) -> None:
        if self._orchestrator and self._thread and self._thread.is_alive():
            self._orchestrator.stop()
            self.log("Abbruch angefordert - laufende Abrufe werden beendet.", "warn")
            self.scrape_view.set_status("Wird abgebrochen ...")

    def test_run(self) -> None:
        """Nur die erste Adresse, eine Seite - zum Ausprobieren."""
        options = self.scrape_view.options()
        if not options.urls:
            Toast.show(self, "Bitte eine Adresse eintragen.", "warn")
            return
        options.urls = options.urls[:1]
        options.follow_links = False
        options.max_pages = 1
        self.log("Testlauf: nur die erste Adresse.", "info")
        self.start_job(options)

    # ==================================================================
    # Ereignisse aus dem Arbeits-Thread
    # ==================================================================
    def _pump(self) -> None:
        """Ereignisse abholen und die Oberfläche nachziehen.

        Läuft im Haupt-Thread; nur hier werden Widgets angefasst.
        """
        try:
            while True:
                event, data = self._events.get_nowait()
                self._handle(event, data)
        except queue.Empty:
            pass
        except Exception as exc:
            self.log(f"Anzeigefehler: {exc}", "error")
        finally:
            self.after(80, self._pump)

    def _handle(self, event: str, data: dict) -> None:
        if event == "log":
            self.log(data.get("text", ""), data.get("level", "info"))

        elif event == "page":
            self._page_count = data.get("done", self._page_count)
            self.scrape_view.set_progress(data.get("done", 0), data.get("total", 1))
            url = data.get("url", "")
            short = url if len(url) <= 62 else url[:59] + "..."
            if data.get("error"):
                self.log(f"Fehler {short}: {data['error']}", "warn")
            else:
                self.log(f"Geladen [{data.get('status')}] {short}", "debug")
            self.scrape_view.set_status(f"{data.get('done', 0)} Seiten geladen ...")

        elif event == "task":
            record = data["record"]
            self.team_view.update_task(record)
            self.team_view.update_usage(self.budget.usage, self.settings.budget_usd)
            self.scrape_view.update_stats(
                self._page_count,
                self.current_job and len(self.current_job.rows) or 0,
                0, self.budget.usage.cost_usd,
            )
            if record.state == "DISPATCHED":
                self.scrape_view.set_status(f"{record.agent}: {record.goal}")

        elif event == "done":
            self._finish(data["job"])

        elif event == "crash":
            self.scrape_view.set_running(False)
            self.scrape_view.set_status("Abgebrochen wegen Fehler.")
            self.log(f"Unerwarteter Fehler: {data['error']}", "error")
            self.log(data.get("trace", ""), "debug")
            Toast.show(self, f"Fehler: {data['error']}", "error", 6000)

    def _finish(self, job: JobResult) -> None:
        self.current_job = job
        self.scrape_view.set_running(False)

        stats = job.summary()
        self.scrape_view.update_stats(
            stats["seiten"], stats["datensaetze"], stats["fehler"], stats["kosten_usd"],
        )
        self.scrape_view.set_progress(1, 1)
        self.team_view.update_usage(job.usage, self.settings.budget_usd)

        if job.cancelled:
            self.scrape_view.set_status("Abgebrochen.")
            self.log("Lauf abgebrochen.", "warn")
        else:
            self.scrape_view.set_status(
                f"Fertig: {stats['datensaetze']} Datensätze aus {stats['seiten']} Seiten "
                f"in {stats['dauer_s']}s."
            )
            self.log(
                f"Fertig. {stats['datensaetze']} Datensätze, {stats['fehler']} Fehler, "
                f"{stats['ki_aufrufe']} KI-Aufrufe, {stats['kosten_usd']:.4f} $.",
                "ok",
            )

        if job.usage.saved_calls:
            self.log(
                f"{job.usage.saved_calls} Modellaufrufe vermieden - Selektoren "
                f"wiederverwendet statt je Seite zu fragen.", "ok",
            )

        self.results_view.set_rows(job.rows, job.summary_text)

        try:
            self.storage.save_job(job)
        except Exception as exc:
            self.log(f"Verlauf nicht gespeichert: {exc}", "warn")

        if self.settings.autosave and job.rows:
            self._autosave(job)

        if job.rows:
            self.show("results")
            Toast.show(self, f"{len(job.rows)} Datensätze gefunden.", "ok")
        elif not job.cancelled:
            Toast.show(self, "Keine Datensätze gefunden - Auftrag oder Selektoren "
                             "anpassen.", "warn", 5000)

    def _autosave(self, job: JobResult) -> None:
        try:
            target = Path(self.settings.export_dir) / exporters.suggest_filename(
                job.name, self.settings.autosave_format
            )
            written = exporters.export(
                job.rows, target, self.settings.autosave_format,
                {"auftrag": job.name, "zusammenfassung": job.summary_text},
            )
            self.log(f"Automatisch gesichert: {written}", "ok")
        except Exception as exc:
            self.log(f"Automatisches Sichern fehlgeschlagen: {exc}", "warn")

    # ==================================================================
    # Verlauf und Vorlagen
    # ==================================================================
    def load_saved_job(self, data: dict) -> None:
        rows = data.get("rows", [])
        self.results_view.set_rows(rows, data.get("summary", ""))

        job = JobResult(
            id=data["id"], name=data["name"],
            options=ScrapeOptions.from_dict(data.get("options", {})),
        )
        job.summary_text = data.get("summary", "")
        usage = data.get("usage") or {}
        job.usage = Usage(**{k: v for k, v in usage.items()
                             if k in Usage.__dataclass_fields__})
        self.current_job = job

        self.show("results")
        Toast.show(self, f"{len(rows)} Datensätze geladen.", "ok")

    def save_template_dialog(self) -> None:
        name = simpledialog.askstring("Vorlage sichern",
                                      "Name der Vorlage:", parent=self)
        if not name or not name.strip():
            return
        options = self.scrape_view.options()
        self.storage.save_template(Template(
            name=name.strip(),
            options=options,
            note=options.instruction[:80] or ", ".join(options.presets),
        ))
        self.history_view.refresh()
        Toast.show(self, f"Vorlage '{name.strip()}' gesichert.", "ok")

    # ==================================================================
    def log(self, message: str, level: str = "info") -> None:
        stamp = time.strftime("%H:%M:%S")
        self.scrape_view.log.add(message, level, stamp)

    def _on_close(self) -> None:
        if self._thread and self._thread.is_alive():
            if not messagebox.askyesno(
                "Beenden", "Es läuft noch ein Auftrag. Wirklich beenden?"
            ):
                return
            self.stop_job()
        try:
            save_settings(self.settings)
            self.storage.close()
        except Exception:
            pass
        self.destroy()


def run() -> None:
    """Einstiegspunkt."""
    ctk.set_default_color_theme("blue")
    app = ScrapeStudio()
    app.mainloop()
