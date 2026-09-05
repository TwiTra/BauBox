"""Alle Testreihen nacheinander laufen lassen.

    python tests/run_all.py

Der Oberflächen-Test braucht eine Anzeige. Ohne Bildschirm:

    xvfb-run -a python tests/run_all.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent

REIHEN = [
    ("Logik-Module", "test_core.py", False),
    ("Orchestrator (echter Server)", "test_orchestrator.py", False),
    ("Oberfläche", "test_ui.py", True),
]


def hat_anzeige() -> bool:
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def main() -> int:
    fehlgeschlagen: list[str] = []
    uebersprungen: list[str] = []

    for titel, datei, braucht_anzeige in REIHEN:
        if braucht_anzeige and not hat_anzeige():
            print(f"\n### {titel}: übersprungen (keine Anzeige)")
            uebersprungen.append(titel)
            continue

        print(f"\n{'#' * 60}\n### {titel}\n{'#' * 60}")
        ergebnis = subprocess.run([sys.executable, str(HIER / datei)])
        if ergebnis.returncode != 0:
            fehlgeschlagen.append(titel)

    print("\n" + "=" * 60)
    if uebersprungen:
        print(f"Übersprungen: {', '.join(uebersprungen)}")
    if fehlgeschlagen:
        print(f"FEHLGESCHLAGEN: {', '.join(fehlgeschlagen)}")
        return 1
    print("Alle Testreihen bestanden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
