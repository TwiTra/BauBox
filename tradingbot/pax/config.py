"""Konfiguration des Systems.

Ein einziger, typisierter Konfigurationsbaum, der aus YAML geladen und wieder
geschrieben werden kann. Jeder Wert hat einen sinnvollen Standard, damit das
System auch ohne Konfigurationsdatei startet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict, fields, is_dataclass
from pathlib import Path
from typing import Any

from .types import Horizon, Timeframe

try:  # PyYAML ist Pflichtabhängigkeit, der Fallback hält Importe trotzdem heil
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


DEFAULT_CONFIG_PATH = Path("config/config.yaml")


# --------------------------------------------------------------------------- #
# Abschnitte
# --------------------------------------------------------------------------- #


@dataclass
class TerminalConfig:
    """Zugangsdaten und Pfad des MT5-Terminals.

    Zugangsdaten gehören nicht in die Konfigurationsdatei. Lasse sie leer und
    setze stattdessen die Umgebungsvariablen MT5_LOGIN, MT5_PASSWORD,
    MT5_SERVER - `from_env` liest sie beim Verbinden ein.
    """

    path: str = ""  # z.B. C:/Program Files/MetaTrader 5/terminal64.exe
    login: int = 0
    password: str = ""
    server: str = ""
    timeout_ms: int = 60_000
    portable: bool = False

    def from_env(self) -> "TerminalConfig":
        """Zugangsdaten aus der Umgebung ergänzen (Umgebung gewinnt)."""
        login = os.environ.get("MT5_LOGIN", "").strip()
        return TerminalConfig(
            path=os.environ.get("MT5_PATH", self.path),
            login=int(login) if login.isdigit() else self.login,
            password=os.environ.get("MT5_PASSWORD", self.password),
            server=os.environ.get("MT5_SERVER", self.server),
            timeout_ms=self.timeout_ms,
            portable=self.portable,
        )

    def redacted(self) -> dict[str, Any]:
        data = asdict(self)
        data["password"] = "***" if self.password else ""
        return data


@dataclass
class DataConfig:
    """Welche Märkte und Zeiteinheiten geladen werden."""

    symbols: list[str] = field(default_factory=lambda: ["EURUSD", "GBPUSD", "XAUUSD"])
    # Zuordnung Horizont -> Zeiteinheit. Das Herz der Mehrfach-Zeitebenen-Analyse.
    timeframes: dict[str, str] = field(
        default_factory=lambda: {
            Horizon.SHORT.value: Timeframe.M15.value,
            Horizon.MEDIUM.value: Timeframe.H1.value,
            Horizon.LONG.value: Timeframe.H4.value,
        }
    )
    # Zusätzlicher Kontext-Rahmen, der nur den Bias liefert, aber nicht handelt.
    context_timeframe: str = Timeframe.D1.value
    history_bars: int = 20_000
    warmup_bars: int = 400  # Balken, die vor dem ersten Signal verworfen werden
    cache_dir: str = "data_cache"
    max_bar_age_seconds: int = 90  # ältere Daten gelten als veraltet

    def tf(self, horizon: Horizon) -> Timeframe:
        return Timeframe.parse(self.timeframes[horizon.value])

    @property
    def base_timeframe(self) -> Timeframe:
        """Feinste genutzte Zeiteinheit - Taktgeber des Live-Betriebs."""
        return min((self.tf(h) for h in Horizon), key=lambda t: t.minutes)

    @property
    def all_timeframes(self) -> list[Timeframe]:
        seen: dict[str, Timeframe] = {}
        for h in Horizon:
            t = self.tf(h)
            seen[t.value] = t
        ctx = Timeframe.parse(self.context_timeframe)
        seen[ctx.value] = ctx
        return sorted(seen.values(), key=lambda t: t.minutes)


@dataclass
class FeatureConfig:
    """Parameter der Price-Action-Analyse."""

    swing_lookback: int = 3  # Fraktal-Breite links/rechts
    swing_atr_filter: float = 0.5  # Mindesthub eines Swings in ATR
    atr_period: int = 14
    ema_periods: list[int] = field(default_factory=lambda: [8, 21, 50, 200])
    rsi_period: int = 14
    adx_period: int = 14
    bb_period: int = 20
    bb_std: float = 2.0
    donchian_period: int = 20
    volume_profile_bins: int = 48
    volume_profile_lookback: int = 240
    level_cluster_atr: float = 0.35  # Cluster-Radius für S/R in ATR
    max_zones: int = 12  # wie viele Zonen je Typ behalten werden
    zone_max_age_bars: int = 300
    fvg_min_atr: float = 0.15  # Mindestgröße einer Fair-Value-Gap in ATR
    ob_lookback: int = 40
    regime_lookback: int = 250
    hurst_window: int = 120
    include_indicators: bool = True
    include_smc: bool = True
    include_patterns: bool = True
    include_levels: bool = True


@dataclass
class LabelConfig:
    """Triple-Barrier-Labeling nach López de Prado."""

    tp_atr: float = 2.0  # Ziel des Trades in ATR (Trade-Konstruktion, Meta-Label)
    sl_atr: float = 1.0  # Stop des Trades in ATR (Trade-Konstruktion, Meta-Label)
    # Die Richtungsfrage braucht einen symmetrischen Abstand, sonst verschiebt
    # sich der neutrale Punkt der Wahrscheinlichkeit weg von 0.5.
    direction_atr: float = 1.5
    max_horizon_bars: int = 48  # vertikale Barriere
    min_return_atr: float = 0.25  # kleinere Bewegungen gelten als neutral
    use_meta_labeling: bool = True
    min_meta_samples: int = 500  # darunter lohnt das Meta-Modell nicht
    sample_weight_decay: float = 0.5  # 0 = keine Zeitgewichtung, 1 = stark
    apply_uniqueness_weights: bool = True


@dataclass
class ModelConfig:
    """Ensemble und Training."""

    # Welche Modelle in den Topf kommen. Nicht installierte werden übersprungen.
    members: list[str] = field(
        default_factory=lambda: [
            "hist_gradient_boosting",
            "random_forest",
            "extra_trees",
            "logistic",
            "lightgbm",
            "xgboost",
            "catboost",
            "mlp",
        ]
    )
    blend: str = "stacking"  # "stacking" | "weighted" | "mean"
    calibration: str = "isotonic"  # "isotonic" | "sigmoid" | "none"
    n_splits: int = 6
    embargo_frac: float = 0.01  # Sperrzone um jede Testfalte (Anteil der Daten)
    min_train_samples: int = 400
    max_features: int = 120  # Feature-Auswahl nach Wichtigkeit
    feature_selection: bool = True
    random_state: int = 42
    n_jobs: int = -1
    prob_clip: float = 0.02  # Wahrscheinlichkeiten auf [clip, 1-clip] begrenzen
    min_member_auc: float = 0.51  # schwächere Modelle fliegen aus dem Ensemble
    hyperparameter_search: bool = False
    search_trials: int = 30


@dataclass
class RiskConfig:
    """Risikomanagement - der Teil, der Konten am Leben hält."""

    risk_per_trade: float = 0.005  # 0,5 % des Kontos je Trade
    max_risk_per_trade: float = 0.02
    use_kelly: bool = True
    kelly_fraction: float = 0.25  # nur ein Viertel des vollen Kelly
    max_open_positions: int = 3
    max_positions_per_symbol: int = 1
    max_daily_loss: float = 0.03  # 3 % Tagesverlust -> Handelsstopp
    max_weekly_loss: float = 0.06
    max_drawdown_stop: float = 0.15  # 15 % Rückgang -> Notaus
    max_correlated_risk: float = 0.02  # Summe des Risikos korrelierter Positionen
    correlation_threshold: float = 0.7
    min_risk_reward: float = 1.4
    # Überzeugungsschwelle auf der Skala der Signal-Engine (0 bis 1). 0,45
    # entspricht rund den obersten 1,5 % aller Balken - selektiv, aber nicht
    # so streng, dass nie ein Trade zustande kommt. 0,58 wäre schon extrem eng.
    min_signal_score: float = 0.45
    min_stop_atr: float = 0.6  # Stop nie enger als 0,6 ATR
    max_stop_atr: float = 3.5
    break_even_at_r: float = 1.0
    break_even_offset_r: float = 0.1
    trail_start_r: float = 1.5
    trail_atr: float = 2.0
    partial_take_r: list[float] = field(default_factory=lambda: [1.0, 2.0])
    partial_fractions: list[float] = field(default_factory=lambda: [0.4, 0.3])
    max_spread_atr: float = 0.25  # Spread über 25 % des ATR -> nicht handeln
    max_hold_bars_factor: float = 1.5  # Vielfaches des Label-Horizonts


@dataclass
class SessionConfig:
    """Handelszeiten und Nachrichtenfilter (alle Zeiten in UTC)."""

    trade_sessions: list[list[str]] = field(
        default_factory=lambda: [["07:00", "11:00"], ["12:30", "16:30"]]
    )
    trade_weekdays: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    avoid_first_minutes_of_day: int = 0
    friday_close_hour_utc: int = 20  # freitags ab hier keine neuen Trades
    news_file: str = "config/news.csv"  # optional: time,impact,currency
    news_block_minutes_before: int = 15
    news_block_minutes_after: int = 15
    news_min_impact: str = "high"


@dataclass
class ExecutionConfig:
    """Orderausführung."""

    magic: int = 770_425
    deviation_points: int = 20
    comment: str = "PAX"
    filling: str = "auto"  # "auto" | "IOC" | "FOK" | "RETURN"
    dry_run: bool = True  # Sicherheitsnetz: erst nach bewusstem Umschalten live
    retry_attempts: int = 3
    retry_delay_seconds: float = 1.0
    close_partial_min_volume: float = 0.01


@dataclass
class BacktestConfig:
    """Kostenmodell und Ablauf des Backtests."""

    initial_balance: float = 10_000.0
    spread_points: float = 12.0
    commission_per_lot: float = 7.0  # Round-Turn in Kontowährung
    slippage_points: float = 3.0
    swap_long_points: float = -0.8
    swap_short_points: float = -0.2
    use_symbol_spec_costs: bool = True
    intrabar_worst_case: bool = True  # bei SL+TP im selben Balken zählt der SL
    allow_shorts: bool = True
    allow_longs: bool = True


@dataclass
class LearningConfig:
    """Selbstlern- und Weiterentwicklungsschleife."""

    journal_path: str = "runtime/journal.sqlite"
    model_dir: str = "runtime/models"
    retrain_every_trades: int = 25
    retrain_every_hours: int = 24
    min_trades_for_feedback: int = 40
    challenger_min_improvement: float = 0.02  # +2 % gegenüber dem Champion
    challenger_min_trades: int = 150
    drift_psi_threshold: float = 0.25
    drift_check_every_bars: int = 500
    blocklist_min_trades: int = 15  # ab hier darf ein Setup gesperrt werden
    blocklist_max_expectancy: float = -0.15  # E[R] darunter -> gesperrt
    keep_model_versions: int = 10
    walk_forward_folds: int = 5


@dataclass
class LogConfig:
    level: str = "INFO"
    file: str = "runtime/pax.log"
    max_bytes: int = 5_000_000
    backups: int = 5
    console: bool = True


@dataclass
class Config:
    """Der gesamte Konfigurationsbaum."""

    terminal: TerminalConfig = field(default_factory=TerminalConfig)
    data: DataConfig = field(default_factory=DataConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    labels: LabelConfig = field(default_factory=LabelConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    logging: LogConfig = field(default_factory=LogConfig)

    # ------------------------------------------------------------------ #
    # Laden / Speichern
    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, path: "str | Path | None" = None) -> "Config":
        """Konfiguration laden. Fehlt die Datei, gelten die Standardwerte."""
        if path is None:
            path = DEFAULT_CONFIG_PATH
        p = Path(path)
        if not p.exists():
            return cls()
        if yaml is None:  # pragma: no cover
            raise RuntimeError("PyYAML fehlt - bitte 'pip install pyyaml' ausführen")
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Config":
        return _build(cls, raw)

    def to_dict(self, redact: bool = True) -> dict[str, Any]:
        data = asdict(self)
        if redact and data.get("terminal", {}).get("password"):
            data["terminal"]["password"] = "***"
        return data

    def save(self, path: "str | Path", redact: bool = True) -> Path:
        if yaml is None:  # pragma: no cover
            raise RuntimeError("PyYAML fehlt - bitte 'pip install pyyaml' ausführen")
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            yaml.safe_dump(self.to_dict(redact=redact), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return p

    # ------------------------------------------------------------------ #
    # Prüfung
    # ------------------------------------------------------------------ #

    def validate(self) -> list[str]:
        """Gibt eine Liste von Problemen zurück. Leer = alles in Ordnung."""
        problems: list[str] = []
        r = self.risk
        if not 0 < r.risk_per_trade <= r.max_risk_per_trade:
            problems.append("risk.risk_per_trade muss zwischen 0 und max_risk_per_trade liegen")
        if r.max_risk_per_trade > 0.05:
            problems.append("risk.max_risk_per_trade über 5 % je Trade ist grob fahrlässig")
        if not 0 < r.kelly_fraction <= 1:
            problems.append("risk.kelly_fraction muss in (0, 1] liegen")
        if r.min_stop_atr >= r.max_stop_atr:
            problems.append("risk.min_stop_atr muss kleiner als max_stop_atr sein")
        if len(r.partial_take_r) != len(r.partial_fractions):
            problems.append("risk.partial_take_r und partial_fractions brauchen gleiche Länge")
        if sum(r.partial_fractions) >= 1.0:
            problems.append("risk.partial_fractions dürfen zusammen keine 100 % ergeben")
        if r.max_daily_loss <= 0 or r.max_daily_loss > 0.2:
            problems.append("risk.max_daily_loss sollte in (0, 0.2] liegen")

        lb = self.labels
        if lb.tp_atr <= 0 or lb.sl_atr <= 0:
            problems.append("labels.tp_atr und labels.sl_atr müssen positiv sein")
        if lb.max_horizon_bars < 2:
            problems.append("labels.max_horizon_bars muss mindestens 2 sein")

        try:
            tfs = [self.data.tf(h) for h in Horizon]
        except (KeyError, ValueError) as exc:
            problems.append(f"data.timeframes unvollständig oder ungültig: {exc}")
        else:
            if not (tfs[0].minutes <= tfs[1].minutes <= tfs[2].minutes):
                problems.append(
                    "data.timeframes: kurzfristig <= mittelfristig <= langfristig verletzt"
                )
        if not self.data.symbols:
            problems.append("data.symbols ist leer")
        if self.data.warmup_bars < 200:
            problems.append("data.warmup_bars unter 200 - Indikatoren sind dann nicht eingeschwungen")

        m = self.model
        if m.n_splits < 3:
            problems.append("model.n_splits sollte mindestens 3 sein")
        if not 0 <= m.embargo_frac < 0.2:
            problems.append("model.embargo_frac muss in [0, 0.2) liegen")
        if m.blend not in {"stacking", "weighted", "mean"}:
            problems.append(f"model.blend unbekannt: {m.blend}")
        if m.calibration not in {"isotonic", "sigmoid", "none"}:
            problems.append(f"model.calibration unbekannt: {m.calibration}")
        return problems

    def require_valid(self) -> "Config":
        problems = self.validate()
        if problems:
            raise ValueError("Konfigurationsfehler:\n  - " + "\n  - ".join(problems))
        return self


# --------------------------------------------------------------------------- #
# Hilfsfunktion: verschachtelte Dataclasses aus dict bauen
# --------------------------------------------------------------------------- #


def _section_type(cls: type, name: str) -> "type | None":
    """Den Dataclass-Typ eines Konfigurationsabschnitts über seine Factory ermitteln.

    Wegen `from __future__ import annotations` sind die Feld-Typen zur Laufzeit
    nur Strings. Die default_factory liefert dagegen eine echte Instanz, aus der
    sich der Typ zuverlässig ablesen lässt.
    """
    f = cls.__dataclass_fields__.get(name)  # type: ignore[attr-defined]
    if f is None:
        return None
    factory = getattr(f, "default_factory", None)
    if not callable(factory):
        return None
    try:
        proto = factory()
    except Exception:  # pragma: no cover - defensive
        return None
    return type(proto) if is_dataclass(proto) else None


def _build(cls: type, raw: Any) -> Any:
    """Rekursiv eine Dataclass aus einem dict aufbauen, unbekannte Keys ignorieren."""
    if not is_dataclass(cls) or not isinstance(raw, dict):
        return raw
    known = {f.name for f in fields(cls)}
    kwargs: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in known:
            continue  # unbekannte Schlüssel still übergehen: Vorwärtskompatibilität
        section = _section_type(cls, key)
        kwargs[key] = _build(section, value) if section is not None else value
    return cls(**kwargs)
