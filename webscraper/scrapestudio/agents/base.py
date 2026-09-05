"""Basis für alle Agenten: Modell-Anbindung, Budget, Cache.

Die Anthropic-Bibliothek ist eine weiche Abhängigkeit. Fehlt sie oder der
Schlüssel, läuft die App weiter - nur ohne Agenten-Ebene. Das gesamte
regelbasierte Scrapen funktioniert davon unabhängig.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import Settings, cost_of
from ..models import AgentResult, Usage

LogFn = Callable[[str, str], None]  # (ebene, nachricht)


class BudgetExceeded(RuntimeError):
    """Wird ausgelöst, wenn Kosten- oder Aufrufgrenze erreicht ist."""


class AgentsUnavailable(RuntimeError):
    """Kein Schlüssel oder Bibliothek fehlt."""


# --------------------------------------------------------------------------
class BudgetGuard:
    """Kostenbremse. Zählt mit und stoppt hart an der Grenze."""

    def __init__(self, max_usd: float, max_calls: int, stop: bool = True) -> None:
        self.max_usd = max_usd
        self.max_calls = max_calls
        self.stop = stop
        self.usage = Usage()
        self._lock = threading.Lock()

    def check(self) -> None:
        if not self.stop:
            return
        with self._lock:
            if self.max_calls and self.usage.calls >= self.max_calls:
                raise BudgetExceeded(
                    f"Aufruf-Grenze erreicht ({self.usage.calls}/{self.max_calls})"
                )
            if self.max_usd and self.usage.cost_usd >= self.max_usd:
                raise BudgetExceeded(
                    f"Kosten-Grenze erreicht ({self.usage.cost_usd:.4f}/{self.max_usd:.2f} USD)"
                )

    def record(self, usage: Usage) -> None:
        with self._lock:
            self.usage.add(usage)

    def record_saved(self, count: int = 1) -> None:
        with self._lock:
            self.usage.saved_calls += count

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.max_usd - self.usage.cost_usd)

    @property
    def remaining_calls(self) -> int:
        return max(0, self.max_calls - self.usage.calls)


# --------------------------------------------------------------------------
class LLMClient:
    """Dünne Hülle um die Anthropic-API mit Zähler, Cache und Prompt-Caching."""

    def __init__(
        self,
        api_key: str,
        settings: Settings,
        budget: BudgetGuard,
        cache: Any = None,
        log: LogFn | None = None,
    ) -> None:
        self.api_key = api_key
        self.settings = settings
        self.budget = budget
        self.cache = cache
        self.log = log or (lambda level, msg: None)
        self._client: Any = None
        self._lock = threading.Lock()

    # -- Verfügbarkeit ------------------------------------------------
    @staticmethod
    def library_available() -> bool:
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            return False

    def available(self) -> bool:
        return bool(self.api_key) and self.library_available()

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise AgentsUnavailable(
                "Kein API-Schlüssel gesetzt. Einstellungen -> Agenten-Team."
            )
        try:
            import anthropic
        except ImportError as exc:
            raise AgentsUnavailable(
                "Paket 'anthropic' fehlt. Installieren mit: pip install anthropic"
            ) from exc
        with self._lock:
            if self._client is None:
                self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def model_for(self, tier: str) -> str:
        return {
            "worker": self.settings.worker_model,
            "verifier": self.settings.verifier_model,
            "advisor": self.settings.advisor_model,
        }.get(tier, self.settings.worker_model)

    # -- Aufruf --------------------------------------------------------
    def call(
        self,
        tier: str,
        system: str,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.0,
        cache_key_extra: str = "",
    ) -> AgentResult:
        """Ein Modellaufruf. Nutzt Cache, zählt Token, achtet aufs Budget."""
        model = self.model_for(tier)

        # 1. Cache - der billigste Aufruf ist der, der nicht stattfindet.
        if self.cache is not None and self.settings.use_cache:
            hit = self.cache.get(model, system, prompt + cache_key_extra)
            if hit is not None:
                self.budget.record_saved()
                self.log("debug", f"Cache-Treffer ({tier}/{model})")
                return AgentResult(ok=True, text=hit, from_cache=True)

        self.budget.check()
        client = self._ensure_client()

        # 2. Prompt-Caching: der System-Teil wiederholt sich über alle
        #    Worker einer Welle, ab ~1024 Token lohnt die Markierung.
        system_block: Any = system
        if self.settings.prompt_cache and len(system) > 4000:
            system_block = [{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }]

        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_block,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # Netz, Kontingent, Modellfehler
            return AgentResult(ok=False, error=f"{type(exc).__name__}: {exc}")

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )

        raw = response.usage
        usage = Usage(
            input_tokens=getattr(raw, "input_tokens", 0) or 0,
            output_tokens=getattr(raw, "output_tokens", 0) or 0,
            cached_tokens=getattr(raw, "cache_read_input_tokens", 0) or 0,
            calls=1,
        )
        usage.cost_usd = cost_of(model, usage.input_tokens, usage.output_tokens)
        self.budget.record(usage)

        if self.cache is not None and self.settings.use_cache and text:
            self.cache.put(model, system, prompt + cache_key_extra, text)

        self.log(
            "debug",
            f"{tier}/{model}: {usage.input_tokens}+{usage.output_tokens} Token, "
            f"{usage.cost_usd:.4f} USD",
        )
        return AgentResult(ok=True, text=text, usage=usage)


# --------------------------------------------------------------------------
def parse_json(text: str) -> Any:
    """JSON aus einer Modellantwort ziehen, auch mit Code-Zaun drumherum."""
    if not text:
        return None
    text = text.strip()

    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except ValueError:
        pass

    # Erstes vollständiges Objekt oder Array herausschneiden
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                continue
    return None


# --------------------------------------------------------------------------
@dataclass
class AgentContext:
    """Alles, was ein Agent zum Arbeiten braucht."""

    llm: LLMClient
    settings: Settings
    log: LogFn = field(default=lambda level, msg: None)
    cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def cancelled(self) -> bool:
        return self.cancel.is_set()


class Agent:
    """Basisklasse. Jeder Agent ist zustandslos und macht genau eine Sache."""

    name = "agent"
    tier = "worker"
    role = ""

    def __init__(self, context: AgentContext) -> None:
        self.ctx = context

    @property
    def model(self) -> str:
        return self.ctx.llm.model_for(self.tier)

    def run(self, *args: Any, **kwargs: Any) -> AgentResult:
        raise NotImplementedError

    # Gemeinsames Auftragsformat: der Worker sieht nur diesen einen Text,
    # keine Vorgeschichte, keine Rückfragen.
    @staticmethod
    def brief(goal: str, inputs: str, criteria: list[str], output_format: str) -> str:
        numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(criteria, 1))
        return (
            "Du bearbeitest EINE Teilaufgabe. Dieser Auftrag ist alles, was du "
            "bekommst. Rückfragen sind nicht möglich.\n\n"
            f"AUFGABE: {goal}\n\n"
            f"EINGABEN:\n{inputs}\n\n"
            f"ABNAHMEKRITERIEN (Ergebnis gilt als gescheitert, wenn eines verletzt ist):\n"
            f"{numbered}\n\n"
            f"AUSGABEFORMAT: {output_format}\n\n"
            "Regeln: nur diese Aufgabe, kein Ausweiten, keine Kommentare. Fehlt "
            "eine Eingabe, schreibe in die erste Zeile LÜCKE: <was fehlt> und "
            "arbeite mit dem Rest weiter. Gib nur das Ergebnis zurück, keine "
            "Einleitung."
        )
