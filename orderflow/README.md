# Footprint (Orderflow-Cluster) für MetaTrader 5

Zerlegt jede Kerze in Preisebenen und zeigt je Ebene, wie viel am **Bid**
(aggressive Verkäufe) und wie viel am **Ask** (aggressive Käufe) gehandelt
wurde — also genau die Darstellung, die man aus ATAS, Sierra Chart oder
Quantower kennt.

```
python install.py          # in den MetaTrader-Datenordner kopieren
```

Danach in MetaEditor `Indicators/BauBox/Footprint.mq5` öffnen und mit **F7**
kompilieren. Der Indikator erscheint im Navigator unter `BauBox`.

---

## Vorab das Wichtigste: woher die Zahlen kommen

Ein Footprint ist nur so gut wie seine Datenquelle. MetaTrader 5 liefert je
nach Instrument zwei sehr verschiedene Dinge, und der Indikator sagt in der
Kopfzeile oben links immer, womit er gerade rechnet.

| Quelle | Wann | Was die Zahlen bedeuten |
|---|---|---|
| **echte Abschlüsse** | Börsengehandelte Papiere (Futures, Aktien, MOEX), wenn der Broker echte Ticks mit `Last` und Volumen liefert | Tatsächlich gehandelte Kontrakte, mit der vom Handelsplatz gemeldeten Käufer-/Verkäuferkennung. Das ist ein echter Footprint. |
| **Bid/Ask-Ticks** | Forex und die meisten CFDs | Es gibt kein echtes Volumen. Gezählt werden **Kursbewegungen**: ein Tick, dessen Mittelkurs gestiegen ist, zählt als Kauf, ein gefallener als Verkauf. |
| **M1-Näherung** | Notlösung, wenn für den Zeitraum keine Tickhistorie vorliegt | Das Volumen der M1-Kerzen wird über deren Spanne verteilt. Reine Schätzung, im Chart mit `≈` vor dem Σ markiert. |

Bei Forex ist ein Footprint also **kein Abbild echter Order**, sondern ein
Aktivitätsprofil. Das ist trotzdem brauchbar — Tickzahl und echtes Volumen
korrelieren im Devisenhandel eng —, aber wer die Zahlen für echte Kontrakte
hält, täuscht sich. Wer echten Orderflow will, braucht ein börsengehandeltes
Instrument bei einem Broker, der `Last`-Ticks weiterreicht.

Damit überhaupt etwas zu sehen ist, muss die Tickhistorie vorhanden sein.
Beim ersten Öffnen lädt MetaTrader sie im Hintergrund nach; die Kopfzeile
zeigt dann `(n laden…)`, und die Spalten füllen sich von rechts nach links.

---

## Was im Chart steht

```
        Δ +103            Delta der Kerze (Ask minus Bid)
        Σ 2.817           gehandeltes Volumen der Kerze
     ┌──────────┐
  ▌  │  63x87   │         Bid x Ask auf dieser Preisebene
  ▌  │ 306x231  │         rot = Verkaufsübergewicht, grün = Kaufübergewicht
  ▌  │ 371x231  │  ◄── schwarzer Rahmen: Serie gestapelter Ungleichgewichte
  ▌  │ 317x245  │
     └──────────┘
  ▲
  eigene Kerze (Körper und Docht)
```

* **Zellfarbe** — Richtung aus dem Delta der Ebene, Stärke wahlweise aus dem
  Delta oder aus dem Volumen. Ausgeglichene Ebenen bleiben blass.
* **Blaue Zahl** — auf dieser Ebene liegt ein *diagonales Ungleichgewicht*:
  das Ask einer Ebene wird gegen das Bid der Ebene darunter gestellt. Ist es um
  den eingestellten Faktor größer (Standard 3,0 = 300 %), war die Seite klar
  aggressiver.
* **Schwarzer Rahmen** — mehrere solche Ungleichgewichte liegen direkt
  übereinander (Standard: ab 3). Solche Zonen gelten als die interessanteste
  Spur im Footprint, weil dort jemand über mehrere Ebenen hinweg in den Markt
  hineingekauft oder -verkauft hat.
* **Grauer Rahmen** — Point of Control, die Ebene mit dem meisten Volumen.
* **Grauer Streifen rechts** — Value Area, standardmäßig 70 % des Volumens.
* **Orangefarbener Strich am Hoch oder Tief** — unvollendete Auktion: am
  äußersten Kurs wurde auf beiden Seiten gehandelt. Solche Extreme werden
  häufig noch einmal angelaufen.
* **Δ und Σ** — Delta und Volumen der ganzen Kerze, wahlweise über und/oder
  unter der Spalte.

Wird weit herausgezoomt, passen keine Zahlen mehr in die Zellen. Dann bleiben
die Farbflächen stehen und der Chart liest sich als Heatmap.

---

## Einstellungen

### Preisraster

| Parameter | Bedeutung |
|---|---|
| `InpTicksPerLevel` | Wie viele Ticks eine Preisebene hoch ist. `0` = automatisch |
| `InpAutoLevels` | Bei Automatik: angepeilte Anzahl Ebenen je Kerze (Standard 16) |

Das Raster ist der wichtigste Regler. Zu fein, und jede Kerze wird zu einer
unlesbaren Säule aus Einsen; zu grob, und die Ungleichgewichte verschwinden im
Mittel. Die Automatik misst die mittlere Kerzenhöhe der letzten 60 Kerzen und
wählt einen runden Wert.

### Datenquelle

| Parameter | Bedeutung |
|---|---|
| `InpSource` | `AUTO` erkennt selbst, ob echte Abschlüsse vorliegen |
| `InpQuotePrice` | Bei Bid/Ask-Ticks: welcher Kurs die Ebene bestimmt. `Bid` deckt sich mit den Kerzen von MetaTrader |
| `InpAllowM1` | M1-Näherung erlauben, wenn keine Ticks da sind |
| `InpMaxBars` | Wie viele Kerzen gleichzeitig im Speicher liegen |
| `InpBudget` | Wie viele Kerzen je Arbeitsschritt aufgebaut werden. Kleiner = flüssigeres Terminal, langsamerer Aufbau |

### Anzeige

`InpMode` schaltet zwischen **Bid x Ask**, **Delta je Ebene**, **Volumen je
Ebene** und einem reinen **Volumenprofil**. `InpHideCandles` blendet die
Standardkerzen von MetaTrader aus, damit sie nicht durch die Zahlen laufen —
die ursprünglichen Farben werden beim Entfernen des Indikators
wiederhergestellt.

Für die Zahlen empfiehlt sich eine Schrift mit gleicher Zeichenbreite
(Standard `Consolas`), sonst sitzt das `x` nicht sauber zwischen den Zahlen.
Die Schriftgröße wird automatisch so gewählt, dass sie in die Zelle passt;
`InpFontMax` und `InpFontMin` begrenzen den Bereich.

Die Vorlage sieht auf hellem Hintergrund am besten aus. In MetaTrader:
Rechtsklick → Eigenschaften → Farben → Vorlage „Schwarz auf Weiß“.

### Ungleichgewichte

| Parameter | Standard | Bedeutung |
|---|---|---|
| `InpImbRatio` | 3,0 | Ab welchem Verhältnis eine Diagonale als Ungleichgewicht gilt |
| `InpImbMinVol` | 4 | Mindestvolumen einer Zelle, damit sie überhaupt zählt |
| `InpStackMin` | 3 | Ab wie vielen Ebenen übereinander eine Serie umrahmt wird |
| `InpVaPercent` | 70 | Anteil des Volumens in der Value Area |

Der Mindestwert ist kein Beiwerk: ohne ihn wird jede Zelle mit `0x2` zum
„unendlichen“ Ungleichgewicht, und der Chart steht voller Markierungen ohne
Aussage.

---

## Zahlen für einen Expert Advisor

Der Indikator legt fünf Puffer an, die sich per `iCustom` auslesen lassen —
und die im Datenfenster von MetaTrader mitlaufen:

| Puffer | Inhalt |
|---|---|
| 0 | Delta der Kerze |
| 1 | kumuliertes Delta über die gespeicherten Kerzen |
| 2 | Kurs des Point of Control |
| 3 | Volumen der Kerze |
| 4 | Serien-Signal: `+1` Serie aufwärts, `-1` abwärts, `0` keine |

```mql5
int h = iCustom(_Symbol, _Period, "BauBox\\Footprint");
double sig[];
ArraySetAsSeries(sig, true);
CopyBuffer(h, 4, 0, 3, sig);      // Puffer 4 = Serien-Signal
```

Das kumulierte Delta beginnt am ältesten gespeicherten Kerzenwert, nicht am
Anfang der Historie — es taugt zum Vergleich innerhalb des Sichtbereichs, nicht
als absolute Größe.

---

## Grenzen, die man kennen sollte

* **Kein echtes Volumen im Devisenhandel.** Siehe oben. Der Indikator behauptet
  das auch nirgends, sondern schreibt seine Quelle in die Kopfzeile.
* **Die Tickregel ist eine Regel, keine Messung.** Ein Tick ohne Kursänderung
  erbt die vorherige Richtung. Bei sehr ruhigem Markt verzerrt das die Bilanz.
* **Tickhistorie ist endlich.** Wie weit sie zurückreicht, entscheidet der
  Broker. Davor greift die M1-Näherung, sofern erlaubt — erkennbar am `≈`.
* **Rechenaufwand.** Ein Tag M1-Footprint auf einem aktiven Symbol sind
  Millionen Ticks. `InpMaxBars` und `InpBudget` halten das im Rahmen; wer weit
  zurückblättert, wartet.
* **Ungleichgewichte sind kein Signal.** Sie zeigen, wo aggressiv gehandelt
  wurde. Ob das ein Einstieg ist, entscheidet der Zusammenhang — Marktstruktur,
  Tageszeit, übergeordnete Richtung.

---

## Aufbau des Quelltextes

| Datei | Aufgabe |
|---|---|
| `MQL5/Indicators/BauBox/Footprint.mq5` | Parameter, Lebenszyklus, Puffer |
| `MQL5/Include/BauBox/Footprint/FpTypes.mqh` | Datenmodell einer Kerze, Ungleichgewichte, Value Area |
| `MQL5/Include/BauBox/Footprint/FpEngine.mqh` | Ticks lesen, einsortieren, zwischenspeichern |
| `MQL5/Include/BauBox/Footprint/FpRender.mqh` | Zeichnen auf eine Leinwand (`CCanvas`) |
| `MQL5/Include/BauBox/Footprint/FpUtil.mqh` | Farben, Zahlenformate |

Gezeichnet wird nicht mit Chartobjekten, sondern auf ein einziges Bitmap über
dem Chart. Bei 50 Kerzen mal 30 Ebenen wären es sonst tausende Objekte, und das
Terminal wird zäh.
