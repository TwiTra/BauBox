"""Kommandozeile.

Ein Befehl je Arbeitsschritt, in der Reihenfolge, in der man sie braucht:

    init        Konfigurationsdatei anlegen
    status      Was ist da? Daten, Modelle, Journal
    connect     MT5-Verbindung prüfen
    fetch       Historie herunterladen
    analyse     aktuelle Lage und Signal für ein Symbol
    backtest    Strategie auf der Historie prüfen
    train       Modell anlernen
    walkforward Vorwärtstest - die ehrlichste Prüfung
    evolve      Lernschleife: nachtrainieren und ablösen
    feedback    Fehleranalyse aus dem Journal
    live        Livebetrieb (standardmäßig Trockenlauf)
    journal     Statistik und Export
    selftest    interne Prüfungen, allen voran auf Lookahead
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .config import Config, DEFAULT_CONFIG_PATH
from .datasource import load_data
from .types import Horizon, Timeframe, utcnow
from .utils import fmt_money, fmt_pct, get_logger, setup_logging

log = get_logger("cli")


# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #


def _load_config(args: argparse.Namespace) -> Config:
    cfg = Config.load(args.config)
    setup_logging(
        level="DEBUG" if getattr(args, "verbose", False) else cfg.logging.level,
        file=cfg.logging.file,
        console=cfg.logging.console,
    )
    problems = cfg.validate()
    if problems:
        print("Die Konfiguration hat Probleme:")
        for p in problems:
            print(f"  - {p}")
        if not getattr(args, "ignore_config_errors", False):
            sys.exit(2)
    return cfg


def _symbols(cfg: Config, args: argparse.Namespace) -> list[str]:
    return [s.strip() for s in args.symbol.split(",")] if getattr(args, "symbol", None) else cfg.data.symbols


def _headline(text: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {text}")
    print("=" * 72)


def _prepare_training_data(cfg: Config, bundle) -> tuple:
    """Merkmale, Ziel und Gewichte - der Weg ist für alle Befehle derselbe."""
    from .features import FeatureBuilder
    from .labeling import direction_labels, label_report, sample_weights

    fs = FeatureBuilder(cfg).build(bundle.frames, symbol=bundle.symbol, digits=bundle.spec.digits)
    lb = cfg.labels
    y, usable, res = direction_labels(
        fs.base, fs.atr, lb.tp_atr, lb.sl_atr, lb.max_horizon_bars, lb.min_return_atr
    )
    w = sample_weights(res, lb.sample_weight_decay, lb.apply_uniqueness_weights)
    mask = usable.to_numpy(dtype=bool)
    original = np.arange(len(fs.frame))[mask]
    # Die Ausstiegsindizes zeigen auf den ungefilterten Rahmen und müssen für das
    # Purging auf die Positionen im gefilterten Rahmen umgerechnet werden.
    exits = np.searchsorted(original, res.exit_index[mask].to_numpy(), side="left").astype(float)
    bericht = label_report(y, usable, res)
    return fs, fs.frame[mask], y[mask].to_numpy(), w[mask].to_numpy(), exits, bericht


# --------------------------------------------------------------------------- #
# Befehle
# --------------------------------------------------------------------------- #


def cmd_init(args: argparse.Namespace) -> int:
    """Konfigurationsdatei mit allen Standardwerten anlegen."""
    path = Path(args.config or DEFAULT_CONFIG_PATH)
    if path.exists() and not args.force:
        print(f"{path} existiert bereits. Mit --force überschreiben.")
        return 1
    cfg = Config()
    cfg.save(path)
    print(f"Konfiguration geschrieben: {path}")
    print("\nNächste Schritte:")
    print("  1. Zugangsdaten als Umgebungsvariablen setzen (NICHT in die Datei):")
    print("       MT5_LOGIN, MT5_PASSWORD, MT5_SERVER")
    print("  2. data.symbols auf die eigenen Märkte anpassen")
    print("  3. 'python main.py connect' zum Prüfen der Verbindung")
    print("\n  execution.dry_run steht auf true - es werden keine echten Orders gesendet.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Überblick über Daten, Modelle und Journal."""
    cfg = _load_config(args)
    from .data.mt5_client import MT5Client
    from .data.store import BarStore
    from .learning.journal import Journal
    from .models.registry import ModelRegistry
    from .models.zoo import available_members, library_versions

    _headline(f"PAX {__version__} - Status")
    print("\n  UMGEBUNG")
    print(f"    MetaTrader5-Paket   {'verfügbar' if MT5Client.available() else 'NICHT verfügbar (nur Windows)'}")
    print(f"    Modelle im Ensemble {', '.join(available_members(cfg.model.members))}")
    for name, version in library_versions().items():
        print(f"      {name:<18}{version}")

    print("\n  KONFIGURATION")
    print(f"    Symbole             {', '.join(cfg.data.symbols)}")
    for h in Horizon:
        print(f"    {h.value:<20}{cfg.data.tf(h).value}")
    print(f"    Risiko je Trade     {fmt_pct(cfg.risk.risk_per_trade)} (max {fmt_pct(cfg.risk.max_risk_per_trade)})")
    print(f"    Tagesverlustgrenze  {fmt_pct(cfg.risk.max_daily_loss)}")
    print(f"    Mindest-Score / CRV {cfg.risk.min_signal_score} / {cfg.risk.min_risk_reward}")
    print(f"    Ausführung          {'TROCKENLAUF' if cfg.execution.dry_run else 'ECHTGELD'}")

    print("\n  KURSDATEN")
    coverage = BarStore(cfg.data.cache_dir).coverage()
    if coverage.empty:
        print("    kein Zwischenspeicher - 'fetch' lädt Historie herunter")
    else:
        print(coverage.to_string(index=False).replace("\n", "\n    ").rjust(4))

    print("\n  MODELLE")
    catalogue = ModelRegistry(cfg.learning.model_dir).catalogue()
    if not catalogue:
        print("    noch kein Modell trainiert - 'train' legt eines an")
    else:
        for row in catalogue[:12]:
            mark = " *" if row["champion"] else "  "
            print(f"   {mark} {row['symbol']:<10}{row['version']:<18}AUC {row['auc']}"
                  f"  {row['members']} Mitglieder  {row['saved_at']}")
        print("    (* = Champion, wird produktiv genutzt)")

    print("\n  JOURNAL")
    journal = Journal(cfg.learning.journal_path)
    for source in ("live", "backtest"):
        stats = journal.stats(source=source)
        if stats.get("trades"):
            print(f"    {source:<10}{stats['trades']} Trades, E[R] {stats['erwartungswert_r']:+.3f}, "
                  f"Quote {fmt_pct(stats['gewinnquote'])}, Summe {stats['summe_r']:+.1f} R")
        else:
            print(f"    {source:<10}keine Trades")
    print()
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    """MT5-Verbindung prüfen und Symbole testen."""
    cfg = _load_config(args)
    from .data.mt5_client import MT5Client, MT5Unavailable

    _headline("MT5-Verbindung")
    if not MT5Client.available():
        print("\n  Das Paket 'MetaTrader5' ist nicht verfügbar.")
        print("  Es läuft ausschließlich unter Windows mit installiertem MT5-Terminal:")
        print("      pip install MetaTrader5")
        print("\n  Ohne Terminal funktionieren weiterhin: backtest, train, walkforward,")
        print("  analyse und selftest - auf zwischengespeicherten oder synthetischen Daten.")
        return 1

    client = MT5Client(cfg.terminal, cfg.execution.magic)
    try:
        client.connect()
    except (MT5Unavailable, Exception) as exc:
        print(f"\n  Verbindung fehlgeschlagen: {exc}")
        print("\n  Prüfen: Läuft das Terminal? Ist der Pfad in terminal.path richtig?")
        print("  Sind MT5_LOGIN / MT5_PASSWORD / MT5_SERVER gesetzt?")
        return 1

    health = client.health()
    account = client.account()
    print(f"\n  Konto      {account.login} auf {account.server}")
    print(f"  Guthaben   {fmt_money(account.balance, account.currency)}")
    print(f"  Equity     {fmt_money(account.equity, account.currency)}")
    print(f"  Hebel      1:{account.leverage}")
    print(f"  Autotrading{'  aktiv' if health.get('autotrading') else '  AUSGESCHALTET - Orders werden abgelehnt'}")

    print("\n  SYMBOLE")
    for symbol in cfg.data.symbols:
        try:
            spec = client.symbol_spec(symbol)
            tick = client.tick(symbol)
            print(f"    {symbol:<10}Bid {tick['bid']:.5f}  Spread {tick['spread_points']:.0f} Punkte  "
                  f"Lot {spec.volume_min}-{spec.volume_max}  Stop-Level {spec.stops_level_points}")
        except Exception as exc:
            print(f"    {symbol:<10}FEHLER: {exc}")
    client.disconnect()
    print()
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """Historie herunterladen und zwischenspeichern."""
    cfg = _load_config(args)
    from .data.mt5_client import MT5Client
    from .data.store import BarStore

    if not MT5Client.available():
        print("Ohne MetaTrader5-Paket lassen sich keine echten Daten laden.")
        return 1
    client = MT5Client(cfg.terminal, cfg.execution.magic).connect()
    store = BarStore(cfg.data.cache_dir, client)
    bars = args.bars or cfg.data.history_bars

    _headline(f"Historie laden ({bars} Balken je Zeiteinheit)")
    for symbol in _symbols(cfg, args):
        for tf in cfg.data.all_timeframes:
            try:
                df = store.load(symbol, tf, bars, update=True, max_age=timedelta(seconds=0))
                print(f"  {symbol:<10}{tf.value:<5}{len(df):>7} Balken  "
                      f"{df.index[0]:%Y-%m-%d} bis {df.index[-1]:%Y-%m-%d}")
            except Exception as exc:
                print(f"  {symbol:<10}{tf.value:<5}FEHLER: {exc}")
    client.disconnect()
    return 0


def cmd_analyse(args: argparse.Namespace) -> int:
    """Aktuelle Lage und Signal für ein Symbol."""
    cfg = _load_config(args)
    from .features import FeatureBuilder
    from .features.regime import RegimeDetector
    from .learning.feedback import Blocklist
    from .models.registry import ModelRegistry
    from .strategy import SignalEngine

    registry = ModelRegistry(cfg.learning.model_dir)
    blocklist = Blocklist.load(Path(cfg.learning.model_dir).parent / "blocklist.json")

    for symbol in _symbols(cfg, args):
        bundle = load_data(cfg, symbol, args.bars)
        fs = FeatureBuilder(cfg).build(bundle.frames, symbol=symbol, digits=bundle.spec.digits)
        model = registry.load(symbol)
        engine = SignalEngine(cfg, model, blocklist=blocklist)
        sig = engine.generate(fs, -1, bundle.spec)
        row = fs.frame.iloc[-1]

        _headline(f"{symbol} - Analyse {fs.frame.index[-1]:%d.%m.%Y %H:%M} UTC")
        if bundle.is_synthetic:
            print("\n  ACHTUNG: synthetische Daten - keine Marktaussage.")
        print(f"\n  Datenquelle          {bundle.source}")
        print(f"  Kurs                 {fs.base['close'].iloc[-1]:.5f}")
        print(f"  ATR                  {sig.atr:.5f}")
        print(f"  Regime               {RegimeDetector.label(row)}")
        print(f"  Modell               {model.version if model else 'keins - nur Regelwerk'}")

        print("\n  ZEITEBENEN")
        for horizon in Horizon:
            view = sig.views.get(horizon.value)
            if not view:
                continue
            arrow = "steigend" if view.bias > 0.1 else "fallend" if view.bias < -0.1 else "neutral"
            print(f"    {horizon.value:<15}{view.timeframe.value:<5}{view.trend.value:<9}"
                  f"Bias {view.bias:+.2f} ({arrow})")
        print(f"    Übereinstimmung      {sig.trend_alignment:+.2f}")

        print(f"\n  SIGNAL")
        print(f"    {sig.summary()}")
        if sig.is_actionable:
            print(f"    Trefferwahrsch.      {sig.prob_win:.1%}")
            print(f"    Erwartungswert       {sig.expected_r:+.2f} R")
            print(f"    Ziele                {', '.join(f'{t:.5f}' for t in sig.take_profits)}")
            print(f"    Aufteilung           {', '.join(f'{f:.0%}' for f in sig.tp_fractions)}")
        if sig.reasons:
            print("\n  BEGRÜNDUNG")
            for reason in sig.reasons[:6]:
                print(f"    - {reason}")
        if sig.warnings:
            print("\n  VORBEHALTE")
            for warning in sig.warnings[:6]:
                print(f"    ! {warning}")
    print()
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    """Strategie auf der Historie prüfen."""
    cfg = _load_config(args)
    from .backtest import BacktestEngine, format_report
    from .data.sessions import SessionFilter
    from .features import FeatureBuilder
    from .learning.feedback import Blocklist
    from .learning.journal import Journal
    from .models.registry import ModelRegistry
    from .strategy import SignalEngine

    registry = ModelRegistry(cfg.learning.model_dir)
    blocklist = (
        Blocklist.load(Path(cfg.learning.model_dir).parent / "blocklist.json")
        if args.use_blocklist else None
    )
    journal = Journal(cfg.learning.journal_path) if args.record else None
    sessions = SessionFilter(cfg.sessions)
    total_r: list[float] = []

    for symbol in _symbols(cfg, args):
        bundle = load_data(cfg, symbol, args.bars)
        print(f"\n{bundle.describe()}")
        if bundle.is_synthetic:
            print("  ACHTUNG: synthetische Daten - das prüft die Software, nicht den Markt.")
        fs = FeatureBuilder(cfg).build(bundle.frames, symbol=symbol, digits=bundle.spec.digits)
        model = registry.load(symbol) if not args.rules_only else None
        engine = SignalEngine(cfg, model, blocklist=blocklist)
        signals = engine.generate_series(fs, bundle.spec)
        result = BacktestEngine(cfg, bundle.spec).run(fs, signals, sessions)
        print(format_report(result, "EUR", n_trials=args.trials,
                            periods_per_year=_periods_per_year(cfg)))
        total_r.extend(result.r_multiples.tolist())
        if journal is not None and result.trades:
            journal.record_trades(result.trades, source="backtest")
            print(f"  {len(result.trades)} Trades ins Journal geschrieben.")

    if len(_symbols(cfg, args)) > 1 and total_r:
        from .validation.metrics import summarize

        _headline("GESAMT über alle Symbole")
        combined = summarize(np.array(total_r), n_trials=args.trials)
        for key in ("trades", "win_rate", "expectancy_r", "total_r", "profit_factor",
                    "max_drawdown_r", "psr", "deflated_sharpe"):
            if key in combined:
                print(f"    {key:<20}{combined[key]}")
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    """Ein Modell anlernen und ablegen."""
    cfg = _load_config(args)
    from .learning.journal import Journal
    from .models import ModelEnsemble, ModelRegistry

    registry = ModelRegistry(cfg.learning.model_dir, cfg.learning.keep_model_versions)
    journal = Journal(cfg.learning.journal_path)

    for symbol in _symbols(cfg, args):
        bundle = load_data(cfg, symbol, args.bars)
        _headline(f"Training {symbol}")
        print(f"\n  {bundle.describe()}")
        if bundle.is_synthetic:
            print("  ACHTUNG: synthetische Daten - das entstehende Modell ist nur ein Funktionstest.")

        fs, X, y, w, exits, label_info = _prepare_training_data(cfg, bundle)
        print(f"  Merkmale: {X.shape[1]}, Beispiele: {X.shape[0]}")
        print("  Zielvariable:")
        for schluessel, wert in label_info.items():
            print(f"    {schluessel:<22}{wert}")

        ensemble = ModelEnsemble(cfg.model)
        try:
            report = ensemble.fit(X, y, w, exits)
        except Exception as exc:
            print(f"\n  Training fehlgeschlagen: {exc}")
            continue
        print("\n" + report.summary())

        registry.save(ensemble, symbol, {"quelle": bundle.source})
        champion = registry.champion(symbol)
        promote = args.promote or champion is None or champion == ensemble.version
        if promote:
            registry.promote(symbol, ensemble.version,
                             "manuell übernommen" if args.promote else "erstes Modell",
                             {"auc": report.auc})
            print(f"\n  Als Champion übernommen: {ensemble.version}")
        else:
            print(f"\n  Gespeichert als {ensemble.version}, Champion bleibt {champion}.")
            print("  Mit --promote übernehmen oder 'evolve' entscheiden lassen.")
        journal.record_training(symbol, ensemble.version, report.auc, report.n_samples,
                                report.n_features, promote, "manuelles Training")

        if not ensemble.feature_importance.empty:
            print("\n  WICHTIGSTE MERKMALE")
            for name, value in ensemble.feature_importance.head(12).items():
                print(f"    {name:<32}{value:.4f}")
    return 0


def cmd_walkforward(args: argparse.Namespace) -> int:
    """Vorwärtstest - trainieren auf Vergangenem, prüfen auf Folgendem."""
    cfg = _load_config(args)
    from .models import ModelEnsemble
    from .validation.metrics import classification_metrics
    from .validation.splits import walk_forward_windows

    for symbol in _symbols(cfg, args):
        bundle = load_data(cfg, symbol, args.bars)
        _headline(f"Vorwärtstest {symbol}")
        print(f"\n  {bundle.describe()}")
        fs, X, y, w, exits, _ = _prepare_training_data(cfg, bundle)

        try:
            windows = walk_forward_windows(
                len(X), args.folds, args.train_frac, not args.rolling, cfg.model.embargo_frac, exits
            )
        except ValueError as exc:
            print(f"  {exc}")
            continue
        if not windows:
            print("  Zu wenige Daten für die gewünschte Zahl an Fenstern.")
            continue

        print(f"\n  {len(windows)} Fenster, {'wachsend' if not args.rolling else 'rollend'}\n")
        print(f"  {'Fenster':<9}{'Training':<12}{'Test':<12}{'AUC':<8}{'Quote':<8}{'Brier':<8}")
        print("  " + "-" * 55)
        aucs = []
        for k, (train_idx, test_idx) in enumerate(windows, 1):
            if len(np.unique(y[train_idx])) < 2 or len(np.unique(y[test_idx])) < 2:
                print(f"  {k:<9}übersprungen - nur eine Klasse")
                continue
            ensemble = ModelEnsemble(cfg.model)
            try:
                ensemble.fit(X.iloc[train_idx], y[train_idx], w[train_idx], exits[train_idx])
                proba = ensemble.predict_proba(X.iloc[test_idx])
            except Exception as exc:
                print(f"  {k:<9}Fehler: {exc}")
                continue
            m = classification_metrics(y[test_idx], proba, w[test_idx])
            aucs.append(m["auc"])
            print(f"  {k:<9}{len(train_idx):<12}{len(test_idx):<12}"
                  f"{m['auc']:<8.4f}{m['accuracy']:<8.4f}{m['brier']:<8.4f}")

        if aucs:
            arr = np.array(aucs)
            print("  " + "-" * 55)
            print(f"  Mittelwert AUC {arr.mean():.4f} (Streuung {arr.std():.4f}, "
                  f"Spanne {arr.min():.4f}-{arr.max():.4f})")
            above = int((arr > 0.5).sum())
            print(f"  über Zufallsniveau in {above} von {len(arr)} Fenstern")
            if arr.mean() < 0.52:
                print("\n  Kein belastbarer Vorteil. Nicht live schalten.")
            elif above < len(arr) * 0.7:
                print("\n  Der Vorteil ist unbeständig - in einzelnen Fenstern verschwindet er.")
    return 0


def cmd_evolve(args: argparse.Namespace) -> int:
    """Lernschleife: nachtrainieren, vergleichen, gegebenenfalls ablösen."""
    cfg = _load_config(args)
    from .learning import Evolver
    from .learning.journal import Journal
    from .models import ModelRegistry

    journal = Journal(cfg.learning.journal_path)
    evolver = Evolver(cfg, ModelRegistry(cfg.learning.model_dir, cfg.learning.keep_model_versions), journal)

    for symbol in _symbols(cfg, args):
        bundle = load_data(cfg, symbol, args.bars)
        _headline(f"Entwicklungszyklus {symbol}")
        print(f"\n  {bundle.describe()}")
        decision = evolver.evolve(bundle.frames, symbol, force=args.force)
        print(f"\n  {decision.summary()}")
        if decision.drift:
            print("\n  DRIFT (die auffälligsten Merkmale)")
            for name, value in list(decision.drift.items())[:5]:
                flag = " <-- deutlich verschoben" if value >= cfg.learning.drift_psi_threshold else ""
                print(f"    {name:<32}PSI {value:.3f}{flag}")
        wf = decision.walk_forward
        if wf and not wf.get("error"):
            print(f"\n  VERGLEICH über {wf['folds']} Fenster")
            print(f"    Champion      {wf['champion_auc']:.4f}")
            print(f"    Herausforderer{wf['challenger_auc']:.4f}")
            print(f"    besser in     {wf['challenger_wins']}/{wf['folds']} Fenstern")
        for warning in decision.warnings:
            print(f"    ! {warning}")
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    """Fehleranalyse aus dem Journal."""
    cfg = _load_config(args)
    from .learning import Blocklist, FeedbackAnalyzer
    from .learning.journal import Journal

    journal = Journal(cfg.learning.journal_path)
    trades = journal.trades(source=args.source)
    _headline(f"Fehleranalyse ({args.source})")
    if trades.empty:
        print(f"\n  Keine Trades der Quelle '{args.source}' im Journal.")
        print("  Mit 'backtest --record' lassen sich Backtest-Trades aufzeichnen.")
        return 0

    analyzer = FeedbackAnalyzer(cfg.learning)
    print("\n" + analyzer.report(trades))

    blocklist = Blocklist.load(Path(cfg.learning.model_dir).parent / "blocklist.json")
    if args.apply:
        added = analyzer.update_blocklist(trades, blocklist)
        print(f"\n  {len(added)} neue Sperre(n) abgeleitet.")
    print("\n  " + blocklist.summary().replace("\n", "\n  "))
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    """Livebetrieb."""
    cfg = _load_config(args)
    if args.real:
        cfg.execution.dry_run = False
    from .live import LiveRunner

    _headline("Livebetrieb")
    if cfg.execution.dry_run:
        print("\n  TROCKENLAUF - es werden keine echten Orders gesendet.")
        print("  Mit --real scharf schalten (erst nach einem erfolgreichen Vorwärtstest!).")
    else:
        print("\n  ECHTGELD-MODUS. Risiko je Trade: " + fmt_pct(cfg.risk.risk_per_trade))
        print(f"  Notaus bei {fmt_pct(cfg.risk.max_drawdown_stop)} Rückgang, "
              f"Tagesstopp bei {fmt_pct(cfg.risk.max_daily_loss)}.")
        if not args.yes:
            answer = input("\n  Wirklich mit Echtgeld starten? (ja/nein): ").strip().lower()
            if answer not in ("ja", "j", "yes", "y"):
                print("  Abgebrochen.")
                return 1

    runner = LiveRunner(cfg)
    try:
        status = runner.run(poll_seconds=args.poll, max_iterations=args.iterations)
    except Exception as exc:
        log.exception("Livebetrieb abgebrochen")
        print(f"\n  Abbruch: {exc}")
        return 1
    print("\n  " + str(status.to_dict()))
    return 0


def cmd_journal(args: argparse.Namespace) -> int:
    """Journalstatistik und Export."""
    cfg = _load_config(args)
    from .learning.journal import Journal

    journal = Journal(cfg.learning.journal_path)
    _headline("Journal")
    for source in ("live", "backtest"):
        stats = journal.stats(source=source, days=args.days)
        print(f"\n  {source.upper()}")
        if not stats.get("trades"):
            print("    keine Trades")
            continue
        for key, value in stats.items():
            print(f"    {key:<20}{value}")
    if args.export:
        paths = journal.export_csv(args.export)
        print(f"\n  Exportiert nach {args.export}: {', '.join(p.name for p in paths)}")
    if args.vacuum:
        removed = journal.vacuum()
        print(f"\n  {removed} alte Signalzeilen entfernt.")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """Interne Prüfungen - allen voran auf Lookahead."""
    cfg = _load_config(args)
    from .features import FeatureBuilder, assert_causal

    _headline("Selbsttest")
    failures = 0

    print("\n  1) Konfiguration")
    problems = cfg.validate()
    print(f"     {'in Ordnung' if not problems else str(len(problems)) + ' Problem(e)'}")
    failures += len(problems)

    print("\n  2) Kausalität der Merkmale (die wichtigste Prüfung überhaupt)")
    symbol = _symbols(cfg, args)[0]
    bundle = load_data(cfg, symbol, args.bars or 4000)
    builder = FeatureBuilder(cfg)
    try:
        diffs = assert_causal(builder, bundle.frames, cut=64, check_rows=120)
        worst = max(diffs.values()) if diffs else 0.0
        print(f"     bestanden - {len(diffs)} Merkmale, größte Abweichung {worst:.3g}")
    except AssertionError as exc:
        print(f"     FEHLGESCHLAGEN: {exc}")
        failures += 1

    print("\n  3) Zeitebenen-Ausrichtung ohne Zukunftsblick")
    from .features.mtf import align_to_base

    base = bundle.frames[cfg.data.base_timeframe.value]
    higher_tf = cfg.data.tf(Horizon.LONG)
    higher = bundle.frames.get(higher_tf.value)
    if higher is not None and len(higher) > 10:
        aligned = align_to_base(higher[["close"]], base.index, higher_tf)
        span = pd.Timedelta(minutes=higher_tf.minutes)
        # Über die Zeit prüfen, nicht über den Kurswert: Der erwartete Balken ist
        # der letzte, dessen Schlusszeit nicht in der Zukunft des Basisbalkens liegt.
        checked = violations = 0
        for probe in base.index[-400:]:
            value = aligned.loc[probe, "close"]
            if pd.isna(value):
                continue
            eligible = higher.index[higher.index + span <= probe]
            if len(eligible) == 0:
                continue
            checked += 1
            expected = float(higher.loc[eligible[-1], "close"])
            if abs(float(value) - expected) > 1e-12:
                violations += 1
        if checked == 0:
            print("     übersprungen - kein überlappender Zeitraum")
        else:
            ok = violations == 0
            print(f"     {'bestanden' if ok else 'FEHLGESCHLAGEN'} - {checked} Basisbalken geprüft, "
                  f"{violations} nutzten einen noch nicht geschlossenen {higher_tf.value}-Balken")
            failures += 0 if ok else 1

    print("\n  4) Barriere-Labeling")
    from .labeling import barrier_outcome

    fs = builder.build(bundle.frames, symbol=symbol, digits=bundle.spec.digits)
    pess = barrier_outcome(fs.base, fs.atr, 2.0, 1.0, 48, pessimistic=True)
    opt = barrier_outcome(fs.base, fs.atr, 2.0, 1.0, 48, pessimistic=False)
    delta = float(opt.r_multiple.mean() - pess.r_multiple.mean())
    ok = delta >= 0
    print(f"     {'bestanden' if ok else 'FEHLGESCHLAGEN'} - die optimistische Auflösung "
          f"schönt das Ergebnis um {delta:+.4f} R je Trade")
    failures += 0 if ok else 1

    print("\n  5) Risikogrenzen")
    from .strategy.risk import RiskManager
    from .types import AccountState, Direction, Signal

    rm = RiskManager(cfg.risk)
    account = AccountState(10_000, 10_000, free_margin=9_000)
    rm.update_account(account)
    rm.record_trade(-cfg.risk.max_daily_loss * 10_000 * 1.2)
    probe_signal = Signal(symbol, utcnow(), Direction.LONG, 0.9, 1.1, 1.097, [1.106],
                          risk_reward=2.0, prob_win=0.6)
    plan = rm.plan(probe_signal, account, bundle.spec)
    ok = not plan.allowed
    print(f"     {'bestanden' if ok else 'FEHLGESCHLAGEN'} - "
          f"nach Überschreiten der Tagesverlustgrenze: {plan.blockers[0] if plan.blockers else 'kein Blocker!'}")
    failures += 0 if ok else 1

    print("\n" + "=" * 72)
    print(f"  {'ALLE PRÜFUNGEN BESTANDEN' if failures == 0 else str(failures) + ' PRÜFUNG(EN) FEHLGESCHLAGEN'}")
    print("=" * 72 + "\n")
    return 0 if failures == 0 else 1


def _periods_per_year(cfg: Config) -> float:
    minutes = cfg.data.base_timeframe.minutes
    return (252 * 24 * 60) / minutes


# --------------------------------------------------------------------------- #
# Argumente
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pax",
        description=f"PAX {__version__} - Price-Action-Handelssystem für MetaTrader 5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", "-c", default=str(DEFAULT_CONFIG_PATH), help="Konfigurationsdatei")
    parser.add_argument("--verbose", "-v", action="store_true", help="ausführliche Protokollierung")
    parser.add_argument("--version", action="version", version=f"PAX {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, help_text):
        p = sub.add_parser(name, help=help_text, description=func.__doc__)
        p.set_defaults(func=func)
        return p

    p = add("init", cmd_init, "Konfigurationsdatei anlegen")
    p.add_argument("--force", action="store_true", help="vorhandene Datei überschreiben")

    add("status", cmd_status, "Überblick über Daten, Modelle und Journal")
    add("connect", cmd_connect, "MT5-Verbindung prüfen")

    p = add("fetch", cmd_fetch, "Historie herunterladen")
    p.add_argument("--symbol", "-s", help="Symbol(e), kommagetrennt")
    p.add_argument("--bars", "-n", type=int, help="Anzahl Balken je Zeiteinheit")

    p = add("analyse", cmd_analyse, "aktuelle Lage und Signal")
    p.add_argument("--symbol", "-s", help="Symbol(e), kommagetrennt")
    p.add_argument("--bars", "-n", type=int, help="Anzahl Balken")

    p = add("backtest", cmd_backtest, "Strategie auf der Historie prüfen")
    p.add_argument("--symbol", "-s", help="Symbol(e), kommagetrennt")
    p.add_argument("--bars", "-n", type=int, help="Anzahl Balken")
    p.add_argument("--rules-only", action="store_true", help="ohne Modell, nur Regelwerk")
    p.add_argument("--use-blocklist", action="store_true", help="gelernte Sperren anwenden")
    p.add_argument("--record", action="store_true", help="Trades ins Journal schreiben")
    p.add_argument("--trials", type=int, default=1,
                   help="Zahl ausprobierter Varianten - korrigiert die Sharpe Ratio nach unten")

    p = add("train", cmd_train, "Modell anlernen")
    p.add_argument("--symbol", "-s", help="Symbol(e), kommagetrennt")
    p.add_argument("--bars", "-n", type=int, help="Anzahl Balken")
    p.add_argument("--promote", action="store_true", help="sofort zum Champion machen")

    p = add("walkforward", cmd_walkforward, "Vorwärtstest")
    p.add_argument("--symbol", "-s", help="Symbol(e), kommagetrennt")
    p.add_argument("--bars", "-n", type=int, help="Anzahl Balken")
    p.add_argument("--folds", type=int, default=5, help="Zahl der Fenster")
    p.add_argument("--train-frac", type=float, default=0.6, help="Anteil für das erste Training")
    p.add_argument("--rolling", action="store_true", help="rollendes statt wachsendes Fenster")

    p = add("evolve", cmd_evolve, "Lernschleife ausführen")
    p.add_argument("--symbol", "-s", help="Symbol(e), kommagetrennt")
    p.add_argument("--bars", "-n", type=int, help="Anzahl Balken")
    p.add_argument("--force", action="store_true", help="unabhängig von den Auslösern trainieren")

    p = add("feedback", cmd_feedback, "Fehleranalyse aus dem Journal")
    p.add_argument("--source", default="live", choices=["live", "backtest"], help="Datenquelle")
    p.add_argument("--apply", action="store_true", help="Sperren daraus ableiten und speichern")

    p = add("live", cmd_live, "Livebetrieb starten")
    p.add_argument("--real", action="store_true", help="echte Orders senden (sonst Trockenlauf)")
    p.add_argument("--yes", "-y", action="store_true", help="Rückfrage überspringen")
    p.add_argument("--poll", type=int, default=20, help="Sekunden zwischen den Takten")
    p.add_argument("--iterations", type=int, help="nach so vielen Takten beenden")

    p = add("journal", cmd_journal, "Journalstatistik und Export")
    p.add_argument("--days", type=int, default=0, help="nur die letzten N Tage")
    p.add_argument("--export", help="Verzeichnis für den CSV-Export")
    p.add_argument("--vacuum", action="store_true", help="alte Signalzeilen entfernen")

    p = add("selftest", cmd_selftest, "interne Prüfungen")
    p.add_argument("--symbol", "-s", help="Symbol für die Prüfung")
    p.add_argument("--bars", "-n", type=int, help="Anzahl Balken")
    return parser


def main(argv: "list[str] | None" = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:  # pragma: no cover
        print("\nAbgebrochen.")
        return 130
    except Exception as exc:
        log.exception("Befehl fehlgeschlagen")
        print(f"\nFehler: {exc}")
        if getattr(args, "verbose", False):
            raise
        print("Mit -v gibt es die vollständige Fehlermeldung.")
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
