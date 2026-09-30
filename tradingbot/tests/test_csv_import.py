"""CSV-Import eigener Kursdaten."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pax.data.csv_import import (
    ImportReport,
    detect_timeframe,
    read_csv_bars,
    sniff,
)
from pax.datasource import load_data
from pax.features.mtf import resample_ohlcv


@pytest.fixture(scope="module")
def kurse() -> pd.DataFrame:
    """Eine kleine, auf fünf Stellen gerundete M1-Reihe."""
    idx = pd.date_range("2025-01-06 00:00", periods=400, freq="1min", tz="UTC")
    rng = np.random.default_rng(3)
    close = np.round(1.10 + np.cumsum(rng.normal(0, 0.00005, 400)), 5)
    open_ = np.round(np.r_[1.10, close[:-1]], 5)
    high = np.round(np.maximum(open_, close) + abs(rng.normal(0, 0.00003, 400)), 5)
    low = np.round(np.minimum(open_, close) - abs(rng.normal(0, 0.00003, 400)), 5)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close,
         "volume": rng.integers(10, 500, 400).astype(float)},
        index=idx,
    )


def _schreibe(pfad, zeilen, kopf=None) -> str:
    with open(pfad, "w", encoding="utf-8") as fh:
        if kopf:
            fh.write(kopf + "\n")
        fh.writelines(z + "\n" for z in zeilen)
    return str(pfad)


def _mt5(tmp_path, df) -> str:
    return _schreibe(
        tmp_path / "mt5.csv",
        [f"{t:%Y.%m.%d}\t{t:%H:%M:%S}\t{r.open:.5f}\t{r.high:.5f}\t{r.low:.5f}\t"
         f"{r.close:.5f}\t{int(r.volume)}\t0\t8" for t, r in df.iterrows()],
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>",
    )


# --------------------------------------------------------------------------- #


def test_mt5_export_wird_exakt_gelesen(tmp_path, kurse):
    df = read_csv_bars(_mt5(tmp_path, kurse))
    assert len(df) == len(kurse)
    for spalte in ("open", "high", "low", "close"):
        assert np.allclose(df[spalte].to_numpy(), kurse[spalte].to_numpy())
    assert df.index[0] == kurse.index[0] and df.index[-1] == kurse.index[-1]


def test_mt4_format_ohne_kopfzeile(tmp_path, kurse):
    pfad = _schreibe(
        tmp_path / "mt4.csv",
        [f"{t:%Y.%m.%d},{t:%H:%M},{r.open:.5f},{r.high:.5f},{r.low:.5f},"
         f"{r.close:.5f},{int(r.volume)}" for t, r in kurse.iterrows()],
    )
    df = read_csv_bars(pfad)
    assert len(df) == len(kurse)
    assert np.allclose(df["close"].to_numpy(), kurse["close"].to_numpy())


def test_dukascopy_format_mit_millisekunden(tmp_path, kurse):
    pfad = _schreibe(
        tmp_path / "duka.csv",
        [f"{t:%d.%m.%Y %H:%M:%S}.000,{r.open:.5f},{r.high:.5f},{r.low:.5f},"
         f"{r.close:.5f},{int(r.volume)}" for t, r in kurse.iterrows()],
        "Gmt time,Open,High,Low,Close,Volume",
    )
    df = read_csv_bars(pfad)
    assert len(df) == len(kurse)
    assert np.allclose(df["high"].to_numpy(), kurse["high"].to_numpy())


def test_semikolon_und_dezimalkomma(tmp_path, kurse):
    pfad = _schreibe(
        tmp_path / "de.csv",
        [f"{t:%Y-%m-%d %H:%M:%S};{r.open:.5f};{r.high:.5f};{r.low:.5f};{r.close:.5f};"
         f"{int(r.volume)}".replace(";1.", ";1,") for t, r in kurse.iterrows()],
        "time;open;high;low;close;volume",
    )
    df = read_csv_bars(pfad)
    assert np.allclose(df["close"].to_numpy(), kurse["close"].to_numpy())


def test_zeitversatz_wird_abgezogen(tmp_path, kurse):
    pfad = _mt5(tmp_path, kurse)
    ohne = read_csv_bars(pfad)
    mit = read_csv_bars(pfad, tz_shift_hours=2.0)
    assert (ohne.index[0] - mit.index[0]) == pd.Timedelta(hours=2)


def test_zeiteinheit_wird_erkannt(kurse):
    assert detect_timeframe(kurse.index) == "M1"
    assert detect_timeframe(resample_ohlcv(kurse, "M15").index) == "M15"
    assert detect_timeframe(kurse.index[:2]) is None


def test_trennzeichen_wird_erkannt(tmp_path, kurse):
    delimiter, kopfzeile = sniff(_mt5(tmp_path, kurse))
    assert delimiter == "\t" and kopfzeile


def test_fehlende_spalten_werden_gemeldet(tmp_path):
    pfad = _schreibe(tmp_path / "kaputt.csv", ["2025-01-06 00:00,1.1"], "time,open")
    with pytest.raises(ValueError, match="fehlen"):
        read_csv_bars(pfad)


def test_fehlende_zeitspalte_wird_gemeldet(tmp_path):
    pfad = _schreibe(tmp_path / "ohnezeit.csv", ["1.1,1.2,1.0,1.15"], "open,high,low,close")
    with pytest.raises(ValueError, match="Zeitspalte"):
        read_csv_bars(pfad)


def test_leere_datei_wird_gemeldet(tmp_path):
    pfad = _schreibe(tmp_path / "leer.csv", [])
    with pytest.raises(ValueError):
        read_csv_bars(pfad)


def test_unstimmige_kerzen_werden_gemeldet(tmp_path):
    """Vertauschte Spalten sollen auffallen, nicht stillschweigend durchgehen."""
    pfad = _schreibe(
        tmp_path / "vertauscht.csv",
        [f"2025-01-06 00:{i:02d}:00,1.10,1.05,1.15,1.12" for i in range(30)],
        "time,open,high,low,close",
    )
    report = ImportReport()
    read_csv_bars(pfad, report=report)
    assert any("Hoch/Tief" in w for w in report.warnings)


def test_doppelte_zeitstempel_werden_entfernt(tmp_path):
    pfad = _schreibe(
        tmp_path / "doppelt.csv",
        ["2025-01-06 00:00:00,1.10,1.11,1.09,1.10"] * 3 + ["2025-01-06 00:01:00,1.10,1.11,1.09,1.10"],
        "time,open,high,low,close",
    )
    report = ImportReport()
    df = read_csv_bars(pfad, report=report)
    assert len(df) == 2
    assert any("doppelte" in w for w in report.warnings)


def test_importierte_daten_werden_auch_benutzt(tmp_path, config, kurse):
    """Der eigentliche Zweck: nach dem Import darf nichts mehr synthetisch sein.

    Vorher scheiterte genau das - der Zwischenspeicher verlangte von *jeder*
    Zeitebene 200 Balken, und die grobe D1-Ebene erreichte das nie.
    """
    from pax.data.store import BarStore
    from pax.types import Timeframe

    lang = pd.date_range("2025-01-06", periods=20_000, freq="1min", tz="UTC")
    rng = np.random.default_rng(5)
    close = np.round(1.10 + np.cumsum(rng.normal(0, 0.00004, len(lang))), 5)
    fein = pd.DataFrame(
        {"open": np.r_[1.10, close[:-1]], "high": close + 0.0001,
         "low": close - 0.0001, "close": close, "volume": 100.0},
        index=lang,
    )
    store = BarStore(config.data.cache_dir)
    for tf in (Timeframe.M15, Timeframe.H1, Timeframe.H4):
        store.write("EURUSD", tf, resample_ohlcv(fein, tf))
    # D1 bleibt bewusst zu dünn - das darf den Import nicht entwerten
    store.write("EURUSD", Timeframe.D1, resample_ohlcv(fein, Timeframe.D1))

    bundle = load_data(config, "EURUSD", bars=5000)
    assert bundle.source == "cache", "importierte Daten wurden ignoriert"
    assert not bundle.is_synthetic
    assert "M15" in bundle.frames and len(bundle.frames["M15"]) > 500
