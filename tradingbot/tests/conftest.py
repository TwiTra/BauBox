"""Gemeinsame Vorrichtungen für die Testsuite.

Alle Tests laufen auf kleinen, festgelegten synthetischen Reihen. Das hält die
Suite schnell und - viel wichtiger - reproduzierbar: Ein Test, der mal
durchläuft und mal nicht, ist schlimmer als gar keiner.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pax.config import Config  # noqa: E402
from pax.data.synthetic import SyntheticMarket  # noqa: E402
from pax.features import FeatureBuilder  # noqa: E402
from pax.features.indicators import atr as atr_fn  # noqa: E402


@pytest.fixture(scope="session")
def market() -> SyntheticMarket:
    return SyntheticMarket("EURUSD", seed=1234)


@pytest.fixture(scope="session")
def bars(market):
    """Eine einzelne M15-Reihe."""
    return market.generate(bars=3000, timeframe="M15")


@pytest.fixture(scope="session")
def atr(bars):
    return atr_fn(bars, 14)


@pytest.fixture(scope="session")
def frames(market):
    """Konsistente Reihen über drei Zeitebenen."""
    return market.generate_multi(400, ["M15", "H1", "H4"])


@pytest.fixture
def config(tmp_path) -> Config:
    cfg = Config()
    cfg.data.symbols = ["EURUSD"]
    cfg.data.cache_dir = str(tmp_path / "cache")
    cfg.data.warmup_bars = 300
    cfg.learning.model_dir = str(tmp_path / "models")
    cfg.learning.journal_path = str(tmp_path / "journal.sqlite")
    cfg.logging.file = str(tmp_path / "pax.log")
    cfg.logging.console = False
    cfg.model.n_splits = 3
    cfg.model.min_train_samples = 200
    cfg.model.max_features = 40
    cfg.model.members = ["hist_gradient_boosting", "logistic"]
    return cfg


@pytest.fixture(scope="session")
def featureset(frames):
    cfg = Config()
    return FeatureBuilder(cfg).build(frames, symbol="EURUSD", warmup=300)
