"""Marktstruktur: Swings, Brüche - und die Kausalität der Swing-Folge."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pax.features.indicators import atr as atr_fn
from pax.features.structure import StructureAnalyzer, _alternate
from pax.types import Direction, Swing, TrendState


def test_swings_werden_gefunden(bars, atr):
    swings = StructureAnalyzer(3, 0.5).find_swings(bars, atr)
    assert len(swings) > 50
    assert any(s.is_high for s in swings) and any(not s.is_high for s in swings)
    assert all(0.0 <= s.strength <= 1.0 for s in swings)


def test_swing_hoch_ist_lokales_maximum(bars, atr):
    highs = bars["high"].to_numpy()
    for s in StructureAnalyzer(3, 0.5).find_swings(bars, atr)[:60]:
        if not s.is_high:
            continue
        fenster = highs[max(0, s.index - 3) : s.index + 4]
        assert highs[s.index] >= fenster.max() - 1e-12


def test_bruchereignisse_entstehen_auf_schlusskursbasis(bars, atr):
    ms = StructureAnalyzer(3, 0.5).analyze(bars, atr)
    assert len(ms.events) > 5
    assert {e.kind for e in ms.events} <= {"BOS", "CHoCH"}
    for e in ms.events[:40]:
        level = e.level
        close = float(bars["close"].iloc[e.index])
        if e.direction is Direction.LONG:
            assert close > level
        else:
            assert close < level


def test_trendzustand_folgt_den_ereignissen(bars, atr):
    ms = StructureAnalyzer(3, 0.5).analyze(bars, atr)
    for e in ms.events[:30]:
        erwartet = 1.0 if e.direction is Direction.LONG else -1.0
        assert ms.frame["struct_trend"].iloc[e.index] == erwartet


@pytest.mark.parametrize("cut", [5, 33, 90])
def test_struktur_ist_kausal(bars, cut):
    """Deckt genau den Fehler auf, bei dem ein späteres Hoch ein früheres löscht."""
    an = StructureAnalyzer(3, 0.5)
    voll = an.analyze(bars, atr_fn(bars, 14)).frame
    kurz_df = bars.iloc[:-cut]
    kurz = an.analyze(kurz_df, atr_fn(kurz_df, 14)).frame
    gemeinsam = kurz.index[-250:]
    abweichung = (voll.loc[gemeinsam] - kurz.loc[gemeinsam]).abs().max().max()
    assert abweichung == 0.0, f"Lookahead in der Struktur bei cut={cut}: {abweichung}"


def test_globale_alternation_ist_bewusst_nicht_kausal():
    """Dokumentiert, warum `_alternate` nur zum Zeichnen taugt.

    Kommt ein höheres Hoch hinzu, verschwindet das frühere rückwirkend aus der
    Folge - obwohl es zu seiner Zeit bestätigt war.
    """
    zeit = pd.Timestamp("2026-01-01", tz="UTC")
    frueh = [Swing(10, zeit, 1.10, True), Swing(20, zeit, 1.05, False)]
    assert len(_alternate(frueh)) == 2

    spaeter = frueh[:1] + [Swing(15, zeit, 1.12, True)] + frueh[1:]
    ergebnis = _alternate(spaeter)
    assert [s.price for s in ergebnis] == [1.12, 1.05]  # das Hoch bei 1.10 ist weg


def test_find_swings_alterniert_standardmaessig_nicht(bars, atr):
    """Die Merkmale müssen die ungefilterte Kandidatenliste bekommen."""
    an = StructureAnalyzer(3, 0.5)
    roh = an.find_swings(bars, atr)
    geglaettet = an.find_swings(bars, atr, alternate=True)
    assert len(roh) >= len(geglaettet)


def test_premium_discount_ist_begrenzt(bars, atr):
    """Vor dem ersten Swing gibt es keine Spanne - danach muss der Wert gedeckelt sein."""
    f = StructureAnalyzer(3, 0.5).analyze(bars, atr).frame
    werte = f["premium_discount"].dropna()
    assert len(werte) > 1000
    assert werte.between(-3.0, 3.0).all()
