"""Tickdaten zu Kerzen verdichten - und die Fallstricke echter MT5-Exporte.

Die Testfaelle stammen aus einer echten EURUSD-Tickdatei mit 33 Millionen
Zeilen: einseitige Ticks, unbrauchbare Spreads und Serverzeit mit Sommerzeit.
Jeder dieser drei Punkte wuerde stillschweigend falsche Kerzen erzeugen.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pax.data.tick_import import MIN_PLAUSIBLE_SPREAD_POINTS, TickReport, aggregate_ticks
from pax.utils import to_utc_index


def _schreibe(path, zeilen: list[str]) -> str:
    kopf = "<DATE>\t<TIME>\t<BID>\t<ASK>\t<LAST>\t<VOLUME>\t<FLAGS>\n"
    path.write_text(kopf + "".join(zeilen), encoding="utf-8")
    return str(path)


def test_kerzen_entstehen_aus_dem_mittelkurs(tmp_path):
    zeilen = [
        "2025.01.02\t10:00:01.000\t1.03000\t1.03010\t0\t0\t6\n",
        "2025.01.02\t10:00:30.000\t1.03040\t1.03050\t0\t0\t6\n",
        "2025.01.02\t10:00:59.000\t1.02980\t1.02990\t0\t0\t6\n",
        "2025.01.02\t10:01:05.000\t1.03100\t1.03110\t0\t0\t6\n",
    ]
    df = aggregate_ticks(_schreibe(tmp_path / "t.csv", zeilen), "M1", progress=False)
    assert len(df) == 2
    erste = df.iloc[0]
    assert erste["open"] == pytest.approx(1.03005, abs=1e-9)
    assert erste["high"] == pytest.approx(1.03045, abs=1e-9)
    assert erste["low"] == pytest.approx(1.02985, abs=1e-9)
    assert erste["close"] == pytest.approx(1.02985, abs=1e-9)
    assert erste["volume"] == 3


def test_einseitige_ticks_werden_je_seite_fortgeschrieben(tmp_path):
    """Flag 2 ist nur Geld-, Flag 4 nur Briefkurs.

    Wer beide Seiten gemeinsam fortschreibt, uebernimmt den fehlenden Wert als 0
    und erzeugt einen Mittelkurs von der halben Hoehe - ein Kurssprung, den es
    nie gab.
    """
    zeilen = [
        "2025.01.02\t10:00:01.000\t1.03000\t1.03010\t0\t0\t6\n",
        "2025.01.02\t10:00:10.000\t1.03020\t\t0\t0\t2\n",   # nur Geldkurs
        "2025.01.02\t10:00:20.000\t\t1.03040\t0\t0\t4\n",   # nur Briefkurs
    ]
    report = TickReport()
    df = aggregate_ticks(_schreibe(tmp_path / "t.csv", zeilen), "M1",
                         report=report, progress=False)
    assert report.only_bid == 1 and report.only_ask == 1
    # Alle Mittelkurse muessen im Bereich der echten Kurse liegen.
    assert df["low"].min() > 1.02, "fehlende Seite wurde als 0 uebernommen"
    assert df["high"].max() < 1.04


def test_unbrauchbarer_spread_wird_verworfen_statt_verschwiegen(tmp_path):
    """Ein Spread von 0 macht jeden Backtest kostenlos - und damit wertlos."""
    zeilen = [
        f"2025.01.02\t10:00:{s:02d}.000\t1.03000\t1.03000\t0\t0\t6\n" for s in range(5)
    ]
    report = TickReport()
    df = aggregate_ticks(_schreibe(tmp_path / "t.csv", zeilen), "M1",
                         report=report, progress=False)
    assert report.spread_median_points < MIN_PLAUSIBLE_SPREAD_POINTS
    assert report.spread_usable is False
    assert "spread" not in df.columns, "unbrauchbarer Spread darf nicht mitgeliefert werden"
    assert any("preads" in w or "Spread" in w for w in report.warnings)


def test_plausibler_spread_bleibt_erhalten(tmp_path):
    zeilen = [
        f"2025.01.02\t10:00:{s:02d}.000\t1.03000\t1.03012\t0\t0\t6\n" for s in range(5)
    ]
    report = TickReport()
    df = aggregate_ticks(_schreibe(tmp_path / "t.csv", zeilen), "M1",
                         report=report, progress=False)
    assert report.spread_usable is True
    assert "spread" in df.columns
    assert report.spread_median_points == pytest.approx(12.0, abs=0.5)


# --------------------------------------------------------------------------- #
# Zeitzone
# --------------------------------------------------------------------------- #


def test_serverzeit_wird_mit_sommerzeit_umgerechnet():
    """MT5-Server laufen meist auf EET/EEST - im Sommer UTC+3, im Winter UTC+2.

    Ein fester Versatz waere ein halbes Jahr lang um eine Stunde daneben und mit
    ihm jedes Handelszeitfenster.
    """
    idx = pd.DatetimeIndex(["2025-01-15 12:00:00", "2025-07-15 12:00:00"])
    utc, verworfen = to_utc_index(idx, tz="Europe/Athens")
    assert verworfen == 0
    assert utc[0].hour == 10, "Winter: UTC+2"
    assert utc[1].hour == 9, "Sommer: UTC+3"


def test_fester_versatz_bleibt_moeglich():
    idx = pd.DatetimeIndex(["2025-01-15 12:00:00"])
    utc, _ = to_utc_index(idx, shift_hours=2.0)  # Server auf UTC+2
    assert utc[0].hour == 10


def test_mehrdeutige_zeitstempel_werden_verworfen_nicht_geraten():
    """In der Stunde der Zeitumstellung ist die Zuordnung nicht eindeutig."""
    idx = pd.DatetimeIndex(["2025-10-26 03:30:00", "2025-11-05 12:00:00"])
    utc, verworfen = to_utc_index(idx, tz="Europe/Athens")
    assert verworfen >= 1
    assert len(utc) == len(idx)
