# Urlaubsplaner

Urlaubsplanung für Teams mit mehreren Abteilungen – läuft im Browser, ohne
Installation, ohne Server, ohne Konto. Der Schwerpunkt liegt auf der Frage:
**Wer ist wann gleichzeitig weg – und ist das noch tragbar?**

![Jahresansicht](docs/jahr.png)

*Jahresansicht: alle Personen nach Abteilungen gruppiert. Die Balken über jeder
Abteilung zeigen tagesgenau die Belegung – rot, sobald zu viele gleichzeitig
fehlen. Betroffene Einträge bekommen einen roten Rahmen.*

## Starten

**Empfohlen** – mit lokalem Server (Python ist auf Windows, macOS und Linux
meist schon vorhanden):

```bash
python start.py
```

Der Browser öffnet sich von selbst. Beenden mit `Strg+C`.

**Alternativ** – `index.html` doppelklicken. Funktioniert ebenfalls, allerdings
behandelt Chrome direkt geöffnete Dateien je nach Version als eigene Herkunft;
der gespeicherte Plan kann dann beim nächsten Start fehlen. Über
`http://localhost` bleiben die Daten zuverlässig erhalten.

## Was der Planer kann

### Überschneidungen erkennen

Jede Abteilung bekommt einen Grenzwert: *wie viele Personen dürfen dort
höchstens gleichzeitig fehlen*. Daraus ergibt sich die zentrale Auswertung:

- **Balken über jeder Abteilung** in der Jahresansicht zeigen tagesgenau, wie
  viele Leute weg sind – grün, orange an der Grenze, rot darüber.
- **Reiter „Überschneidungen“** listet alle kritischen Zeiträume nach Schwere
  sortiert, mit Datum, Anzahl Arbeitstagen und den beteiligten Personen. Ein
  Klick springt in die Jahresansicht an die Stelle.
- **Wochen-Heatmap** über das ganze Jahr, eine Zeile je Abteilung.
- **Engpasstage**: Zeiträume genau an der Grenze – hier passt kein weiterer
  Urlaub mehr rein.
- **Warnung beim Eintragen**, noch bevor gespeichert wird: „An 3 Arbeitstagen
  wären bis zu 2 Personen gleichzeitig abwesend – erlaubt ist 1.“

![Überschneidungen](docs/ueberschneidungen.png)

### Abteilungen und Personen

- Abteilungen anlegen, benennen, einfärben und den Grenzwert festlegen.
- **Drag & Drop**: Personenkarten in der Team-Ansicht zwischen Abteilungen
  ziehen, inklusive Position innerhalb der Spalte. In der Jahresansicht geht
  das genauso – den Namen links anfassen und auf eine andere Abteilung ziehen.
- Spalten selbst lassen sich per Kopfzeile umsortieren.
- Personen ohne Abteilung landen in einer eigenen Spalte und gehen nicht
  verloren.

![Team-Ansicht](docs/team.png)

### Urlaub eintragen

- In Jahres- oder Monatsansicht **über den Zeitraum ziehen** – fertig.
- Balken **verschieben** (anfassen und ziehen) und **verlängern** (an den
  Rändern ziehen), jeweils mit Live-Vorschau der Arbeitstage.
- Klick auf einen Balken öffnet den Dialog mit Art, Status, halben Tagen und
  Notiz.
- Acht Arten: Urlaub, Resturlaub, Sonderurlaub, Überstunden, Krank,
  Fortbildung, Elternzeit, Homeoffice. Homeoffice zählt nicht als Abwesenheit.
- Drei Status: beantragt (gestreift), genehmigt, abgelehnt.
- Überlappende Einträge derselben Person – etwa krank im Urlaub – werden
  untereinander in eigenen Spuren dargestellt.

### Jahre

Jedes Jahr ist ein eigener, dauerhaft gespeicherter Datensatz. Über die
Jahreszahl oben links:

- zwischen Jahren wechseln (auch weit zurück),
- ein neues Jahr anlegen und dabei **Abteilungen und Personen aus dem Vorjahr
  übernehmen** – wahlweise mit dem Resturlaub als Übertrag,
- abgeschlossene Jahre **schreibgeschützt archivieren**, damit alte Pläne nicht
  versehentlich verändert werden.

Änderungen an Personen oder Abteilungen wirken immer nur im geöffneten Jahr.
Wer 2024 die Abteilung wechselt, taucht 2023 weiterhin an der alten Stelle auf.

### Urlaubskonten

Anspruch, Übertrag aus dem Vorjahr, genehmigte und beantragte Tage, Resttage –
je Person und im Überblick. Feiertage und Wochenenden werden automatisch nicht
als Urlaubstag gezählt, halbe Tage sind möglich.

### Weitere Funktionen

| | |
|---|---|
| **Feiertage** | Alle 16 Bundesländer, dazu Österreich und Schweiz. Bewegliche Feiertage werden berechnet, Buß- und Bettag und Fronleichnam inklusive. |
| **Brückentage** | Vorschläge sortiert nach Effizienz: „1 Urlaubstag ergibt 4 freie Tage“. Direkt eintragbar. |
| **Betriebsruhe** | Sperrzeiten als farbiger Streifen über das ganze Team. |
| **Statistik** | Verteilung über die Monate, Planungsstand je Abteilung, Konten aller Personen, sortierbar. |
| **Export** | JSON-Sicherung (alle Jahre), CSV für Urlaubskonten, Einträge und Überschneidungen, ICS für Outlook und Google Kalender. |
| **Drucken** | Eigenes Drucklayout im Querformat, auch als PDF speicherbar. |
| **Rückgängig** | 60 Schritte weit, für jede Änderung inklusive Drag & Drop. |
| **Design** | Hell, dunkel oder nach Systemeinstellung. |
| **Suche** | Personen filtern, nicht passende Zeilen werden ausgegraut. |

## Tastenkürzel

| Taste | Wirkung |
|---|---|
| `N` | Neue Abwesenheit |
| `T` | Zum heutigen Tag |
| `1`–`5` | Ansicht wechseln |
| `+` / `−` | Zeitachse zoomen |
| `←` / `→` | Monat blättern (Monatsansicht) |
| `Strg` + `←` / `→` | Jahr wechseln |
| `/` | Personensuche |
| `Strg`+`Z` / `Strg`+`Umschalt`+`Z` | Rückgängig / Wiederherstellen |
| `Strg`+`S` | Sicherung speichern |
| `Esc` | Dialog schließen, laufendes Ziehen abbrechen |
| `?` | Hilfe |

## Wo liegen die Daten?

Ausschließlich im Browser auf dem jeweiligen Rechner (`localStorage`). Es gibt
keinen Server, keine Anmeldung, keine Übertragung nach außen.

Das heißt umgekehrt: **Sicherungen sind wichtig.** Menü → „Sicherung speichern“
legt eine JSON-Datei mit allen Jahren ab. Sie lässt sich auf einem anderen
Rechner wieder einlesen – wahlweise ersetzend oder zusammenführend. Wer den
Browser-Verlauf inklusive Websitedaten löscht, verliert sonst den Plan.

## Aufbau

Reines HTML, CSS und JavaScript – kein Build-Schritt, keine Abhängigkeiten.

```
urlaubsplaner/
├── index.html          Grundgerüst und Kopfleiste
├── start.py            lokaler Server + Browser öffnen
├── css/app.css         Design-System, hell und dunkel
└── js/
    ├── utils.js        Datums-, DOM- und Formatierungshelfer
    ├── holidays.js     Feiertage (DE/AT/CH) und Brückentage
    ├── store.js        Datenmodell, Speicherung, Undo, Auswertungen
    ├── dnd.js          Drag & Drop auf Pointer-Basis
    ├── timeline.js     Jahresansicht
    ├── month.js        Monatsansicht
    ├── conflicts.js    Überschneidungen
    ├── board.js        Team-Board
    ├── stats.js        Statistik und Konten
    └── app.js          Steuerung, Dialoge, Import/Export
```

Alle Berechnungen – Arbeitstage, Belegung, Konflikte – liegen in `store.js` und
sind von der Darstellung getrennt. Die Ansichten lesen nur.

## Bekannte Grenzen

- Ein Zeitraum gehört immer zu genau einem Jahr. Urlaub über Silvester wird als
  zwei Einträge geplant, einer je Jahr.
- Halbe Tage werden beim Urlaubskonto berücksichtigt, bei der
  Überschneidungs-Prüfung aber als ganzer Tag gewertet – wer einen halben Tag
  fehlt, fehlt für die Besetzung.
- Es gibt keine Mehrbenutzer-Verwaltung. Wenn mehrere Personen planen sollen,
  läuft der Abgleich über die JSON-Sicherung.
- Feiertage, die nur in einzelnen Gemeinden gelten, sind nicht hinterlegt –
  konkret Mariä Himmelfahrt in Bayern (dort nur in überwiegend katholischen
  Gemeinden) und Fronleichnam in Teilen von Sachsen und Thüringen. Solche Tage
  lassen sich bei Bedarf als Betriebsruhe eintragen.
