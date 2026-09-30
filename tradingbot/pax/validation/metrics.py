"""Kennzahlen für Modelle und Handelsergebnisse.

Zwei Sichtweisen, die man nicht verwechseln darf: Ein Modell mit 58 % Trefferquote
kann Geld verlieren, ein Modell mit 38 % kann prächtig verdienen. Deshalb stehen
hier beide Blöcke nebeneinander - Klassifikationsgüte *und* Handelsergebnis.

Besonderes Gewicht liegt auf der ehrlichen Bewertung: `deflated_sharpe` bestraft,
dass man viele Varianten durchprobiert hat. Wer 500 Strategien testet, findet
garantiert eine mit Sharpe 2 - aus reinem Zufall.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

try:  # scipy nur für die Normalverteilung - Fallback ist ausreichend genau
    from scipy.stats import norm

    _norm_cdf = norm.cdf
except ImportError:  # pragma: no cover
    def _norm_cdf(x):  # type: ignore[misc]
        arr = np.asarray(x, dtype=float)
        return 0.5 * (1.0 + np.vectorize(math.erf)(arr / math.sqrt(2.0)))


# --------------------------------------------------------------------------- #
# Modellgüte
# --------------------------------------------------------------------------- #


def classification_metrics(
    y_true: "np.ndarray | pd.Series",
    proba: "np.ndarray | pd.Series",
    weights: "np.ndarray | pd.Series | None" = None,
    threshold: float = 0.5,
) -> dict[str, float]:
    """Trefferquote, AUC, Brier-Score und Kalibrierungsfehler."""
    y = np.asarray(y_true, dtype=float).ravel()
    p = np.clip(np.asarray(proba, dtype=float).ravel(), 1e-6, 1 - 1e-6)
    w = np.ones_like(y) if weights is None else np.asarray(weights, dtype=float).ravel()
    mask = np.isfinite(y) & np.isfinite(p) & np.isfinite(w)
    y, p, w = y[mask], p[mask], w[mask]
    if len(y) == 0:
        return {"n": 0}

    pred = (p >= threshold).astype(float)
    tp = float((w * (pred == 1) * (y == 1)).sum())
    fp = float((w * (pred == 1) * (y == 0)).sum())
    fn = float((w * (pred == 0) * (y == 1)).sum())
    tn = float((w * (pred == 0) * (y == 0)).sum())
    total = tp + fp + fn + tn

    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    return {
        "n": int(len(y)),
        "accuracy": round((tp + tn) / total, 4) if total else 0.0,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall > 0 else 0.0,
        "auc": round(roc_auc(y, p, w), 4),
        "brier": round(float((w * (p - y) ** 2).sum() / w.sum()), 4),
        "log_loss": round(float(-(w * (y * np.log(p) + (1 - y) * np.log(1 - p))).sum() / w.sum()), 4),
        "calibration_error": round(expected_calibration_error(y, p, w), 4),
        "base_rate": round(float((w * y).sum() / w.sum()), 4),
        "mean_proba": round(float((w * p).sum() / w.sum()), 4),
    }


def roc_auc(y: np.ndarray, p: np.ndarray, w: "np.ndarray | None" = None) -> float:
    """Fläche unter der ROC-Kurve über die Rangstatistik (Mann-Whitney-U)."""
    w = np.ones_like(y) if w is None else w
    pos, neg = y == 1, y == 0
    if pos.sum() == 0 or neg.sum() == 0:
        return 0.5
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    # Bindungen mitteln, sonst wird die AUC bei groben Wahrscheinlichkeiten verzerrt
    sorted_p = p[order]
    i = 0
    while i < len(sorted_p):
        j = i
        while j + 1 < len(sorted_p) and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    w_pos = w[pos].sum()
    w_neg = w[neg].sum()
    rank_sum = float((w[pos] * ranks[pos]).sum())
    # Gewichtete Näherung der U-Statistik
    n_pos_eff = w_pos / w.mean() if w.mean() > 0 else pos.sum()
    u = rank_sum / w.mean() - n_pos_eff * (n_pos_eff + 1) / 2.0 if w.mean() > 0 else 0.0
    n_neg_eff = w_neg / w.mean() if w.mean() > 0 else neg.sum()
    denom = n_pos_eff * n_neg_eff
    return float(np.clip(u / denom, 0.0, 1.0)) if denom > 0 else 0.5


def expected_calibration_error(
    y: np.ndarray, p: np.ndarray, w: "np.ndarray | None" = None, bins: int = 10
) -> float:
    """Mittlere Abweichung zwischen versprochener und erreichter Trefferquote.

    Für den Handel wichtiger als die AUC: die Positionsgröße hängt direkt an der
    Wahrscheinlichkeit. Wer "70 %" sagt und 50 % liefert, riskiert zu viel.
    """
    w = np.ones_like(y) if w is None else w
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = w.sum()
    if total <= 0:
        return 0.0
    error = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1.0 else p <= hi)
        if not m.any():
            continue
        wm = w[m].sum()
        error += (wm / total) * abs(float((w[m] * y[m]).sum() / wm) - float((w[m] * p[m]).sum() / wm))
    return float(error)


def reliability_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Kalibrierungstabelle: versprochen gegen tatsächlich eingetreten."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1.0 else p <= hi)
        if not m.any():
            continue
        rows.append(
            {
                "bereich": f"{lo:.1f}-{hi:.1f}",
                "n": int(m.sum()),
                "versprochen": round(float(p[m].mean()), 4),
                "eingetreten": round(float(y[m].mean()), 4),
                "abweichung": round(float(y[m].mean() - p[m].mean()), 4),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Handelsergebnis
# --------------------------------------------------------------------------- #


def trading_metrics(r_multiples: "np.ndarray | pd.Series", costs_r: float = 0.0) -> dict[str, float]:
    """Kennzahlen aus einer Reihe von R-Vielfachen.

    In R zu rechnen macht Ergebnisse über Symbole und Positionsgrößen hinweg
    vergleichbar: ein Trade mit +2R ist ein Trade mit +2R, egal ob im DAX oder
    im EURUSD.
    """
    r = np.asarray(r_multiples, dtype=float).ravel()
    r = r[np.isfinite(r)] - costs_r
    n = len(r)
    if n == 0:
        return {"trades": 0}

    wins, losses = r[r > 0], r[r < 0]
    gross_win, gross_loss = float(wins.sum()), float(-losses.sum())
    expectancy = float(r.mean())
    std = float(r.std(ddof=1)) if n > 1 else 0.0

    equity = np.cumsum(r)
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    dd = peak - equity
    max_dd = float(dd.max()) if n else 0.0

    return {
        "trades": n,
        "win_rate": round(len(wins) / n, 4),
        "expectancy_r": round(expectancy, 4),
        "total_r": round(float(r.sum()), 3),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else float("inf"),
        "avg_win_r": round(float(wins.mean()), 3) if len(wins) else 0.0,
        "avg_loss_r": round(float(losses.mean()), 3) if len(losses) else 0.0,
        "payoff_ratio": round(float(wins.mean() / -losses.mean()), 3) if len(wins) and len(losses) else 0.0,
        "std_r": round(std, 3),
        "sharpe_per_trade": round(expectancy / std, 3) if std > 0 else 0.0,
        "sortino": round(_sortino(r), 3),
        "max_drawdown_r": round(max_dd, 3),
        "recovery_factor": round(float(r.sum()) / max_dd, 3) if max_dd > 0 else float("inf"),
        "max_consecutive_losses": int(_max_streak(r < 0)),
        "kelly_fraction": round(_kelly(r), 4),
    }


def equity_metrics(
    equity: "pd.Series | np.ndarray", periods_per_year: float = 252 * 24
) -> dict[str, float]:
    """Kennzahlen aus einer Kapitalkurve."""
    eq = pd.Series(np.asarray(equity, dtype=float)).dropna()
    if len(eq) < 3:
        return {"bars": len(eq)}
    ret = eq.pct_change().dropna()
    total_return = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
    peak = eq.cummax()
    dd = (eq - peak) / peak
    max_dd = float(dd.min())
    ann_factor = math.sqrt(periods_per_year)
    std = float(ret.std(ddof=1))
    years = len(eq) / periods_per_year

    return {
        "bars": len(eq),
        "total_return": round(total_return, 4),
        "cagr": round(float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1.0), 4) if years > 0.1 else 0.0,
        "sharpe": round(float(ret.mean() / std * ann_factor), 3) if std > 0 else 0.0,
        "sortino": round(_sortino(ret.to_numpy()) * ann_factor, 3),
        "max_drawdown": round(max_dd, 4),
        "calmar": round(total_return / abs(max_dd), 3) if max_dd < 0 else float("inf"),
        "volatility_ann": round(std * ann_factor, 4),
        "ulcer_index": round(float(np.sqrt((dd**2).mean())), 4),
        "longest_drawdown_bars": int(_longest_drawdown(eq)),
    }


def probabilistic_sharpe(sharpe: float, n: int, skew: float = 0.0, kurtosis: float = 3.0,
                         benchmark: float = 0.0) -> float:
    """Wahrscheinlichkeit, dass die wahre Sharpe Ratio über `benchmark` liegt.

    Berücksichtigt Schiefe und Wölbung: eine Strategie mit vielen kleinen
    Gewinnen und seltenen Katastrophen hat eine schmeichelhafte Sharpe Ratio
    und eine miserable PSR.
    """
    if n < 3:
        return 0.5
    denom = math.sqrt(max(1e-12, 1 - skew * sharpe + (kurtosis - 1) / 4.0 * sharpe**2))
    z = (sharpe - benchmark) * math.sqrt(n - 1) / denom
    return float(_norm_cdf(z))


def deflated_sharpe(
    sharpe: float, n: int, n_trials: int = 1, skew: float = 0.0, kurtosis: float = 3.0,
    variance_of_trials: "float | None" = None,
) -> float:
    """Sharpe Ratio, bereinigt um die Zahl der ausprobierten Varianten.

    Wer 200 Parametersätze testet, findet auch in reinem Rauschen einen mit
    Sharpe 2. Diese Kennzahl setzt die Messlatte entsprechend höher und ist der
    ehrlichste Einzelwert, den man einer optimierten Strategie geben kann.

    `variance_of_trials` ist die Streuung der Sharpe Ratios *über die Versuche*.
    Liegt sie nicht vor, wird die Stichprobenvarianz des Schätzers benutzt,
    Var(SR) ~ (1 + SR^2/2) / n. Eine feste 1,0 wäre um Größenordnungen zu hoch -
    die Messlatte läge dann so absurd hoch, dass jede Strategie bei 0 landet und
    die Kennzahl gar nichts mehr unterscheidet.
    """
    if n_trials <= 1:
        return probabilistic_sharpe(sharpe, n, skew, kurtosis)
    if variance_of_trials is None:
        variance_of_trials = (1.0 + 0.5 * sharpe**2) / max(n, 2)
    euler = 0.5772156649
    e = math.e
    # Erwartetes Maximum von n_trials unabhängigen Nullstrategien
    expected_max = math.sqrt(max(variance_of_trials, 1e-12)) * (
        (1 - euler) * _norm_ppf(1 - 1.0 / n_trials)
        + euler * _norm_ppf(1 - 1.0 / (n_trials * e))
    )
    return probabilistic_sharpe(sharpe, n, skew, kurtosis, benchmark=expected_max)


def _norm_ppf(q: float) -> float:
    """Inverse Standardnormalverteilung (Acklam-Näherung, genügt hier völlig)."""
    q = min(max(q, 1e-12), 1 - 1e-12)
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if q < p_low:
        x = math.sqrt(-2 * math.log(q))
        return (((((c[0] * x + c[1]) * x + c[2]) * x + c[3]) * x + c[4]) * x + c[5]) / (
            (((d[0] * x + d[1]) * x + d[2]) * x + d[3]) * x + 1
        )
    if q > p_high:
        x = math.sqrt(-2 * math.log(1 - q))
        return -(((((c[0] * x + c[1]) * x + c[2]) * x + c[3]) * x + c[4]) * x + c[5]) / (
            (((d[0] * x + d[1]) * x + d[2]) * x + d[3]) * x + 1
        )
    x = q - 0.5
    r = x * x
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * x / (
        ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1
    )


def _sortino(r: np.ndarray) -> float:
    """Sortino: Ertrag geteilt durch die Abweichung nach unten.

    Entscheidend ist der Nenner: Quadriert wird über *alle* Beobachtungen, nicht
    nur über die negativen. Sonst bestraft die Kennzahl eine Strategie mit
    wenigen, dafür flachen Verlusten - also genau das Gegenteil ihres Zwecks.
    """
    if len(r) == 0:
        return 0.0
    downside = np.minimum(r, 0.0)
    dd = float(np.sqrt((downside**2).mean()))
    return float(r.mean() / dd) if dd > 0 else 0.0


def _max_streak(flags: np.ndarray) -> int:
    best = current = 0
    for f in flags:
        current = current + 1 if f else 0
        best = max(best, current)
    return best


def _kelly(r: np.ndarray) -> float:
    """Optimale Einsatzquote nach Kelly aus den beobachteten R-Werten."""
    wins, losses = r[r > 0], r[r < 0]
    if len(wins) == 0 or len(losses) == 0:
        return 0.0
    p = len(wins) / len(r)
    b = float(wins.mean() / -losses.mean())
    if b <= 0:
        return 0.0
    return float(max(0.0, (p * (b + 1) - 1) / b))


def _longest_drawdown(equity: pd.Series) -> int:
    peak = equity.cummax()
    under = (equity < peak).to_numpy()
    return _max_streak(under)


def summarize(
    r_multiples: "np.ndarray | pd.Series",
    equity: "pd.Series | np.ndarray | None" = None,
    n_trials: int = 1,
    periods_per_year: float = 252 * 24,
) -> dict[str, float]:
    """Alles zusammen, inklusive der um Mehrfachtests bereinigten Sharpe Ratio."""
    out = trading_metrics(r_multiples)
    if equity is not None:
        out.update(equity_metrics(equity, periods_per_year))
    r = np.asarray(r_multiples, dtype=float).ravel()
    r = r[np.isfinite(r)]
    if len(r) > 3 and r.std(ddof=1) > 0:
        sr = float(r.mean() / r.std(ddof=1))
        centered = (r - r.mean()) / r.std(ddof=1)
        out["psr"] = round(
            probabilistic_sharpe(sr, len(r), float((centered**3).mean()), float((centered**4).mean())), 4
        )
        out["deflated_sharpe"] = round(
            deflated_sharpe(sr, len(r), n_trials, float((centered**3).mean()), float((centered**4).mean())), 4
        )
    return out
