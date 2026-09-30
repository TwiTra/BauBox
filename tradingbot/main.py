#!/usr/bin/env python3
"""PAX - Price-Action-Handelssystem für MetaTrader 5.

Einstiegspunkt. Beispiele:

    python main.py init                  Konfiguration anlegen
    python main.py status                Überblick
    python main.py selftest              interne Prüfungen
    python main.py backtest --rules-only Strategie ohne Modell testen
    python main.py train                 Modell anlernen
    python main.py walkforward           Vorwärtstest
    python main.py live                  Livebetrieb (Trockenlauf)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pax.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
