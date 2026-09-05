"""ScrapeStudio - Einstiegspunkt.

Start:      python main.py
Als EXE:    python build_exe.py   (erzeugt dist/ScrapeStudio.exe)
"""

from __future__ import annotations

import sys
import traceback


FEHLT = """
Es fehlen Pakete, ohne die das Programm nicht starten kann:

  {pakete}

Installieren mit:

  pip install -r requirements.txt
"""


def pruefe_abhaengigkeiten() -> list[str]:
    """Harte Abhängigkeiten prüfen, bevor irgendetwas geladen wird."""
    fehlend = []
    for modul, paket in (
        ("tkinter", "tkinter (unter Linux: sudo apt install python3-tk)"),
        ("customtkinter", "customtkinter"),
        ("requests", "requests"),
        ("bs4", "beautifulsoup4"),
        ("lxml", "lxml"),
    ):
        try:
            __import__(modul)
        except ImportError:
            fehlend.append(paket)
    return fehlend


def main() -> int:
    fehlend = pruefe_abhaengigkeiten()
    if fehlend:
        print(FEHLT.format(pakete="\n  ".join(fehlend)))
        return 1

    try:
        from scrapestudio.ui import run
        run()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        traceback.print_exc()
        # Bei der EXE gibt es keine Konsole - Fehler zusätzlich als Fenster.
        try:
            import tkinter.messagebox as mb
            mb.showerror("ScrapeStudio", f"Unerwarteter Fehler:\n\n{traceback.format_exc()}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
