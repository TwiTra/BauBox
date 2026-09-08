"""Tickdaten zu Kerzen verdichten.

MT5 exportiert Ticks im Format

    <DATE>  <TIME>  <BID>  <ASK>  <LAST>  <VOLUME>  <FLAGS>
    2025.01.02  00:00:26.247  1.03515  1.03587      6
    2025.01.02  00:00:33.699           1.03585      4

Zwei Eigenheiten muss man kennen:

* **Bid und Ask stehen einzeln.** Ein Tick, der nur den Briefkurs ändert, lässt
  den Geldkurs leer. Wer die Zeilen einfach wegwirft, verliert die Hälfte der
  Daten; wer die Lücken als Null liest, bekommt Unsinn. Beide Seiten werden
  deshalb einzeln fortgeschrieben.
* **Der Spread ist echt.** Das ist der eigentliche Gewinn gegenüber fertigen
  Kerzen: Statt einen Spread zu schätzen, lässt er sich je Kerze messen - und
  damit wird das Kostenmodell des Backtests belastbar statt geraten.

Die Datei wird in Blöcken gelesen und blockweise verdichtet, nie am Stück
geladen. Eine Tickdatei über zwei Jahre hat leicht mehrere Gigabyte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..types import Timeframe
from ..utils import get_logger, to_utc_index

log = get_logger("ticks")

TICK_COLUMNS = ["date", "time", "bid", "ask", "last", "volume", "flags"]

#: Unterhalb dieses Median-Spreads (in Punkten) gilt die Spalte als nicht
#: belastbar. Selbst der engste EURUSD-Broker bleibt über 3 Punkten; alles
#: darunter heißt, dass der Feed den Spread nicht mitliefert.
MIN_PLAUSIBLE_SPREAD_POINTS = 3.0


@dataclass
class TickReport:
    """Was beim Verdichten herauskam."""

    path: str = ""
    ticks: int = 0
    bars: int = 0
    timeframe: str = ""
    first: "pd.Timestamp | None" = None
    last: "pd.Timestamp | None" = None
    tz_shift_hours: float = 0.0
    tz: str = ""
    spread_median_points: float = 0.0
    spread_p90_points: float = 0.0
    spread_max_points: float = 0.0
    only_bid: int = 0
    only_ask: int = 0
    spread_usable: bool = True
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"  Datei              {self.path}",
            f"  Ticks              {self.ticks:,}".replace(",", " "),
            f"  Kerzen             {self.bars:,} auf {self.timeframe}".replace(",", " "),
            f"  Zeitraum           {self.first} bis {self.last}",
            f"  nur Geldkurs       {self.only_bid:,}".replace(",", " "),
            f"  nur Briefkurs      {self.only_ask:,}".replace(",", " "),
            f"  Spread (Punkte)    Median {self.spread_median_points:.1f} | "
            f"90 % unter {self.spread_p90_points:.1f} | Maximum {self.spread_max_points:.1f}"
            + ("" if self.spread_usable else "   -> VERWORFEN, siehe unten"),
        ]
        if self.tz:
            lines.append(f"  Zeitzone           {self.tz} (mit Sommerzeit) auf UTC gerechnet")
        elif self.tz_shift_hours:
            lines.append(f"  Zeitversatz        {self.tz_shift_hours:+g} Stunden auf UTC gerechnet")
        for w in self.warnings:
            lines.append(f"  ! {w}")
        return "\n".join(lines)


def aggregate_ticks(
    path: "str | Path",
    timeframe: "str | Timeframe" = Timeframe.M1,
    tz_shift_hours: float = 0.0,
    tz: "str | None" = None,
    point: float = 0.00001,
    chunksize: int = 2_000_000,
    report: "TickReport | None" = None,
    progress: bool = True,
) -> pd.DataFrame:
    """Tickdatei zu OHLCV-Kerzen verdichten - blockweise, speicherschonend.

    Die Kerzen entstehen aus dem Mittelkurs `(bid + ask) / 2`; zusätzlich wird
    je Kerze der mittlere Spread in Punkten mitgeführt.
    """
    tf = Timeframe.parse(timeframe)
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {p}")
    report = report or TickReport()
    report.path, report.timeframe = str(p), tf.value
    report.tz_shift_hours = tz_shift_hours

    freq = f"{tf.minutes}min"
    teile: list[pd.DataFrame] = []
    letzter_bid = np.nan
    letzter_ask = np.nan
    gelesen = 0

    leser = pd.read_csv(
        p, sep="\t", header=None, names=TICK_COLUMNS, skiprows=1,
        dtype={"bid": "float64", "ask": "float64"},
        usecols=["date", "time", "bid", "ask"],
        chunksize=chunksize, encoding="utf-8-sig",
    )

    for block_nr, block in enumerate(leser, 1):
        gelesen += len(block)
        report.only_bid += int((block["bid"].notna() & block["ask"].isna()).sum())
        report.only_ask += int((block["ask"].notna() & block["bid"].isna()).sum())

        # Beide Seiten einzeln fortschreiben - über Blockgrenzen hinweg
        block["bid"] = block["bid"].ffill()
        block["ask"] = block["ask"].ffill()
        if np.isfinite(letzter_bid):
            block["bid"] = block["bid"].fillna(letzter_bid)
        if np.isfinite(letzter_ask):
            block["ask"] = block["ask"].fillna(letzter_ask)
        gueltig = block["bid"].notna() & block["ask"].notna()
        block = block[gueltig]
        if block.empty:
            continue
        letzter_bid = float(block["bid"].iloc[-1])
        letzter_ask = float(block["ask"].iloc[-1])

        zeit = pd.to_datetime(
            block["date"] + " " + block["time"], format="%Y.%m.%d %H:%M:%S.%f", errors="coerce"
        )
        block = block.assign(zeit=zeit).dropna(subset=["zeit"])
        if block.empty:
            continue

        mid = (block["bid"] + block["ask"]) / 2.0
        spread = (block["ask"] - block["bid"]).clip(lower=0)
        eimer = block["zeit"].dt.floor(freq)

        # Teilaggregate je Kerze - über Blöcke hinweg zusammenführbar
        teil = pd.DataFrame({"bucket": eimer, "mid": mid, "spread": spread}).groupby(
            "bucket", sort=False
        ).agg(
            open=("mid", "first"), high=("mid", "max"), low=("mid", "min"),
            close=("mid", "last"), ticks=("mid", "size"), spread_sum=("spread", "sum"),
            spread_max=("spread", "max"),
        )
        teile.append(teil)
        if progress and block_nr % 5 == 0:
            log.info("  %d Blöcke verarbeitet (%s Ticks)", block_nr, f"{gelesen:,}".replace(",", " "))

    if not teile:
        raise ValueError(f"{p} enthält keine auswertbaren Ticks")

    roh = pd.concat(teile)
    # Nur die Kerze an der Blockgrenze ist geteilt - der zweite Zusammenzug fügt sie.
    bars = roh.groupby(level=0, sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), ticks=("ticks", "sum"),
        spread_sum=("spread_sum", "sum"), spread_max=("spread_max", "max"),
    )
    bars["volume"] = bars["ticks"].astype("float64")
    bars["spread"] = (bars["spread_sum"] / bars["ticks"].replace(0, np.nan)) / point
    bars = bars.drop(columns=["spread_sum", "ticks"])

    neuer_index, verworfen = to_utc_index(bars.index, tz=tz, shift_hours=tz_shift_hours)
    bars.index = neuer_index
    bars.index.name = "time"
    if verworfen:
        bars = bars[bars.index.notna()]
        report.warnings.append(
            f"{verworfen} Kerzen an der Zeitumstellung verworfen - die Stunde gibt es doppelt"
        )
    report.tz = tz or ""

    report.ticks = gelesen
    report.bars = len(bars)
    report.first, report.last = bars.index[0], bars.index[-1]
    spreads = bars["spread"].dropna()
    if len(spreads):
        report.spread_median_points = round(float(spreads.median()), 2)
        report.spread_p90_points = round(float(spreads.quantile(0.9)), 2)
        report.spread_max_points = round(float((bars["spread_max"] / point).max()), 2)
    if report.only_bid + report.only_ask > gelesen * 0.9:
        report.warnings.append(
            "Fast alle Ticks nennen nur eine Seite - der Spread ist dann teils fortgeschrieben"
        )

    # --- Plausibilitätsriegel für den Spread --------------------------- #
    # Manche Feeds liefern Geld- und Briefkurs identisch. Ein Spread von null
    # ist bei keinem Broker echt, und mit ihm zu rechnen hieße, kostenlos zu
    # handeln - der häufigste Grund, warum Backtests glänzen und Konten nicht.
    # In dem Fall fliegt die Spalte raus, statt eine Zahl zu liefern, der
    # später jemand glaubt.
    report.spread_usable = report.spread_median_points >= MIN_PLAUSIBLE_SPREAD_POINTS
    if not report.spread_usable:
        anteil_null = float((spreads <= 0.05).mean()) if len(spreads) else 1.0
        report.warnings.append(
            f"Spread unbrauchbar: Median {report.spread_median_points:.2f} Punkte, "
            f"{anteil_null * 100:.0f} % der Kerzen praktisch bei null. Echtes EURUSD liegt bei "
            f"5-15 Punkten. Die Spalte wird verworfen - der Backtest rechnet mit dem "
            f"konfigurierten Spread."
        )
        bars = bars.drop(columns=["spread"])

    spalten = ["open", "high", "low", "close", "volume"]
    if "spread" in bars.columns:
        spalten.append("spread")
    return bars.drop(columns=["spread_max"])[spalten]


def infer_server_offset(bars: pd.DataFrame) -> dict[str, float]:
    """Zeitversatz des Brokers aus dem Handelsrhythmus schätzen.

    Zwei unabhängige Anhaltspunkte, die sich gegenseitig prüfen:

    * **Umsatzmaximum**: Die Überschneidung London/New York liegt in UTC bei
      etwa 13-15 Uhr. Wo das Tickaufkommen gipfelt, verrät den Versatz.
    * **Wochenschluss**: Der Devisenhandel endet freitags 22:00 UTC. Der letzte
      Freitagstick zeigt dieselbe Verschiebung.

    Die Rückgabe ist eine Schätzung, kein Beweis - sie soll dem Anwender die
    Entscheidung erleichtern, nicht sie ihm abnehmen.
    """
    if bars.empty:
        return {}
    stunden = bars.index.hour + bars.index.minute / 60.0
    volumen = bars["volume"].to_numpy(dtype=float)
    je_stunde = pd.Series(volumen).groupby(bars.index.hour).sum()
    gipfel = float(je_stunde.idxmax())

    freitags = bars[bars.index.dayofweek == 4]
    letzte_stunde = float(freitags.index.hour.max()) if len(freitags) else np.nan

    return {
        "umsatz_gipfel_stunde": gipfel,
        "versatz_aus_umsatz": round(gipfel - 14.0, 1),
        "letzter_freitagstick_stunde": letzte_stunde,
        "versatz_aus_wochenschluss": round(letzte_stunde - 21.0, 1)
        if np.isfinite(letzte_stunde) else float("nan"),
    }
