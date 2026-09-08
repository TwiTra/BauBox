"""Datenschicht: Erzeugung, Speicher, Sessions, MT5-Hülle."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from pax.config import Config, SessionConfig
from pax.data import BarStore, MT5Client, MT5Unavailable, SessionFilter, SyntheticMarket
from pax.data.store import _merge, _normalize
from pax.datasource import load_data
from pax.types import SymbolSpec, Timeframe, utcnow


def test_synthetische_kerzen_sind_in_sich_stimmig(bars):
    assert (bars["high"] >= bars[["open", "close"]].max(axis=1) - 1e-12).all()
    assert (bars["low"] <= bars[["open", "close"]].min(axis=1) + 1e-12).all()
    assert (bars["high"] >= bars["low"]).all()
    assert bars.index.is_monotonic_increasing
    assert not bars.index.duplicated().any()
    assert bars.index.tz is not None


def test_generierung_ist_reproduzierbar():
    a = SyntheticMarket("EURUSD", seed=42).generate(500)
    b = SyntheticMarket("EURUSD", seed=42).generate(500)
    assert np.allclose(a["close"], b["close"])


def test_hoehere_zeitebene_ist_echtes_aggregat(frames):
    m15, h1 = frames["M15"], frames["H1"]
    t = h1.index[10]
    teil = m15[(m15.index >= t) & (m15.index < t + pd.Timedelta(hours=1))]
    assert float(teil["high"].max()) == pytest.approx(float(h1.loc[t, "high"]))
    assert float(teil["low"].min()) == pytest.approx(float(h1.loc[t, "low"]))
    assert float(teil["open"].iloc[0]) == pytest.approx(float(h1.loc[t, "open"]))


def test_wochenenden_werden_ausgelassen(bars):
    assert not (bars.index.dayofweek == 5).any()


def test_speicher_roundtrip(tmp_path, bars):
    store = BarStore(tmp_path)
    store.write("EURUSD", "M15", bars)
    zurueck = store.read("EURUSD", "M15")
    assert len(zurueck) == len(bars)
    assert np.allclose(zurueck["close"], bars["close"])
    uebersicht = store.coverage()
    assert len(uebersicht) == 1 and uebersicht.iloc[0]["bars"] == len(bars)


def test_speicher_liefert_leeren_rahmen_ohne_datei(tmp_path):
    assert BarStore(tmp_path).read("GIBTESNICHT", "M15").empty


def test_zusammenfuehren_bevorzugt_neue_daten(bars):
    alt = bars.iloc[:100]
    neu = bars.iloc[80:150].copy()
    neu.loc[:, "close"] = 9.99
    zusammen = _merge(alt, neu)
    assert len(zusammen) == 150
    assert zusammen["close"].iloc[90] == pytest.approx(9.99)


def test_normalisierung_erzwingt_utc_und_sortierung():
    idx = pd.to_datetime(["2026-01-02", "2026-01-01"])
    df = pd.DataFrame({"Open": [1, 2], "High": [2, 3], "Low": [0, 1], "Close": [1, 2]}, index=idx)
    out = _normalize(df)
    assert out.index.is_monotonic_increasing
    assert str(out.index.tz) == "UTC"
    assert "volume" in out.columns


def test_normalisierung_meldet_fehlende_spalten():
    df = pd.DataFrame({"open": [1.0]}, index=pd.to_datetime(["2026-01-01"]))
    with pytest.raises(ValueError, match="unvollständig"):
        _normalize(df)


def test_sessionfilter_haelt_sich_an_die_fenster():
    sf = SessionFilter(SessionConfig())
    assert sf.check(datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc))[0]      # Montag London
    assert not sf.check(datetime(2026, 9, 7, 3, 0, tzinfo=timezone.utc))[0]  # Asien
    assert not sf.check(datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc))[0] # Samstag


def test_sessionfilter_blockt_freitagabend():
    sf = SessionFilter(SessionConfig(trade_sessions=[["00:00", "23:59"]], friday_close_hour_utc=20))
    assert sf.check(datetime(2026, 9, 4, 19, 0, tzinfo=timezone.utc))[0]
    assert not sf.check(datetime(2026, 9, 4, 21, 0, tzinfo=timezone.utc))[0]


def test_nachrichtenfilter(tmp_path):
    pfad = tmp_path / "news.csv"
    pfad.write_text("time,impact,currency\n2026-09-07T14:30:00Z,high,USD\n", encoding="utf-8")
    sf = SessionFilter(SessionConfig(news_file=str(pfad), trade_sessions=[["00:00", "23:59"]]))
    assert sf.news_block(datetime(2026, 9, 7, 14, 20, tzinfo=timezone.utc), "EURUSD")
    assert sf.news_block(datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc), "EURUSD") is None
    # Andere Währung, kein Block
    assert sf.news_block(datetime(2026, 9, 7, 14, 20, tzinfo=timezone.utc), "AUDNZD") is None


def test_sessionfilter_uebersteht_kaputte_nachrichtendatei(tmp_path):
    pfad = tmp_path / "news.csv"
    pfad.write_text("völliger unsinn\n;;;\n", encoding="utf-8")
    sf = SessionFilter(SessionConfig(news_file=str(pfad)))
    assert sf.news_block(utcnow(), "EURUSD") is None


def test_mt5_huelle_ist_ohne_paket_ehrlich():
    if MT5Client.available():
        pytest.skip("MetaTrader5 ist installiert - der Fehlerpfad greift hier nicht")
    client = MT5Client()
    assert not client.connected
    with pytest.raises(MT5Unavailable, match="Windows"):
        client.connect()
    assert client.health()["ok"] is False


def test_datenquelle_faellt_auf_synthetik_zurueck(config):
    bundle = load_data(config, "EURUSD", bars=2000)
    assert bundle.source in ("mt5", "cache", "synthetisch")
    assert set(bundle.frames) == {t.value for t in config.data.all_timeframes}
    assert isinstance(bundle.spec, SymbolSpec)
    assert "EURUSD" in bundle.describe()


def test_datenquelle_kann_synthetik_verweigern(config):
    if MT5Client.available():
        pytest.skip("MetaTrader5 ist installiert")
    with pytest.raises(MT5Unavailable):
        load_data(config, "EURUSD", bars=2000, allow_synthetic=False)


def test_kontraktdaten_normalisieren_richtig():
    spec = SymbolSpec("EURUSD", digits=5, point=1e-5, tick_size=1e-5,
                      volume_min=0.01, volume_step=0.01, volume_max=50.0)
    assert spec.normalize_volume(0.237) == pytest.approx(0.23)
    assert spec.normalize_volume(0.001) == pytest.approx(0.01)
    assert spec.normalize_volume(999.0) == pytest.approx(50.0)
    assert spec.normalize_price(1.123456) == pytest.approx(1.12346)
    assert spec.pip == pytest.approx(0.0001)


def test_zeiteinheiten():
    assert Timeframe.parse("h4") is Timeframe.H4
    assert Timeframe.M15.minutes == 15
    assert Timeframe.M15 < Timeframe.H1
    with pytest.raises(ValueError):
        Timeframe.parse("Q7")
