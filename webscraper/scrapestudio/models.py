"""Datenmodelle für Scrape-Aufträge, Ergebnisse und das Agenten-Team."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 ScrapeStudio/1.0"
)


# --------------------------------------------------------------------------
# Scraping
# --------------------------------------------------------------------------
@dataclass
class ScrapeOptions:
    """Alle Einstellungen eines Scrape-Laufs."""

    urls: list[str] = field(default_factory=list)
    mode: str = "preset"  # preset | selectors | agent
    presets: list[str] = field(default_factory=lambda: ["text"])
    selectors: dict[str, str] = field(default_factory=dict)
    instruction: str = ""  # Klartext-Auftrag für das Agenten-Team

    follow_links: bool = False
    max_depth: int = 1
    max_pages: int = 25
    same_domain_only: bool = True
    url_contains: str = ""

    delay: float = 0.5
    timeout: int = 20
    retries: int = 2
    workers: int = 4
    user_agent: str = DEFAULT_USER_AGENT
    respect_robots: bool = True
    verify_ssl: bool = True

    dedupe: bool = True
    strip_whitespace: bool = True
    min_text_length: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScrapeOptions":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


@dataclass
class PageResult:
    """Ergebnis einer einzelnen abgerufenen Seite."""

    url: str
    status: int = 0
    title: str = ""
    depth: int = 0
    elapsed: float = 0.0
    bytes: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and 200 <= self.status < 300


@dataclass
class JobResult:
    """Gesamtergebnis eines Laufs über alle Seiten."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    options: ScrapeOptions = field(default_factory=ScrapeOptions)
    pages: list[PageResult] = field(default_factory=list)
    cancelled: bool = False
    # Vom Agenten-Team beigesteuert
    ledger: list["TaskRecord"] = field(default_factory=list)
    usage: "Usage" = field(default_factory=lambda: Usage())
    summary_text: str = ""
    learned_selectors: dict[str, str] = field(default_factory=dict)

    @property
    def rows(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for page in self.pages:
            out.extend(page.rows)
        return out

    @property
    def duration(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    @property
    def errors(self) -> list[PageResult]:
        return [p for p in self.pages if not p.ok]

    def summary(self) -> dict[str, Any]:
        return {
            "seiten": len(self.pages),
            "erfolgreich": sum(1 for p in self.pages if p.ok),
            "fehler": len(self.errors),
            "datensaetze": len(self.rows),
            "dauer_s": round(self.duration, 2),
            "kosten_usd": round(self.usage.cost_usd, 4),
            "ki_aufrufe": self.usage.calls,
        }


@dataclass
class Template:
    """Wiederverwendbare Vorlage aus Optionen."""

    name: str
    options: ScrapeOptions
    created_at: float = field(default_factory=time.time)
    note: str = ""


# --------------------------------------------------------------------------
# Agenten-Team
# --------------------------------------------------------------------------
@dataclass
class Usage:
    """Token- und Kostenzähler, über alle Agenten aufsummiert."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0
    saved_calls: int = 0  # durch Cache/Selektor-Wiederverwendung eingespart

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cached_tokens += other.cached_tokens
        self.calls += other.calls
        self.cost_usd += other.cost_usd
        self.saved_calls += other.saved_calls

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Zustände einer Teilaufgabe, wie im Status-Board angezeigt
PENDING = "PENDING"
DISPATCHED = "DISPATCHED"
PASS = "PASS"
FIX = "FIX"
ESCALATED = "ESCALATED"


@dataclass
class TaskRecord:
    """Eine Teilaufgabe im Verify-Ledger des Orchestrators."""

    id: str
    agent: str
    goal: str
    state: str = PENDING
    retries: int = 0
    model: str = ""
    note: str = ""
    usage: Usage = field(default_factory=Usage)
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0

    @property
    def duration(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    def board_line(self) -> str:
        """Einzeiliges Status-Board, z. B. 'W2: PASS | haiku | 1 Wdh.'."""
        parts = [f"{self.id}: {self.state}", self.model or "-"]
        if self.retries:
            parts.append(f"{self.retries} Wdh.")
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["usage"] = self.usage.to_dict()
        return data


@dataclass
class AgentResult:
    """Rückgabe eines einzelnen Worker-Laufs."""

    ok: bool
    data: Any = None
    text: str = ""
    error: str = ""
    usage: Usage = field(default_factory=Usage)
    from_cache: bool = False
