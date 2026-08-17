# BauBox

Kleine Werkzeuge für den Arbeitsalltag – ohne Installation im Browser nutzbar.

## Urlaubsplaner

Urlaubsplanung für Teams mit mehreren Abteilungen. Zeigt strukturiert, wo sich
Urlaub überschneidet, damit nicht zu viele Leute gleichzeitig fehlen. Mit
Drag & Drop für Personen und Zeiträume, Urlaubskonten, Feiertagen aller
Bundesländer und dauerhaft gespeicherten Vorjahren.

➡ **[Zum Urlaubsplaner](urlaubsplaner/README.md)**

```bash
cd urlaubsplaner
python start.py
```

Der Plan kann an drei Orten liegen, umschaltbar im Menü:

| | Von mehreren Geräten | PC muss laufen | Einrichtung |
|---|---|---|---|
| Nur dieser Browser | nein | – | keine |
| [Eigener Server auf dem PC](urlaubsplaner/ZUGRIFF-VON-UEBERALL.md) | ja | ja | ein Befehl |
| [Google Drive](urlaubsplaner/CLOUD-EINRICHTEN.md) | ja | nein | ~10 Minuten |

In beiden Mehrgeräte-Varianten wird automatisch gespeichert, live verteilt und
bei gleichzeitigen Änderungen zusammengeführt statt überschrieben.
