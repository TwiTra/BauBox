"""Ansicht 'Team': wer arbeitet gerade, was kostet es, was wurde gespart."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from ..config import TIER_LABELS, cost_of
from ..models import TaskRecord
from .components import Card, StatTile, ghost_button
from .theme import C, PAD, PAD_SM, RADIUS_SM, STATE_COLORS, Fonts

ROLLEN = [
    ("Sammler", "regelbasiert", "Holt die Seiten. Kostet nichts."),
    ("Selektor-Sucher", "worker",
     "Sieht EINE Beispielseite und leitet die CSS-Selektoren ab."),
    ("Anwender", "regelbasiert",
     "Wendet die gelernten Selektoren auf alle weiteren Seiten an. Kostet nichts."),
    ("Prüfer", "verifier", "Kontrolliert eine Stichprobe und sagt PASS oder FIX."),
    ("Direkt-Leser", "worker", "Rückfall: liest einzelne Seiten selbst, wenn nötig."),
    ("Zusammenfasser", "worker", "Verdichtet das Ergebnis zu einer Antwort."),
    ("Berater", "advisor", "Wird nur gerufen, wenn nichts anderes greift."),
]


class TeamView(ctk.CTkFrame):
    """Status-Board des Agenten-Teams plus Kostenrechnung."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=2, uniform="cols")
        self.grid_columnconfigure(1, weight=1, uniform="cols")
        self.grid_rowconfigure(1, weight=1)

        self._rows: dict[str, ctk.CTkFrame] = {}
        self._build_stats()
        self._build_board()
        self._build_side()

    # ==================================================================
    def _build_stats(self) -> None:
        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, PAD_SM))
        stats.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.tile_calls = StatTile(stats, "KI-Aufrufe")
        self.tile_calls.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.tile_saved = StatTile(stats, "Aufrufe gespart", color=C["ok"])
        self.tile_saved.grid(row=0, column=1, sticky="ew", padx=4)
        self.tile_tokens = StatTile(stats, "Token")
        self.tile_tokens.grid(row=0, column=2, sticky="ew", padx=4)
        self.tile_cost = StatTile(stats, "Kosten", "0,0000 $")
        self.tile_cost.grid(row=0, column=3, sticky="ew", padx=4)
        self.tile_budget = StatTile(stats, "Budget frei", "-", color=C["ok"])
        self.tile_budget.grid(row=0, column=4, sticky="ew", padx=(4, 0))

    def _build_board(self) -> None:
        card = Card(self, "Status-Board",
                    "Jede Teilaufgabe mit Zustand, Modell und Wiederholungen.")
        card.grid(row=1, column=0, sticky="nsew", padx=(0, PAD_SM))
        card.grid_rowconfigure(card.body_row, weight=1)

        self.board = ctk.CTkScrollableFrame(card.body, fg_color=C["surface_2"],
                                            corner_radius=RADIUS_SM)
        self.board.pack(fill="both", expand=True)
        self.board.grid_columnconfigure(0, weight=1)

        self.empty_hint = ctk.CTkLabel(
            self.board,
            text="Noch nichts gelaufen.\n\nStarte einen Auftrag im Modus "
                 "'KI-Agenten', dann siehst du hier jede Teilaufgabe.",
            font=Fonts.body, text_color=C["text_faint"], justify="left",
        )
        self.empty_hint.grid(row=0, column=0, sticky="w", padx=PAD, pady=PAD)

        tools = ctk.CTkFrame(card.body, fg_color="transparent")
        tools.pack(fill="x", pady=(PAD_SM, 0))
        ghost_button(tools, "Board leeren", self.clear, width=100,
                     height=28).pack(side="left")

    # ==================================================================
    def _build_side(self) -> None:
        side = ctk.CTkScrollableFrame(self, fg_color="transparent")
        side.grid(row=1, column=1, sticky="nsew")
        side.grid_columnconfigure(0, weight=1)

        # -- So spart das Team -----------------------------------------
        saving = Card(side, "Warum das günstig ist")
        saving.grid(row=0, column=0, sticky="ew", pady=(0, PAD_SM))
        ctk.CTkLabel(
            saving.body,
            text=(
                "Der teure Weg wäre, jede Seite von einem Modell lesen zu "
                "lassen. Bei 100 Seiten sind das 100 Aufrufe.\n\n"
                "Hier liest ein Arbeiter genau EINE Beispielseite und leitet "
                "daraus CSS-Selektoren ab. Diese Selektoren laufen dann über "
                "alle übrigen 99 Seiten - ohne einen weiteren Token.\n\n"
                "Aus Kosten je Seite werden Kosten je Auftrag."
            ),
            font=Fonts.small, text_color=C["text_muted"], justify="left",
            wraplength=260, anchor="w",
        ).pack(fill="x")

        self.saving_note = ctk.CTkLabel(
            saving.body, text="", font=Fonts.small_bold, text_color=C["ok"],
            justify="left", wraplength=260, anchor="w",
        )
        self.saving_note.pack(fill="x", pady=(PAD_SM, 0))

        # -- Weitere Sparmassnahmen ------------------------------------
        more = Card(side, "Weitere Bremsen")
        more.grid(row=1, column=0, sticky="ew", pady=(0, PAD_SM))
        for title, text in [
            ("HTML eindampfen",
             "Skripte, Styles und Navigation fliegen raus, bevor etwas ans "
             "Modell geht - meist über 90 % weniger Text."),
            ("Cache",
             "Derselbe Auftrag auf derselben Seite kostet beim zweiten Mal nichts."),
            ("Modell-Ebenen",
             "Die Fleissarbeit macht das günstigste Modell. Das teure prüft nur."),
            ("Kostenbremse",
             "Bei erreichtem Budget bricht der Lauf ab, statt weiterzulaufen."),
        ]:
            block = ctk.CTkFrame(more.body, fg_color="transparent")
            block.pack(fill="x", pady=(0, PAD_SM))
            ctk.CTkLabel(block, text=title, font=Fonts.small_bold,
                         text_color=C["text"], anchor="w").pack(fill="x")
            ctk.CTkLabel(block, text=text, font=Fonts.small,
                         text_color=C["text_muted"], anchor="w", justify="left",
                         wraplength=260).pack(fill="x")

        # -- Besetzung -------------------------------------------------
        roster = Card(side, "Besetzung")
        roster.grid(row=2, column=0, sticky="ew")
        self.roster_body = roster.body
        self.refresh_roster()

    def refresh_roster(self) -> None:
        for child in self.roster_body.winfo_children():
            child.destroy()

        for name, tier, description in ROLLEN:
            block = ctk.CTkFrame(self.roster_body, fg_color=C["surface_2"],
                                 corner_radius=RADIUS_SM)
            block.pack(fill="x", pady=(0, 5))

            head = ctk.CTkFrame(block, fg_color="transparent")
            head.pack(fill="x", padx=PAD_SM, pady=(PAD_SM, 0))
            ctk.CTkLabel(head, text=name, font=Fonts.small_bold,
                         text_color=C["text"], anchor="w").pack(side="left")

            if tier == "regelbasiert":
                label, color = "ohne KI", C["ok"]
            else:
                label = self.app.model_for(tier).replace("claude-", "")
                color = {"worker": C["info"], "verifier": C["warn"],
                         "advisor": C["error"]}.get(tier, C["text_muted"])
            ctk.CTkLabel(head, text=label, font=Fonts.small,
                         text_color=color, anchor="e").pack(side="right")

            ctk.CTkLabel(block, text=description, font=Fonts.small,
                         text_color=C["text_muted"], anchor="w", justify="left",
                         wraplength=240).pack(fill="x", padx=PAD_SM, pady=(1, PAD_SM))

    # ==================================================================
    # Live-Aktualisierung
    # ==================================================================
    def clear(self) -> None:
        for widget in self._rows.values():
            widget.destroy()
        self._rows.clear()
        self.empty_hint.grid()

    def update_task(self, record: TaskRecord) -> None:
        """Eine Teilaufgabe anlegen oder ihren Zustand ändern."""
        self.empty_hint.grid_remove()

        # Bekannte Aufgabe behält ihren Platz, neue kommt ans Ende.
        if record.id in self._rows:
            position = list(self._rows).index(record.id)
            self._rows[record.id].destroy()
        else:
            position = len(self._rows)

        row = ctk.CTkFrame(self.board, fg_color=C["surface"], corner_radius=RADIUS_SM)
        row.grid(row=position, column=0, sticky="ew", padx=PAD_SM, pady=3)
        row.grid_columnconfigure(1, weight=1)

        # Kennung
        ctk.CTkLabel(row, text=record.id, font=Fonts.mono, width=34,
                     text_color=C["text_faint"]).grid(row=0, column=0, rowspan=2,
                                                      padx=(PAD_SM, 6), pady=PAD_SM)

        # Agent und Ziel
        ctk.CTkLabel(row, text=record.agent, font=Fonts.small_bold,
                     text_color=C["text"], anchor="w").grid(row=0, column=1, sticky="w",
                                                            pady=(PAD_SM, 0))
        detail = record.goal
        if record.note:
            detail += f"  -  {record.note}"
        ctk.CTkLabel(row, text=detail, font=Fonts.small, text_color=C["text_muted"],
                     anchor="w", justify="left", wraplength=430).grid(
            row=1, column=1, sticky="w", pady=(0, PAD_SM))

        # Zustand
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.grid(row=0, column=2, rowspan=2, padx=(6, PAD_SM))

        color = STATE_COLORS.get(record.state, C["text_muted"])
        ctk.CTkLabel(right, text=record.state, font=Fonts.small_bold,
                     text_color=color).pack(anchor="e")

        info = record.model.replace("claude-", "") if record.model else ""
        if record.retries:
            info += f"  ·  {record.retries} Wdh."
        if record.usage.calls:
            info += f"  ·  {record.usage.cost_usd:.4f} $"
        if info:
            ctk.CTkLabel(right, text=info, font=Fonts.small,
                         text_color=C["text_faint"]).pack(anchor="e")

        self._rows[record.id] = row

    def update_usage(self, usage: Any, budget_usd: float) -> None:
        self.tile_calls.set(str(usage.calls))
        self.tile_saved.set(str(usage.saved_calls))
        total_tokens = usage.input_tokens + usage.output_tokens
        self.tile_tokens.set(f"{total_tokens:,}".replace(",", "."))
        self.tile_cost.set(f"{usage.cost_usd:.4f} $".replace(".", ","))

        remaining = max(0.0, budget_usd - usage.cost_usd)
        share = remaining / budget_usd if budget_usd else 0
        self.tile_budget.set(
            f"{remaining:.2f} $".replace(".", ","),
            C["ok"] if share > 0.5 else C["warn"] if share > 0.15 else C["error"],
        )

        if usage.saved_calls:
            # Was hätte der naive Weg gekostet? Ein Direkt-Leser-Aufruf je Seite.
            per_call = (
                usage.cost_usd / usage.calls if usage.calls
                else cost_of(self.app.model_for("worker"), 4000, 800)
            )
            hypothetical = per_call * (usage.calls + usage.saved_calls)
            self.saving_note.configure(
                text=f"Dieser Lauf: {usage.saved_calls} Modellaufrufe vermieden.\n"
                     f"Etwa {hypothetical:.3f} $ statt {usage.cost_usd:.4f} $."
                     .replace(".", ",")
            )
        else:
            self.saving_note.configure(text="")
