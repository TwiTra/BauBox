# Google Drive als Speicher einrichten

Der Plan liegt dann als **eine Datei in deinem eigenen Google Drive**. Alle
Geräte – PC, Handy, Laptop – greifen darauf zu und sehen denselben Stand. Ein
Rechner, der durchgehend laufen muss, ist nicht nötig.

Die Einrichtung ist einmalig und dauert etwa zehn Minuten. Danach meldet sich
jedes weitere Gerät nur noch mit dem Google-Konto an.

> **Vorab zum Datenschutz:** Der Planer kann Krankheitstage erfassen. Das sind
> Gesundheitsdaten nach Art. 9 DSGVO. Sie liegen dann unverschlüsselt in einem
> Google-Konto. Kläre das im Zweifel mit der Person, die bei euch für
> Datenschutz zuständig ist – oder verzichte auf die Art „Krank“ und trage
> Ausfälle stattdessen als „Sonderurlaub“ ein.

---

## Teil 1 – Zugangskennung bei Google erstellen

Google verlangt, dass sich jede Anwendung ausweist, die auf ein Drive zugreift.
Diesen Ausweis stellst du dir selbst aus. Er ist kostenlos und **nicht geheim** –
er darf offen im Quelltext stehen.

> Google hat die Konsole 2025 umgebaut: Was früher unter „APIs und Dienste →
> OAuth-Zustimmungsbildschirm“ lag, heißt jetzt **Google Auth-Plattform**. Viele
> Anleitungen im Netz beschreiben noch die alte Oberfläche. Die Schritte unten
> gelten für die neue. Da die Konsole zweisprachig genutzt wird, stehen die
> englischen Bezeichnungen in Klammern.

### 1. Projekt anlegen

1. [console.cloud.google.com](https://console.cloud.google.com) öffnen und mit
   dem Google-Konto anmelden, in dessen Drive der Plan liegen soll.
2. Oben in der Kopfzeile auf die Projektauswahl klicken → **Neues Projekt**
   (*New Project*).
3. Name: `Urlaubsplaner`. **Erstellen**.
4. Warten, bis das Projekt angelegt ist, und oben darauf umschalten. Alles
   Folgende passiert in diesem Projekt – bei Fehlern lohnt der Blick nach oben,
   ob noch das richtige ausgewählt ist.

### 2. Drive-API einschalten

1. Im Menü links: **APIs und Dienste** → **Bibliothek** (*Library*).
2. Nach `Google Drive API` suchen und darauf klicken.
3. **Aktivieren** (*Enable*).

### 3. Zustimmungsbildschirm einrichten

Das ist die Seite, die Google später anzeigt, wenn du dem Planer den Zugriff
erlaubst.

1. Im Menü links **Google Auth-Plattform** (*Google Auth Platform*) öffnen.
   Falls du sie nicht findest: oben in der Suche `Google Auth` eingeben.
2. Beim ersten Mal erscheint **Jetzt starten** (*Get started*) – ein Assistent
   mit vier Abschnitten auf einer Seite:
   - **App-Informationen**: App-Name `Urlaubsplaner`, Nutzersupport-E-Mail deine
     Adresse
   - **Zielgruppe** (*Audience*): **Extern** (*External*)
   - **Kontaktdaten**: deine E-Mail-Adresse
   - Nutzungsbedingungen bestätigen → **Erstellen**
3. Danach links auf **Zielgruppe** (*Audience*). Unten bei **Testnutzer**
   (*Test users*) auf **Nutzer hinzufügen** und deine eigene Google-Adresse
   eintragen – ebenso die Adressen aller Kolleginnen und Kollegen, die den
   Planer nutzen sollen. **Speichern**.

   Ohne diesen Schritt lehnt Google die Anmeldung mit „Zugriff verweigert“ ab.

### 4. Kennung erzeugen

1. In der **Google Auth-Plattform** links auf **Clients**, dann
   **Client erstellen** (*Create client*).
   *Der alte Weg über* **APIs und Dienste → Anmeldedaten → Anmeldedaten
   erstellen → OAuth-Client-ID** *führt zum selben Ziel und existiert weiterhin.*
2. Anwendungstyp (*Application type*): **Webanwendung** (*Web application*).
3. Name: `Urlaubsplaner Browser`. Der Name ist nur für dich.
4. Bei **Autorisierte JavaScript-Quellen** (*Authorized JavaScript origins*) auf
   **URI hinzufügen** und die Adresse eintragen, unter der du den Planer
   öffnest. **Ohne Schrägstrich am Ende, ohne Pfad.** Beispiele:

   | Wie du den Planer öffnest | Was hier eingetragen wird |
   |---|---|
   | lokal mit `python start.py` | `http://localhost:8000` |
   | lokal mit `python server.py` | `http://localhost:8000` |
   | im Heimnetz über die IP | `http://192.168.1.42:8000` |
   | über einen Cloudflare-Tunnel | `https://deine-adresse.trycloudflare.com` |
   | über Cloudflare Pages / GitHub Pages | `https://dein-name.pages.dev` |

   Mehrere Einträge sind erlaubt – trage ruhig alle ein, die du benutzt.
   **Autorisierte Weiterleitungs-URIs** (*Authorized redirect URIs*) bleiben
   leer; der Planer braucht sie nicht.
5. **Erstellen**. Es erscheint ein Fenster mit der **Client-ID**. Sie sieht so
   aus:

   ```
   123456789012-a1b2c3d4e5f6g7h8.apps.googleusercontent.com
   ```

   Diese Zeichenfolge kopieren. Ein danebenstehendes **Client-Secret** brauchst
   du nicht – der Planer läuft im Browser und verwendet keines.

### 5. Veröffentlichen (empfohlen)

Solange das Projekt auf **Testing** steht, läuft der Zugang nach sieben Tagen ab
und jedes Gerät muss sich neu anmelden. Das lässt sich abstellen:

1. **Google Auth-Plattform** → **Zielgruppe** (*Audience*).
2. Bei **Veröffentlichungsstatus** auf **App veröffentlichen**
   (*Publish app*) → bestätigen.

Eine Prüfung durch Google ist dafür **nicht** nötig. Der Planer nutzt
ausschließlich den Bereich `drive.file`, und der gilt bei Google als nicht
sensibel: Die Anwendung sieht nur Dateien, die sie selbst angelegt hat – der
übrige Inhalt deines Drive bleibt für sie unsichtbar. Deshalb entfällt das
Überprüfungsverfahren, das für weitergehende Zugriffe verlangt wird.

---

## Teil 2 – Kennung im Planer hinterlegen

Zwei Wege, beide führen zum selben Ergebnis.

**Fest in der Datei** (empfohlen, gilt dann für alle Geräte):

`js/config.js` öffnen und die Kennung eintragen:

```js
window.UP_CONFIG = {
  googleClientId: '123456789012-a1b2c3d4e5f6g7h8.apps.googleusercontent.com',
  driveFileName: 'Urlaubsplaner.json',
};
```

**Oder im Planer selbst:** Menü (☰) → **Speicherort wählen** → **Google Drive**.
Der Dialog fragt nach der Kennung und speichert sie in diesem Browser. Auf jedem
weiteren Gerät muss sie dann erneut eingegeben werden.

![Einrichtungsdialog](docs/drive-einrichten.png)

*Der Dialog zeigt in Schritt 4 die Adresse an, die bei Google unter
„Autorisierte JavaScript-Quellen“ eingetragen werden muss – genau so, wie der
Planer gerade geöffnet ist.*

Danach auf **Verbinden** klicken. Google fragt nach der Zustimmung, anschließend
lädt der Planer neu und arbeitet mit Drive.

Beim ersten Mal legt der Planer die Datei `Urlaubsplaner.json` in deinem Drive
an und überträgt den bisherigen Plan hinein. Du findest sie ganz normal in
[drive.google.com](https://drive.google.com) und kannst sie ansehen, kopieren
oder herunterladen.

---

## Teil 3 – Webversion erreichbar machen

Damit du den Planer auch unterwegs öffnen kannst, muss die Seite selbst
irgendwo liegen. Die Plandaten sind davon nicht betroffen – die kommen aus
deinem Drive.

### Cloudflare Pages (kostenlos, auch für private Repos)

1. [dash.cloudflare.com](https://dash.cloudflare.com) → **Workers & Pages** →
   **Create** → **Pages** → **Connect to Git**.
2. Dieses Repository auswählen.
3. Einstellungen:
   - Build command: *leer lassen*
   - Build output directory: `urlaubsplaner`
4. **Save and Deploy**.
5. Die entstandene Adresse (`https://…​.pages.dev`) in der Google Cloud Console
   unter **Autorisierte JavaScript-Quellen** ergänzen.

### GitHub Pages

Bei **Settings** → **Pages** als Quelle den Branch wählen. GitHub Pages liefert
nur aus dem Wurzelverzeichnis oder aus `/docs` aus – für den Unterordner
`urlaubsplaner/` braucht es also einen Workflow oder eine Kopie im Wurzel-
verzeichnis. Cloudflare Pages ist hier der kürzere Weg.

### Ohne Hosting

Es geht auch ohne: `python start.py` auf dem PC und der Cloudflare-Tunnel aus
[ZUGRIFF-VON-UEBERALL.md](ZUGRIFF-VON-UEBERALL.md). Dann kommen die Seite vom
PC und die Daten aus dem Drive. Der PC muss dafür allerdings wieder laufen –
womit der Hauptvorteil der Drive-Lösung entfällt.

---

## Betrieb

### Was passiert bei gleichzeitigen Änderungen?

Dasselbe wie beim eigenen Server: Der Planer führt zusammen. Trägst du am PC
Urlaub für Anna ein und gleichzeitig am Handy für Bernd, sind hinterher beide
Einträge da. Nur wenn beide Geräte **denselben** Eintrag ändern, gewinnt das
Gerät, an dem du gerade arbeitest.

Drive kennt kein „nur schreiben, wenn unverändert“. Der Planer prüft deshalb
unmittelbar vor jedem Speichern die Versionsnummer der Datei. Es bleibt ein
Zeitfenster von Sekundenbruchteilen, in dem zwei Geräte gleichzeitig schreiben
könnten; die nächste Abfrage erkennt das und führt zusammen.

### Wie schnell sehen andere Geräte eine Änderung?

Der Planer fragt Drive alle acht Sekunden, ob sich etwas getan hat – bei
ausgeblendetem Tab seltener. Beim eigenen Server geht es schneller, weil der
von sich aus Bescheid geben kann.

### Ohne Internet

Änderungen bleiben im Browser und gehen automatisch raus, sobald wieder eine
Verbindung besteht. Die Statusanzeige oben rechts steht so lange auf „Offline“.

### Frühere Fassungen

Klick auf die Statusanzeige oben rechts zeigt die Revisionen, die Google Drive
zu der Datei führt, und stellt sie auf Wunsch wieder her. Drive bewahrt diese
Revisionen allerdings nur begrenzt auf. Für ein dauerhaftes Archiv zusätzlich
über Menü → **Sicherung speichern** eine JSON-Datei ablegen.

### Speicherort wieder wechseln

Menü → **Speicherort**. Ein Wechsel löscht nichts: Die Drive-Datei bleibt
liegen, und der Planer führt zusammen, statt zu überschreiben.

![Speicherort wählen](docs/speicherort.png)

---

## Wenn etwas nicht klappt

| Meldung | Ursache und Abhilfe |
|---|---|
| „Google akzeptiert die Adresse … noch nicht“ | Die Adresse fehlt unter **Autorisierte JavaScript-Quellen**. Exakt eintragen – ohne Schrägstrich am Ende. Änderungen brauchen dort manchmal ein paar Minuten. |
| „Die Freigabe wurde abgelehnt“ | Dein Konto steht nicht als Testnutzer auf dem Zustimmungsbildschirm, oder du hast im Google-Fenster auf „Abbrechen“ geklickt. |
| „Die Client-ID ist unbekannt“ | Tippfehler beim Kopieren, oder die Kennung stammt aus einem anderen Projekt. |
| „Das Anmeldefenster wurde blockiert“ | Der Browser hat das Pop-up unterdrückt. Pop-ups für diese Seite erlauben. |
| Status bleibt auf „Anmelden“ | Die Google-Sitzung ist abgelaufen. Auf die Statusanzeige klicken. Passiert das alle paar Tage, ist das Projekt noch im Testmodus – siehe Schritt 5. |
| Datei taucht im Drive nicht auf | Suche nach `Urlaubsplaner.json`. Der Planer legt sie erst an, sobald er das erste Mal etwas speichert. |

## Grenzen

- **Ein Google-Konto ist der Eigentümer.** Andere Personen brauchen ein eigenes
  Google-Konto und müssen als Testnutzer eingetragen sein; sie greifen dann über
  ihr eigenes Konto auf dieselbe Datei zu, sobald du sie im Drive für sie
  freigibst.
- **Die Daten liegen unverschlüsselt.** Google könnte den Inhalt technisch
  einsehen. Wer das nicht möchte, bleibt beim eigenen Server.
- **Kein Rechtemodell.** Wer Zugriff auf die Datei hat, sieht und ändert den
  ganzen Plan. Wer nur zuschauen soll, bekommt einen CSV- oder PDF-Auszug.
