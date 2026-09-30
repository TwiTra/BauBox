"""Indikatoren, ausschließlich mit numpy und pandas.

Bewusst ohne TA-Lib: keine Kompilierung, keine Installationshürde unter Windows,
und jede Formel ist hier nachlesbar statt in einer Blackbox.

Alle Funktionen sind kausal - der Wert an Position i benutzt nur Daten bis
einschließlich i. Wer das ändert, zerstört jedes Backtest-Ergebnis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Glättung
# --------------------------------------------------------------------------- #


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilders Glättung - die Grundlage von RSI, ATR und ADX."""
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def wma(series: pd.Series, period: int) -> pd.Series:
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(period, min_periods=period).apply(
        lambda w: float(np.dot(w, weights) / weights.sum()), raw=True
    )


def hma(series: pd.Series, period: int) -> pd.Series:
    """Hull Moving Average - schnell und trotzdem glatt."""
    half, root = max(1, period // 2), max(1, int(np.sqrt(period)))
    return wma(2 * wma(series, half) - wma(series, period), root)


# --------------------------------------------------------------------------- #
# Volatilität
# --------------------------------------------------------------------------- #


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return wilder(true_range(df), period)


def natr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR in Prozent des Preises - über Symbole hinweg vergleichbar."""
    return 100.0 * atr(df, period) / df["close"].replace(0, np.nan)


def realized_vol(close: pd.Series, period: int = 20, annualize: float = 0.0) -> pd.Series:
    with np.errstate(invalid="ignore", divide="ignore"):
        ret = np.log(close / close.shift(1))
    vol = ret.rolling(period, min_periods=period).std()
    return vol * np.sqrt(annualize) if annualize else vol


def parkinson_vol(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Parkinson-Schätzer: nutzt High/Low und ist damit effizienter als Close-Vol."""
    with np.errstate(invalid="ignore", divide="ignore"):
        hl = np.log(df["high"] / df["low"].replace(0, np.nan)) ** 2
    return np.sqrt(hl.rolling(period, min_periods=period).mean() / (4 * np.log(2)))


# --------------------------------------------------------------------------- #
# Momentum / Oszillatoren
# --------------------------------------------------------------------------- #


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = wilder(delta.clip(lower=0), period)
    loss = wilder((-delta).clip(lower=0), period)
    rs = gain / loss.replace(0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # Ohne einen einzigen Verlust ist die Division nicht definiert - der RSI ist
    # dann aber nicht "neutral", sondern maximal. Umgekehrt genauso. Wer das
    # pauschal auf 50 setzt, verliert genau die Extremwerte, auf die es ankommt.
    kein_verlust = (loss.notna()) & (loss <= 0)
    out = out.mask(kein_verlust & (gain > 0), 100.0)
    out = out.mask(kein_verlust & (gain <= 0), 50.0)
    return out.fillna(50.0).where(close.notna())


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    low = df["low"].rolling(k_period, min_periods=k_period).min()
    high = df["high"].rolling(k_period, min_periods=k_period).max()
    k = 100.0 * (df["close"] - low) / (high - low).replace(0, np.nan)
    return pd.DataFrame({"stoch_k": k, "stoch_d": k.rolling(d_period, min_periods=d_period).mean()})


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    ma = tp.rolling(period, min_periods=period).mean()
    md = (tp - ma).abs().rolling(period, min_periods=period).mean()
    return (tp - ma) / (0.015 * md.replace(0, np.nan))


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].rolling(period, min_periods=period).max()
    low = df["low"].rolling(period, min_periods=period).min()
    return -100.0 * (high - df["close"]) / (high - low).replace(0, np.nan)


def roc(close: pd.Series, period: int = 10) -> pd.Series:
    return 100.0 * (close / close.shift(period) - 1.0)


# --------------------------------------------------------------------------- #
# Trendstärke
# --------------------------------------------------------------------------- #


def directional_movement(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ADX mit +DI und -DI nach Wilder.

    ADX misst nur die Stärke einer Bewegung, nicht ihre Richtung - die steckt
    in der Differenz der beiden DI-Linien.
    """
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)

    tr = wilder(true_range(df), period)
    plus_di = 100.0 * wilder(plus_dm, period) / tr.replace(0, np.nan)
    minus_di = 100.0 * wilder(minus_dm, period) / tr.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame(
        {"plus_di": plus_di, "minus_di": minus_di, "adx": wilder(dx, period), "dx": dx}
    )


def efficiency_ratio(close: pd.Series, period: int = 20) -> pd.Series:
    """Kaufmans Effizienzquotient: gerichtete Strecke geteilt durch Gesamtweg.

    Nahe 1 heißt sauberer Trend, nahe 0 heißt Sägezahn. Der einfachste und einer
    der robustesten Trendfilter überhaupt.
    """
    direction = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(period, min_periods=period).sum()
    return direction / volatility.replace(0, np.nan)


def hurst(close: pd.Series, window: int = 120, lags: "tuple[int, ...]" = (2, 4, 8, 16)) -> pd.Series:
    """Hurst-Exponent über das Varianzverhältnis geschätzt.

    > 0,5 spricht für Persistenz (Trendfolge lohnt), < 0,5 für Mittelwertrückkehr
    (Ausbrüche verpuffen). Die Regression über mehrere Lags ist deutlich
    stabiler als die klassische R/S-Statistik auf kurzen Fenstern.
    """
    # In der Einschwingphase enthalten Rendite und Varianz NaN. Das ist erwartet -
    # numpy soll deswegen nicht bei jedem Aufruf warnen.
    with np.errstate(invalid="ignore", divide="ignore"):
        ret = np.log(close / close.shift(1))
        log_lags = np.log(np.array(lags, dtype=float))
        variances = []
        for lag in lags:
            agg = ret.rolling(lag, min_periods=lag).sum()
            variances.append(agg.rolling(window, min_periods=window).var())
        log_var = np.log(pd.concat(variances, axis=1).clip(lower=1e-18))
    # Steigung der Regression log(Var) auf log(lag); H = Steigung / 2
    centered_x = log_lags - log_lags.mean()
    denom = float((centered_x**2).sum())
    slope = (log_var.values * centered_x).sum(axis=1) / denom
    return pd.Series(slope / 2.0, index=close.index, name="hurst")


def linreg_slope(series: pd.Series, period: int = 20, normalize: bool = True) -> pd.Series:
    """Steigung der Regressionsgeraden über die letzten `period` Werte."""
    x = np.arange(period, dtype=float)
    x_centered = x - x.mean()
    denom = float((x_centered**2).sum())

    def _slope(window: np.ndarray) -> float:
        return float(np.dot(window - window.mean(), x_centered) / denom)

    slope = series.rolling(period, min_periods=period).apply(_slope, raw=True)
    if normalize:
        slope = slope / series.replace(0, np.nan).abs()
    return slope


def linreg_r2(series: pd.Series, period: int = 20) -> pd.Series:
    """Bestimmtheitsmaß der Trendgeraden - wie geradlinig läuft der Markt?"""
    x = np.arange(period, dtype=float)
    xc = x - x.mean()
    sxx = float((xc**2).sum())

    def _r2(w: np.ndarray) -> float:
        wc = w - w.mean()
        syy = float((wc**2).sum())
        if syy <= 1e-18:
            return 0.0
        sxy = float(np.dot(wc, xc))
        return float(min(1.0, max(0.0, (sxy * sxy) / (sxx * syy))))

    return series.rolling(period, min_periods=period).apply(_r2, raw=True)


# --------------------------------------------------------------------------- #
# Kanäle und Bänder
# --------------------------------------------------------------------------- #


def bollinger(close: pd.Series, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    mid = sma(close, period)
    dev = close.rolling(period, min_periods=period).std(ddof=0)
    upper, lower = mid + std * dev, mid - std * dev
    width = (upper - lower) / mid.replace(0, np.nan)
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame(
        {"bb_mid": mid, "bb_upper": upper, "bb_lower": lower, "bb_width": width, "bb_pct": pct_b}
    )


def keltner(df: pd.DataFrame, period: int = 20, mult: float = 2.0) -> pd.DataFrame:
    mid = ema(df["close"], period)
    rng = atr(df, period)
    return pd.DataFrame(
        {"kc_mid": mid, "kc_upper": mid + mult * rng, "kc_lower": mid - mult * rng}
    )


def donchian(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Donchian-Kanal aus den *vorherigen* Balken.

    Der aktuelle Balken wird bewusst ausgeschlossen: sonst berührt der Kurs sein
    eigenes Extrem und jedes Ausbruchssignal wäre tautologisch.
    """
    upper = df["high"].shift(1).rolling(period, min_periods=period).max()
    lower = df["low"].shift(1).rolling(period, min_periods=period).min()
    mid = (upper + lower) / 2.0
    pos = (df["close"] - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame(
        {"dc_upper": upper, "dc_lower": lower, "dc_mid": mid, "dc_pos": pos}
    )


def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.DataFrame:
    """Supertrend - ATR-Band, das nur in Trendrichtung nachgezogen wird."""
    hl2 = (df["high"] + df["low"]) / 2.0
    rng = atr(df, period)
    upper_basic = (hl2 + mult * rng).to_numpy()
    lower_basic = (hl2 - mult * rng).to_numpy()
    close = df["close"].to_numpy()

    n = len(df)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    trend = np.zeros(n, dtype=int)
    for i in range(n):
        if not np.isfinite(upper_basic[i]):
            continue
        if i == 0 or not np.isfinite(upper[i - 1]):
            upper[i], lower[i], trend[i] = upper_basic[i], lower_basic[i], 1
            continue
        upper[i] = (
            min(upper_basic[i], upper[i - 1]) if close[i - 1] <= upper[i - 1] else upper_basic[i]
        )
        lower[i] = (
            max(lower_basic[i], lower[i - 1]) if close[i - 1] >= lower[i - 1] else lower_basic[i]
        )
        if close[i] > upper[i - 1]:
            trend[i] = 1
        elif close[i] < lower[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
    line = np.where(trend == 1, lower, upper)
    return pd.DataFrame(
        {"st_line": line, "st_trend": trend.astype(float)}, index=df.index
    )


# --------------------------------------------------------------------------- #
# Volumen
# --------------------------------------------------------------------------- #


def obv(df: pd.DataFrame) -> pd.Series:
    sign = np.sign(df["close"].diff()).fillna(0.0)
    return (sign * df.get("volume", pd.Series(0.0, index=df.index))).cumsum()


def money_flow_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    flow = tp * df.get("volume", pd.Series(0.0, index=df.index))
    up = flow.where(tp.diff() > 0, 0.0).rolling(period, min_periods=period).sum()
    down = flow.where(tp.diff() < 0, 0.0).rolling(period, min_periods=period).sum()
    return 100.0 - 100.0 / (1.0 + up / down.replace(0, np.nan))


def chaikin_money_flow(df: pd.DataFrame, period: int = 20) -> pd.Series:
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng
    vol = df.get("volume", pd.Series(0.0, index=df.index))
    return (mfm * vol).rolling(period, min_periods=period).sum() / vol.rolling(
        period, min_periods=period
    ).sum().replace(0, np.nan)


def vwap(df: pd.DataFrame, anchor: str = "D") -> pd.Series:
    """VWAP, täglich (oder wöchentlich) neu verankert.

    Der wichtigste institutionelle Referenzpreis: darüber kaufen Institutionen
    tendenziell teurer als ihr Durchschnitt, darunter günstiger.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df.get("volume", pd.Series(1.0, index=df.index)).replace(0, 1.0)
    # normalize() erhält die Zeitzone; to_period() würde sie verwerfen
    if anchor.upper().startswith("W"):
        groups = df.index.normalize() - pd.to_timedelta(df.index.dayofweek, unit="D")
    else:
        groups = df.index.normalize()
    pv = (tp * vol).groupby(groups).cumsum()
    vv = vol.groupby(groups).cumsum()
    return pv / vv.replace(0, np.nan)


def volume_zscore(df: pd.DataFrame, period: int = 50) -> pd.Series:
    vol = df.get("volume", pd.Series(0.0, index=df.index))
    mean = vol.rolling(period, min_periods=period).mean()
    std = vol.rolling(period, min_periods=period).std(ddof=0)
    return (vol - mean) / std.replace(0, np.nan)


# --------------------------------------------------------------------------- #
# Normalisierung
# --------------------------------------------------------------------------- #


def zscore(series: pd.Series, period: int = 100) -> pd.Series:
    mean = series.rolling(period, min_periods=period // 2).mean()
    std = series.rolling(period, min_periods=period // 2).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)


def rolling_rank(series: pd.Series, period: int = 250) -> pd.Series:
    """Perzentilrang im rollierenden Fenster, in [0, 1].

    Für Modelle deutlich wertvoller als Rohwerte: der Rang bleibt über Regime
    und Symbole hinweg vergleichbar.
    """
    return series.rolling(period, min_periods=max(20, period // 5)).rank(pct=True)


def add_all(df: pd.DataFrame, cfg: object = None) -> pd.DataFrame:
    """Standardpaket an Indikatoren als neuen DataFrame (Index bleibt gleich)."""
    p_atr = getattr(cfg, "atr_period", 14)
    p_rsi = getattr(cfg, "rsi_period", 14)
    p_adx = getattr(cfg, "adx_period", 14)
    p_bb = getattr(cfg, "bb_period", 20)
    bb_std = getattr(cfg, "bb_std", 2.0)
    p_dc = getattr(cfg, "donchian_period", 20)
    emas = getattr(cfg, "ema_periods", [8, 21, 50, 200])
    hurst_win = getattr(cfg, "hurst_window", 120)

    close = df["close"]
    out = pd.DataFrame(index=df.index)

    a = atr(df, p_atr)
    out["atr"] = a
    out["atr_pct"] = a / close.replace(0, np.nan)
    out["atr_rank"] = rolling_rank(a, 250)
    out["tr_atr"] = true_range(df) / a.replace(0, np.nan)

    for period in emas:
        e = ema(close, period)
        out[f"ema_{period}"] = e
        out[f"dist_ema_{period}_atr"] = (close - e) / a.replace(0, np.nan)
    if len(emas) >= 2:
        fast, slow = emas[0], emas[-1]
        out["ema_stack"] = (
            (ema(close, fast) > ema(close, slow)).astype(float) * 2 - 1
        )
        out["ema_spread_atr"] = (ema(close, fast) - ema(close, slow)) / a.replace(0, np.nan)

    out["rsi"] = rsi(close, p_rsi)
    out["rsi_slope"] = out["rsi"].diff(3)
    out = out.join(macd(close))
    out["macd_hist_atr"] = out["macd_hist"] / a.replace(0, np.nan)
    out = out.join(stochastic(df))
    out["cci"] = cci(df)
    out["williams_r"] = williams_r(df)
    out["roc_10"] = roc(close, 10)

    dm = directional_movement(df, p_adx)
    out["adx"] = dm["adx"]
    out["di_diff"] = dm["plus_di"] - dm["minus_di"]
    out["efficiency_ratio"] = efficiency_ratio(close, 20)
    out["hurst"] = hurst(close, hurst_win)
    out["slope_20"] = linreg_slope(close, 20)
    out["r2_20"] = linreg_r2(close, 20)

    out = out.join(bollinger(close, p_bb, bb_std))
    out["bb_squeeze"] = (out["bb_width"] < out["bb_width"].rolling(120, min_periods=40).quantile(0.2)).astype(float)
    out = out.join(donchian(df, p_dc))
    out = out.join(supertrend(df))

    out["cmf"] = chaikin_money_flow(df)
    out["mfi"] = money_flow_index(df)
    out["vol_z"] = volume_zscore(df)
    vw = vwap(df)
    out["vwap_dist_atr"] = (close - vw) / a.replace(0, np.nan)

    out["ret_1"] = close.pct_change(1)
    out["ret_5"] = close.pct_change(5)
    out["ret_20"] = close.pct_change(20)
    out["realized_vol_20"] = realized_vol(close, 20)
    out["parkinson_20"] = parkinson_vol(df, 20)
    return out
