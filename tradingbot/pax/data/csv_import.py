"""Eigene Kursdaten aus CSV einlesen.

Wer Minutendaten hat, braucht kein MT5-Terminal, um das System auf echten
Kursen zu prüfen. Dieses Modul erkennt die üblichen Ausgabeformate selbst:

* **MT5 "Bars exportieren"** - Tabulator, Kopfzeile in spitzen Klammern:
  `<DATE>  <TIME>  <OPEN>  <HIGH>  <LOW>  <CLOSE>  <TICKVOL>  <VOL>  <SPREAD>`
* **MT4-Historie** - Komma, ohne Kopfzeile:
  `2024.01.02,00:00,1.10000,1.10010,1.09990,1.10005,123`
* **Dukascopy und ähnliche** - `Gmt time,Open,High,Low,Close,Volume` mit
  `02.01.2024 00:00:00.000`
* **Allgemein** - eine Zeitspalte plus open/high/low/close

Der wichtigste Punkt ist die Zeitzone. MT5 exportiert in *Serverzeit*, meist
UTC+2 oder UTC+3. Das System rechnet durchgehend in UTC. Wer den Versatz nicht
angibt, verschiebt seine Handelszeiten um zwei bis drei Stunden - und misst
damit etwas anderes, als er glaubt.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..types import Timeframe
from ..utils import get_logger

log = get_logger("csv")

#: Übliche Schreibweisen der Spalten, auf unsere Namen abgebildet
COLUMN_ALIASES = {
    "open": {"open", "o", "openprice", "eroeffnung", "eröffnung"},
    "high": {"high", "h", "highprice", "hoch"},
    "low": {"low", "l", "lowprice", "tief"},
    "close": {"close", "c", "closeprice", "schluss", "last"},
    "volume": {"volume", "vol", "tickvol", "tickvolume", "realvol", "realvolume", "volumen"},
    "spread": {"spread"},
}

DATE_ALIASES = {"date", "datum", "day"}
TIME_ALIASES = {"time", "zeit", "uhrzeit"}
DATETIME_ALIASES = {
    "datetime", "timestamp", "gmttime", "gmt time", "localtime", "time", "date",
    "zeitstempel", "opentime", "bartime",
}

#: Datumsformate in der Reihenfolge, in der sie probiert werden
DATE_FORMATS = [
    "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y.%m.%d",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%d.%m.%Y %H:%M:%S.%f", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
    "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M",
    "%Y%m%d %H:%M:%S", "%Y%m%d",
]


@dataclass
class ImportReport:
    """Was beim Einlesen herauskam - und was daran auffällig war."""

    path: str = ""
    symbol: str = ""
    rows_read: int = 0
    rows_kept: int = 0
    timeframe: str = ""
    first: "pd.Timestamp | None" = None
    last: "pd.Timestamp | None" = None
    delimiter: str = ""
    columns: dict[str, str] = field(default_factory=dict)
    tz_shift_hours: float = 0.0
    written: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"  Datei              {self.path}",
            f"  Trennzeichen       {self.delimiter!r}",
            f"  erkannte Spalten   " + ", ".join(f"{v}->{k}" for k, v in self.columns.items()),
            f"  Zeilen             {self.rows_read} gelesen, {self.rows_kept} brauchbar",
            f"  Zeiteinheit        {self.timeframe}",
            f"  Zeitraum           {self.first} bis {self.last}",
        ]
        if self.tz_shift_hours:
            lines.append(f"  Zeitversatz        {self.tz_shift_hours:+g} Stunden auf UTC gerechnet")
        if self.written:
            lines.append("  geschrieben        " + ", ".join(
                f"{k}: {v}" for k, v in self.written.items()))
        for w in self.warnings:
            lines.append(f"  ! {w}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #


def sniff(path: "str | Path", sample_bytes: int = 65_536) -> tuple[str, bool]:
    """Trennzeichen und Vorhandensein einer Kopfzeile bestimmen."""
    p = Path(path)
    with p.open("r", encoding="utf-8-sig", errors="replace") as fh:
        sample = fh.read(sample_bytes)
    if not sample.strip():
        raise ValueError(f"{p} ist leer")

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,;| ")
        delimiter = dialect.delimiter
    except csv.Error:
        # Notfall: das häufigste Zeichen der ersten Zeile gewinnt
        first = sample.splitlines()[0]
        delimiter = max("\t,;|", key=first.count)

    first_line = sample.splitlines()[0]
    fields = [f.strip().strip("<>").lower() for f in first_line.split(delimiter)]
    # Kopfzeile erkennt man daran, dass die Felder Namen und keine Zahlen sind
    has_header = any(f in DATE_ALIASES | DATETIME_ALIASES for f in fields) or any(
        f in alias for aliases in COLUMN_ALIASES.values() for alias in [aliases] for f in fields
    )
    return delimiter, has_header


def _normalize_name(name: str) -> str:
    return str(name).strip().strip("<>").strip().lower().replace("_", "").replace(" ", "")


def _map_columns(columns: list[str]) -> dict[str, str]:
    """Spaltennamen auf unsere Bezeichnungen abbilden."""
    mapping: dict[str, str] = {}
    normalized = {c: _normalize_name(c) for c in columns}
    for target, aliases in COLUMN_ALIASES.items():
        for original, norm in normalized.items():
            if norm in {a.replace(" ", "") for a in aliases} and target not in mapping:
                mapping[target] = original
                break
    return mapping


def _parse_datetime(series: pd.Series) -> pd.Series:
    """Zeitspalte robust einlesen - erst feste Formate, dann als letzte Wahl frei."""
    sample = series.dropna().astype(str).head(200)
    for fmt in DATE_FORMATS:
        try:
            parsed = pd.to_datetime(sample, format=fmt)
        except (ValueError, TypeError):
            continue
        if parsed.notna().all():
            return pd.to_datetime(series, format=fmt, errors="coerce")
    # Kein festes Format passte - pandas raten lassen
    return pd.to_datetime(series, errors="coerce", format="mixed")


def read_csv_bars(
    path: "str | Path",
    tz_shift_hours: float = 0.0,
    report: "ImportReport | None" = None,
) -> pd.DataFrame:
    """Eine CSV-Datei als OHLCV-Rahmen mit UTC-Index einlesen."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {p}")
    report = report or ImportReport()
    report.path = str(p)

    delimiter, has_header = sniff(p)
    report.delimiter = delimiter
    df = pd.read_csv(
        p, sep=delimiter, header=0 if has_header else None,
        encoding="utf-8-sig", engine="python", skipinitialspace=True,
    )
    report.rows_read = len(df)
    if df.empty:
        raise ValueError(f"{p} enthält keine Datenzeilen")

    if not has_header:
        # MT4-Reihenfolge: Datum, Zeit, O, H, L, C, Volumen
        namen = ["date", "time", "open", "high", "low", "close", "volume", "spread"]
        df.columns = namen[: len(df.columns)] + [
            f"extra{i}" for i in range(max(0, len(df.columns) - len(namen)))
        ]

    normalized = {c: _normalize_name(c) for c in df.columns}
    date_col = next((c for c, n in normalized.items() if n in DATE_ALIASES), None)
    time_col = next((c for c, n in normalized.items() if n in TIME_ALIASES), None)
    dt_col = next(
        (c for c, n in normalized.items()
         if n in {a.replace(" ", "") for a in DATETIME_ALIASES}), None
    )

    if date_col is not None and time_col is not None and date_col != time_col:
        zeit = _parse_datetime(
            df[date_col].astype(str).str.strip() + " " + df[time_col].astype(str).str.strip()
        )
    elif dt_col is not None:
        zeit = _parse_datetime(df[dt_col])
    elif date_col is not None:
        zeit = _parse_datetime(df[date_col])
    else:
        raise ValueError(
            "Keine Zeitspalte gefunden. Erwartet wird entweder eine Spalte 'time'/'datetime' "
            f"oder 'date' plus 'time'. Gefunden: {list(df.columns)}"
        )

    mapping = _map_columns(list(df.columns))
    fehlend = [k for k in ("open", "high", "low", "close") if k not in mapping]
    if fehlend:
        raise ValueError(
            f"Es fehlen die Spalten {fehlend}. Gefunden: {list(df.columns)}"
        )
    report.columns = dict(mapping)

    out = pd.DataFrame({"time": zeit})
    for ziel, quelle in mapping.items():
        out[ziel] = _to_number(df[quelle])
    if "volume" not in out.columns:
        out["volume"] = 0.0

    vorher = len(out)
    out = out.dropna(subset=["time", "open", "high", "low", "close"])
    if len(out) < vorher:
        report.warnings.append(f"{vorher - len(out)} unvollständige Zeilen verworfen")

    out = out.set_index("time").sort_index()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    if tz_shift_hours:
        # Die Datei steht in Serverzeit; wir rechnen auf UTC zurück.
        out.index = out.index - pd.Timedelta(hours=tz_shift_hours)
        report.tz_shift_hours = tz_shift_hours

    doppelt = int(out.index.duplicated().sum())
    if doppelt:
        report.warnings.append(f"{doppelt} doppelte Zeitstempel - jeweils der letzte gilt")
        out = out[~out.index.duplicated(keep="last")]

    _sanity_check(out, report)
    report.rows_kept = len(out)
    report.first, report.last = (out.index[0], out.index[-1]) if len(out) else (None, None)
    report.timeframe = detect_timeframe(out.index) or "?"
    return out


def _to_number(series: pd.Series) -> pd.Series:
    """Zahlen einlesen, auch mit Komma als Dezimaltrenner oder Tausenderpunkt."""
    if pd.api.types.is_numeric_dtype(series):
        return series.astype("float64")
    text = series.astype(str).str.strip().str.replace(" ", "", regex=False)
    numerisch = pd.to_numeric(text, errors="coerce")
    if numerisch.notna().mean() < 0.9:
        # Zweiter Versuch mit deutscher Schreibweise: 1.234,56
        numerisch = pd.to_numeric(
            text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
            errors="coerce",
        )
    return numerisch.astype("float64")


def _sanity_check(df: pd.DataFrame, report: ImportReport) -> None:
    """Auffälligkeiten melden, statt sie stillschweigend mitzuschleppen."""
    if df.empty:
        return
    verletzt = int(
        ((df["high"] < df[["open", "close"]].max(axis=1) - 1e-12)
         | (df["low"] > df[["open", "close"]].min(axis=1) + 1e-12)).sum()
    )
    if verletzt:
        report.warnings.append(
            f"{verletzt} Kerzen mit unstimmigem Hoch/Tief - vermutlich Spaltenverwechslung"
        )
    if (df[["open", "high", "low", "close"]] <= 0).to_numpy().any():
        report.warnings.append("Kurse kleiner oder gleich null gefunden")
    if len(df) > 10:
        luecken = df.index.to_series().diff().dt.total_seconds().dropna()
        typisch = luecken.median()
        grosse = int((luecken > typisch * 50).sum())
        if grosse:
            report.warnings.append(
                f"{grosse} größere Lücken in der Reihe (Wochenenden und Feiertage sind normal)"
            )


def detect_timeframe(index: pd.DatetimeIndex) -> "str | None":
    """Zeiteinheit aus den Abständen ableiten."""
    if len(index) < 3:
        return None
    minuten = index.to_series().diff().dt.total_seconds().dropna() / 60.0
    if minuten.empty:
        return None
    typisch = float(minuten.mode().iloc[0]) if not minuten.mode().empty else float(minuten.median())
    for tf in sorted(Timeframe, key=lambda t: t.minutes):
        if abs(tf.minutes - typisch) < max(0.5, tf.minutes * 0.1):
            return tf.value
    return None
