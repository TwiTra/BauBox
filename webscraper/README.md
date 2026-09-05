# ScrapeStudio

Ein Webscraper als Desktop-Programm für Windows. Er holt Daten aus Webseiten,
zeigt sie in einer sortierbaren Tabelle und sichert sie in neun Formaten.

Die Besonderheit steckt im dritten Betriebsmodus: dort arbeitet ein **Team aus
KI-Agenten**, das so gebaut ist, dass es möglichst wenig kostet. Ein günstiger
Arbeiter sieht *eine* Beispielseite und leitet daraus CSS-Selektoren ab. Diese
Selektoren laufen anschliessend über alle weiteren Seiten — ohne einen weiteren
Token. Aus Kosten *je Seite* werden Kosten *je Auftrag*.

---

## Schnellstart

**Windows, einfachster Weg:** `start.bat` doppelklicken. Beim ersten Mal
installiert das Skript selbst, was fehlt.

**Von Hand:**

```bash
pip install -r requirements.txt
python main.py
```

Unter Linux zusätzlich `sudo apt install python3-tk`.

**Als EXE bauen:**

```bash
pip install pyinstaller
python build_exe.py
```

Danach liegt `dist/ScrapeStudio.exe` bereit — eigenständig, läuft ohne
installiertes Python. Die EXE entsteht immer für das System, auf dem gebaut
wird; eine Windows-EXE also nur unter Windows.

---

## Die drei Betriebsmodi

| Modus | Was passiert | KI-Kosten |
|---|---|---|
| **Presets** | Fertige Bausteine: Links, Bilder, Tabellen, Überschriften, E-Mails, Telefonnummern, Preise, Meta-Daten, JSON-LD | keine |
| **Eigene Selektoren** | Du gibst die CSS-Selektoren selbst vor | keine |
| **KI-Agenten** | Du beschreibst in normalem Deutsch, was du brauchst | gering, siehe unten |

Ohne API-Schlüssel funktionieren die ersten beiden Modi vollständig. Das
Programm ist also auch ganz ohne KI brauchbar.

---

## Das Agenten-Team

Drei Ebenen, damit teure Modelle nicht die Fleissarbeit machen:

```
   Orchestrator          plant, verteilt, prüft, führt zusammen
        │                (ruft selbst kein Modell für Fleissarbeit)
        ├── Arbeiter     günstiges Modell, macht die Masse
        ├── Prüfer       mittleres Modell, kontrolliert Stichproben
        └── Berater      teures Modell, nur wenn nichts anderes greift
```

Der Ablauf eines Auftrags:

1. **Sammler** holt die Seiten — regelbasiert, keine Token.
2. **Selektor-Sucher** sieht **eine** Beispielseite und leitet CSS-Selektoren ab.
3. **Anwender** wendet diese Selektoren auf **alle** übrigen Seiten an — kostenlos.
4. **Prüfer** sieht eine Stichprobe und entscheidet `PASS` oder `FIX`.
5. Bei `FIX` wird mit konkreter Rückmeldung neu gelernt (bis zu zwei Versuche).
   Erst als letzte Stufe liest ein **Direkt-Leser** einzelne Seiten selbst.
6. **Zusammenfasser** beantwortet den Auftrag in Prosa.

Im Reiter **Team** siehst du das live: jede Teilaufgabe mit Zustand, Modell,
Wiederholungen und Kosten.

### Was das spart

Gemessen im Testlauf (`tests/test_orchestrator.py`): **6 Seiten, 3 Modellaufrufe.**
Bei 60 Seiten wären es immer noch 3. Der naive Weg — jede Seite von einem
Modell lesen lassen — bräuchte 60.

Dazu kommen vier weitere Bremsen:

- **HTML eindampfen** — Skripte, Styles, SVG und Navigation fliegen raus, bevor
  etwas ans Modell geht. Meist über 90 % weniger Text.
- **Cache** — derselbe Auftrag auf derselben Seite kostet beim zweiten Mal nichts.
- **Prompt-Caching** — der wiederkehrende System-Teil wird markiert.
- **Kostenbremse** — bei erreichtem Budget bricht der Lauf ab, statt
  weiterzulaufen. Standard: 1 USD und 60 Aufrufe je Lauf.

---

## Ergebnisse sichern

Neun Formate: **CSV**, **Excel**, **JSON**, **JSON Lines**, **Markdown**,
**HTML**, **PDF**, **Text** und **SQLite**.

Dazu:

- **Schnellablage** — ein Klick, ohne Dialog, in den Export-Ordner
- **Zwischenablage** — als Tabelle (fügt sich direkt in Excel ein) oder als JSON
- **Automatisch sichern** nach jedem Lauf, wenn eingeschaltet

Gesichert wird immer das, was gerade sichtbar ist — ein gesetzter Filter wirkt
also mit.

---

## Was die Bedienung leichter macht

- **Testlauf** — nur die erste Adresse, eine Seite. Zum Ausprobieren, bevor
  ein grosser Lauf startet.
- **Vorlagen** — Einstellungen unter einem Namen sichern und wieder aufrufen.
- **Verlauf** — jeder Lauf landet in einer lokalen Datenbank. Ergebnisse
  zurückholen oder den Lauf mit denselben Einstellungen wiederholen.
- **Beispiel-Aufträge** zum Anklicken statt Tippen.
- **Suchen, Sortieren, Zeilen löschen** direkt in der Tabelle.
- **Live-Protokoll** mit Farben je Meldungsart.
- **Hell und Dunkel**, folgt auf Wunsch dem Betriebssystem.

### Tastenkürzel

| Kürzel | Wirkung |
|---|---|
| `Strg` + `Enter` | Auftrag starten |
| `Esc` | Abbrechen |
| `Strg` + `S` | Schnellablage |
| `Strg` + `F` | In den Ergebnissen suchen |
| `Strg` + `1` … `5` | Zwischen den Ansichten wechseln |

---

## Einstellungen und Daten

Alles liegt lokal unter `~/.scrapestudio` (Windows:
`C:\Users\<Name>\.scrapestudio`):

| Datei | Inhalt |
|---|---|
| `settings.json` | Einstellungen |
| `credentials.json` | API-Schlüssel, Rechte auf 0600 gesetzt |
| `scrapestudio.db` | Verlauf, Vorlagen, KI-Cache |
| `exports/` | Standard-Ordner für Exporte |

Der Schlüssel wird nie in einen Export geschrieben und nie protokolliert.
Alternativ die Umgebungsvariable `ANTHROPIC_API_KEY` setzen — die hat Vorrang.

Einen Schlüssel gibt es unter [console.anthropic.com](https://console.anthropic.com).

---

## Aufbau

```
webscraper/
├── main.py                    Einstiegspunkt
├── build_exe.py               erzeugt die EXE
├── start.bat                  Windows-Starter
├── scrapestudio/
│   ├── models.py              Datenmodelle
│   ├── config.py              Einstellungen, Modell-Ebenen, Preise
│   ├── compress.py            HTML für die KI eindampfen
│   ├── extractors.py          Presets und CSS-Selektoren (ohne KI)
│   ├── engine.py              Abruf, Crawling, robots.txt
│   ├── storage.py             SQLite: Verlauf, Vorlagen, Cache
│   ├── exporters.py           die neun Ausgabeformate
│   ├── agents/
│   │   ├── base.py            Modell-Anbindung, Budget, Auftragsformat
│   │   ├── workers.py         die einzelnen Agenten
│   │   └── orchestrator.py    der Dirigent
│   └── ui/                    Oberfläche
└── tests/                     drei Testreihen
```

---

## Tests

```bash
python tests/run_all.py
```

Ohne Bildschirm (der Oberflächen-Test braucht eine Anzeige):

```bash
xvfb-run -a python tests/run_all.py
```

Drei Reihen:

- **Logik-Module** — Kompression, Extraktion, alle Exportformate, Speicher,
  Budget, Auswertung von Modellantworten
- **Orchestrator** — läuft gegen einen echten lokalen Webserver: Abruf,
  Link-Verfolgung, robots.txt, Fehlerfälle, Abbruch, Kostenbremse und der
  Nachweis, dass genau ein Selektor-Aufruf stattfindet
- **Oberfläche** — baut das echte Fenster und klickt es durch

Es geht dabei kein Aufruf ins Netz; das Modell wird durch eine Attrappe ersetzt.

---

## Grenzen

- **JavaScript** wird nicht ausgeführt. Seiten, die ihre Inhalte erst im
  Browser nachladen, liefern wenig. Für solche Fälle braucht es einen echten
  Browser (Playwright, Selenium) oder einen Dienst wie ZenRows.
- **Anmeldungen und Paywalls** sind nicht vorgesehen.
- **Rücksicht:** `robots.txt` wird standardmässig beachtet und zwischen den
  Abrufen liegt eine Pause. Beides lässt sich abschalten — die Verantwortung
  dafür, ob ein Abruf zulässig ist, liegt dann bei dir. Nutzungsbedingungen
  und Datenschutz gelten weiterhin.
