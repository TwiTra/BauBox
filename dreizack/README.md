# Dreizack – Price-Action-Leiste für MetaTrader 5

Eine Bedienleiste am Chartrand mit vier Werkzeuggruppen, einem Fenster für die
Kerzenrestzeit bzw. die laufende Handelssession und einer Taste zum Einklappen.

```
cd dreizack
python install.py     # in den MetaTrader-Datenordner kopieren
```

Danach in MetaEditor `Indicators/BauBox/Dreizack.mq5` öffnen und mit **F7**
kompilieren. Der Indikator erscheint im Navigator unter `BauBox`.

---

## Vorab: was hier neu geschrieben wurde und warum

Die Vorlage war `vilka.ex5` – eine **kompilierte** MQL5-Datei. MetaTrader
verschlüsselt den Programmteil einer `.ex5`, lesbar bleiben nur ein paar
Kopfdaten (hier: Autor „Михайлов Максим“, `maxxlmm@mail.ru`). Aus der Datei
lässt sich also **kein Quelltext zurückgewinnen**, und die ursprüngliche
Dreizack-Funktion konnte nicht übernommen, sondern nur aus den Screenshots
nachgebaut werden.

Konkret heißt das: Der **Aufbau** der Stufen 1–3 ist so umgesetzt, wie er im
Chart-Screenshot aussieht – drei gleichmäßig gestaffelte Ziele über
Zinken vom Ausbruchspunkt aus. Die **Faktoren** dafür sind Eingabewerte
(Vorgabe 1 / 2 / 3), weil sich aus einem Bild nicht ablesen lässt, mit welchen
Zahlen das Original gerechnet hat. Wenn die Stufen bei Ihnen anders liegen
sollen, ist das eine reine Einstellungssache – siehe
[Stufen einstellen](#stufen-einstellen).

---

## Die Leiste

Aufbau von links nach rechts, so wie in der Vorlage:

```
┌──────────────┬─────────┬─────────┬────────────────────┬───┐
│ ■ ■ ■        │ ■ ■     │ ■ ■     │   M5  Kerze        │ – │
│ ■ ■ ■        │ ■ ■     │ ■ ■     │   00:03:42         │   │
│              │         │         │   ■ ■ ■ ■          │   │
└──────────────┴─────────┴─────────┴────────────────────┴───┘
  Rechtecke      Rechtecke  Dreizack   Kerzenzeit /
  MIT Alarm      ohne Alarm            Session
  (6 Farben)     (4 Farben) (4 Farben) + Trendlinien (4)
```

Die Leiste klebt an einer Chartecke (Vorgabe: **oben rechts**) und lässt sich
über `Ecke`, `Abstand zum Rand` und `Massstab in Prozent` verschieben und
vergrößern.

### Bedienung in einem Satz

Farbtaste anklicken → die Taste bleibt gedrückt und unter der Leiste steht,
was als Nächstes zu tun ist → die nötigen Punkte in den Chart klicken.
**Esc** bricht ab, ein zweiter Klick auf dieselbe Taste ebenfalls.

| Werkzeug | Klicks im Chart |
|---|---|
| Rechteck (mit und ohne Alarm) | 2 – zwei gegenüberliegende Ecken |
| Trendlinie | 2 – Anfang und Ende |
| Dreizack | 3 – Start, Spitze, Rücklauf (oder 1 im Automatikbetrieb) |

---

## Der Dreizack

Gemessen wird der Impuls **A → B**. Von der Basis aus – das ist gewöhnlich der
Rücklauf **C** – werden drei Stufen nach oben (bzw. unten) projiziert:

```
                                        ─────────────── 3   Ende der Bewegung
                                   ╱
                          ─────────────── 2               sicherer Bereich
                     ╱
              ─────────────── 1                           erstes Ziel
         ╱
    B ╲    ╱ Zinken laufen von C zu den Stufen
       ╲  ╱
        ╲╱
         C
   ┌ ─ ─ ┐  gestrichelte Basisbox
   │  A  │
   └ ─ ─ ┘
```

* **Stufe 1** = Basis + 1 × Impuls – das erste, meist schnell erreichte Ziel.
* **Stufe 2** = Basis + 2 × Impuls – hier liegt der Bereich, in dem sich ein
  Takeprofit sicher abholen lässt.
* **Stufe 3** = Basis + 3 × Impuls – meist das Ende der Bewegung. Danach folgt
  typischerweise eine Seitwärtsphase oder eine Trendwende; weiter reicht der
  Takeprofit-Bereich nicht.

Damit man das auf einen Blick sieht, werden **Stufe 2 und 3 kräftiger
gezeichnet** als Stufe 1 (Stufe 1 gepunktet, 2 und 3 durchgezogen und dicker).
Abschaltbar über `Stufe 2 und 3 hervorheben`.

Der kleine Text an der Spitze zeigt in der Vorgabe **`Kerzen/Punkte`** des
Impulses – bei `9/98` also: neun Kerzen lang, 98 Punkte hoch. Umstellbar auf
nur Punkte, auf `Impuls/Weg bis Stufe 3` oder ganz aus.

### Nachjustieren

Die beiden **Schenkel** (A→B und B→C) sind die Griffe: anklicken, Endpunkt
ziehen – alle Stufen, Zinken, die Basisbox und der Messtext rechnen sich sofort
neu. Alles andere am Dreizack ist bewusst nicht auswählbar, damit beim Arbeiten
im Chart nichts versehentlich verschoben wird.

Wird ein Schenkel gelöscht, verschwindet der ganze Dreizack mit.

### Stufen einstellen

| Eingabe | Vorgabe | Bedeutung |
|---|---|---|
| `Stufe 1/2/3 = Faktor x Impuls` | 1.0 / 2.0 / 3.0 | Für Fibonacci-Ziele z. B. 1.0 / 1.618 / 2.618 eintragen |
| `Stufen messen ab` | Rücklauf (C) | Alternativ ab der Spitze (B) |
| `Vorlauf je Zinke in Kerzen` | 0 | 0 = die Impulsdauer wird auf die drei Stufen aufgeteilt |
| `Laenge einer Stufe in Kerzen` | 60 | Wie weit eine Stufe nach rechts läuft |
| `Stufen endlos nach rechts` | aus | Statt fester Länge ein Strahl |

### Automatik statt drei Klicks

Steht `Setzen per drei Klicks oder automatisch` auf **automatisch**, genügt ein
Klick in die Nähe der Bewegung. Im Suchfenster (Vorgabe 30 Kerzen) werden Hoch
und Tief gesucht; das ältere davon wird zum Start, das jüngere zur Spitze, das
Gegenextrem danach zum Rücklauf. Anschließend lässt sich wie oben nachziehen.

---

## Der Alarm

Der Alarm gilt **ausschließlich für die Rechtecke aus der ersten Gruppe**.

Das ist keine Absichtserklärung, sondern folgt aus der Bauart: Alarmrechtecke
heißen intern `DZ_A_…`, und das Alarmmodul sieht nur Objekte mit genau diesem
Namensanfang an. Rechtecke aus der zweiten Gruppe heißen `DZ_R_…`, ein von Hand
in MetaTrader gezogenes Rechteck heißt `Rectangle 1234` – beide werden nie
geprüft, auch nicht, wenn der Kurs mitten hindurchläuft.

**Ausgelöst wird beim Eintritt in die Zone, nicht während man darin steht.**
Steht der Kurs beim Start des Indikators bereits in einer Zone, gilt sie als
schon betreten und bleibt still, bis der Kurs sie verlassen und erneut betreten
hat. Damit gibt es kein Dauerfeuer, wenn man den Zeitrahmen wechselt.

| Eingabe | Vorgabe | Bedeutung |
|---|---|---|
| `ausloesen bei` | Berührung | Alternativ erst, wenn eine Kerze in der Zone **schließt** |
| `nur innerhalb der Zeitspanne des Rechtecks` | aus | Aus: die Zone gilt ab ihrer linken Kante dauerhaft nach rechts |
| `bei jedem neuen Eintritt erneut melden` | ein | Aus: jede Zone meldet sich genau einmal |
| `Sperrzeit je Zone in Sekunden` | 60 | Schützt vor Mehrfachmeldungen beim Zappeln um die Kante |
| `Fenster / Ton / Push / E-Mail` | Fenster + Ton | Push braucht die MetaQuotes-ID in den Terminaleinstellungen |
| `ausgeloeste Zone gestrichelt zeichnen` | ein | Man sieht, welche Zone schon gerufen hat |

Für den Modus *Berührung* wird der **Bid** herangezogen, für *Kerzenschluss*
der Schlusskurs der eben beendeten Kerze.

---

## Das Fenster oben rechts

Ein Klick darauf schaltet um:

| Anzeige | Inhalt |
|---|---|
| **Kerzenzeit** | Zeitrahmen und Restzeit der laufenden Kerze, z. B. `M5 Kerze` / `00:03:42` |
| **Session** | Laufende Handelssession und ihre Zeitspanne, z. B. `London` / `10:00 - 19:00` |

Laufen zwei Sessions gleichzeitig, steht oben `London + New York`; angezeigt
wird die Zeitspanne der zuletzt geöffneten. Läuft gerade keine, steht dort
`Pause` und darunter, welche als Nächstes öffnet und in wie vielen Stunden.

Die Restzeit läuft im Sekundentakt weiter, auch wenn gerade keine Ticks
hereinkommen.

### Zeitzonen – die einzige Stelle, die Aufmerksamkeit braucht

Die vier Sessions werden **in GMT** eingetragen (Vorgabe: Sydney 22–07,
Tokio 00–09, London 08–17, New York 13–22) und vom Indikator auf die Zeit des
Brokerservers umgerechnet. Angezeigt wird immer Serverzeit – also genau die
Zeit, die auch an der Chartachse steht.

Der Abstand Server↔GMT wird selbst bestimmt (`Serverzeit gegen GMT selbst
bestimmen`). Das setzt eine richtig gestellte Uhr am Rechner voraus. Stimmt die
angezeigte Spanne nicht, den Haken entfernen und `Server minus GMT in Stunden`
von Hand eintragen – im europäischen Sommer sind die meisten Broker auf GMT+3,
im Winter auf GMT+2.

Die Sessionzeiten selbst sind ebenfalls Eingabewerte, inklusive Name und Farbe.
Sommerzeit verschiebt die echten Handelszeiten; wer es genau braucht, passt
zweimal im Jahr die Spannen an.

---

## Einklappen

Die Taste rechts oben in der Leiste klappt sie zusammen. In der Vorgabe bleibt
das Fenster mit Kerzenzeit bzw. Session sichtbar – das ist meist genau das, was
man dauerhaft im Blick haben will. Wer die Leiste vollständig verschwinden
lassen möchte, setzt `eingeklappt: Fenster weiter zeigen` auf aus; dann bleibt
nur ein schmaler Balken mit dem Namen und der Taste stehen.

Ob die Leiste eingeklappt ist und welche Anzeige das Fenster zeigt, überlebt
Zeitrahmenwechsel und Neukompilieren.

---

## Was beim Entfernen passiert

Zeichnungen bleiben stehen, wenn der Indikator vom Chart genommen wird – die
Leiste selbst verschwindet. Wer das anders will, setzt
`Zeichnungen beim Entfernen loeschen` auf ein.

Beim Wechsel des Zeitrahmens, beim Ändern der Eingaben und beim Neukompilieren
bleibt ohnehin alles erhalten.

---

## Aufbau des Quelltexts

| Datei | Inhalt |
|---|---|
| `Indicators/BauBox/Dreizack.mq5` | Eingaben, Start/Ende, Verteilung der Chart-Ereignisse |
| `Include/BauBox/Dreizack/DzTypes.mqh` | Namensraum der Objekte, Aufzählungen, Bausteine |
| `Include/BauBox/Dreizack/DzUtil.mqh` | Farben, Objekt-Helfer, Formatierung |
| `Include/BauBox/Dreizack/DzSession.mqh` | Kerzenrestzeit, Handelssessions, GMT-Abstand |
| `Include/BauBox/Dreizack/DzPanel.mqh` | Aufbau der Leiste, Ein- und Ausklappen |
| `Include/BauBox/Dreizack/DzTools.mqh` | Rechtecke, Trendlinien, Dreizack samt Nachziehen |
| `Include/BauBox/Dreizack/DzAlarm.mqh` | Alarm, ausschließlich für `DZ_A_…` |

Alle Objektnamen beginnen mit `DZ_`. Der Indikator fasst nichts an, was nicht
so heißt – von Hand gezeichnete Objekte bleiben unberührt.
