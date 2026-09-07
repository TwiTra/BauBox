"""Merkmalsaufbau: aus Kerzen wird eine Matrix, mit der ein Modell arbeiten kann.

Hier läuft alles zusammen. Je Zeiteinheit werden Indikatoren, Marktstruktur,
Kerzenformationen, institutionelle Zonen, Preisniveaus und Regime berechnet;
anschließend werden die höheren Zeitebenen zeitrichtig auf die Basisebene
gelegt.

Zwei Regeln gelten hier ohne Ausnahme:

1. Kein Merkmal darf Daten aus der Zukunft benutzen. `assert_causal` prüft das
   maschinell, und die Testsuite führt diese Prüfung bei jedem Lauf aus.
2. Merkmale werden in ATR oder Rängen ausgedrückt, nicht in Preiseinheiten.
   Sonst lernt das Modell den Kursstand auswendig statt das Verhalten.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import Config, FeatureConfig
from ..types import Horizon, Timeframe, TrendState, VolRegime
from ..utils import get_logger
from . import indicators as ind
from . import levels as lv
from . import mtf
from . import patterns as pat
from .regime import RegimeDetector
from .smc import SMCAnalyzer, SMCResult
from .structure import MarketStructure, StructureAnalyzer

log = get_logger("features")


@dataclass
class FeatureSet:
    """Fertige Merkmalsmatrix samt Zwischenergebnissen."""

    frame: pd.DataFrame
    base: pd.DataFrame
    atr: pd.Series
    timeframe: Timeframe
    structures: dict[str, MarketStructure] = field(default_factory=dict)
    smc: dict[str, SMCResult] = field(default_factory=dict)
    per_timeframe: dict[str, pd.DataFrame] = field(default_factory=dict)
    symbol: str = ""

    @property
    def feature_names(self) -> list[str]:
        return list(self.frame.columns)

    def latest(self) -> pd.Series:
        return self.frame.iloc[-1]

    def horizon_columns(self, horizon: Horizon, tf_map: dict[str, str]) -> list[str]:
        """Spalten, die zu einem Horizont gehören."""
        prefix = f"{tf_map[horizon.value].lower()}_"
        base_tf = min(tf_map.values(), key=lambda t: Timeframe.parse(t).minutes)
        if tf_map[horizon.value] == base_tf:
            return [c for c in self.frame.columns if "_" not in c[:4] or not _has_tf_prefix(c, tf_map)]
        return [c for c in self.frame.columns if c.startswith(prefix)]

    def trend_of(self, timeframe: "str | Timeframe") -> TrendState:
        tf = Timeframe.parse(timeframe).value
        ms = self.structures.get(tf)
        return ms.current_trend if ms else TrendState.RANGE

    def describe(self) -> str:
        return (
            f"{self.symbol} {self.timeframe.value}: {len(self.frame)} Zeilen x "
            f"{len(self.frame.columns)} Merkmale, "
            f"{self.frame.index[0]:%Y-%m-%d} bis {self.frame.index[-1]:%Y-%m-%d}"
        )


def _has_tf_prefix(col: str, tf_map: dict[str, str]) -> bool:
    return any(col.startswith(f"{v.lower()}_") for v in tf_map.values())


class FeatureBuilder:
    """Baut die Merkmalsmatrix für ein Symbol über alle Zeitebenen."""

    def __init__(self, cfg: "Config | FeatureConfig | None" = None) -> None:
        if isinstance(cfg, Config):
            self.cfg = cfg.features
            self.full_cfg: Config | None = cfg
        else:
            self.cfg = cfg or FeatureConfig()
            self.full_cfg = None
        f = self.cfg
        self.structure = StructureAnalyzer(f.swing_lookback, f.swing_atr_filter, f.atr_period)
        self.smc = SMCAnalyzer(f.fvg_min_atr, f.ob_lookback, f.max_zones, f.zone_max_age_bars)
        self.regime = RegimeDetector(f.regime_lookback, f.atr_period, f.adx_period)

    # ------------------------------------------------------------------ #
    # Eine Zeiteinheit
    # ------------------------------------------------------------------ #

    def build_single(
        self, df: pd.DataFrame, digits: int = 5, with_context: bool = True
    ) -> tuple[pd.DataFrame, MarketStructure, SMCResult]:
        """Alle Merkmale einer einzelnen Zeitebene."""
        if len(df) < 60:
            raise ValueError(f"Zu wenige Balken für eine Analyse: {len(df)}")
        f = self.cfg
        atr = ind.atr(df, f.atr_period)
        parts: list[pd.DataFrame] = []

        if f.include_indicators:
            parts.append(ind.add_all(df, f))

        structure = self.structure.analyze(df, atr)
        parts.append(structure.frame)

        if f.include_patterns:
            parts.append(pat.detect(df, atr))

        smc_result = (
            self.smc.analyze(df, atr, structure.events, structure.swings, structure.frame)
            if f.include_smc
            else SMCResult(frame=pd.DataFrame(index=df.index))
        )
        if not smc_result.frame.empty:
            parts.append(smc_result.frame)

        if f.include_levels:
            parts.append(
                lv.all_level_features(
                    df, atr, structure.swings, f.level_cluster_atr,
                    f.volume_profile_lookback, f.volume_profile_bins, digits,
                )
            )

        if with_context:
            parts.append(self.regime.analyze(df, atr))

        frame = pd.concat(parts, axis=1)
        frame = frame.loc[:, ~frame.columns.duplicated()]
        # Absolute Preisspalten fliegen raus: das Modell soll Verhalten lernen,
        # nicht den Kursstand von 2019 auswendig.
        drop = [
            c for c in frame.columns
            if c.startswith(("ema_", "bb_mid", "bb_upper", "bb_lower", "kc_", "dc_upper",
                             "dc_lower", "dc_mid", "st_line", "swing_high", "swing_low",
                             "prev_swing_high", "prev_swing_low"))
            and not c.startswith("ema_stack") and not c.startswith("ema_spread")
        ]
        frame = frame.drop(columns=drop, errors="ignore")
        return _sanitize(frame), structure, smc_result

    # ------------------------------------------------------------------ #
    # Alle Zeitebenen
    # ------------------------------------------------------------------ #

    def build(
        self,
        frames: dict[str, pd.DataFrame],
        base_timeframe: "str | Timeframe | None" = None,
        symbol: str = "",
        digits: int = 5,
        warmup: "int | None" = None,
    ) -> FeatureSet:
        """Merkmalsmatrix über mehrere Zeitebenen, auf die Basisebene ausgerichtet.

        `frames` bildet Zeiteinheit (z. B. "M15") auf OHLCV ab. Die feinste
        Ebene ist die Basis; alle gröberen werden zeitrichtig darauf gelegt.
        """
        if not frames:
            raise ValueError("Keine Kursdaten übergeben")
        tfs = {Timeframe.parse(k): v for k, v in frames.items()}
        base_tf = Timeframe.parse(base_timeframe) if base_timeframe else min(tfs, key=lambda t: t.minutes)
        base_df = tfs[base_tf]

        structures: dict[str, MarketStructure] = {}
        smcs: dict[str, SMCResult] = {}
        per_tf: dict[str, pd.DataFrame] = {}

        base_frame, base_struct, base_smc = self.build_single(base_df, digits, with_context=True)
        structures[base_tf.value] = base_struct
        smcs[base_tf.value] = base_smc
        per_tf[base_tf.value] = base_frame

        combined = base_frame
        for tf, df in sorted(tfs.items(), key=lambda kv: kv[0].minutes):
            if tf is base_tf:
                continue
            if len(df) < 60:
                log.warning("%s %s hat nur %d Balken - Zeitebene wird übersprungen", symbol, tf.value, len(df))
                continue
            frame, structure, smc_result = self.build_single(df, digits, with_context=True)
            structures[tf.value] = structure
            smcs[tf.value] = smc_result
            per_tf[tf.value] = frame
            # Nur die aussagekräftigen Spalten übernehmen - sonst explodiert die
            # Merkmalszahl und mit ihr die Überanpassungsgefahr.
            selected = frame[[c for c in HIGHER_TF_COLUMNS if c in frame.columns]]
            aligned = mtf.align_to_base(selected, base_frame.index, tf, prefix=f"{tf.value.lower()}_")
            combined = combined.join(aligned)

        combined = self._add_cross_timeframe(combined, base_tf, tfs)
        combined = _sanitize(combined)

        warmup = self.full_cfg.data.warmup_bars if (warmup is None and self.full_cfg) else (warmup or 0)
        if warmup and len(combined) > warmup:
            combined = combined.iloc[warmup:]

        return FeatureSet(
            frame=combined,
            base=base_df.loc[combined.index],
            atr=ind.atr(base_df, self.cfg.atr_period).loc[combined.index],
            timeframe=base_tf,
            structures=structures,
            smc=smcs,
            per_timeframe=per_tf,
            symbol=symbol,
        )

    @staticmethod
    def _add_cross_timeframe(
        frame: pd.DataFrame, base_tf: Timeframe, tfs: dict[Timeframe, pd.DataFrame]
    ) -> pd.DataFrame:
        """Merkmale, die erst aus dem Vergleich der Ebenen entstehen.

        Genau hier steckt der Mehrwert der Mehrfach-Zeitebenen-Analyse: nicht in
        den Einzelwerten, sondern in ihrer Übereinstimmung.
        """
        out = frame.copy()
        trend_cols = [c for c in out.columns if c.endswith("struct_trend")]
        if len(trend_cols) >= 2:
            trends = out[trend_cols]
            out["mtf_trend_sum"] = trends.sum(axis=1)
            out["mtf_trend_agree"] = (trends.abs().sum(axis=1) > 0) * (
                trends.sum(axis=1).abs() / trends.abs().sum(axis=1).replace(0, np.nan)
            )
            out["mtf_trend_agree"] = out["mtf_trend_agree"].fillna(0.0)
            # Signum der Basisebene gegen das der höchsten Ebene
            higher = [c for c in trend_cols if c != "struct_trend"]
            if higher and "struct_trend" in out.columns:
                out["mtf_base_vs_high"] = out["struct_trend"] * out[higher[-1]]

        regime_cols = [c for c in out.columns if c.endswith("regime_score")]
        if len(regime_cols) >= 2:
            out["mtf_regime_sum"] = out[regime_cols].sum(axis=1)

        pd_cols = [c for c in out.columns if c.endswith("premium_discount")]
        if len(pd_cols) >= 2:
            # Im Aufwärtstrend der höheren Ebene in deren Discount-Zone kaufen -
            # der Kern jedes "Buy the dip"-Ansatzes, hier messbar gemacht.
            out["mtf_premium_spread"] = out[pd_cols[0]] - out[pd_cols[-1]]
        return out


# Spalten, die von höheren Zeitebenen übernommen werden. Bewusst kurz gehalten:
# der große Rahmen liefert Richtung und Kontext, nicht Feinheiten.
HIGHER_TF_COLUMNS = [
    "struct_trend", "struct_event", "struct_event_dir", "bars_since_struct_event",
    "swing_sequence", "premium_discount", "range_position",
    "dist_swing_high_atr", "dist_swing_low_atr",
    "adx", "di_diff", "rsi", "efficiency_ratio", "hurst",
    "atr_pct", "atr_rank", "ema_stack", "ema_spread_atr", "dist_ema_50_atr",
    "bb_pct", "bb_width", "dc_pos", "st_trend",
    "trendiness", "trend_regime", "trend_direction", "regime_score",
    "vol_rank", "vol_regime", "vol_expansion",
    "smc_score", "zone_confluence", "sweep_signal",
    "ob_in_bull", "ob_in_bear", "fvg_in_bull", "fvg_in_bear",
    "res_dist_atr", "sup_dist_atr", "level_balance",
    "pattern_score", "pat_pinbar", "pat_engulfing",
]


def _sanitize(frame: pd.DataFrame) -> pd.DataFrame:
    """Unendliche Werte entfernen, Lücken schließen, Ausreißer kappen.

    Wichtig: ausschließlich mit `ffill` gefüllt, niemals mit `bfill` - letzteres
    würde Werte aus der Zukunft rückwärts kopieren.
    """
    out = frame.replace([np.inf, -np.inf], np.nan)
    out = out.ffill()
    out = out.fillna(0.0)
    numeric = out.select_dtypes(include=[np.number]).columns
    out[numeric] = out[numeric].clip(-1e6, 1e6)
    return out


def assert_causal(
    builder: FeatureBuilder,
    frames: dict[str, pd.DataFrame],
    cut: int = 50,
    check_rows: int = 100,
    tolerance: float = 1e-9,
) -> dict[str, float]:
    """Prüft maschinell, dass kein Merkmal in die Zukunft schaut.

    Die Matrix wird zweimal gebaut - einmal auf allen Daten, einmal auf den um
    `cut` Balken gekürzten. Auf dem gemeinsamen Zeitraum müssen beide identisch
    sein. Jede Abweichung ist ein Datenleck.
    """
    full = builder.build(frames, warmup=0)
    trimmed_frames = {}
    for tf_name, df in frames.items():
        tf = Timeframe.parse(tf_name)
        base = min(Timeframe.parse(k) for k in frames)
        scale = max(1, tf.minutes // base.minutes)
        drop = max(1, cut // scale)
        trimmed_frames[tf_name] = df.iloc[:-drop]
    trimmed = builder.build(trimmed_frames, warmup=0)

    common = trimmed.frame.index[-check_rows:]
    common = common.intersection(full.frame.index)
    if len(common) == 0:
        raise AssertionError("Kein gemeinsamer Zeitraum für die Kausalitätsprüfung")

    a = full.frame.loc[common]
    b = trimmed.frame.loc[common]
    shared = [c for c in a.columns if c in b.columns]
    diff = (a[shared] - b[shared]).abs().max()
    leaks = {c: float(v) for c, v in diff.items() if v > tolerance}
    if leaks:
        raise AssertionError(
            "Lookahead entdeckt in: "
            + ", ".join(f"{k} (Δ{v:.3g})" for k, v in sorted(leaks.items(), key=lambda x: -x[1])[:10])
        )
    return {c: float(v) for c, v in diff.items()}
