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
python start.py            # nur auf diesem Rechner
python server.py --tunnel  # von überall erreichbar, Daten bleiben hier
```

Im zweiten Fall liegt der Plan in einer Datenbank auf dem eigenen Rechner und
ist über einen passwortgeschützten HTTPS-Link von jedem Gerät erreichbar.
Änderungen werden sofort gespeichert und live verteilt –
[Einrichtung](urlaubsplaner/ZUGRIFF-VON-UEBERALL.md).
