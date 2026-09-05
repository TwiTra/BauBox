@echo off
REM ScrapeStudio starten (Windows). Installiert beim ersten Mal, was fehlt.
setlocal

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python wurde nicht gefunden.
    echo Bitte von python.org installieren und dabei
    echo "Add Python to PATH" ankreuzen.
    pause
    exit /b 1
)

python -c "import customtkinter, requests, bs4, lxml" >nul 2>nul
if errorlevel 1 (
    echo Erster Start - installiere die benoetigten Pakete ...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Installation fehlgeschlagen.
        pause
        exit /b 1
    )
)

python main.py
if errorlevel 1 pause
