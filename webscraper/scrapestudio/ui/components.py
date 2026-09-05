"""Wiederverwendbare Bausteine der Oberfläche."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

import customtkinter as ctk

from ..extractors import all_columns
from .theme import C, PAD, PAD_SM, RADIUS, RADIUS_SM, Fonts, style_treeview


class Card(ctk.CTkFrame):
    """Abgesetzte Fläche mit optionaler Überschrift."""

    def __init__(self, master: Any, title: str = "", subtitle: str = "", **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", C["surface"])
        kwargs.setdefault("corner_radius", RADIUS)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", C["border"])
        super().__init__(master, **kwargs)
        self.body_row = 0

        if title:
            head = ctk.CTkFrame(self, fg_color="transparent")
            head.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 0))
            head.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(head, text=title, font=Fonts.h3, text_color=C["text"],
                         anchor="w").grid(row=0, column=0, sticky="w")
            if subtitle:
                ctk.CTkLabel(head, text=subtitle, font=Fonts.small,
                             text_color=C["text_muted"], anchor="w",
                             justify="left").grid(row=1, column=0, sticky="w", pady=(2, 0))
            self.body_row = 1

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=self.body_row, column=0, sticky="nsew",
                       padx=PAD, pady=(PAD_SM, PAD))
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(self.body_row, weight=1)
        self.body.grid_columnconfigure(0, weight=1)


class StatTile(ctk.CTkFrame):
    """Kennzahl mit Beschriftung."""

    def __init__(self, master: Any, label: str, value: str = "0",
                 color: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", C["surface_2"])
        kwargs.setdefault("corner_radius", RADIUS_SM)
        super().__init__(master, **kwargs)
        self.value_label = ctk.CTkLabel(
            self, text=value, font=Fonts.h2, text_color=color or C["text"],
        )
        self.value_label.pack(padx=PAD_SM, pady=(PAD_SM, 0))
        ctk.CTkLabel(self, text=label, font=Fonts.small,
                     text_color=C["text_muted"]).pack(padx=PAD_SM, pady=(0, PAD_SM))

    def set(self, value: str, color: Any = None) -> None:
        self.value_label.configure(text=value)
        if color:
            self.value_label.configure(text_color=color)


class Badge(ctk.CTkLabel):
    """Kleine farbige Plakette für Zustände."""

    def __init__(self, master: Any, text: str, color: Any = None,
                 bg: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("font", Fonts.small_bold)
        kwargs.setdefault("corner_radius", 5)
        kwargs.setdefault("padx", 8)
        super().__init__(
            master, text=text,
            text_color=color or C["text"],
            fg_color=bg or C["surface_3"],
            **kwargs,
        )

    def set(self, text: str, color: Any = None, bg: Any = None) -> None:
        self.configure(text=text)
        if color:
            self.configure(text_color=color)
        if bg:
            self.configure(fg_color=bg)


class Toast(ctk.CTkFrame):
    """Kurze Einblendung am unteren Rand."""

    @staticmethod
    def show(master: Any, message: str, kind: str = "info", ms: int = 3200) -> None:
        colors = {
            "info": (C["info"], C["info_soft"]),
            "ok": (C["ok"], C["ok_soft"]),
            "warn": (C["warn"], C["warn_soft"]),
            "error": (C["error"], C["error_soft"]),
        }
        fg, bg = colors.get(kind, colors["info"])
        icon = {"info": "i", "ok": "✓", "warn": "!", "error": "×"}.get(kind, "i")

        toast = ctk.CTkFrame(master, fg_color=bg, corner_radius=RADIUS_SM,
                             border_width=1, border_color=fg)
        ctk.CTkLabel(toast, text=f"  {icon}  ", font=Fonts.body_bold,
                     text_color=fg).pack(side="left")
        ctk.CTkLabel(toast, text=message, font=Fonts.body, text_color=C["text"],
                     wraplength=520, justify="left").pack(side="left", padx=(0, 14), pady=10)
        toast.place(relx=0.5, rely=0.97, anchor="s")
        toast.after(ms, toast.destroy)


class LogView(ctk.CTkTextbox):
    """Fortlaufendes Protokoll mit Farben je Ebene."""

    LEVELS = {
        "info": "text",
        "debug": "text_faint",
        "ok": "ok",
        "warn": "warn",
        "error": "error",
    }

    def __init__(self, master: Any, **kwargs: Any) -> None:
        kwargs.setdefault("font", Fonts.mono_sm)
        kwargs.setdefault("fg_color", C["surface_2"])
        kwargs.setdefault("corner_radius", RADIUS_SM)
        kwargs.setdefault("wrap", "word")
        super().__init__(master, **kwargs)
        self.configure(state="disabled")
        self._tags_ready = False

    def _ensure_tags(self) -> None:
        if self._tags_ready:
            return
        mode = ctk.get_appearance_mode().lower()
        index = 1 if mode == "dark" else 0
        for level, key in self.LEVELS.items():
            self.tag_config(level, foreground=C[key][index])
        self._tags_ready = True

    def add(self, message: str, level: str = "info", timestamp: str = "") -> None:
        self._ensure_tags()
        self.configure(state="normal")
        prefix = f"{timestamp}  " if timestamp else ""
        self.insert("end", f"{prefix}{message}\n", level if level in self.LEVELS else "info")
        self.see("end")
        self.configure(state="disabled")

    def clear(self) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")

    def text(self) -> str:
        return self.get("1.0", "end").strip()


class DataTable(ctk.CTkFrame):
    """Tabelle mit Sortierung, Filter und Mehrfachauswahl."""

    def __init__(self, master: Any, on_select: Callable[[dict], None] | None = None,
                 **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", C["surface"])
        kwargs.setdefault("corner_radius", RADIUS_SM)
        super().__init__(master, **kwargs)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._rows: list[dict[str, Any]] = []
        self._view: list[dict[str, Any]] = []
        self._columns: list[str] = []
        self._sort_column: str = ""
        self._sort_desc = False
        self._query = ""
        self.on_select = on_select

        mode = ctk.get_appearance_mode().lower()
        self._stripe = style_treeview(self, mode)

        self.tree = ttk.Treeview(self, show="headings", style="Studio.Treeview",
                                 selectmode="extended")
        self.tree.grid(row=0, column=0, sticky="nsew")

        y_scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview,
                                 style="Studio.Vertical.TScrollbar")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview,
                                 style="Studio.Horizontal.TScrollbar")
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.tag_configure("odd", background=self._stripe)
        self.tree.bind("<<TreeviewSelect>>", self._selected)

    # ------------------------------------------------------------------
    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows or []
        self._columns = all_columns(self._rows)
        self._sort_column = ""
        self.refresh()

    def refresh(self) -> None:
        """Filter und Sortierung anwenden und neu zeichnen."""
        view = self._rows
        if self._query:
            needle = self._query.lower()
            view = [
                row for row in view
                if any(needle in str(value).lower() for value in row.values())
            ]
        if self._sort_column:
            view = sorted(
                view,
                key=lambda r: _sort_key(r.get(self._sort_column)),
                reverse=self._sort_desc,
            )
        self._view = view
        self._render()

    def _render(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = self._columns

        for column in self._columns:
            arrow = ""
            if column == self._sort_column:
                arrow = "  ▼" if self._sort_desc else "  ▲"
            self.tree.heading(
                column, text=f"{column}{arrow}",
                command=lambda c=column: self.sort_by(c),
            )
            width = max(90, min(300, 11 * (len(column) + 6)))
            self.tree.column(column, width=width, minwidth=70, stretch=False, anchor="w")

        for index, row in enumerate(self._view[:5000]):  # Anzeigegrenze
            values = [_cell(row.get(column)) for column in self._columns]
            self.tree.insert("", "end", iid=str(index), values=values,
                             tags=("odd",) if index % 2 else ())

    # ------------------------------------------------------------------
    def sort_by(self, column: str) -> None:
        if self._sort_column == column:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_column = column
            self._sort_desc = False
        self.refresh()

    def set_filter(self, query: str) -> None:
        self._query = (query or "").strip()
        self.refresh()

    def _selected(self, _event: Any = None) -> None:
        if not self.on_select:
            return
        rows = self.selected_rows()
        if rows:
            self.on_select(rows[0])

    def selected_rows(self) -> list[dict[str, Any]]:
        out = []
        for iid in self.tree.selection():
            try:
                out.append(self._view[int(iid)])
            except (ValueError, IndexError):
                continue
        return out

    def visible_rows(self) -> list[dict[str, Any]]:
        return list(self._view)

    def all_rows(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def remove_selected(self) -> int:
        """Ausgewählte Zeilen aus dem Datenbestand entfernen."""
        chosen = self.selected_rows()
        if not chosen:
            return 0
        marked = {id(row) for row in chosen}
        self._rows = [row for row in self._rows if id(row) not in marked]
        self.refresh()
        return len(chosen)

    def select_all(self) -> None:
        self.tree.selection_set(self.tree.get_children())

    @property
    def count(self) -> int:
        return len(self._view)

    @property
    def total(self) -> int:
        return len(self._rows)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\t", " ")
    return text[:400]


def _sort_key(value: Any) -> tuple[int, float, str]:
    """Zahlen vor Text sortieren, Leeres ganz nach hinten."""
    text = str(value or "").strip()
    if not text:
        return (2, 0.0, "")
    cleaned = text.replace(".", "").replace(",", ".")
    cleaned = "".join(c for c in cleaned if c.isdigit() or c in ".-")
    try:
        return (0, float(cleaned), "")
    except ValueError:
        return (1, 0.0, text.lower())


# --------------------------------------------------------------------------
def labeled(master: Any, text: str, hint: str = "") -> ctk.CTkFrame:
    """Beschriftungszeile über einem Eingabefeld."""
    box = ctk.CTkFrame(master, fg_color="transparent")
    ctk.CTkLabel(box, text=text, font=Fonts.small_bold, text_color=C["text"],
                 anchor="w").pack(side="left")
    if hint:
        ctk.CTkLabel(box, text=f"  {hint}", font=Fonts.small,
                     text_color=C["text_faint"], anchor="w").pack(side="left")
    return box


def divider(master: Any) -> ctk.CTkFrame:
    return ctk.CTkFrame(master, height=1, fg_color=C["border"])


def primary_button(master: Any, text: str, command: Callable[[], None],
                   **kwargs: Any) -> ctk.CTkButton:
    kwargs.setdefault("fg_color", C["accent"])
    kwargs.setdefault("hover_color", C["accent_hover"])
    kwargs.setdefault("text_color", "#ffffff")
    kwargs.setdefault("font", Fonts.body_bold)
    kwargs.setdefault("corner_radius", RADIUS_SM)
    kwargs.setdefault("height", 38)
    return ctk.CTkButton(master, text=text, command=command, **kwargs)


def ghost_button(master: Any, text: str, command: Callable[[], None],
                 **kwargs: Any) -> ctk.CTkButton:
    kwargs.setdefault("fg_color", "transparent")
    kwargs.setdefault("hover_color", C["surface_3"])
    kwargs.setdefault("text_color", C["text"])
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("border_color", C["border"])
    kwargs.setdefault("font", Fonts.body)
    kwargs.setdefault("corner_radius", RADIUS_SM)
    kwargs.setdefault("height", 34)
    return ctk.CTkButton(master, text=text, command=command, **kwargs)


def copy_to_clipboard(widget: Any, text: str) -> None:
    """Text in die Zwischenablage legen (ohne Zusatzpaket)."""
    widget.clipboard_clear()
    widget.clipboard_append(text)
    widget.update_idletasks()
