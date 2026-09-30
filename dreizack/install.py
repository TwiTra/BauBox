#!/usr/bin/env python3
"""Kopiert den Dreizack-Indikator in den Datenordner von MetaTrader 5.

    python install.py                 # Terminals suchen und fragen
    python install.py "C:\\...\\MQL5"  # Zielordner direkt angeben

Der Datenordner steht in MetaTrader unter Datei -> Datenverzeichnis oeffnen.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

QUELLE = Path(__file__).resolve().parent / "MQL5"
TEILE = [
    Path("Indicators") / "BauBox",
    Path("Include") / "BauBox" / "Dreizack",
]


def terminal_ordner() -> list[Path]:
    """Alle MQL5-Ordner installierter Terminals einsammeln."""
    wurzeln: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        wurzeln.append(Path(appdata) / "MetaQuotes" / "Terminal")
    heim = Path.home()
    wurzeln += [
        heim / ".mt5" / "drive_c" / "users" / os.environ.get("USER", "user")
        / "AppData" / "Roaming" / "MetaQuotes" / "Terminal",
        heim / ".wine" / "drive_c" / "users" / os.environ.get("USER", "user")
        / "AppData" / "Roaming" / "MetaQuotes" / "Terminal",
        heim / "Library" / "Application Support" / "net.metaquotes.wine.metatrader5"
        / "drive_c" / "Program Files" / "MetaTrader 5" / "MQL5",
    ]

    gefunden: list[Path] = []
    for wurzel in wurzeln:
        if not wurzel.is_dir():
            continue
        if wurzel.name == "MQL5":
            gefunden.append(wurzel)
            continue
        for eintrag in sorted(wurzel.iterdir()):
            if eintrag.name.lower() == "common":
                continue
            mql5 = eintrag / "MQL5"
            if mql5.is_dir():
                gefunden.append(mql5)
    return gefunden


def kopieren(ziel: Path) -> int:
    """Dateien kopieren, Rueckgabe: Anzahl kopierter Dateien."""
    anzahl = 0
    for teil in TEILE:
        von = QUELLE / teil
        nach = ziel / teil
        if not von.is_dir():
            print(f"  fehlt in der Quelle: {von}")
            continue
        nach.mkdir(parents=True, exist_ok=True)
        for datei in sorted(von.iterdir()):
            if datei.is_file():
                shutil.copy2(datei, nach / datei.name)
                print(f"  {teil / datei.name}")
                anzahl += 1
    return anzahl


def main() -> int:
    if not QUELLE.is_dir():
        print(f"Quellordner nicht gefunden: {QUELLE}")
        return 1

    if len(sys.argv) > 1:
        ziel = Path(sys.argv[1]).expanduser()
        if ziel.name != "MQL5" and (ziel / "MQL5").is_dir():
            ziel = ziel / "MQL5"
        if not ziel.is_dir():
            print(f"Zielordner gibt es nicht: {ziel}")
            return 1
        ziele = [ziel]
    else:
        ziele = terminal_ordner()
        if not ziele:
            print("Kein MetaTrader-Datenordner gefunden.")
            print("In MetaTrader: Datei -> Datenverzeichnis oeffnen, Pfad kopieren und")
            print('so aufrufen:  python install.py "<Pfad>\\MQL5"')
            return 1
        if len(ziele) > 1:
            print("Gefundene Terminals:")
            for i, z in enumerate(ziele, 1):
                print(f"  [{i}] {z}")
            antwort = input("Nummer waehlen (leer = alle): ").strip()
            if antwort:
                try:
                    ziele = [ziele[int(antwort) - 1]]
                except (ValueError, IndexError):
                    print("Ungueltige Eingabe.")
                    return 1

    gesamt = 0
    for ziel in ziele:
        print(f"\nZiel: {ziel}")
        gesamt += kopieren(ziel)

    if gesamt == 0:
        print("\nNichts kopiert.")
        return 1

    print(f"\n{gesamt} Dateien kopiert.")
    print("In MetaTrader nun: MetaEditor oeffnen, Navigator -> Indicators -> BauBox ->")
    print("Dreizack.mq5, F7 zum Kompilieren. Danach steht der Indikator im Navigator.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
