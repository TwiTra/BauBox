"""Ansicht 'Auftrag': einrichten, starten, zusehen."""

from __future__ import annotations

from typing import Any, Callable

import customtkinter as ctk

from ..extractors import PRESETS
from ..models import DEFAULT_USER_AGENT, ScrapeOptions
from .components import (
    Card, LogView, StatTile, Toast, divider, ghost_button, labeled, primary_button,
)
from .theme import C, PAD, PAD_SM, RADIUS_SM, Fonts

MODES = ["Presets", "Eigene Selektoren", "KI-Agenten"]
MODE_KEYS = {"Presets": "preset", "Eigene Selektoren": "selectors", "KI-Agenten": "agent"}
KEY_MODES = {v: k for k, v in MODE_KEYS.items()}

BEISPIELE = [
    ("Produkte und Preise", "Alle Produktnamen, Preise und Links zur Detailseite"),
    ("Nachrichten", "Überschrift, Datum, Kurztext und Link jedes Artikels"),
    ("Kontaktdaten", "Firmenname, Adresse, Telefon und E-Mail"),
    ("Stellenanzeigen", "Titel, Ort, Arbeitgeber und Veröffentlichungsdatum"),
    ("Immobilien", "Objekt, Preis, Wohnfläche, Zimmerzahl und Ort"),
]


class ScrapeView(ctk.CTkFrame):
    """Formular für einen Lauf plus Fortschrittsanzeige."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=3, uniform="cols")
        self.grid_columnconfigure(1, weight=2, uniform="cols")
        self.grid_rowconfigure(0, weight=1)

        self._build_left()
        self._build_right()
        self._on_mode_change(KEY_MODES.get(app.settings_mode_default(), "Presets"))

    # ==================================================================
    def _build_left(self) -> None:
        left = ctk.CTkScrollableFrame(self, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, PAD_SM))
        left.grid_columnconfigure(0, weight=1)
        row = 0

        # -- Adressen --------------------------------------------------
        url_card = Card(left, "Adressen", "Eine URL je Zeile. Ohne https:// geht auch.")
        url_card.grid(row=row, column=0, sticky="ew", pady=(0, PAD_SM))
        row += 1
        self.url_box = ctk.CTkTextbox(url_card.body, height=88, font=Fonts.mono,
                                      fg_color=C["surface_2"], corner_radius=RADIUS_SM,
                                      wrap="none")
        self.url_box.pack(fill="x")
        self.url_box.insert("1.0", "")

        url_tools = ctk.CTkFrame(url_card.body, fg_color="transparent")
        url_tools.pack(fill="x", pady=(PAD_SM, 0))
        ghost_button(url_tools, "Aus Zwischenablage", self._paste_urls,
                     width=150).pack(side="left")
        ghost_button(url_tools, "Leeren", lambda: self.url_box.delete("1.0", "end"),
                     width=70).pack(side="left", padx=(6, 0))
        self.url_count = ctk.CTkLabel(url_tools, text="0 Adressen", font=Fonts.small,
                                      text_color=C["text_muted"])
        self.url_count.pack(side="right")
        self.url_box.bind("<KeyRelease>", lambda _e: self._count_urls())

        # -- Was soll gelesen werden -----------------------------------
        mode_card = Card(left, "Was soll gelesen werden?")
        mode_card.grid(row=row, column=0, sticky="ew", pady=(0, PAD_SM))
        row += 1

        self.mode_switch = ctk.CTkSegmentedButton(
            mode_card.body, values=MODES, command=self._on_mode_change,
            font=Fonts.body, selected_color=C["accent"],
            selected_hover_color=C["accent_hover"], unselected_color=C["surface_2"],
            unselected_hover_color=C["surface_3"], corner_radius=RADIUS_SM, height=34,
        )
        self.mode_switch.pack(fill="x")
        self.mode_switch.set("Presets")

        self.mode_hint = ctk.CTkLabel(
            mode_card.body, text="", font=Fonts.small, text_color=C["text_muted"],
            anchor="w", justify="left", wraplength=520,
        )
        self.mode_hint.pack(fill="x", pady=(PAD_SM, 0))

        # Bereich, der je nach Modus wechselt
        self.mode_panel = ctk.CTkFrame(mode_card.body, fg_color="transparent")
        self.mode_panel.pack(fill="x", pady=(PAD_SM, 0))
        self._build_preset_panel()
        self._build_selector_panel()
        self._build_agent_panel()

        # -- Weiterverfolgen -------------------------------------------
        crawl = Card(left, "Links verfolgen", "Aus einer Startseite viele Seiten machen.")
        crawl.grid(row=row, column=0, sticky="ew", pady=(0, PAD_SM))
        row += 1

        self.follow = ctk.CTkSwitch(crawl.body, text="Links auf der Seite verfolgen",
                                    font=Fonts.body, progress_color=C["accent"],
                                    command=self._toggle_crawl)
        self.follow.pack(anchor="w")

        self.crawl_opts = ctk.CTkFrame(crawl.body, fg_color="transparent")
        self.crawl_opts.pack(fill="x", pady=(PAD_SM, 0))
        grid = ctk.CTkFrame(self.crawl_opts, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(grid, text="Tiefe", font=Fonts.small,
                     text_color=C["text_muted"]).grid(row=0, column=0, sticky="w")
        self.depth = ctk.CTkEntry(grid, width=60, font=Fonts.body)
        self.depth.insert(0, "1")
        self.depth.grid(row=0, column=1, sticky="w", padx=(6, PAD))

        ctk.CTkLabel(grid, text="Höchstens Seiten", font=Fonts.small,
                     text_color=C["text_muted"]).grid(row=0, column=2, sticky="w")
        self.max_pages = ctk.CTkEntry(grid, width=70, font=Fonts.body)
        self.max_pages.insert(0, "25")
        self.max_pages.grid(row=0, column=3, sticky="w", padx=(6, 0))

        self.same_domain = ctk.CTkCheckBox(self.crawl_opts, text="Nur dieselbe Domain",
                                           font=Fonts.small, checkbox_width=18,
                                           checkbox_height=18, fg_color=C["accent"])
        self.same_domain.select()
        self.same_domain.pack(anchor="w", pady=(PAD_SM, 0))

        filter_row = ctk.CTkFrame(self.crawl_opts, fg_color="transparent")
        filter_row.pack(fill="x", pady=(PAD_SM, 0))
        ctk.CTkLabel(filter_row, text="URL muss enthalten", font=Fonts.small,
                     text_color=C["text_muted"]).pack(side="left")
        self.url_contains = ctk.CTkEntry(filter_row, font=Fonts.body,
                                         placeholder_text="z. B. /produkt/")
        self.url_contains.pack(side="left", fill="x", expand=True, padx=(6, 0))

        # -- Abruf-Feinheiten ------------------------------------------
        net = Card(left, "Abruf", "Rücksichtsvoll bleiben - langsamer ist sicherer.")
        net.grid(row=row, column=0, sticky="ew", pady=(0, PAD_SM))
        row += 1

        net_grid = ctk.CTkFrame(net.body, fg_color="transparent")
        net_grid.pack(fill="x")
        for index in (1, 3, 5):
            net_grid.grid_columnconfigure(index, weight=1)

        specs = [
            ("Pause (s)", "delay", "0.5", 60),
            ("Zeitlimit (s)", "timeout", "20", 60),
            ("Parallel", "workers", "4", 55),
        ]
        for index, (label, attr, default, width) in enumerate(specs):
            ctk.CTkLabel(net_grid, text=label, font=Fonts.small,
                         text_color=C["text_muted"]).grid(row=0, column=index * 2, sticky="w")
            entry = ctk.CTkEntry(net_grid, width=width, font=Fonts.body)
            entry.insert(0, default)
            entry.grid(row=0, column=index * 2 + 1, sticky="w", padx=(6, PAD))
            setattr(self, attr, entry)

        self.robots = ctk.CTkCheckBox(net.body, text="robots.txt beachten",
                                      font=Fonts.small, checkbox_width=18,
                                      checkbox_height=18, fg_color=C["accent"])
        self.robots.select()
        self.robots.pack(anchor="w", pady=(PAD_SM, 0))

        self.dedupe = ctk.CTkCheckBox(net.body, text="Doppelte Datensätze entfernen",
                                      font=Fonts.small, checkbox_width=18,
                                      checkbox_height=18, fg_color=C["accent"])
        self.dedupe.select()
        self.dedupe.pack(anchor="w", pady=(4, 0))

    # ==================================================================
    def _build_preset_panel(self) -> None:
        self.preset_panel = ctk.CTkFrame(self.mode_panel, fg_color="transparent")
        grid = ctk.CTkFrame(self.preset_panel, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1, 2), weight=1)

        self.preset_vars: dict[str, ctk.CTkCheckBox] = {}
        for index, (key, label) in enumerate(PRESETS.items()):
            box = ctk.CTkCheckBox(grid, text=label, font=Fonts.small,
                                  checkbox_width=17, checkbox_height=17,
                                  fg_color=C["accent"])
            box.grid(row=index // 3, column=index % 3, sticky="w", pady=2, padx=(0, 6))
            self.preset_vars[key] = box
        self.preset_vars["text"].select()

    def _build_selector_panel(self) -> None:
        self.selector_panel = ctk.CTkFrame(self.mode_panel, fg_color="transparent")

        labeled(self.selector_panel, "Container",
                "ein sich wiederholendes Element, leer lassen für die ganze Seite"
                ).pack(fill="x")
        self.container = ctk.CTkEntry(self.selector_panel, font=Fonts.mono,
                                      placeholder_text="z. B. article.produkt")
        self.container.pack(fill="x", pady=(3, PAD_SM))

        labeled(self.selector_panel, "Felder", "je Zeile:  name = css-selektor").pack(fill="x")
        self.selector_box = ctk.CTkTextbox(self.selector_panel, height=110,
                                           font=Fonts.mono, fg_color=C["surface_2"],
                                           corner_radius=RADIUS_SM, wrap="none")
        self.selector_box.pack(fill="x", pady=(3, 0))
        self.selector_box.insert("1.0", "titel = h2.name\npreis = .preis\nlink = a@href")

        ctk.CTkLabel(
            self.selector_panel,
            text="Mit @attribut liest du ein Attribut statt des Textes, z. B. a@href.",
            font=Fonts.small, text_color=C["text_faint"], anchor="w", justify="left",
        ).pack(fill="x", pady=(5, 0))

    def _build_agent_panel(self) -> None:
        self.agent_panel = ctk.CTkFrame(self.mode_panel, fg_color="transparent")

        labeled(self.agent_panel, "Auftrag an das Team",
                "in normalem Deutsch").pack(fill="x")
        self.instruction = ctk.CTkTextbox(self.agent_panel, height=84, font=Fonts.body,
                                          fg_color=C["surface_2"],
                                          corner_radius=RADIUS_SM, wrap="word")
        self.instruction.pack(fill="x", pady=(3, PAD_SM))

        ctk.CTkLabel(self.agent_panel, text="Beispiele zum Übernehmen:",
                     font=Fonts.small, text_color=C["text_muted"],
                     anchor="w").pack(fill="x")
        chips = ctk.CTkFrame(self.agent_panel, fg_color="transparent")
        chips.pack(fill="x", pady=(4, 0))
        for index, (label, text) in enumerate(BEISPIELE):
            ctk.CTkButton(
                chips, text=label, font=Fonts.small, height=26, width=0,
                corner_radius=13, fg_color=C["surface_3"], hover_color=C["accent_soft"],
                text_color=C["text_muted"],
                command=lambda t=text: self._set_instruction(t),
            ).grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 5), pady=2)

        self.agent_note = ctk.CTkLabel(
            self.agent_panel, text="", font=Fonts.small, anchor="w",
            justify="left", wraplength=520,
        )
        self.agent_note.pack(fill="x", pady=(PAD_SM, 0))

    # ==================================================================
    def _build_right(self) -> None:
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)

        # -- Steuerung -------------------------------------------------
        control = Card(right)
        control.grid(row=0, column=0, sticky="ew", pady=(0, PAD_SM))

        self.start_button = primary_button(control.body, "Auftrag starten",
                                           self.app.start_job, height=42)
        self.start_button.pack(fill="x")

        second = ctk.CTkFrame(control.body, fg_color="transparent")
        second.pack(fill="x", pady=(PAD_SM, 0))
        self.stop_button = ghost_button(second, "Abbrechen", self.app.stop_job)
        self.stop_button.pack(side="left", fill="x", expand=True)
        self.stop_button.configure(state="disabled")
        ghost_button(second, "Testlauf", self.app.test_run,
                     width=90).pack(side="left", padx=(6, 0))
        ghost_button(second, "Als Vorlage", self.app.save_template_dialog,
                     width=100).pack(side="left", padx=(6, 0))

        self.progress = ctk.CTkProgressBar(control.body, height=6,
                                           progress_color=C["accent"],
                                           fg_color=C["surface_3"])
        self.progress.pack(fill="x", pady=(PAD_SM, 4))
        self.progress.set(0)

        self.status = ctk.CTkLabel(control.body, text="Bereit.", font=Fonts.small,
                                   text_color=C["text_muted"], anchor="w")
        self.status.pack(fill="x")

        # -- Kennzahlen ------------------------------------------------
        stats = ctk.CTkFrame(right, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", pady=(0, PAD_SM))
        stats.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.tile_pages = StatTile(stats, "Seiten")
        self.tile_pages.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.tile_rows = StatTile(stats, "Datensätze", color=C["accent"])
        self.tile_rows.grid(row=0, column=1, sticky="ew", padx=4)
        self.tile_errors = StatTile(stats, "Fehler")
        self.tile_errors.grid(row=0, column=2, sticky="ew", padx=4)
        self.tile_cost = StatTile(stats, "KI-Kosten", "0,00 $")
        self.tile_cost.grid(row=0, column=3, sticky="ew", padx=(4, 0))

        # -- Protokoll -------------------------------------------------
        log_card = Card(right, "Protokoll")
        log_card.grid(row=2, column=0, sticky="nsew")
        log_card.grid_rowconfigure(log_card.body_row, weight=1)
        self.log = LogView(log_card.body)
        self.log.pack(fill="both", expand=True)

        log_tools = ctk.CTkFrame(log_card.body, fg_color="transparent")
        log_tools.pack(fill="x", pady=(PAD_SM, 0))
        ghost_button(log_tools, "Leeren", self.log.clear, width=70,
                     height=28).pack(side="left")
        ghost_button(log_tools, "Kopieren", self._copy_log, width=80,
                     height=28).pack(side="left", padx=(6, 0))

    # ==================================================================
    # Verhalten
    # ==================================================================
    def _on_mode_change(self, choice: str) -> None:
        for panel in (self.preset_panel, self.selector_panel, self.agent_panel):
            panel.pack_forget()

        key = MODE_KEYS.get(choice, "preset")
        if key == "preset":
            self.preset_panel.pack(fill="x")
            self.mode_hint.configure(
                text="Fertige Bausteine. Schnell, zuverlässig, ohne KI-Kosten.")
        elif key == "selectors":
            self.selector_panel.pack(fill="x")
            self.mode_hint.configure(
                text="Du gibst die CSS-Selektoren vor. Volle Kontrolle, keine KI-Kosten.")
        else:
            self.agent_panel.pack(fill="x")
            self.mode_hint.configure(
                text="Das Team liest eine Beispielseite, leitet daraus Selektoren ab "
                     "und wendet sie auf alle weiteren Seiten an - ohne weitere Kosten.")
            self._refresh_agent_note()

    def _refresh_agent_note(self) -> None:
        if self.app.agents_ready():
            self.agent_note.configure(
                text=f"Bereit. Arbeiter: {self.app.settings.worker_model}  ·  "
                     f"Budget: {self.app.settings.budget_usd:.2f} $ je Lauf.",
                text_color=C["ok"],
            )
        else:
            self.agent_note.configure(
                text="Noch kein API-Schlüssel hinterlegt. Unter Einstellungen eintragen - "
                     "bis dahin laufen Presets und eigene Selektoren ganz normal.",
                text_color=C["warn"],
            )

    def _set_instruction(self, text: str) -> None:
        self.instruction.delete("1.0", "end")
        self.instruction.insert("1.0", text)

    def _paste_urls(self) -> None:
        try:
            content = self.clipboard_get()
        except Exception:
            Toast.show(self.app, "Zwischenablage ist leer.", "warn")
            return
        current = self.url_box.get("1.0", "end").strip()
        self.url_box.delete("1.0", "end")
        self.url_box.insert("1.0", f"{current}\n{content}".strip())
        self._count_urls()

    def _count_urls(self) -> None:
        count = len(self.urls())
        self.url_count.configure(text=f"{count} Adresse{'n' if count != 1 else ''}")

    def _copy_log(self) -> None:
        from .components import copy_to_clipboard
        copy_to_clipboard(self, self.log.text())
        Toast.show(self.app, "Protokoll kopiert.", "ok")

    def _toggle_crawl(self) -> None:
        state = "normal" if self.follow.get() else "disabled"
        for widget in (self.depth, self.max_pages, self.url_contains):
            widget.configure(state=state)
        self.same_domain.configure(state=state)

    # ==================================================================
    # Werte auslesen und setzen
    # ==================================================================
    def urls(self) -> list[str]:
        raw = self.url_box.get("1.0", "end")
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def parse_selectors(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in self.selector_box.get("1.0", "end").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, sep, selector = line.partition("=")
            if sep and name.strip() and selector.strip():
                out[name.strip()] = selector.strip()
        return out

    @staticmethod
    def _number(widget: Any, default: float, cast: type = int) -> Any:
        try:
            return cast(str(widget.get()).replace(",", ".").strip())
        except (ValueError, AttributeError):
            return cast(default)

    def options(self) -> ScrapeOptions:
        """Formular in ein Optionen-Objekt übersetzen."""
        mode = MODE_KEYS.get(self.mode_switch.get(), "preset")
        selectors = self.parse_selectors() if mode == "selectors" else {}
        presets = [k for k, box in self.preset_vars.items() if box.get()] or ["text"]

        return ScrapeOptions(
            urls=self.urls(),
            mode=mode,
            presets=presets,
            selectors=selectors,
            instruction=self.instruction.get("1.0", "end").strip(),
            follow_links=bool(self.follow.get()),
            max_depth=max(1, self._number(self.depth, 1)),
            max_pages=max(1, self._number(self.max_pages, 25)),
            same_domain_only=bool(self.same_domain.get()),
            url_contains=self.url_contains.get().strip(),
            delay=max(0.0, self._number(self.delay, 0.5, float)),
            timeout=max(3, self._number(self.timeout, 20)),
            workers=max(1, min(16, self._number(self.workers, 4))),
            retries=2,
            user_agent=DEFAULT_USER_AGENT,
            respect_robots=bool(self.robots.get()),
            dedupe=bool(self.dedupe.get()),
        )

    def load_options(self, options: ScrapeOptions) -> None:
        """Vorlage oder alten Auftrag ins Formular zurückschreiben."""
        self.url_box.delete("1.0", "end")
        self.url_box.insert("1.0", "\n".join(options.urls))
        self._count_urls()

        self.mode_switch.set(KEY_MODES.get(options.mode, "Presets"))
        self._on_mode_change(KEY_MODES.get(options.mode, "Presets"))

        for key, box in self.preset_vars.items():
            box.select() if key in options.presets else box.deselect()

        if options.selectors:
            self.selector_box.delete("1.0", "end")
            self.selector_box.insert(
                "1.0", "\n".join(f"{k} = {v}" for k, v in options.selectors.items())
            )
        self._set_instruction(options.instruction)

        self.follow.select() if options.follow_links else self.follow.deselect()
        self._toggle_crawl()
        for widget, value in (
            (self.depth, options.max_depth), (self.max_pages, options.max_pages),
            (self.delay, options.delay), (self.timeout, options.timeout),
            (self.workers, options.workers),
        ):
            widget.configure(state="normal")
            widget.delete(0, "end")
            widget.insert(0, str(value))
        self.url_contains.delete(0, "end")
        self.url_contains.insert(0, options.url_contains)

        self.same_domain.select() if options.same_domain_only else self.same_domain.deselect()
        self.robots.select() if options.respect_robots else self.robots.deselect()
        self.dedupe.select() if options.dedupe else self.dedupe.deselect()
        self._toggle_crawl()

    # ==================================================================
    def set_running(self, running: bool) -> None:
        self.start_button.configure(
            state="disabled" if running else "normal",
            text="Läuft ..." if running else "Auftrag starten",
        )
        self.stop_button.configure(state="normal" if running else "disabled")
        if running:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(min(1.0, done / total))

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def update_stats(self, pages: int, rows: int, errors: int, cost: float) -> None:
        self.tile_pages.set(str(pages))
        self.tile_rows.set(str(rows))
        self.tile_errors.set(str(errors),
                             C["error"] if errors else C["text"])
        self.tile_cost.set(f"{cost:.2f} $".replace(".", ","),
                           C["warn"] if cost > 0.5 else C["text"])
