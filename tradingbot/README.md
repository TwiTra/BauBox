# PAX – Price Action eXpert

Ein eigenständiges Handelssystem für MetaTrader 5: Es liest die Marktstruktur auf
drei Zeithorizonten, kombiniert mehrere KI-Modelle zu einer kalibrierten
Wahrscheinlichkeit, rechnet Positionsgrößen aus, führt offene Trades nach und
lernt aus jedem abgeschlossenen Geschäft dazu.

```bash
python main.py selftest     # interne Prüfungen, allen voran auf Lookahead
python main.py backtest     # Strategie auf der Historie
python main.py live         # Livebetrieb (standardmäßig Trockenlauf)
```

---

## Vorab, damit keine falschen Erwartungen entstehen

„Perfekte Signale“ gibt es nicht. Wer das verspricht, verkauft etwas. Märkte sind
nicht stationär: Was drei Jahre lang funktioniert hat, hört ohne Vorwarnung auf zu
funktionieren, und kein Modell der Welt sieht das kommen.

Was dieses Programm stattdessen leistet:

* Es rechnet **ehrlich**. Jede Zahl entsteht unter Annahmen, die eher zu
  pessimistisch als zu freundlich sind.
* Es sagt, **wann es nichts weiß**. Findet das Training keinen messbaren Vorteil,
  steht das im Bericht – statt einer schön aussehenden Kurve.
* Es lässt sich **prüfen**. Der Befehl `selftest` weist maschinell nach, dass kein
  Merkmal in die Zukunft schaut. Ohne diesen Nachweis ist jeder Backtest wertlos.
* Es **überlebt Fehler**: Verlustgrenzen, Notaus und Trockenlauf sind keine
  Nebenfunktionen, sondern der Kern.

Der Vorteil, den ein solches System realistisch erreicht, ist klein – eine
Trefferquote leicht über dem Zufall bei ordentlichem Chance-Risiko-Verhältnis. Das
reicht, wenn das Risikomanagement stimmt. Ohne dieses reicht auch ein großer
Vorteil nicht.

### Der bisher gemessene Stand

Damit hier keine Behauptung ohne Zahl steht — der Vorwärtstest auf **echten
EURUSD-Tickdaten** (33 Mio. Ticks, Januar 2025 bis September 2026, fünf Fenster,
jedes Modell kannte nur Daten vor seinem Fenster):

| | |
|---|---|
| Trades | 19 |
| Erwartungswert | **−0,42 R je Trade** |
| Summe | −8,0 R (−7,7 %) |
| Trefferquote | 36,8 % |
| AUC der Modelle | 0,538 ± 0,028 |
| PSR | 0,03 |

**Das ist kein Vorteil.** Die Modelle liegen mit AUC 0,538 knapp über dem Zufall,
aber der Vorsprung trägt die Kosten nicht — allein Spread und Kommission fressen
24 % des Bruttoergebnisses. Der PSR von 0,03 sagt genau das: Die Wahrscheinlichkeit,
dass hier ein echter Vorteil vorliegt, ist gering. Bei 19 Trades ist umgekehrt auch
das Gegenteil nicht bewiesen — die Stichprobe ist für beides zu klein.

Diese Zahl steht hier, weil sie das Ergebnis ist. Sie durch Nachjustieren der
Schwellen freundlicher zu machen, wäre genau die Anpassung an die Vergangenheit,
gegen die der ganze Rest dieses Programms gebaut ist.

---

## Was drinsteckt

### 1. Marktstruktur statt Indikatorensalat

Grundlage ist die Abfolge der Hoch- und Tiefpunkte, so wie ein Chartleser sie liest:

| Baustein | Was er erkennt |
|---|---|
| **Swings** | Fraktale Wendepunkte, per ATR entrauscht – erst nach Bestätigung nutzbar |
| **BOS** | Break of Structure: der Trend bestätigt sich |
| **CHoCH** | Change of Character: der erste Bruch gegen die Struktur |
| **Order Blocks** | Letzte Gegenkerze vor dem Impuls, der die Struktur brach |
| **Fair Value Gaps** | Drei-Kerzen-Imbalances, die der Markt oft nachholt |
| **Liquidität** | Gleiche Hochs/Tiefs – dort liegen die Stops |
| **Sweeps** | Über ein Niveau laufen und darunter zurückschließen |
| **Premium/Discount** | Wo in der Spanne der Kurs steht – der Einstiegsort |
| **S/R-Cluster** | Geclusterte Swing-Niveaus mit Zähler, wie oft getestet |
| **Volumenprofil** | POC und Value Area – wo tatsächlich Umsatz stattfand |

Indikatoren (ATR, RSI, ADX, MACD, Bollinger, Donchian, Supertrend, VWAP, Hurst,
Kaufmans Effizienzquotient …) kommen dazu – als Kontext, nicht als Entscheider.
Alles in reinem numpy/pandas, kein TA-Lib, keine Kompilierung.

### 2. Drei Zeithorizonte, sauber getrennt

| Horizont | Standard | Aufgabe |
|---|---|---|
| langfristig | H4 | Richtung und Kontext |
| mittelfristig | H1 | Aufbau des Setups |
| kurzfristig | M15 | Einstieg und Timing |

Der Kniff steckt in der Zeitverschiebung: Ein H4-Balken, der um 12:00 öffnet, ist
erst um 16:00 abgeschlossen. Sein Wert darf frühestens ab 16:00 auf die M15-Ebene
gelegt werden. Genau das prüft `selftest` Punkt 3 – Balken für Balken.

Widersprechen sich die Ebenen, fällt die Bewertung stark ab statt sich nur
wegzumitteln. Ein starker H4-Long und ein starker M15-Short ergeben kein
„halb so gutes Setup“, sondern gar keins.

### 3. Das KI-Ensemble

Mehrere Verfahren, weil jedes anders danebenliegt: Gradient Boosting
(HistGradientBoosting, LightGBM, XGBoost, CatBoost), Random Forest, Extra Trees,
logistische Regression und ein kleines neuronales Netz. Fehlt eine Bibliothek,
entfällt genau dieses Mitglied – der Rest arbeitet weiter.

Der Trainingsablauf ist bewusst konservativ:

1. Merkmalsauswahl: konstante und stark korrelierte Spalten fliegen raus
2. Out-of-Fold-Vorhersagen über **gesperrte** Faltungen (Purging + Embargo)
3. Mitglieder unter der Mindest-AUC fliegen aus dem Ensemble
4. Verschmelzung per Stapelung, Gewichtung oder Mittelwert
5. **Kalibrierung** – aus einem Score wird eine belastbare Wahrscheinlichkeit
6. Neutraining aller Mitglieder auf allen Daten

Schritt 5 wird meist übersehen und ist für den Handel der wichtigste: Die
Positionsgröße hängt direkt an der Wahrscheinlichkeit. Ein Modell, das bei jedem
zweiten Setup „80 %“ sagt, ruiniert das Konto durch zu große Positionen – selbst
wenn seine Rangfolge stimmt.

### 4. Zielvariable: Triple Barrier

Die naive Frage „steht der Kurs in zehn Balken höher?“ ist für den Handel wertlos –
sie ignoriert, dass die Position vorher ausgestoppt worden wäre. Stattdessen gilt:
*Wird zuerst das Ziel oder zuerst der Stop getroffen?* Drei Barrieren begrenzen
jedes Beispiel, alle in ATR skaliert.

**Die Richtungsfrage braucht symmetrische Barrieren.** Das klingt nach einem
Detail und ist keines. Bei einem Verhältnis von 2:1 trifft schon ein driftloser
Zufallspfad die obere Barriere nur in einem Drittel der Fälle; ein sauber
kalibriertes Modell gibt dann im Mittel 0,33 aus. Wer diesen Wert gegen 0,5 als
neutralen Punkt liest, verteilt auf jedem Balken eine Short-Neigung, die nichts
über den Markt aussagt, sondern nur über die Barrierewahl. `direction_labels`
nimmt deshalb nur *einen* Abstand entgegen (`labels.direction_atr`, Vorgabe 1,5)
— das Verhältnis 2:1 gehört zum Trade, nicht zur Richtungsfrage.

Ebenso gilt: Ein weiter entferntes Ziel ist kein Vorteil, sondern ein selteneres
Ereignis. Der Erwartungswert wird deshalb am fairen Wert verankert: Ohne
erkennbaren Vorteil ist er exakt null, bei jedem Chance-Risiko-Verhältnis.

Dazu Stichprobengewichte nach Einzigartigkeit: Überlappende Beispiele enthalten
dieselbe Kursinformation mehrfach. Auf typischen Daten schrumpft die effektive
Stichprobe dadurch von 8 000 auf unter 1 000 – wer das ignoriert, hält sein Modell
für achtmal sicherer, als es ist.

### 5. Risikomanagement

Der Teil, den man vollständig kontrollieren kann.

* Festes Risiko je Trade, per **fraktionalem Kelly** gedämpft. Kelly darf nach
  unten stark korrigieren, nach oben höchstens auf das 1,5-fache des eingestellten
  Werts. Wer 0,5 % einstellt, steht nicht plötzlich mit 2 % im Markt.
* Stop hinter der Struktur, nicht nach Formel – begrenzt auf ein sinnvolles
  ATR-Band.
* Korrelierte Positionen zählen zusammen. Drei Longs in EURUSD, GBPUSD und AUDUSD
  sind ein Trade, nicht drei.
* Tages-, Wochen- und Gesamtverlustgrenze mit hartem Notaus.
* Nach Verlustserien wird die Positionsgröße automatisch kleiner.

### 6. Positionsführung, die einen Neustart übersteht

MetaTrader kennt weder den ursprünglichen Stop noch die Zahl der bereits
genommenen Teilgewinne. Diese Angaben führt das System selbst - und legt sie im
Journal ab. Ohne diese Ablage begänne der Bot nach jedem Stromausfall oder
Windows-Update bei null: Er hielte den längst nachgezogenen Stop für den
ursprünglichen (im Test ein Risiko-Fehlfaktor von 10), verlöre die restlichen
Teilziele und schaltete den Zeitausstieg stillschweigend ab.

### 7. Die Lernschleife

```
Handeln → Journal → Fehleranalyse → Sperren
                 ↘ Nachtraining → Vorwärtsvergleich → Ablösung?
```

**Fehleranalyse** zerlegt die Historie nach Regime, Horizont, Handelszeit,
Signalstärke und Symbol und sucht Bereiche mit dauerhaft negativem Erwartungswert.
Wo genug Belege vorliegen, entsteht eine **Sperre** – das System hört auf, denselben
Fehler zu wiederholen. Zwei Schutzmechanismen halten das ehrlich: eine
Mindestanzahl an Trades (fünf Verluste sind Zufall, keine Erkenntnis) und ein
Ablaufdatum (Märkte ändern sich zurück).

**Champion/Challenger:** Ein Herausforderer wird trainiert, im Vorwärtstest gegen
den amtierenden Champion gemessen und nur bei klarem, beständigem Vorsprung
übernommen. Ohne diese Hürde verwandelt sich jede Lernschleife binnen Wochen in
einen Zufallsgenerator, der dem letzten Rauschen hinterherläuft.

**Driftmessung** über den Population Stability Index: Verschiebt sich die
Merkmalsverteilung, wird unabhängig vom Zeitplan nachtrainiert.

---

## Installation

### Windows (für den Livebetrieb)

MetaTrader 5 installieren, dann `start.bat` doppelklicken. Beim ersten Lauf werden
Umgebung und Abhängigkeiten eingerichtet, danach erscheint ein Menü.

Von Hand:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-extra.txt
python main.py init
```

### Linux / macOS (Analyse, Backtest, Training)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py init
```

Das Paket `MetaTrader5` gibt es nur für Windows. Alles außer Live-Daten und
Orderausführung funktioniert trotzdem – auf zwischengespeicherten oder
synthetischen Daten.

### Zugangsdaten

Gehören **nicht** in die Konfigurationsdatei:

```bash
export MT5_LOGIN=12345678
export MT5_PASSWORD=...
export MT5_SERVER=Broker-Server
```

```bat
set MT5_LOGIN=12345678
set MT5_PASSWORD=...
set MT5_SERVER=Broker-Server
```

---

## Befehle

| Befehl | Zweck |
|---|---|
| `init` | Konfigurationsdatei anlegen |
| `status` | Überblick: Daten, Modelle, Journal |
| `connect` | MT5-Verbindung und Symbole prüfen |
| `fetch` | Historie vom Broker herunterladen |
| `import` | eigene Kursdaten aus CSV übernehmen (MT4/MT5/Dukascopy/allgemein) |
| `analyse` | Aktuelle Lage und Signal, mit Begründung |
| `backtest` | Strategie auf der Historie. Mit Modell **vorwärts**: je Fenster ein eigenes, blindes Modell |
| `train` | Modell anlernen |
| `walkforward` | Vorwärtstest – die ehrlichste Prüfung |
| `evolve` | Lernschleife: nachtrainieren, vergleichen, ggf. ablösen |
| `feedback` | Fehleranalyse aus dem Journal |
| `live` | Livebetrieb (standardmäßig Trockenlauf) |
| `journal` | Statistik und CSV-Export |
| `selftest` | Interne Prüfungen, allen voran auf Lookahead |

Nützliche Schalter: `-s EURUSD,GBPUSD` wählt Symbole, `-n 20000` die Balkenzahl,
`-v` schaltet ausführliche Protokollierung ein.

---

## Eigene Kursdaten einlesen

Wer Minutendaten hat, braucht für die Auswertung kein Terminal:

```bash
python main.py import EURUSD_M1.csv --symbol EURUSD --tz-shift 2
```

Erkannt werden die üblichen Ausgabeformate von selbst - MT5 („Bars exportieren",
Tabulator, Kopfzeile in spitzen Klammern), MT4-Historie ohne Kopfzeile,
Dukascopy, sowie allgemeine Dateien mit Semikolon oder deutschem Dezimalkomma.
Die Datei wird auf alle konfigurierten Zeitebenen verdichtet und abgelegt.

Für **Tickdaten** — die Rohausgabe von MT5 mit Geld- und Briefkurs je Tick —
gibt es `--ticks`. Die Datei wird blockweise gelesen, sodass auch mehrere
Gigabyte nicht in den Speicher müssen:

```bash
python main.py import EURUSD_ticks.csv --symbol EURUSD --ticks --tz Europe/Athens
```

Kerzen entstehen aus dem Mittelkurs. Einseitige Ticks (nur Geld- oder nur
Briefkurs) werden je Seite fortgeschrieben; wer beide Seiten gemeinsam
fortschreibt, erzeugt Kurssprünge, die es nie gab. Ist der Spread in der Datei
unbrauchbar — bei vielen Exporten steht dort durchgehend 0 —, wird die Spalte
verworfen statt stillschweigend übernommen. Ein Backtest ohne Spread ist ein
Backtest ohne Kosten und damit wertlos.

**Der Zeitversatz ist der wichtigste Schalter.** MT5 exportiert in *Serverzeit*,
meist UTC+2 im Winter und UTC+3 im Sommer; gerechnet wird durchgehend in UTC.
Ohne `--tz-shift` sind sämtliche Handelszeitfenster um Stunden verschoben, und
man misst etwas anderes, als man glaubt. Zur Probe: Das Umsatzmaximum eines
Devisenpaares liegt in UTC gegen 13-15 Uhr. Liegt es woanders, stimmt der
Versatz nicht. Mit `--dry-run` lässt sich das prüfen, ohne etwas zu schreiben.

Besser als `--tz-shift` ist `--tz Europe/Athens`: Ein fester Versatz ist ein
halbes Jahr lang um eine Stunde daneben, weil die Sommerzeit fehlt. Die
mehrdeutige Stunde der Zeitumstellung wird verworfen, nicht geraten.

## Der Weg zum Livebetrieb

Diese Reihenfolge ist keine Empfehlung, sondern die Mindestanforderung.

**1. Selbsttest** – ohne diesen Nachweis ist alles Weitere Zeitverschwendung.

```bash
python main.py selftest
```

**2. Daten holen.** Mindestens ein Jahr, besser drei.

```bash
python main.py fetch -n 50000
```

**3. Vorwärtstest.** Die Zahl, auf die es ankommt.

```bash
python main.py walkforward --folds 6
```

Liegt die mittlere AUC unter etwa 0,52 oder ist sie nur in der Hälfte der Fenster
über 0,5, gibt es keinen belastbaren Vorteil. Dann hilft kein Nachjustieren an den
Parametern – das erzeugt nur einen Vorteil, der aus dem Optimieren stammt und live
sofort verschwindet.

**4. Backtest.** Sobald ein Modell im Spiel ist, läuft er **vorwärts**: Die
Historie wird in Fenster geteilt, für jedes entsteht ein eigenes Modell aus
ausschließlich früheren Daten, und gehandelt wird nur im Fenster selbst. Kein
Balken wird also von einem Modell gehandelt, das ihn kannte.

```bash
python main.py backtest --trials 20 --folds 6
```

`--trials` gibt an, wie viele Varianten ausprobiert wurden; der Deflated Sharpe
korrigiert das Ergebnis entsprechend nach unten.

Zum Vergleich, gemessen auf identischen Daten:

| | in-sample | vorwärts |
|---|---|---|
| Gewinn | +80,7 % | +4,7 % |
| Trefferquote | 77,7 % | 60,0 % |
| Sharpe | 2,57 | 0,35 |
| max. Rückgang | 3,25 % | 7,05 % |

Dieselbe Strategie, dieselben Kurse. Der Unterschied ist allein, ob das Modell
die Antworten schon kannte. `--in-sample` erzwingt den linken Weg – nur zur
Fehlersuche, mit entsprechender Warnung im Bericht.

**5. Trockenlauf, mehrere Wochen.** Volle Mechanik, keine echten Orders.

```bash
python main.py live
```

**6. Echtgeld – mit dem kleinsten Betrag, dessen Verlust völlig gleichgültig ist.**

```bash
python main.py live --real
```

Zwischen Schritt 5 und 6 gehören Wochen, keine Stunden.

---

## Konfiguration

`config/config.example.yaml` enthält jeden Wert mit Erläuterung. Die wichtigsten:

```yaml
risk:
  risk_per_trade: 0.005      # 0,5 % des Kontos je Trade
  max_daily_loss: 0.03       # danach ist für heute Schluss
  max_drawdown_stop: 0.15    # Notaus
  min_signal_score: 0.45     # Überzeugungsschwelle (obere ~1,5 % der Balken)
  min_risk_reward: 1.4

execution:
  dry_run: true              # erst nach Schritt 5 umstellen
```

Zur Score-Skala: Sie läuft von 0 bis 1 und entsteht aus einer sättigenden Kennlinie
über der gewichteten Regel- und Modellbewertung. 0,45 entspricht ungefähr den
obersten 1,5 % aller Balken – selektiv, aber nicht so streng, dass nie ein Trade
zustande kommt. 0,58 wäre schon extrem eng.

---

## Was das System bewusst *nicht* tut

* **Keine Gitteroptimierung über Strategieparameter.** Sie ist der schnellste Weg zu
  einem Backtest, der wunderschön aussieht und live sofort zerfällt. Wer trotzdem
  optimiert, muss `--trials` ehrlich angeben.
* **Kein Martingale, kein Grid, kein Averaging-down.** Diese Verfahren erzeugen
  jahrelang glatte Kurven und dann einen Totalverlust.
* **Keine Positionen ohne Stop.** Ausnahmslos.
* **Kein in-sample-Backtest als Standard.** Sobald ein Modell mitspielt, wird
  vorwärts gerechnet; das geschönte Ergebnis gibt es nur auf ausdrückliche
  Anforderung und mit Warnung.
* **Kein automatisches Schließen beim Beenden.** Offene Positionen tragen
  serverseitige Stops und Ziele, die auch ohne laufenden Bot greifen. Sie beim
  Beenden zu schließen hieße, jeden Neustart mit einem realisierten Verlust zu
  bezahlen.

---

## Aufbau

```
tradingbot/
  main.py                     Einstiegspunkt
  start.bat                   Windows-Menü
  config/config.example.yaml  jeder Wert erklärt
  pax/
    config.py types.py utils.py datasource.py
    data/        MT5-Client, Speicher, Sessions, synthetischer Markt
    features/    Indikatoren, Struktur, Muster, SMC, Level, Regime, Zeitebenen
    labeling/    Triple Barrier, Meta-Labeling, Stichprobengewichte
    models/      Modell-Zoo, Ensemble, Kalibrierung, Versionsverwaltung
    validation/  gesperrte Faltungen, Vorwärtstest, Kennzahlen
    strategy/    Regelwerk, Signal-Engine, Risiko, Portfolio
    backtest/    Engine und Bericht
    execution/   Broker-Abstraktion, Positionsführung
    learning/    Journal, Fehleranalyse, Weiterentwicklung
    live/        Wächter, Hauptschleife
    cli.py       Kommandozeile
  tests/         209 Tests
```

```bash
python -m pytest tests/ -q
```

Die Suite prüft nicht nur, ob der Code läuft, sondern ob er *ehrlich* ist:

* **Kausalität jedes Merkmals** – die Matrix wird zweimal gebaut, einmal mit
  abgeschnittener Zukunft; auf dem gemeinsamen Zeitraum muss die Abweichung
  exakt 0 sein
* **Nicht-Überlappung der Faltungen** inklusive Barrierehorizont
* **Pessimistische Barrierenauflösung** – die optimistische Variante darf nie
  schlechter abschneiden
* **Gegenprobe auf gemischten Labels** – das Ensemble muss dabei auf
  Zufallsniveau bleiben
* **Kursziele dürfen nicht auf ihren Boden kollabieren** – der Regressionstest
  gegen den Fehler, bei dem ein Nebenlevel direkt neben dem Kurs jedes CRV
  deckelte und der Backtest still null Trades lieferte

Bei jeder Änderung unter `tradingbot/` läuft auf GitHub zusätzlich der Workflow
`Handelssystem testen` (Python 3.11 und 3.12): Testsuite, Selbsttest und ein
Probe-Backtest. Der Selbsttest ist dort der eigentliche Punkt – ein
Lookahead-Fehler fällt beim Lesen praktisch nie auf, also soll ihn bei jeder
Änderung eine Maschine suchen.

---

## Haftungsausschluss

Handel mit Devisen und CFDs birgt erhebliche Risiken und kann zum Totalverlust
führen. Diese Software ist ein Werkzeug, keine Anlageberatung und keine
Gewinngarantie. Vergangene Ergebnisse – auch aus Backtests – sagen nichts über die
Zukunft. Der Betrieb erfolgt auf eigenes Risiko. Vor dem Einsatz von echtem Geld:
Trockenlauf, kleines Konto, und nur Kapital, dessen Verlust verkraftbar ist.
