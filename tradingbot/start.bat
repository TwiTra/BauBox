@echo off
REM ---------------------------------------------------------------------------
REM PAX - Start unter Windows
REM
REM Legt beim ersten Lauf eine virtuelle Umgebung an, installiert die
REM Abhaengigkeiten und oeffnet das Menue. Danach genuegt ein Doppelklick.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Erster Start - die Umgebung wird eingerichtet. Das dauert einige Minuten.
    echo.
    python -m venv .venv
    if errorlevel 1 (
        echo   FEHLER: Python wurde nicht gefunden.
        echo   Python 3.10 oder neuer von python.org installieren und dabei
        echo   "Add Python to PATH" ankreuzen.
        pause
        exit /b 1
    )
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip --quiet
    python -m pip install -r requirements.txt
    echo.
    echo   Optionale Zusatzmodelle werden installiert (Fehler sind unkritisch)...
    python -m pip install -r requirements-extra.txt
) else (
    call .venv\Scripts\activate.bat
)

if not exist "config\config.yaml" (
    echo.
    echo   Es gibt noch keine Konfiguration - sie wird jetzt angelegt.
    python main.py init
    echo.
    echo   Bitte config\config.yaml anpassen, dann dieses Fenster erneut starten.
    pause
)

:menu
cls
echo ===========================================================================
echo   PAX - Price-Action-Handelssystem fuer MetaTrader 5
echo ===========================================================================
echo.
echo    1  Status          Was ist da? Daten, Modelle, Journal
echo    2  Verbindung      MT5-Terminal pruefen
echo    3  Daten laden     Historie herunterladen
echo    4  Selbsttest      interne Pruefungen (Lookahead!)
echo    5  Analyse         aktuelle Lage und Signal
echo    6  Backtest        Strategie auf der Historie pruefen
echo    7  Training        Modell anlernen
echo    8  Vorwaertstest   die ehrlichste Pruefung
echo    9  Lernschleife    nachtrainieren und ggf. ablosen
echo   10  Fehleranalyse   wo verliert das System?
echo   11  LIVE            Trockenlauf (keine echten Orders)
echo   12  LIVE ECHT       mit echtem Geld - erst nach Punkt 8!
echo    0  Beenden
echo.
set /p wahl="   Auswahl: "

if "%wahl%"=="1"  ( python main.py status & pause & goto menu )
if "%wahl%"=="2"  ( python main.py connect & pause & goto menu )
if "%wahl%"=="3"  ( python main.py fetch & pause & goto menu )
if "%wahl%"=="4"  ( python main.py selftest & pause & goto menu )
if "%wahl%"=="5"  ( python main.py analyse & pause & goto menu )
if "%wahl%"=="6"  ( python main.py backtest & pause & goto menu )
if "%wahl%"=="7"  ( python main.py train & pause & goto menu )
if "%wahl%"=="8"  ( python main.py walkforward & pause & goto menu )
if "%wahl%"=="9"  ( python main.py evolve & pause & goto menu )
if "%wahl%"=="10" ( python main.py feedback & pause & goto menu )
if "%wahl%"=="11" ( python main.py live & pause & goto menu )
if "%wahl%"=="12" ( python main.py live --real & pause & goto menu )
if "%wahl%"=="0"  ( exit /b 0 )
goto menu
