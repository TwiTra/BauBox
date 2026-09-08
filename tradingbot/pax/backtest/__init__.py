"""Backtest: ereignisgesteuerte Simulation mit realistischen Kosten."""

from .engine import BacktestEngine, BacktestResult
from .report import format_report, equity_frame, trade_frame, monthly_table
from .walkforward import (
    walk_forward_backtest,
    format_walkforward_report,
    WalkForwardResult,
    WindowResult,
)

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "format_report",
    "equity_frame",
    "trade_frame",
    "monthly_table",
    "walk_forward_backtest",
    "format_walkforward_report",
    "WalkForwardResult",
    "WindowResult",
]
