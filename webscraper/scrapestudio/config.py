"""Konfiguration, Modell-Ebenen und Preise.

Der API-Schlüssel liegt in einer Datei unter ``~/.scrapestudio`` mit
Benutzer-Rechten (0600). Er wird nie ins Log und nie in einen Export
geschrieben.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

APP_DIR = Path(os.environ.get("SCRAPESTUDIO_HOME") or (Path.home() / ".scrapestudio"))
CONFIG_FILE = APP_DIR / "settings.json"
KEY_FILE = APP_DIR / "credentials.json"
DB_FILE = APP_DIR / "scrapestudio.db"
EXPORT_DIR = APP_DIR / "exports"


# --------------------------------------------------------------------------
# Modell-Ebenen: billig arbeiten, teuer nur prüfen
# --------------------------------------------------------------------------
# Preise in USD pro 1 Mio. Token (Stand der Auslieferung, in den
# Einstellungen überschreibbar).
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (15.00, 75.00),
}

TIERS: dict[str, str] = {
    # Die Fleißarbeit: viele Aufrufe, günstigstes Modell.
    "worker": "claude-haiku-4-5-20251001",
    # Prüft Worker-Ergebnisse stichprobenartig, deutlich seltener.
    "verifier": "claude-sonnet-5",
    # Nur für schwierige Entscheidungen, die der Orchestrator eskaliert.
    "advisor": "claude-opus-5",
}

TIER_LABELS = {
    "worker": "Arbeiter (günstig, macht die Masse)",
    "verifier": "Prüfer (kontrolliert Stichproben)",
    "advisor": "Berater (nur bei Problemen)",
}


def price_for(model: str) -> tuple[float, float]:
    """Preis (Eingabe, Ausgabe) pro 1 Mio. Token; unbekannt -> Worker-Preis."""
    return MODEL_PRICES.get(model, MODEL_PRICES["claude-haiku-4-5-20251001"])


def cost_of(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = price_for(model)
    return (input_tokens / 1_000_000) * pin + (output_tokens / 1_000_000) * pout


@dataclass
class Settings:
    """Alles, was der Nutzer in den Einstellungen ändern kann."""

    theme: str = "dark"  # dark | light | system
    accent: str = "violet"

    # Agenten-Team
    agents_enabled: bool = True
    worker_model: str = TIERS["worker"]
    verifier_model: str = TIERS["verifier"]
    advisor_model: str = TIERS["advisor"]
    parallel_agents: int = 3
    verify_sample: int = 3  # so viele Datensätze prüft der Prüfer je Welle

    # Token sparen
    use_cache: bool = True
    cache_ttl_hours: int = 168
    compress_html: bool = True
    max_chars_per_page: int = 12000
    reuse_selectors: bool = True  # Selektoren einmal lernen, dann anwenden
    prompt_cache: bool = True

    # Kostenbremse
    budget_usd: float = 1.00
    budget_calls: int = 60
    stop_on_budget: bool = True

    # Scraping-Standards
    default_delay: float = 0.5
    default_timeout: int = 20
    default_workers: int = 4
    respect_robots: bool = True

    # Export
    export_dir: str = str(EXPORT_DIR)
    autosave: bool = False
    autosave_format: str = "csv"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


def ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    Path(EXPORT_DIR).mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    ensure_dirs()
    if CONFIG_FILE.exists():
        try:
            return Settings.from_dict(json.loads(CONFIG_FILE.read_text("utf-8")))
        except (OSError, ValueError):
            pass  # kaputte Datei -> Standardwerte, App startet trotzdem
    return Settings()


def save_settings(settings: Settings) -> None:
    ensure_dirs()
    CONFIG_FILE.write_text(
        json.dumps(settings.to_dict(), indent=2, ensure_ascii=False), "utf-8"
    )


def load_api_key() -> str:
    """Schlüssel aus Datei oder Umgebung. Umgebung gewinnt."""
    env = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        try:
            return str(json.loads(KEY_FILE.read_text("utf-8")).get("anthropic", "")).strip()
        except (OSError, ValueError):
            return ""
    return ""


def save_api_key(key: str) -> None:
    ensure_dirs()
    KEY_FILE.write_text(json.dumps({"anthropic": key.strip()}), "utf-8")
    try:
        KEY_FILE.chmod(0o600)
    except OSError:
        pass  # Windows kennt den Modus nicht - kein Grund abzubrechen


def mask_key(key: str) -> str:
    """Für die Anzeige: nur Anfang und Ende zeigen."""
    if not key:
        return "nicht gesetzt"
    if len(key) <= 12:
        return "*" * len(key)
    return f"{key[:7]}...{key[-4:]}"
