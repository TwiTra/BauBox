"""Kleine Helfer: Logging, Zahlen, Wiederholversuche, Zeit."""

from __future__ import annotations

import json
import logging
import logging.handlers
import math
import time
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import is_dataclass, asdict
from datetime import datetime, date
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

_LOG_CONFIGURED = False


def setup_logging(
    level: str = "INFO",
    file: "str | None" = "runtime/pax.log",
    console: bool = True,
    max_bytes: int = 5_000_000,
    backups: int = 5,
) -> logging.Logger:
    """Root-Logger einrichten. Mehrfachaufrufe sind unschädlich."""
    global _LOG_CONFIGURED
    root = logging.getLogger("pax")
    if _LOG_CONFIGURED:
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        return root

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.propagate = False
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)-22s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    if console:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    if file:
        path = Path(file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    _LOG_CONFIGURED = True
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"pax.{name}")


def ensure_dir(path: "str | Path") -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    """Division, die bei 0 oder NaN den Standardwert liefert statt zu werfen."""
    try:
        if b == 0 or not math.isfinite(b) or not math.isfinite(a):
            return default
        result = a / b
        return result if math.isfinite(result) else default
    except (TypeError, ZeroDivisionError):
        return default


def clamp(value: float, low: float, high: float) -> float:
    if not math.isfinite(value):
        return low
    return max(low, min(high, value))


def sigmoid(x: float, scale: float = 1.0) -> float:
    """Numerisch stabile Logistik-Funktion."""
    z = clamp(x * scale, -60.0, 60.0)
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def percentile_rank(values: Sequence[float], value: float) -> float:
    """Anteil der Werte unterhalb von `value`, in [0, 1]."""
    finite = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    if not finite:
        return 0.5
    below = sum(1 for v in finite if v < value)
    return below / len(finite)


def retry(
    attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    logger: "logging.Logger | None" = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Dekorator: Aufruf bei Fehlern mit wachsender Wartezeit wiederholen."""

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            wait = delay
            last: BaseException | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:  # noqa: PERF203 - Wiederholung ist der Zweck
                    last = exc
                    if attempt == attempts:
                        break
                    if logger:
                        logger.warning(
                            "%s fehlgeschlagen (Versuch %d/%d): %s - neuer Versuch in %.1fs",
                            fn.__name__, attempt, attempts, exc, wait,
                        )
                    time.sleep(wait)
                    wait *= backoff
            assert last is not None
            raise last

        return wrapper

    return decorator


@contextmanager
def timed(label: str, logger: "logging.Logger | None" = None):
    """Laufzeit eines Blocks messen und loggen."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        msg = f"{label} dauerte {elapsed:.2f}s"
        if logger:
            logger.info(msg)


class JsonEncoder(json.JSONEncoder):
    """JSON-Encoder, der numpy, datetime, Enums und Dataclasses versteht."""

    def default(self, o: Any) -> Any:
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if is_dataclass(o) and not isinstance(o, type):
            return asdict(o)
        if hasattr(o, "item") and callable(o.item):  # numpy-Skalare
            try:
                return o.item()
            except Exception:  # pragma: no cover
                pass
        if hasattr(o, "tolist") and callable(o.tolist):  # numpy-Arrays
            try:
                return o.tolist()
            except Exception:  # pragma: no cover
                pass
        if isinstance(o, Path):
            return str(o)
        return super().default(o)


def to_json(obj: Any, indent: "int | None" = 2) -> str:
    return json.dumps(obj, cls=JsonEncoder, indent=indent, ensure_ascii=False)


def write_json(path: "str | Path", obj: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(to_json(obj), encoding="utf-8")
    return p


def read_json(path: "str | Path", default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def chunked(seq: Sequence[T], size: int) -> Iterable[Sequence[T]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def fmt_money(value: float, currency: str = "EUR") -> str:
    return f"{value:,.2f} {currency}".replace(",", " ")


def fmt_pct(value: float, digits: int = 2) -> str:
    return f"{value * 100:.{digits}f} %"
