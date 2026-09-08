"""Ereignisgesteuerter Backtest.

Ein Backtest ist nur so ehrlich wie seine Annahmen. Diese hier sind bewusst
unbequem:

* **Einstieg zur Eröffnung des Folgebalkens.** Ein Signal entsteht mit dem
  Schlusskurs; wer zu diesem Kurs kauft, handelt in der Vergangenheit.
* **Neue Positionen sind ab derselben Kerze gefährdet.** Wer sie erst ab dem
  nächsten Balken überwacht, schenkt sich jeden sofortigen Ausstopper.
* **Spread, Kommission, Schlupf und Swap werden voll berechnet.** Der Spread
  fällt einmal je Umlauf an; Marktausstiege bekommen zusätzlich Schlupf.
* **Liegen Stop und Ziel im selben Balken, gilt der Stop.** Ohne Tickdaten ist
  die Reihenfolge nicht feststellbar - und die günstige Annahme wäre eine Lüge.

Genau diese vier Punkte trennen einen Backtest, der ungefähr stimmt, von einem,
der wunderschön aussieht und live sofort zerfällt.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ..config import Config
from ..features.builder import FeatureSet
from ..types import (
    AccountState,
    Direction,
    ExitReason,
    Horizon,
    Position,
    Signal,
    SymbolSpec,
    Trade,
    VolRegime,
)
from ..utils import get_logger, safe_div
from ..strategy.portfolio import Portfolio
from ..strategy.risk import RiskManager

log = get_logger("backtest")


def _bucket(reason: str) -> str:
    """Ablehnungsgrund auf seine Kategorie kürzen - alles ab der Klammer ist Detail."""
    return reason.split("(")[0].strip() or reason


@dataclass
class BacktestResult:
    """Alles, was ein Lauf hinterlässt."""

    trades: list[Trade] = field(default_factory=list)
    equity: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    balance: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    signals_total: int = 0
    signals_actionable: int = 0
    rejections: Counter = field(default_factory=Counter)
    initial_balance: float = 0.0
    final_balance: float = 0.0
    symbol: str = ""
    costs: dict[str, float] = field(default_factory=dict)

    @property
    def r_multiples(self) -> np.ndarray:
        return np.array([t.r_multiple for t in self.trades], dtype=float)

    @property
    def net_profit(self) -> float:
        return self.final_balance - self.initial_balance

    def metrics(self, n_trials: int = 1, periods_per_year: float = 252 * 24) -> dict[str, float]:
        from ..validation.metrics import summarize

        return summarize(self.r_multiples, self.equity, n_trials, periods_per_year)


class BacktestEngine:
    """Simuliert die Strategie Balken für Balken."""

    def __init__(self, cfg: Config, spec: "SymbolSpec | None" = None) -> None:
        self.cfg = cfg
        self.spec = spec or SymbolSpec("SYMBOL")
        self.risk = RiskManager(cfg.risk)
        self._ticket = 0

    # ------------------------------------------------------------------ #

    def run(
        self,
        fs: FeatureSet,
        signals: "list[Signal] | None" = None,
        session_filter: object = None,
        engine: object = None,
    ) -> BacktestResult:
        """Backtest über die gesamte Merkmalsmatrix."""
        bt = self.cfg.backtest
        base = fs.base
        n = len(base)
        if n < 10:
            raise ValueError("Zu wenige Balken für einen Backtest")

        if signals is None:
            if engine is None:
                raise ValueError("Entweder fertige Signale oder eine SignalEngine übergeben")
            signals = engine.generate_series(fs, self.spec)  # type: ignore[attr-defined]
        if len(signals) != n:
            raise ValueError(f"Signalzahl {len(signals)} passt nicht zu {n} Balken")

        spec = self.spec
        point = spec.point
        spread_price = self._spread_price(bt, spec)
        slippage_price = bt.slippage_points * point

        portfolio = Portfolio()
        portfolio.reset(bt.initial_balance)
        self.risk = RiskManager(self.cfg.risk)
        result = BacktestResult(
            initial_balance=bt.initial_balance, symbol=fs.symbol or spec.name
        )
        cost_totals = Counter()

        opens = base["open"].to_numpy(dtype=float)
        highs = base["high"].to_numpy(dtype=float)
        lows = base["low"].to_numpy(dtype=float)
        closes = base["close"].to_numpy(dtype=float)
        times = base.index.to_pydatetime()
        atr_values = fs.atr.to_numpy(dtype=float)

        equity_curve = np.empty(n)
        balance_curve = np.empty(n)
        pending: "Signal | None" = None

        for i in range(n):
            now = times[i]
            bar = (opens[i], highs[i], lows[i], closes[i])

            # 1) Swap für über Nacht gehaltene Positionen
            if i > 0 and times[i].date() != times[i - 1].date():
                cost_totals["swap"] += self._apply_swap(portfolio, bt, spec)

            # 2) Signal des Vorbalkens ausführen - zur Eröffnung, nicht zum Schluss
            if pending is not None:
                opened = self._try_open(
                    pending, portfolio, result, now, opens[i], spread_price, slippage_price,
                    spec, bt, atr_values[i], cost_totals,
                )
                if opened:
                    cost_totals["entries"] += 1
                pending = None

            # 3) Offene Positionen gegen diesen Balken führen - auch die soeben
            #    eröffnete. Wer das auslässt, unterschlägt jeden Sofortausstopper.
            self._manage(
                portfolio, result, i, now, bar, spread_price, slippage_price,
                spec, bt, atr_values[i], cost_totals,
            )

            # 4) Signal dieses Balkens für den nächsten vormerken
            sig = signals[i]
            result.signals_total += 1
            if sig.is_actionable:
                result.signals_actionable += 1
                allowed, reason = self._pre_check(sig, now, session_filter, portfolio)
                if allowed:
                    pending = sig
                else:
                    result.rejections[_bucket(reason)] += 1
            elif sig.warnings:
                result.rejections[_bucket(sig.warnings[0])] += 1

            unrealised = sum(
                p.unrealised_pnl(closes[i], spec.value_per_point) for p in portfolio.open_list
            )
            balance_curve[i] = portfolio.balance
            equity_curve[i] = portfolio.balance + unrealised

        # Am Datenende alles glattstellen
        for pos in list(portfolio.open_list):
            self._close(
                portfolio, result, pos, pos.volume, closes[-1], times[-1],
                ExitReason.END_OF_DATA, spec, bt, len(base) - 1, cost_totals,
            )

        idx = base.index
        result.equity = pd.Series(equity_curve, index=idx, name="equity")
        result.balance = pd.Series(balance_curve, index=idx, name="balance")
        result.final_balance = portfolio.balance
        result.trades = portfolio.closed
        result.costs = {
            "spread_und_schlupf": round(cost_totals["slippage_cost"], 2),
            "kommission": round(cost_totals["commission"], 2),
            "swap": round(cost_totals["swap"], 2),
            "gesamt": round(
                cost_totals["slippage_cost"] + cost_totals["commission"] + abs(cost_totals["swap"]), 2
            ),
        }
        return result

    # ------------------------------------------------------------------ #
    # Ein- und Ausstieg
    # ------------------------------------------------------------------ #

    def _pre_check(
        self, sig: Signal, now: datetime, session_filter: object, portfolio: Portfolio
    ) -> tuple[bool, str]:
        if session_filter is not None:
            ok, reason = session_filter.check(now, sig.symbol)  # type: ignore[attr-defined]
            if not ok:
                return False, reason
        bt = self.cfg.backtest
        if sig.direction is Direction.LONG and not bt.allow_longs:
            return False, "Longs deaktiviert"
        if sig.direction is Direction.SHORT and not bt.allow_shorts:
            return False, "Shorts deaktiviert"
        if portfolio.has(sig.symbol):
            return False, "Position bereits offen"
        return True, ""

    def _try_open(
        self, sig: Signal, portfolio: Portfolio, result: BacktestResult, now: datetime,
        open_price: float, spread: float, slippage: float, spec: SymbolSpec,
        bt: object, atr: float, costs: Counter,
    ) -> bool:
        is_long = sig.direction is Direction.LONG
        # Balken sind Geldkurse: ein Kauf wird zum Briefkurs ausgeführt.
        fill = open_price + spread + slippage if is_long else open_price - slippage
        fill = spec.normalize_price(fill)

        account = AccountState(
            balance=portfolio.balance,
            equity=portfolio.balance,
            free_margin=portfolio.balance,
        )
        # Stop und Ziel relativ zum tatsächlichen Einstieg verschieben, damit das
        # Risiko in R gleich bleibt - sonst verzerrt der Schlupf jede Auswertung.
        shift = fill - sig.entry
        stop = sig.stop_loss + shift
        targets = [tp + shift for tp in sig.take_profits]

        adjusted = Signal(
            symbol=sig.symbol, time=sig.time, direction=sig.direction, score=sig.score,
            entry=fill, stop_loss=stop, take_profits=targets, tp_fractions=sig.tp_fractions,
            horizon=sig.horizon, prob_win=sig.prob_win, expected_r=sig.expected_r,
            risk_reward=sig.risk_reward, atr=sig.atr, regime=sig.regime,
            trend_alignment=sig.trend_alignment, reasons=sig.reasons,
            model_version=sig.model_version, max_hold_bars=sig.max_hold_bars,
        )

        plan = self.risk.plan(adjusted, account, spec, portfolio.open_list, now)
        if not plan.allowed:
            result.rejections[_bucket(plan.blockers[0]) if plan.blockers else "Risikoprüfung"] += 1
            return False

        self._ticket += 1
        commission = plan.volume * getattr(bt, "commission_per_lot", 0.0)
        portfolio.balance -= commission
        costs["commission"] += commission
        costs["slippage_cost"] += (spread + slippage) / spec.point * spec.value_per_point * plan.volume

        position = Position(
            ticket=self._ticket,
            symbol=adjusted.symbol,
            direction=adjusted.direction,
            volume=plan.volume,
            entry_price=fill,
            entry_time=now,
            stop_loss=stop,
            take_profit=targets[-1] if targets else 0.0,
            initial_stop=stop,
            initial_volume=plan.volume,
            signal_score=adjusted.score,
            horizon=adjusted.horizon,
            meta={
                "targets": list(targets),
                "fractions": list(adjusted.tp_fractions),
                "entry_bar": len(portfolio.closed),
                "realized_profit": 0.0,
                "closed_volume": 0.0,
                "exit_value": 0.0,
                "commission": commission,
                "swap": 0.0,
                "slippage": abs(shift),
                "prob_win": adjusted.prob_win,
                "regime": adjusted.regime,
                "reasons": list(adjusted.reasons[:5]),
                "model_version": adjusted.model_version,
                "max_hold": adjusted.max_hold_bars or self.cfg.labels.max_horizon_bars * 2,
                "entry_index": None,
                "atr": atr,
                "features": {},
            },
        )
        portfolio.add(position)
        return True

    def _manage(
        self, portfolio: Portfolio, result: BacktestResult, i: int, now: datetime,
        bar: tuple[float, float, float, float], spread: float, slippage: float,
        spec: SymbolSpec, bt: object, atr: float, costs: Counter,
    ) -> None:
        """Alle offenen Positionen gegen den aktuellen Balken führen."""
        _, high, low, close = bar
        risk_cfg = self.cfg.risk

        for pos in list(portfolio.open_list):
            if pos.meta.get("entry_index") is None:
                pos.meta["entry_index"] = i
            is_long = pos.direction is Direction.LONG
            # Bei Shortpositionen entscheidet der Briefkurs über Stop und Ziel.
            eff_high = high + (spread if not is_long else 0.0)
            eff_low = low - (0.0 if not is_long else 0.0)

            risk = pos.risk_per_unit
            if risk > 0:
                favourable = ((high - pos.entry_price) if is_long else (pos.entry_price - low)) / risk
                adverse = ((pos.entry_price - low) if is_long else (high - pos.entry_price)) / risk
                pos.max_favorable = max(pos.max_favorable, float(favourable))
                pos.max_adverse = max(pos.max_adverse, float(adverse))

            hit_stop = (low <= pos.stop_loss) if is_long else (eff_high >= pos.stop_loss)
            targets = pos.meta.get("targets", [])
            final_target = targets[-1] if targets else pos.take_profit
            hit_target = (
                (high >= final_target) if is_long else (low - 0.0 <= final_target)
            ) if final_target else False

            # Grenzfall: beide im selben Balken. Ohne Tickdaten gilt der Stop.
            if hit_stop and (hit_target and getattr(bt, "intrabar_worst_case", True) or not hit_target):
                self._close(
                    portfolio, result, pos, pos.volume,
                    pos.stop_loss - (slippage if is_long else -slippage),
                    now, ExitReason.STOP_LOSS, spec, bt, i, costs,
                )
                continue
            if hit_stop and hit_target:
                self._close(portfolio, result, pos, pos.volume, pos.stop_loss, now,
                            ExitReason.STOP_LOSS, spec, bt, i, costs)
                continue

            # Teilgewinne der Reihe nach mitnehmen
            fractions = pos.meta.get("fractions", [])
            while pos.partials_done < len(targets) - 1 and pos.partials_done < len(fractions):
                level = targets[pos.partials_done]
                reached = (high >= level) if is_long else (low <= level)
                if not reached:
                    break
                fraction = fractions[pos.partials_done]
                volume = spec.normalize_volume(pos.initial_volume * fraction)
                volume = min(volume, pos.volume - spec.volume_min) if pos.volume > spec.volume_min else 0.0
                pos.partials_done += 1
                if volume >= spec.volume_min:
                    self._partial(portfolio, pos, volume, level, spec, bt, costs)
                if pos.volume < spec.volume_min:
                    break

            if pos.ticket not in portfolio.positions:
                continue

            if hit_target and final_target:
                self._close(portfolio, result, pos, pos.volume, final_target, now,
                            ExitReason.TAKE_PROFIT, spec, bt, i, costs)
                continue

            # Stop auf Einstand ziehen
            if not pos.break_even_done and risk > 0 and pos.max_favorable >= risk_cfg.break_even_at_r:
                offset = risk_cfg.break_even_offset_r * risk
                new_stop = pos.entry_price + (offset if is_long else -offset)
                if (is_long and new_stop > pos.stop_loss) or (not is_long and new_stop < pos.stop_loss):
                    pos.stop_loss = spec.normalize_price(new_stop)
                    pos.break_even_done = True

            # Stop nachziehen
            if risk > 0 and pos.max_favorable >= risk_cfg.trail_start_r and atr > 0:
                trail = risk_cfg.trail_atr * atr
                candidate = (close - trail) if is_long else (close + trail)
                if (is_long and candidate > pos.stop_loss) or (not is_long and candidate < pos.stop_loss):
                    pos.stop_loss = spec.normalize_price(candidate)

            # Zeitausstieg
            entry_index = pos.meta.get("entry_index", i)
            if i - entry_index >= pos.meta.get("max_hold", 96):
                self._close(portfolio, result, pos, pos.volume, close, now,
                            ExitReason.TIME, spec, bt, i, costs)

    # ------------------------------------------------------------------ #

    def _partial(
        self, portfolio: Portfolio, pos: Position, volume: float, price: float,
        spec: SymbolSpec, bt: object, costs: Counter,
    ) -> None:
        """Teilgewinn mitnehmen - Position bleibt mit Restgröße offen."""
        profit = (price - pos.entry_price) * pos.direction.sign * volume * spec.value_per_point / spec.point
        commission = volume * getattr(bt, "commission_per_lot", 0.0) * 0.5
        portfolio.balance += profit - commission
        costs["commission"] += commission
        pos.meta["realized_profit"] += profit - commission
        pos.meta["closed_volume"] += volume
        pos.meta["exit_value"] += price * volume
        pos.volume = round(pos.volume - volume, 6)

    def _close(
        self, portfolio: Portfolio, result: BacktestResult, pos: Position, volume: float,
        price: float, now: datetime, reason: ExitReason, spec: SymbolSpec,
        bt: object, bar_index: int, costs: Counter,
    ) -> None:
        """Position schließen und als Trade verbuchen."""
        volume = min(volume, pos.volume)
        price = spec.normalize_price(price)
        profit = (price - pos.entry_price) * pos.direction.sign * volume * spec.value_per_point / spec.point
        commission = volume * getattr(bt, "commission_per_lot", 0.0) * 0.5
        portfolio.balance += profit - commission
        costs["commission"] += commission

        total_profit = pos.meta.get("realized_profit", 0.0) + profit - commission
        total_volume = pos.meta.get("closed_volume", 0.0) + volume
        exit_value = pos.meta.get("exit_value", 0.0) + price * volume
        avg_exit = safe_div(exit_value, total_volume, price)

        risk_amount = pos.risk_per_unit * pos.initial_volume * spec.value_per_point / spec.point
        r_multiple = safe_div(total_profit, risk_amount)

        trade = Trade(
            symbol=pos.symbol,
            direction=pos.direction,
            volume=pos.initial_volume,
            entry_price=pos.entry_price,
            entry_time=pos.entry_time,
            exit_price=float(avg_exit),
            exit_time=now,
            profit=round(float(total_profit), 2),
            r_multiple=round(float(r_multiple), 4),
            exit_reason=reason,
            stop_loss=pos.initial_stop,
            take_profit=pos.take_profit,
            commission=round(pos.meta.get("commission", 0.0) + commission, 2),
            swap=round(pos.meta.get("swap", 0.0), 2),
            slippage=pos.meta.get("slippage", 0.0),
            bars_held=int(bar_index - (pos.meta.get("entry_index") or bar_index)),
            max_favorable_r=round(pos.max_favorable, 3),
            max_adverse_r=round(pos.max_adverse, 3),
            signal_score=pos.signal_score,
            prob_win=pos.meta.get("prob_win", 0.5),
            horizon=pos.horizon,
            regime=pos.meta.get("regime", VolRegime.NORMAL),
            model_version=pos.meta.get("model_version", ""),
            ticket=pos.ticket,
            reasons=pos.meta.get("reasons", []),
        )
        portfolio.close(trade)
        self.risk.record_trade(trade.profit, trade.r_multiple)

    def _apply_swap(self, portfolio: Portfolio, bt: object, spec: SymbolSpec) -> float:
        """Haltekosten über Nacht."""
        total = 0.0
        for pos in portfolio.open_list:
            points = (
                getattr(bt, "swap_long_points", 0.0)
                if pos.direction is Direction.LONG
                else getattr(bt, "swap_short_points", 0.0)
            )
            amount = points * spec.value_per_point * pos.volume
            portfolio.balance += amount
            pos.meta["swap"] = pos.meta.get("swap", 0.0) + amount
            total += amount
        return total

    @staticmethod
    def _spread_price(bt: object, spec: SymbolSpec) -> float:
        points = (
            spec.spread_points
            if getattr(bt, "use_symbol_spec_costs", True) and spec.spread_points > 0
            else getattr(bt, "spread_points", 10.0)
        )
        return float(points) * spec.point
