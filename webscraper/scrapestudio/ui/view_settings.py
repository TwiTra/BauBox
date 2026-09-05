"""Ansicht 'Einstellungen': Schlüssel, Modelle, Budget, Sparmassnahmen."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk
from tkinter import filedialog

from ..config import (
    APP_DIR, MODEL_PRICES, TIER_LABELS, load_api_key, mask_key, save_api_key,
    save_settings,
)
from .components import Card, Toast, ghost_button, labeled, primary_button
from .theme import C, PAD, PAD_SM, RADIUS_SM, Fonts, apply_mode

MODELLE = list(MODEL_PRICES)


class SettingsView(ctk.CTkScrollableFrame):
    """Alles Einstellbare an einer Stelle."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        row = 0

        # ==============================================================
        # Zugang
        # ==============================================================
        key_card = Card(self, "Zugang zum Agenten-Team",
                        "Ohne Schlüssel laufen Presets und eigene Selektoren "
                        "weiterhin uneingeschränkt.")
        key_card.grid(row=row, column=0, sticky="ew", pady=(0, PAD_SM))
        row += 1

        labeled(key_card.body, "Anthropic API-Schlüssel",
                "wird lokal gespeichert, nie exportiert").pack(fill="x")
        entry_row = ctk.CTkFrame(key_card.body, fg_color="transparent")
        entry_row.pack(fill="x", pady=(3, 0))

        self.key_entry = ctk.CTkEntry(entry_row, show="•", font=Fonts.mono,
                                      placeholder_text="sk-ant-...")
        self.key_entry.pack(side="left", fill="x", expand=True)
        self.show_key = ctk.CTkButton(
            entry_row, text="Zeigen", width=70, height=28, font=Fonts.small,
            fg_color=C["surface_3"], hover_color=C["accent"], text_color=C["text"],
            command=self._toggle_key,
        )
        self.show_key.pack(side="left", padx=(6, 0))
        ghost_button(entry_row, "Sichern", self._save_key, width=80,
                     height=28).pack(side="left", padx=(6, 0))

        self.key_status = ctk.CTkLabel(key_card.body, text="", font=Fonts.small,
                                       anchor="w")
        self.key_status.pack(fill="x", pady=(6, 0))

        ctk.CTkLabel(
            key_card.body,
            text="Schlüssel gibt es unter console.anthropic.com. Alternativ die "
                 "Umgebungsvariable ANTHROPIC_API_KEY setzen - die hat Vorrang.",
            font=Fonts.small, text_color=C["text_faint"], anchor="w",
            justify="left", wraplength=620,
        ).pack(fill="x", pady=(4, 0))

        # ==============================================================
        # Modell-Ebenen
        # ==============================================================
        tier_card = Card(self, "Modell-Ebenen",
                         "Die Fleissarbeit gehört auf das günstigste Modell.")
        tier_card.grid(row=row, column=0, sticky="ew", pady=(0, PAD_SM))
        row += 1

        self.tier_menus: dict[str, ctk.CTkOptionMenu] = {}
        for tier in ("worker", "verifier", "advisor"):
            block = ctk.CTkFrame(tier_card.body, fg_color="transparent")
            block.pack(fill="x", pady=(0, PAD_SM))
            block.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(block, text=TIER_LABELS[tier], font=Fonts.small_bold,
                         text_color=C["text"], anchor="w").grid(row=0, column=0, sticky="w")

            menu = ctk.CTkOptionMenu(
                block, values=MODELLE, font=Fonts.small, width=230, height=30,
                fg_color=C["surface_2"], button_color=C["surface_3"],
                button_hover_color=C["accent"], text_color=C["text"],
                corner_radius=RADIUS_SM,
                command=lambda _v, t=tier: self._on_tier_change(t),
            )
            menu.grid(row=0, column=1, rowspan=2, padx=(PAD, 0))
            self.tier_menus[tier] = menu

            price = ctk.CTkLabel(block, text="", font=Fonts.small,
                                 text_color=C["text_muted"], anchor="w")
            price.grid(row=1, column=0, sticky="w")
            setattr(self, f"price_{tier}", price)

        # ==============================================================
        # Kostenbremse
        # ==============================================================
        budget_card = Card(self, "Kostenbremse", "Gilt je Lauf.")
        budget_card.grid(row=row, column=0, sticky="ew", pady=(0, PAD_SM))
        row += 1

        grid = ctk.CTkFrame(budget_card.body, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(grid, text="Höchstbetrag (USD)", font=Fonts.small,
                     text_color=C["text_muted"]).grid(row=0, column=0, sticky="w")
        self.budget_usd = ctk.CTkEntry(grid, width=90, font=Fonts.body)
        self.budget_usd.grid(row=0, column=1, sticky="w", padx=(6, PAD))

        ctk.CTkLabel(grid, text="Höchstzahl Aufrufe", font=Fonts.small,
                     text_color=C["text_muted"]).grid(row=0, column=2, sticky="w")
        self.budget_calls = ctk.CTkEntry(grid, width=90, font=Fonts.body)
        self.budget_calls.grid(row=0, column=3, sticky="w", padx=(6, 0))

        self.stop_on_budget = ctk.CTkCheckBox(
            budget_card.body, text="Bei Erreichen abbrechen (statt weiterzulaufen)",
            font=Fonts.small, checkbox_width=18, checkbox_height=18, fg_color=C["accent"],
        )
        self.stop_on_budget.pack(anchor="w", pady=(PAD_SM, 0))

        # ==============================================================
        # Sparmassnahmen
        # ==============================================================
        save_card = Card(self, "Token sparen",
                         "Alle drei sind an - Abschalten kostet spürbar mehr.")
        save_card.grid(row=row, column=0, sticky="ew", pady=(0, PAD_SM))
        row += 1

        self.reuse_selectors = ctk.CTkCheckBox(
            save_card.body,
            text="Selektoren einmal lernen und wiederverwenden (grösster Hebel)",
            font=Fonts.small, checkbox_width=18, checkbox_height=18, fg_color=C["accent"],
        )
        self.reuse_selectors.pack(anchor="w")

        self.compress = ctk.CTkCheckBox(
            save_card.body, text="HTML vor dem Senden eindampfen",
            font=Fonts.small, checkbox_width=18, checkbox_height=18, fg_color=C["accent"],
        )
        self.compress.pack(anchor="w", pady=(5, 0))

        self.use_cache = ctk.CTkCheckBox(
            save_card.body, text="Antworten zwischenspeichern",
            font=Fonts.small, checkbox_width=18, checkbox_height=18, fg_color=C["accent"],
        )
        self.use_cache.pack(anchor="w", pady=(5, 0))

        chars_row = ctk.CTkFrame(save_card.body, fg_color="transparent")
        chars_row.pack(fill="x", pady=(PAD_SM, 0))
        ctk.CTkLabel(chars_row, text="Zeichen je Seite ans Modell", font=Fonts.small,
                     text_color=C["text_muted"]).pack(side="left")
        self.max_chars = ctk.CTkEntry(chars_row, width=90, font=Fonts.body)
        self.max_chars.pack(side="left", padx=(6, 0))

        cache_row = ctk.CTkFrame(save_card.body, fg_color="transparent")
        cache_row.pack(fill="x", pady=(PAD_SM, 0))
        self.cache_info = ctk.CTkLabel(cache_row, text="", font=Fonts.small,
                                       text_color=C["text_muted"])
        self.cache_info.pack(side="left")
        ghost_button(cache_row, "Cache leeren", self._clear_cache, width=110,
                     height=28).pack(side="right")

        # ==============================================================
        # Darstellung und Ablage
        # ==============================================================
        look_card = Card(self, "Darstellung und Ablage")
        look_card.grid(row=row, column=0, sticky="ew", pady=(0, PAD_SM))
        row += 1

        theme_row = ctk.CTkFrame(look_card.body, fg_color="transparent")
        theme_row.pack(fill="x")
        ctk.CTkLabel(theme_row, text="Erscheinungsbild", font=Fonts.small,
                     text_color=C["text_muted"]).pack(side="left")
        self.theme_switch = ctk.CTkSegmentedButton(
            theme_row, values=["Dunkel", "Hell", "System"], command=self._on_theme,
            font=Fonts.small, selected_color=C["accent"],
            selected_hover_color=C["accent_hover"], unselected_color=C["surface_2"],
            corner_radius=RADIUS_SM, height=30,
        )
        self.theme_switch.pack(side="left", padx=(PAD, 0))

        dir_row = ctk.CTkFrame(look_card.body, fg_color="transparent")
        dir_row.pack(fill="x", pady=(PAD_SM, 0))
        ctk.CTkLabel(dir_row, text="Export-Ordner", font=Fonts.small,
                     text_color=C["text_muted"]).pack(side="left")
        self.export_dir = ctk.CTkEntry(dir_row, font=Fonts.small)
        self.export_dir.pack(side="left", fill="x", expand=True, padx=(6, 6))
        ghost_button(dir_row, "Wählen", self._choose_dir, width=80,
                     height=28).pack(side="left")

        self.autosave = ctk.CTkCheckBox(
            look_card.body,
            text="Nach jedem Lauf automatisch in den Export-Ordner sichern",
            font=Fonts.small, checkbox_width=18, checkbox_height=18, fg_color=C["accent"],
        )
        self.autosave.pack(anchor="w", pady=(PAD_SM, 0))

        ctk.CTkLabel(
            look_card.body, text=f"Alle Daten liegen in: {APP_DIR}",
            font=Fonts.small, text_color=C["text_faint"], anchor="w",
        ).pack(fill="x", pady=(PAD_SM, 0))

        # ==============================================================
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=row, column=0, sticky="ew", pady=(PAD_SM, PAD))
        primary_button(actions, "Einstellungen sichern", self._save).pack(side="left")
        ghost_button(actions, "Zurücksetzen", self._reset,
                     width=130).pack(side="left", padx=(PAD_SM, 0))

        self.load()

    # ==================================================================
    def load(self) -> None:
        """Werte aus den Einstellungen ins Formular."""
        settings = self.app.settings

        key = load_api_key()
        self.key_entry.delete(0, "end")
        if key:
            self.key_entry.insert(0, key)
        self._refresh_key_status()

        for tier in ("worker", "verifier", "advisor"):
            model = getattr(settings, f"{tier}_model")
            self.tier_menus[tier].set(model if model in MODELLE else MODELLE[0])
            self._on_tier_change(tier, save=False)

        self.budget_usd.delete(0, "end")
        self.budget_usd.insert(0, f"{settings.budget_usd:.2f}")
        self.budget_calls.delete(0, "end")
        self.budget_calls.insert(0, str(settings.budget_calls))
        self.stop_on_budget.select() if settings.stop_on_budget else self.stop_on_budget.deselect()

        for widget, value in (
            (self.reuse_selectors, settings.reuse_selectors),
            (self.compress, settings.compress_html),
            (self.use_cache, settings.use_cache),
            (self.autosave, settings.autosave),
        ):
            widget.select() if value else widget.deselect()

        self.max_chars.delete(0, "end")
        self.max_chars.insert(0, str(settings.max_chars_per_page))

        self.theme_switch.set(
            {"dark": "Dunkel", "light": "Hell"}.get(settings.theme, "System")
        )
        self.export_dir.delete(0, "end")
        self.export_dir.insert(0, settings.export_dir)
        self._refresh_cache_info()

    # ==================================================================
    def _toggle_key(self) -> None:
        hidden = self.key_entry.cget("show") == "•"
        self.key_entry.configure(show="" if hidden else "•")
        self.show_key.configure(text="Verbergen" if hidden else "Zeigen")

    def _save_key(self) -> None:
        key = self.key_entry.get().strip()
        save_api_key(key)
        self.app.rebuild_llm()
        self._refresh_key_status()
        self.app.scrape_view._refresh_agent_note()
        Toast.show(self.app, "Schlüssel gesichert." if key else "Schlüssel entfernt.", "ok")

    def _refresh_key_status(self) -> None:
        key = load_api_key()
        from ..agents.base import LLMClient

        if not LLMClient.library_available():
            self.key_status.configure(
                text="Paket 'anthropic' fehlt - installieren mit: pip install anthropic",
                text_color=C["warn"],
            )
        elif key:
            self.key_status.configure(text=f"Aktiv: {mask_key(key)}", text_color=C["ok"])
        else:
            self.key_status.configure(
                text="Kein Schlüssel - Modus 'KI-Agenten' ist deaktiviert.",
                text_color=C["text_muted"],
            )

    def _on_tier_change(self, tier: str, save: bool = True) -> None:
        model = self.tier_menus[tier].get()
        pin, pout = MODEL_PRICES.get(model, (0, 0))
        getattr(self, f"price_{tier}").configure(
            text=f"{pin:.2f} $ je Mio. Eingabe-Token  ·  {pout:.2f} $ je Mio. Ausgabe"
        )

    def _on_theme(self, choice: str) -> None:
        theme = {"Dunkel": "dark", "Hell": "light"}.get(choice, "system")
        self.app.settings.theme = theme
        apply_mode(theme)
        save_settings(self.app.settings)

    def _choose_dir(self) -> None:
        path = filedialog.askdirectory(title="Export-Ordner wählen",
                                       initialdir=self.export_dir.get())
        if path:
            self.export_dir.delete(0, "end")
            self.export_dir.insert(0, path)

    def _clear_cache(self) -> None:
        count = self.app.storage.clear_cache()
        self._refresh_cache_info()
        Toast.show(self.app, f"{count} Cache-Einträge gelöscht.", "ok")

    def _refresh_cache_info(self) -> None:
        stats = self.app.storage.cache_stats()
        size_kb = stats["zeichen"] / 1024
        self.cache_info.configure(
            text=f"Cache: {stats['eintraege']} Einträge ({size_kb:.0f} KB)"
        )

    # ==================================================================
    @staticmethod
    def _num(widget: Any, default: Any, cast: type) -> Any:
        try:
            return cast(str(widget.get()).replace(",", ".").strip())
        except (ValueError, TypeError):
            return default

    def _save(self) -> None:
        settings = self.app.settings

        for tier in ("worker", "verifier", "advisor"):
            setattr(settings, f"{tier}_model", self.tier_menus[tier].get())

        settings.budget_usd = max(0.0, self._num(self.budget_usd, 1.0, float))
        settings.budget_calls = max(1, self._num(self.budget_calls, 60, int))
        settings.stop_on_budget = bool(self.stop_on_budget.get())

        settings.reuse_selectors = bool(self.reuse_selectors.get())
        settings.compress_html = bool(self.compress.get())
        settings.use_cache = bool(self.use_cache.get())
        settings.max_chars_per_page = max(2000, self._num(self.max_chars, 12000, int))

        settings.export_dir = self.export_dir.get().strip() or settings.export_dir
        settings.autosave = bool(self.autosave.get())

        save_settings(settings)
        self.app.rebuild_llm()
        self.app.team_view.refresh_roster()
        Toast.show(self.app, "Einstellungen gesichert.", "ok")

    def _reset(self) -> None:
        from ..config import Settings

        theme = self.app.settings.theme
        self.app.settings = Settings()
        self.app.settings.theme = theme
        save_settings(self.app.settings)
        self.load()
        self.app.rebuild_llm()
        Toast.show(self.app, "Auf Standardwerte zurückgesetzt.", "ok")
