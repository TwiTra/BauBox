"""Die Arbeiter-Agenten.

Alle laufen auf der günstigen Ebene. Der wichtigste ist der
``SelectorAgent``: er sieht **eine** Beispielseite und leitet daraus CSS-
Selektoren ab. Diese Selektoren wendet danach ``extractors`` auf alle
weiteren Seiten an - ohne einen weiteren Token. Aus Kosten in der
Grössenordnung "je Seite" werden Kosten "je Auftrag".
"""

from __future__ import annotations

import json
from typing import Any

from ..compress import compress_html, structure_sample, to_readable_text
from ..extractors import extract_by_selectors
from ..models import AgentResult, Usage
from .base import Agent, parse_json


# --------------------------------------------------------------------------
class SelectorAgent(Agent):
    """Leitet aus einer Beispielseite wiederverwendbare CSS-Selektoren ab."""

    name = "Selektor-Sucher"
    tier = "worker"
    role = "Findet einmalig die CSS-Selektoren, die danach kostenlos laufen."

    SYSTEM = (
        "Du bist Spezialist für HTML-Struktur. Du bekommst das eingedampfte "
        "Gerüst einer Webseite und einen Auftrag, welche Daten daraus gelesen "
        "werden sollen. Du lieferst CSS-Selektoren, die auf allen ähnlichen "
        "Seiten derselben Website funktionieren.\n\n"
        "Regeln für gute Selektoren:\n"
        "- Nutze stabile Klassen und semantische Tags, keine zufällig "
        "wirkenden Hash-Klassen wie 'css-1x9f3'.\n"
        "- 'container' ist der Selektor für EIN sich wiederholendes Element "
        "(eine Produktkarte, ein Treffer, ein Inserat). Wiederholt sich "
        "nichts, setze container auf \"\".\n"
        "- Die Selektoren in 'felder' werden INNERHALB des Containers "
        "gesucht, also relativ dazu.\n"
        "- Für ein Attribut statt des Textes hänge @attribut an, "
        "z. B. \"a.title@href\" oder \"img@src\".\n"
        "- Feldnamen: kurz, klein geschrieben, deutsch, ohne Leerzeichen."
    )

    def run(self, html: str, url: str, instruction: str) -> AgentResult:
        compressed = compress_html(html, self.ctx.settings.max_chars_per_page)
        repeated = structure_sample(html)

        prompt = self.brief(
            goal=f"Finde CSS-Selektoren für: {instruction}",
            inputs=(
                f"URL: {url}\n\n"
                f"HÄUFIGE STRUKTUREN (Anzahl x Selektor):\n{repeated or '(keine)'}\n\n"
                f"HTML-GERÜST:\n{compressed}"
            ),
            criteria=[
                "Jeder Selektor ist gültiges CSS und kommt im gezeigten HTML vor.",
                "Feldnamen beschreiben den Inhalt, nicht die Technik.",
                "Enthält die Seite eine Liste gleichartiger Einträge, ist "
                "'container' gesetzt und die Feld-Selektoren sind relativ dazu.",
                "Antwort ist ausschliesslich JSON, ohne Text davor oder danach.",
            ],
            output_format=(
                '{"container": "css oder leer", '
                '"felder": {"name": "css-selektor"}, '
                '"begruendung": "ein Satz"}'
            ),
        )

        result = self.ctx.llm.call(self.tier, self.SYSTEM, prompt, max_tokens=1200)
        if not result.ok:
            return result

        data = parse_json(result.text)
        if not isinstance(data, dict) or not isinstance(data.get("felder"), dict):
            return AgentResult(
                ok=False,
                error="Selektoren nicht lesbar (kein gültiges JSON-Objekt).",
                usage=result.usage,
            )

        fields = {
            str(k).strip(): str(v).strip()
            for k, v in data["felder"].items()
            if str(v).strip()
        }
        if not fields:
            return AgentResult(ok=False, error="Keine Selektoren geliefert.",
                               usage=result.usage)

        return AgentResult(
            ok=True,
            data={
                "container": str(data.get("container", "")).strip(),
                "felder": fields,
                "begruendung": str(data.get("begruendung", "")).strip(),
            },
            usage=result.usage,
            from_cache=result.from_cache,
        )


# --------------------------------------------------------------------------
class ExtractAgent(Agent):
    """Liest Daten direkt aus einer Seite - Rückfalloption.

    Kommt nur zum Zug, wenn Selektoren nicht greifen (z. B. bei sehr
    unregelmässigen Seiten). Kostet je Seite Token, deshalb nicht der
    Standardweg.
    """

    name = "Direkt-Leser"
    tier = "worker"
    role = "Liest Daten direkt aus der Seite, wenn Selektoren nicht greifen."

    SYSTEM = (
        "Du liest strukturierte Daten aus Webseiten-Text. Du gibst reines "
        "JSON zurück: eine Liste von Objekten mit einheitlichen Schlüsseln. "
        "Du erfindest nichts. Steht ein Wert nicht auf der Seite, lässt du "
        "das Feld leer. Feldnamen sind deutsch, klein, ohne Leerzeichen."
    )

    def run(self, html: str, url: str, instruction: str) -> AgentResult:
        compressed = compress_html(html, self.ctx.settings.max_chars_per_page)

        prompt = self.brief(
            goal=f"Lies aus dieser Seite: {instruction}",
            inputs=f"URL: {url}\n\nSEITENINHALT:\n{compressed}",
            criteria=[
                "Nur Werte, die wörtlich auf der Seite stehen; nichts ergänzen.",
                "Alle Objekte haben dieselben Schlüssel.",
                "Antwort ist ausschliesslich ein JSON-Array.",
            ],
            output_format='[{"feld": "wert"}, ...] - leeres Array, wenn nichts passt',
        )

        result = self.ctx.llm.call(self.tier, self.SYSTEM, prompt, max_tokens=4000)
        if not result.ok:
            return result

        data = parse_json(result.text)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return AgentResult(ok=False, error="Antwort war kein JSON-Array.",
                               usage=result.usage)

        rows = []
        for item in data:
            if isinstance(item, dict):
                row = {str(k): item[k] for k in item}
                row["quelle"] = url
                rows.append(row)

        return AgentResult(ok=True, data=rows, usage=result.usage,
                           from_cache=result.from_cache)


# --------------------------------------------------------------------------
class ScoutAgent(Agent):
    """Recherche: welche Seiten sind für den Auftrag überhaupt interessant."""

    name = "Kundschafter"
    tier = "worker"
    role = "Sichtet Links und wählt die Seiten aus, die zum Auftrag passen."

    SYSTEM = (
        "Du wählst aus einer Liste von Links diejenigen aus, die für einen "
        "gegebenen Rechercheauftrag relevant sind. Du bewertest nur anhand "
        "von URL und Linktext. Du gibst reines JSON zurück."
    )

    def run(self, instruction: str, links: list[dict[str, str]], limit: int = 20) -> AgentResult:
        if not links:
            return AgentResult(ok=True, data=[])

        listing = "\n".join(
            f"{i}. {link.get('text', '')[:80]} -> {link.get('url', '')}"
            for i, link in enumerate(links[:200], 1)
        )

        prompt = self.brief(
            goal=f"Wähle die relevantesten Links für: {instruction}",
            inputs=f"LINKS:\n{listing}",
            criteria=[
                f"Höchstens {limit} Nummern.",
                "Nur Nummern, die in der Liste vorkommen.",
                "Sortiert nach Relevanz, die beste zuerst.",
                "Antwort ist ausschliesslich ein JSON-Array aus Zahlen.",
            ],
            output_format="[3, 17, 4]",
        )

        result = self.ctx.llm.call(self.tier, self.SYSTEM, prompt, max_tokens=600)
        if not result.ok:
            return result

        picks = parse_json(result.text)
        if not isinstance(picks, list):
            return AgentResult(ok=False, error="Auswahl nicht lesbar.", usage=result.usage)

        chosen: list[dict[str, str]] = []
        for number in picks[:limit]:
            try:
                index = int(number) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(links):
                chosen.append(links[index])

        return AgentResult(ok=True, data=chosen, usage=result.usage,
                           from_cache=result.from_cache)


# --------------------------------------------------------------------------
class SummarizerAgent(Agent):
    """Fasst das Gesammelte zu einer lesbaren Antwort zusammen."""

    name = "Zusammenfasser"
    tier = "worker"
    role = "Verdichtet die Ergebnisse zu einer Antwort auf den Auftrag."

    SYSTEM = (
        "Du fasst gescrapte Daten für einen Menschen zusammen. Du schreibst "
        "auf Deutsch, sachlich und knapp. Du nennst nur, was in den Daten "
        "steht, und schreibst dazu, wenn etwas fehlt. Keine Floskeln, keine "
        "Einleitung wie 'Hier ist die Zusammenfassung'."
    )

    def run(self, instruction: str, rows: list[dict[str, Any]], max_rows: int = 60) -> AgentResult:
        if not rows:
            return AgentResult(ok=True, text="Keine Daten zum Zusammenfassen.")

        sample = rows[:max_rows]
        payload = json.dumps(sample, ensure_ascii=False, indent=None)[:20000]
        omitted = len(rows) - len(sample)

        prompt = self.brief(
            goal=f"Beantworte anhand der Daten: {instruction}",
            inputs=(
                f"DATENSÄTZE GESAMT: {len(rows)}"
                + (f" (davon {omitted} nicht gezeigt)" if omitted else "")
                + f"\n\nDATEN:\n{payload}"
            ),
            criteria=[
                "Nur Aussagen, die durch die Daten gedeckt sind.",
                "Konkrete Zahlen und Namen nennen, keine vagen Umschreibungen.",
                "Höchstens 200 Wörter.",
                "Markdown mit kurzen Aufzählungspunkten.",
            ],
            output_format="Fliesstext mit Aufzählung, kein JSON",
        )

        result = self.ctx.llm.call(self.tier, self.SYSTEM, prompt, max_tokens=1200)
        return result


# --------------------------------------------------------------------------
class VerifierAgent(Agent):
    """Prüft Stichproben der Worker-Ergebnisse gegen den Auftrag."""

    name = "Prüfer"
    tier = "verifier"
    role = "Kontrolliert Stichproben und entscheidet PASS oder FIX."

    SYSTEM = (
        "Du prüfst das Ergebnis eines Extraktions-Laufs. Du bekommst den "
        "Auftrag und eine Stichprobe der Datensätze. Du entscheidest, ob die "
        "Daten den Auftrag erfüllen.\n\n"
        "PASS: Die Daten passen zum Auftrag und wirken vollständig.\n"
        "FIX: Etwas stimmt nicht - falsche Felder, leere Werte, Navigation "
        "statt Inhalt, offensichtlich abgeschnitten.\n\n"
        "Du bist streng, aber nicht pedantisch: einzelne leere Felder sind "
        "kein FIX, systematisch leere Spalten schon. Du gibst reines JSON "
        "zurück."
    )

    def run(self, instruction: str, rows: list[dict[str, Any]], sample_size: int = 3) -> AgentResult:
        if not rows:
            return AgentResult(
                ok=True,
                data={"verdikt": "FIX", "grund": "Keine Datensätze gefunden.",
                      "vorschlag": "Selektoren neu ableiten oder Direkt-Leser nutzen."},
            )

        # Anfang, Mitte, Ende - so fallen abgeschnittene Läufe auf.
        indices = {0, len(rows) // 2, len(rows) - 1}
        sample = [rows[i] for i in sorted(indices)][:max(1, sample_size)]
        columns = sorted({key for row in rows for key in row})

        empty_ratio = {
            column: round(
                sum(1 for row in rows if not str(row.get(column, "")).strip()) / len(rows), 2
            )
            for column in columns
        }

        prompt = self.brief(
            goal=f"Prüfe, ob die Daten diesen Auftrag erfüllen: {instruction}",
            inputs=(
                f"ANZAHL DATENSÄTZE: {len(rows)}\n"
                f"SPALTEN: {', '.join(columns)}\n"
                f"LEER-ANTEIL JE SPALTE: {json.dumps(empty_ratio, ensure_ascii=False)}\n\n"
                f"STICHPROBE:\n{json.dumps(sample, ensure_ascii=False, indent=2)[:8000]}"
            ),
            criteria=[
                "Verdikt ist genau 'PASS' oder 'FIX'.",
                "Bei FIX nennt 'grund' den konkreten Mangel, nicht allgemein.",
                "Bei FIX enthält 'vorschlag' eine umsetzbare Korrektur.",
                "Antwort ist ausschliesslich JSON.",
            ],
            output_format='{"verdikt": "PASS", "grund": "...", "vorschlag": "..."}',
        )

        result = self.ctx.llm.call(self.tier, self.SYSTEM, prompt, max_tokens=800)
        if not result.ok:
            return result

        data = parse_json(result.text)
        if not isinstance(data, dict):
            # Prüfung selbst kaputt: nicht den Lauf blockieren.
            return AgentResult(
                ok=True,
                data={"verdikt": "PASS", "grund": "Prüfung nicht auswertbar.", "vorschlag": ""},
                usage=result.usage,
            )

        verdict = str(data.get("verdikt", "PASS")).upper().strip()
        return AgentResult(
            ok=True,
            data={
                "verdikt": "FIX" if verdict == "FIX" else "PASS",
                "grund": str(data.get("grund", "")).strip(),
                "vorschlag": str(data.get("vorschlag", "")).strip(),
            },
            usage=result.usage,
            from_cache=result.from_cache,
        )


# --------------------------------------------------------------------------
def apply_selectors(
    html: str, url: str, learned: dict[str, Any], strip: bool = True
) -> list[dict[str, Any]]:
    """Gelernte Selektoren auf eine Seite anwenden - kostet keine Token."""
    return extract_by_selectors(
        html,
        url,
        learned.get("felder", {}),
        container=learned.get("container", ""),
        strip=strip,
    )


ROSTER = [SelectorAgent, ScoutAgent, ExtractAgent, SummarizerAgent, VerifierAgent]
