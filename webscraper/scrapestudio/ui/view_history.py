"""Ansicht 'Verlauf': frühere Läufe und gespeicherte Vorlagen."""

from __future__ import annotations

import time
from typing import Any

import customtkinter as ctk
from tkinter import messagebox

from .components import Card, Toast, ghost_button, primary_button
from .theme import C, PAD, PAD_SM, RADIUS_SM, Fonts


def _when(timestamp: float) -> str:
    """Zeitangabe in Worten, für die Liste."""
    if not timestamp:
        return "-"
    delta = time.time() - timestamp
    if delta < 60:
        return "gerade eben"
    if delta < 3600:
        return f"vor {int(delta // 60)} Min."
    if delta < 86400:
        return f"vor {int(delta // 3600)} Std."
    if delta < 604800:
        return f"vor {int(delta // 86400)} Tagen"
    return time.strftime("%d.%m.%Y", time.localtime(timestamp))


class HistoryView(ctk.CTkFrame):
    """Zwei Spalten: links Läufe, rechts Vorlagen."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=3, uniform="cols")
        self.grid_columnconfigure(1, weight=2, uniform="cols")
        self.grid_rowconfigure(0, weight=1)

        # -- Läufe -----------------------------------------------------
        jobs_card = Card(self, "Frühere Läufe",
                         "Anklicken lädt die Ergebnisse zurück in die Tabelle.")
        jobs_card.grid(row=0, column=0, sticky="nsew", padx=(0, PAD_SM))
        jobs_card.grid_rowconfigure(jobs_card.body_row, weight=1)

        self.jobs_list = ctk.CTkScrollableFrame(jobs_card.body, fg_color=C["surface_2"],
                                                corner_radius=RADIUS_SM)
        self.jobs_list.pack(fill="both", expand=True)
        self.jobs_list.grid_columnconfigure(0, weight=1)

        jobs_tools = ctk.CTkFrame(jobs_card.body, fg_color="transparent")
        jobs_tools.pack(fill="x", pady=(PAD_SM, 0))
        ghost_button(jobs_tools, "Aktualisieren", self.refresh, width=110,
                     height=30).pack(side="left")
        ghost_button(jobs_tools, "Verlauf leeren", self._clear_jobs, width=120,
                     height=30).pack(side="left", padx=(6, 0))

        # -- Vorlagen --------------------------------------------------
        tpl_card = Card(self, "Vorlagen",
                        "Fertige Einstellungen für wiederkehrende Aufträge.")
        tpl_card.grid(row=0, column=1, sticky="nsew")
        tpl_card.grid_rowconfigure(tpl_card.body_row, weight=1)

        self.tpl_list = ctk.CTkScrollableFrame(tpl_card.body, fg_color=C["surface_2"],
                                               corner_radius=RADIUS_SM)
        self.tpl_list.pack(fill="both", expand=True)
        self.tpl_list.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            tpl_card.body,
            text="Vorlagen legst du im Reiter 'Auftrag' über 'Als Vorlage' an.",
            font=Fonts.small, text_color=C["text_faint"], anchor="w",
            justify="left", wraplength=300,
        ).pack(fill="x", pady=(PAD_SM, 0))

        self.refresh()

    # ==================================================================
    def refresh(self) -> None:
        self._fill_jobs()
        self._fill_templates()

    # ------------------------------------------------------------------
    def _fill_jobs(self) -> None:
        for child in self.jobs_list.winfo_children():
            child.destroy()

        jobs = self.app.storage.list_jobs(80)
        if not jobs:
            ctk.CTkLabel(self.jobs_list, text="Noch keine Läufe gespeichert.",
                         font=Fonts.body, text_color=C["text_faint"]).grid(
                row=0, column=0, sticky="w", padx=PAD, pady=PAD)
            return

        for index, job in enumerate(jobs):
            row = ctk.CTkFrame(self.jobs_list, fg_color=C["surface"],
                               corner_radius=RADIUS_SM)
            row.grid(row=index, column=0, sticky="ew", padx=PAD_SM, pady=3)
            row.grid_columnconfigure(0, weight=1)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.grid(row=0, column=0, sticky="ew", padx=PAD_SM, pady=PAD_SM)
            info.grid_columnconfigure(0, weight=1)

            name = job["name"] or "(ohne Namen)"
            ctk.CTkLabel(info, text=name[:70], font=Fonts.small_bold,
                         text_color=C["text"], anchor="w").grid(row=0, column=0, sticky="w")

            duration = (job["finished_at"] or 0) - job["started_at"]
            detail = (f"{job['row_count']} Datensätze  ·  {_when(job['started_at'])}"
                      f"  ·  {duration:.1f}s")
            ctk.CTkLabel(info, text=detail, font=Fonts.small,
                         text_color=C["text_muted"], anchor="w").grid(row=1, column=0,
                                                                      sticky="w")

            buttons = ctk.CTkFrame(row, fg_color="transparent")
            buttons.grid(row=0, column=1, padx=(0, PAD_SM))
            ghost_button(buttons, "Laden", lambda j=job["id"]: self._load(j),
                         width=64, height=28).pack(side="left")
            ghost_button(buttons, "Erneut", lambda j=job["id"]: self._rerun(j),
                         width=64, height=28).pack(side="left", padx=(5, 0))
            ghost_button(buttons, "✕", lambda j=job["id"]: self._delete(j),
                         width=30, height=28).pack(side="left", padx=(5, 0))

    def _fill_templates(self) -> None:
        for child in self.tpl_list.winfo_children():
            child.destroy()

        templates = self.app.storage.list_templates()
        if not templates:
            ctk.CTkLabel(self.tpl_list, text="Noch keine Vorlagen.",
                         font=Fonts.body, text_color=C["text_faint"]).grid(
                row=0, column=0, sticky="w", padx=PAD, pady=PAD)
            return

        for index, template in enumerate(templates):
            row = ctk.CTkFrame(self.tpl_list, fg_color=C["surface"],
                               corner_radius=RADIUS_SM)
            row.grid(row=index, column=0, sticky="ew", padx=PAD_SM, pady=3)
            row.grid_columnconfigure(0, weight=1)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.grid(row=0, column=0, sticky="ew", padx=PAD_SM, pady=PAD_SM)
            info.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(info, text=template.name, font=Fonts.small_bold,
                         text_color=C["text"], anchor="w").grid(row=0, column=0, sticky="w")

            urls = ", ".join(template.options.urls[:2]) or "(keine Adresse)"
            detail = template.note or urls
            ctk.CTkLabel(info, text=detail[:60], font=Fonts.small,
                         text_color=C["text_muted"], anchor="w").grid(row=1, column=0,
                                                                      sticky="w")

            buttons = ctk.CTkFrame(row, fg_color="transparent")
            buttons.grid(row=0, column=1, padx=(0, PAD_SM))
            ghost_button(buttons, "Nutzen",
                         lambda t=template: self._use_template(t),
                         width=68, height=28).pack(side="left")
            ghost_button(buttons, "✕", lambda n=template.name: self._delete_template(n),
                         width=30, height=28).pack(side="left", padx=(5, 0))

    # ==================================================================
    def _load(self, job_id: str) -> None:
        data = self.app.storage.load_job(job_id)
        if not data:
            Toast.show(self.app, "Lauf nicht gefunden.", "error")
            return
        self.app.load_saved_job(data)

    def _rerun(self, job_id: str) -> None:
        data = self.app.storage.load_job(job_id)
        if not data:
            Toast.show(self.app, "Lauf nicht gefunden.", "error")
            return
        from ..models import ScrapeOptions
        self.app.scrape_view.load_options(ScrapeOptions.from_dict(data["options"]))
        self.app.show("scrape")
        Toast.show(self.app, "Einstellungen übernommen - Start drücken.", "ok")

    def _delete(self, job_id: str) -> None:
        self.app.storage.delete_job(job_id)
        self.refresh()
        Toast.show(self.app, "Lauf gelöscht.", "ok")

    def _clear_jobs(self) -> None:
        if not messagebox.askyesno("Verlauf leeren",
                                   "Wirklich alle gespeicherten Läufe löschen?"):
            return
        self.app.storage.clear_jobs()
        self.refresh()
        Toast.show(self.app, "Verlauf geleert.", "ok")

    def _use_template(self, template: Any) -> None:
        self.app.scrape_view.load_options(template.options)
        self.app.show("scrape")
        Toast.show(self.app, f"Vorlage '{template.name}' geladen.", "ok")

    def _delete_template(self, name: str) -> None:
        self.app.storage.delete_template(name)
        self.refresh()
        Toast.show(self.app, "Vorlage gelöscht.", "ok")
