"""Ansicht 'Ergebnisse': ansehen, filtern, sichern."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import customtkinter as ctk
from tkinter import filedialog

from .. import exporters
from ..extractors import all_columns
from .components import (
    Card, DataTable, StatTile, Toast, copy_to_clipboard, ghost_button, primary_button,
)
from .theme import C, PAD, PAD_SM, RADIUS_SM, Fonts


class ResultsView(ctk.CTkFrame):
    """Tabelle links, Detail und Export rechts."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=3, uniform="cols")
        self.grid_columnconfigure(1, weight=1, uniform="cols")
        self.grid_rowconfigure(1, weight=1)

        self._build_toolbar()
        self._build_table()
        self._build_side()

    # ==================================================================
    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=RADIUS_SM,
                           border_width=1, border_color=C["border"])
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, PAD_SM))

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=PAD_SM, pady=PAD_SM)

        self.search = ctk.CTkEntry(inner, placeholder_text="Suchen ... (Strg+F)",
                                   font=Fonts.body, height=32, width=260)
        self.search.pack(side="left")
        self.search.bind("<KeyRelease>", self._on_search)

        ghost_button(inner, "Filter weg", self._clear_search, width=90,
                     height=32).pack(side="left", padx=(6, 0))
        ghost_button(inner, "Auswahl löschen", self._delete_selected, width=120,
                     height=32).pack(side="left", padx=(6, 0))
        ghost_button(inner, "Alles wählen", lambda: self.table.select_all(),
                     width=100, height=32).pack(side="left", padx=(6, 0))

        self.counter = ctk.CTkLabel(inner, text="0 Datensätze", font=Fonts.small,
                                    text_color=C["text_muted"])
        self.counter.pack(side="right")

    def _build_table(self) -> None:
        wrapper = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=RADIUS_SM,
                               border_width=1, border_color=C["border"])
        wrapper.grid(row=1, column=0, sticky="nsew", padx=(0, PAD_SM))
        wrapper.grid_rowconfigure(0, weight=1)
        wrapper.grid_columnconfigure(0, weight=1)

        self.table = DataTable(wrapper, on_select=self._show_detail,
                               fg_color="transparent")
        self.table.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

    # ==================================================================
    def _build_side(self) -> None:
        side = ctk.CTkFrame(self, fg_color="transparent")
        side.grid(row=1, column=1, sticky="nsew")
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(2, weight=1)

        # -- Zusammenfassung des Teams ---------------------------------
        self.summary_card = Card(side, "Zusammenfassung des Teams")
        self.summary_card.grid(row=0, column=0, sticky="ew", pady=(0, PAD_SM))
        self.summary_box = ctk.CTkTextbox(self.summary_card.body, height=110,
                                          font=Fonts.body, wrap="word",
                                          fg_color=C["surface_2"],
                                          corner_radius=RADIUS_SM)
        self.summary_box.pack(fill="x")
        self.summary_box.insert("1.0", "Noch kein Lauf.")
        self.summary_box.configure(state="disabled")

        # -- Export ----------------------------------------------------
        export_card = Card(side, "Sichern")
        export_card.grid(row=1, column=0, sticky="ew", pady=(0, PAD_SM))

        self.format_menu = ctk.CTkOptionMenu(
            export_card.body,
            values=[f"{f.label}  ({f.suffix})" for f in exporters.FORMATS],
            font=Fonts.body, fg_color=C["surface_2"], button_color=C["surface_3"],
            button_hover_color=C["accent"], text_color=C["text"],
            corner_radius=RADIUS_SM, height=34, command=self._on_format_change,
        )
        self.format_menu.pack(fill="x")
        self.format_menu.set(f"{exporters.FORMATS[0].label}  ({exporters.FORMATS[0].suffix})")

        self.format_hint = ctk.CTkLabel(
            export_card.body, text=exporters.FORMATS[0].description,
            font=Fonts.small, text_color=C["text_muted"], anchor="w",
            justify="left", wraplength=250,
        )
        self.format_hint.pack(fill="x", pady=(5, PAD_SM))

        primary_button(export_card.body, "Speichern unter ...",
                       self._export_as).pack(fill="x")

        quick = ctk.CTkFrame(export_card.body, fg_color="transparent")
        quick.pack(fill="x", pady=(6, 0))
        ghost_button(quick, "Schnellablage", self._quick_export,
                     height=30).pack(side="left", fill="x", expand=True)
        ghost_button(quick, "Ordner", self._open_export_dir, width=70,
                     height=30).pack(side="left", padx=(6, 0))

        clip = ctk.CTkFrame(export_card.body, fg_color="transparent")
        clip.pack(fill="x", pady=(6, 0))
        ghost_button(clip, "Tabelle kopieren", self._copy_table,
                     height=30).pack(side="left", fill="x", expand=True)
        ghost_button(clip, "JSON kopieren", self._copy_json,
                     height=30).pack(side="left", fill="x", expand=True, padx=(6, 0))

        ctk.CTkLabel(
            export_card.body,
            text="Gesichert wird immer, was gerade sichtbar ist - Filter wirken mit.",
            font=Fonts.small, text_color=C["text_faint"], anchor="w",
            justify="left", wraplength=250,
        ).pack(fill="x", pady=(PAD_SM, 0))

        # -- Detail ----------------------------------------------------
        detail_card = Card(side, "Datensatz")
        detail_card.grid(row=2, column=0, sticky="nsew")
        detail_card.grid_rowconfigure(detail_card.body_row, weight=1)
        self.detail = ctk.CTkTextbox(detail_card.body, font=Fonts.mono_sm, wrap="word",
                                     fg_color=C["surface_2"], corner_radius=RADIUS_SM)
        self.detail.pack(fill="both", expand=True)
        self.detail.insert("1.0", "Zeile anklicken, um Einzelheiten zu sehen.")
        self.detail.configure(state="disabled")

        ghost_button(detail_card.body, "Datensatz kopieren", self._copy_detail,
                     height=28).pack(fill="x", pady=(PAD_SM, 0))

    # ==================================================================
    # Verhalten
    # ==================================================================
    def set_rows(self, rows: list[dict[str, Any]], summary: str = "") -> None:
        self.table.set_rows(rows)
        self._update_counter()

        self.summary_box.configure(state="normal")
        self.summary_box.delete("1.0", "end")
        self.summary_box.insert("1.0", summary or "Für diesen Lauf gibt es keine "
                                                 "Zusammenfassung (nur im Modus KI-Agenten).")
        self.summary_box.configure(state="disabled")

    def _on_search(self, _event: Any = None) -> None:
        self.table.set_filter(self.search.get())
        self._update_counter()

    def _clear_search(self) -> None:
        self.search.delete(0, "end")
        self.table.set_filter("")
        self._update_counter()

    def _update_counter(self) -> None:
        shown, total = self.table.count, self.table.total
        text = f"{shown} von {total} Datensätzen" if shown != total else f"{total} Datensätze"
        self.counter.configure(text=text)

    def _delete_selected(self) -> None:
        removed = self.table.remove_selected()
        if removed:
            self._update_counter()
            Toast.show(self.app, f"{removed} Zeile(n) entfernt.", "ok")
        else:
            Toast.show(self.app, "Nichts ausgewählt.", "warn")

    def _show_detail(self, row: dict[str, Any]) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        width = max((len(k) for k in row), default=0)
        lines = [f"{key.ljust(width)} : {value}" for key, value in row.items()]
        self.detail.insert("1.0", "\n".join(lines))
        self.detail.configure(state="disabled")

    def _on_format_change(self, _choice: str) -> None:
        fmt = self._current_format()
        note = fmt.description
        if not exporters.available(fmt):
            note = f"Paket '{fmt.needs}' fehlt - installieren mit: pip install {fmt.needs}"
        self.format_hint.configure(
            text=note,
            text_color=C["warn"] if not exporters.available(fmt) else C["text_muted"],
        )

    def _current_format(self) -> exporters.Format:
        label = self.format_menu.get().split("  (")[0]
        for fmt in exporters.FORMATS:
            if fmt.label == label:
                return fmt
        return exporters.FORMATS[0]

    # ==================================================================
    def _rows_to_export(self) -> list[dict[str, Any]]:
        return self.table.visible_rows()

    def _meta(self) -> dict[str, Any]:
        job = self.app.current_job
        meta: dict[str, Any] = {"erzeugt_mit": "ScrapeStudio"}
        if job:
            meta.update({
                "auftrag": job.name,
                "adressen": ", ".join(job.options.urls[:5]),
                "modus": job.options.mode,
                "anweisung": job.options.instruction,
                "zusammenfassung": job.summary_text,
                **{f"kennzahl_{k}": v for k, v in job.summary().items()},
            })
        return meta

    def _export_as(self) -> None:
        rows = self._rows_to_export()
        if not rows:
            Toast.show(self.app, "Keine Daten zum Sichern.", "warn")
            return

        fmt = self._current_format()
        if not exporters.available(fmt):
            Toast.show(self.app, f"Paket '{fmt.needs}' fehlt. "
                                 f"pip install {fmt.needs}", "error", 6000)
            return

        name = self.app.current_job.name if self.app.current_job else "export"
        path = filedialog.asksaveasfilename(
            title="Ergebnisse sichern",
            defaultextension=fmt.suffix,
            initialfile=exporters.suggest_filename(name, fmt.key),
            initialdir=self.app.settings.export_dir,
            filetypes=[(fmt.label, f"*{fmt.suffix}"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return
        self._write(rows, path, fmt)

    def _quick_export(self) -> None:
        """Ohne Dialog in den Export-Ordner schreiben."""
        rows = self._rows_to_export()
        if not rows:
            Toast.show(self.app, "Keine Daten zum Sichern.", "warn")
            return
        fmt = self._current_format()
        if not exporters.available(fmt):
            Toast.show(self.app, f"Paket '{fmt.needs}' fehlt.", "error")
            return
        name = self.app.current_job.name if self.app.current_job else "export"
        target = Path(self.app.settings.export_dir) / exporters.suggest_filename(name, fmt.key)
        self._write(rows, target, fmt)

    def _write(self, rows: list[dict], path: Any, fmt: exporters.Format) -> None:
        try:
            written = exporters.export(rows, path, fmt.key, self._meta())
        except Exception as exc:
            Toast.show(self.app, f"Fehler beim Sichern: {exc}", "error", 6000)
            self.app.log(f"Export fehlgeschlagen: {exc}", "error")
            return
        Toast.show(self.app, f"{len(rows)} Datensätze -> {written.name}", "ok", 4200)
        self.app.log(f"Gesichert: {written}", "ok")

    def _open_export_dir(self) -> None:
        path = Path(self.app.settings.export_dir)
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            Toast.show(self.app, f"Ordner nicht zu öffnen: {exc}", "warn")

    def _copy_table(self) -> None:
        rows = self._rows_to_export()
        if not rows:
            Toast.show(self.app, "Keine Daten.", "warn")
            return
        copy_to_clipboard(self, exporters.to_clipboard_text(rows))
        Toast.show(self.app, f"{len(rows)} Zeilen kopiert - direkt in Excel einfügbar.",
                   "ok")

    def _copy_json(self) -> None:
        rows = self._rows_to_export()
        if not rows:
            Toast.show(self.app, "Keine Daten.", "warn")
            return
        copy_to_clipboard(self, json.dumps(rows, ensure_ascii=False, indent=2))
        Toast.show(self.app, f"{len(rows)} Datensätze als JSON kopiert.", "ok")

    def _copy_detail(self) -> None:
        text = self.detail.get("1.0", "end").strip()
        if not text:
            return
        copy_to_clipboard(self, text)
        Toast.show(self.app, "Datensatz kopiert.", "ok")

    def focus_search(self) -> None:
        self.search.focus_set()
