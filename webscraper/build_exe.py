"""Erzeugt aus dem Programm eine eigenständige EXE.

    python build_exe.py              einzelne Datei (empfohlen)
    python build_exe.py --ordner     Ordner mit EXE (startet schneller)
    python build_exe.py --konsole    mit Konsolenfenster (zur Fehlersuche)

Ergebnis liegt danach in  dist/.

Wichtig: Die EXE lässt sich nur auf dem Betriebssystem erzeugen, auf dem
sie laufen soll. Eine Windows-EXE entsteht also nur unter Windows.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
NAME = "ScrapeStudio"

# Diese Pakete lädt PyInstaller nicht von allein vollständig ein:
# customtkinter bringt Themes und Schriften als Dateien mit.
COLLECT = ["customtkinter"]

# Module, die dynamisch nachgeladen werden und deshalb erzwungen gehören.
HIDDEN = [
    "bs4", "lxml", "lxml.etree", "lxml._elementpath",
    "tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.simpledialog",
    "tkinter.ttk",
]

# Optionales - nur einbinden, wenn installiert.
OPTIONAL = ["anthropic", "openpyxl", "reportlab"]

# Ballast, der die Datei sonst unnötig aufbläht.
EXCLUDE = ["matplotlib", "numpy", "pandas", "scipy", "PyQt5", "PySide6",
           "IPython", "jupyter", "pytest", "setuptools"]


def vorhanden(modul: str) -> bool:
    try:
        __import__(modul)
        return True
    except ImportError:
        return False


def pruefe_pyinstaller() -> bool:
    if vorhanden("PyInstaller"):
        return True
    print("PyInstaller fehlt. Installieren mit:\n\n    pip install pyinstaller\n")
    return False


def baue(einzeldatei: bool = True, konsole: bool = False) -> int:
    if not pruefe_pyinstaller():
        return 1

    for ordner in ("build", "dist"):
        pfad = HIER / ordner
        if pfad.exists():
            print(f"Räume {ordner}/ auf ...")
            shutil.rmtree(pfad, ignore_errors=True)
    spec = HIER / f"{NAME}.spec"
    if spec.exists():
        spec.unlink()

    befehl = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onefile" if einzeldatei else "--onedir",
        "--console" if konsole else "--windowed",
        "--clean",
        "--noconfirm",
    ]

    for paket in COLLECT:
        if vorhanden(paket):
            befehl += ["--collect-all", paket]
        else:
            print(f"Warnung: {paket} ist nicht installiert - die EXE wird nicht laufen.")

    for modul in HIDDEN:
        befehl += ["--hidden-import", modul]

    for modul in OPTIONAL:
        if vorhanden(modul):
            befehl += ["--hidden-import", modul]
            print(f"Optional eingebunden: {modul}")
        else:
            print(f"Übersprungen (nicht installiert): {modul}")

    for modul in EXCLUDE:
        befehl += ["--exclude-module", modul]

    symbol = HIER / "icon.ico"
    if symbol.exists():
        befehl += ["--icon", str(symbol)]

    befehl.append(str(HIER / "main.py"))

    print("\nBaue ... das dauert ein bis drei Minuten.\n")
    ergebnis = subprocess.run(befehl, cwd=HIER)
    if ergebnis.returncode != 0:
        print("\nBauen fehlgeschlagen. Ausgabe oben ansehen.")
        return ergebnis.returncode

    endung = ".exe" if sys.platform.startswith("win") else ""
    ziel = HIER / "dist" / (f"{NAME}{endung}" if einzeldatei else NAME)
    print(f"\nFertig: {ziel}")
    if ziel.is_file():
        print(f"Grösse: {ziel.stat().st_size / 1_048_576:.1f} MB")
    print("\nDie Datei ist eigenständig und läuft ohne installiertes Python.")
    return 0


if __name__ == "__main__":
    sys.exit(baue(
        einzeldatei="--ordner" not in sys.argv,
        konsole="--konsole" in sys.argv,
    ))
