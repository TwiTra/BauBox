"""Farben, Schriften und Abstände - eine Quelle für das ganze Programm."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

# --------------------------------------------------------------------------
# Farbpaare: (heller Modus, dunkler Modus). CustomTkinter wählt selbst aus.
# --------------------------------------------------------------------------
C: dict[str, Any] = {
    # Flächen
    "bg":          ("#f4f5f8", "#131419"),
    "surface":     ("#ffffff", "#1b1d24"),
    "surface_2":   ("#eef0f4", "#22252e"),
    "surface_3":   ("#e4e7ed", "#2a2e39"),
    "border":      ("#d9dce3", "#2f3340"),

    # Schrift
    "text":        ("#15171d", "#e9eaef"),
    "text_muted":  ("#5f6672", "#9aa1b1"),
    "text_faint":  ("#8b93a1", "#6c7482"),

    # Akzent
    "accent":      ("#6a4df5", "#7c5cff"),
    "accent_hover": ("#5a3ee0", "#8f74ff"),
    "accent_soft": ("#ece8ff", "#2a2450"),

    # Zustände
    "ok":          ("#128a5c", "#2fbe86"),
    "ok_soft":     ("#dff5ec", "#123529"),
    "warn":        ("#b06d00", "#e0a33a"),
    "warn_soft":   ("#fdf1dc", "#3a2e14"),
    "error":       ("#c02c3a", "#ff6b7a"),
    "error_soft":  ("#fde7e9", "#3a1c20"),
    "info":        ("#1668c4", "#4d9dff"),
    "info_soft":   ("#e3eefc", "#16283f"),
}

# Farbe je Zustand im Status-Board
STATE_COLORS = {
    "PENDING": C["text_faint"],
    "DISPATCHED": C["info"],
    "PASS": C["ok"],
    "FIX": C["warn"],
    "ESCALATED": C["error"],
}

RADIUS = 10
RADIUS_SM = 7
PAD = 16
PAD_SM = 9

FONT_FAMILY = "Segoe UI"
MONO_FAMILY = "Consolas"


class Fonts:
    """Schriften. Erst nach dem Anlegen des Hauptfensters erzeugen."""

    _made: bool = False
    h1: Any = None
    h2: Any = None
    h3: Any = None
    body: Any = None
    body_bold: Any = None
    small: Any = None
    small_bold: Any = None
    mono: Any = None
    mono_sm: Any = None

    @classmethod
    def build(cls) -> None:
        if cls._made:
            return
        cls.h1 = ctk.CTkFont(family=FONT_FAMILY, size=23, weight="bold")
        cls.h2 = ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold")
        cls.h3 = ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold")
        cls.body = ctk.CTkFont(family=FONT_FAMILY, size=13)
        cls.body_bold = ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold")
        cls.small = ctk.CTkFont(family=FONT_FAMILY, size=11)
        cls.small_bold = ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")
        cls.mono = ctk.CTkFont(family=MONO_FAMILY, size=12)
        cls.mono_sm = ctk.CTkFont(family=MONO_FAMILY, size=11)
        cls._made = True


def apply_mode(theme: str) -> None:
    """Hell, dunkel oder wie das Betriebssystem."""
    ctk.set_appearance_mode({"light": "light", "dark": "dark"}.get(theme, "system"))


def style_treeview(widget: Any, mode: str = "dark") -> None:
    """ttk.Treeview an das Erscheinungsbild angleichen.

    CustomTkinter bringt keine Tabelle mit; die Treeview aus ttk ist die
    brauchbarste Grundlage, sieht ohne Anpassung aber fremd aus.
    """
    from tkinter import ttk

    dark = mode == "dark"
    bg = "#1b1d24" if dark else "#ffffff"
    fg = "#e9eaef" if dark else "#15171d"
    head_bg = "#262a34" if dark else "#eef0f4"
    sel_bg = "#7c5cff" if dark else "#6a4df5"
    stripe = "#20232b" if dark else "#f7f8fa"

    style = ttk.Style(widget)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(
        "Studio.Treeview",
        background=bg, foreground=fg, fieldbackground=bg,
        rowheight=28, borderwidth=0, font=(FONT_FAMILY, 10),
    )
    style.configure(
        "Studio.Treeview.Heading",
        background=head_bg, foreground=fg, relief="flat",
        font=(FONT_FAMILY, 10, "bold"), padding=(8, 7),
    )
    style.map(
        "Studio.Treeview",
        background=[("selected", sel_bg)],
        foreground=[("selected", "#ffffff")],
    )
    style.map("Studio.Treeview.Heading", background=[("active", sel_bg)])

    style.configure("Studio.Vertical.TScrollbar",
                    background=head_bg, troughcolor=bg, borderwidth=0, arrowsize=13)
    style.configure("Studio.Horizontal.TScrollbar",
                    background=head_bg, troughcolor=bg, borderwidth=0, arrowsize=13)
    return stripe
