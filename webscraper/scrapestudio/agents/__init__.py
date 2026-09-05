"""Das Agenten-Team.

Drei Ebenen, damit teure Modelle nicht die Fleissarbeit machen:

* **Worker** (günstig) - Recherche, Extraktion, Zusammenfassung. Viele Aufrufe.
* **Prüfer** (mittel) - kontrolliert Stichproben der Worker-Ergebnisse.
* **Berater** (teuer) - nur, wenn der Orchestrator eskaliert.

Der Orchestrator selbst ruft kein Modell für Fleissarbeit auf. Er plant,
verteilt, prüft und führt zusammen.
"""

from .base import Agent, AgentContext, BudgetExceeded, BudgetGuard, LLMClient
from .orchestrator import Orchestrator

__all__ = [
    "Agent",
    "AgentContext",
    "BudgetExceeded",
    "BudgetGuard",
    "LLMClient",
    "Orchestrator",
]
