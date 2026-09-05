"""Deterministische Extraktion - ohne KI, ohne Token.

Zwei Wege:

* **Presets** - fertige Bausteine für Links, Bilder, Tabellen, Kontaktdaten
  und so weiter. Braucht nie ein Modell.
* **Selektoren** - ein Satz benannter CSS-Selektoren, angewendet auf jede
  Seite. Der Satz kann von Hand kommen oder einmalig vom Agenten-Team
  gelernt worden sein. Genau hier wird gespart: gelernt wird einmal,
  angewendet beliebig oft.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}")
PHONE_RE = re.compile(r"(?:(?:\+|00)\d{1,3}[\s./-]?)?(?:\(?\d{2,5}\)?[\s./-]?){2,4}\d{2,}")
PRICE_RE = re.compile(
    r"(?:(?:€|EUR|\$|USD|£|CHF)\s?\d[\d.,]*)|(?:\d[\d.,]*\s?(?:€|EUR|\$|USD|£|CHF))"
)

PRESETS: dict[str, str] = {
    "text": "Fliesstext der Seite",
    "headings": "Überschriften H1-H6",
    "links": "Alle Links mit Text",
    "images": "Bilder mit Quelle und Alt-Text",
    "tables": "Tabellenzeilen",
    "lists": "Listeneinträge",
    "emails": "E-Mail-Adressen",
    "phones": "Telefonnummern",
    "prices": "Preisangaben",
    "meta": "Meta-Daten und Open Graph",
    "jsonld": "Strukturierte Daten (JSON-LD)",
    "paragraphs": "Absätze",
}


def _clean(value: str, strip: bool = True) -> str:
    if not value:
        return ""
    value = re.sub(r"\s+", " ", value)
    return value.strip() if strip else value


def extract_presets(
    html: str, url: str, presets: list[str], strip: bool = True, min_len: int = 0
) -> list[dict[str, Any]]:
    """Presets auf eine Seite anwenden und Zeilen zurückgeben."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict[str, Any]] = []

    def add(kind: str, **fields: Any) -> None:
        row = {"typ": kind, "quelle": url}
        row.update(fields)
        text = str(row.get("text") or row.get("wert") or "")
        if min_len and len(text) < min_len:
            return
        rows.append(row)

    for preset in presets:
        if preset == "text":
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            body = _clean(soup.get_text(" ", strip=True), strip)
            if body:
                add("text", text=body, laenge=len(body))

        elif preset == "paragraphs":
            for node in soup.find_all("p"):
                text = _clean(node.get_text(" ", strip=True), strip)
                if text:
                    add("absatz", text=text)

        elif preset == "headings":
            for level in range(1, 7):
                for node in soup.find_all(f"h{level}"):
                    text = _clean(node.get_text(" ", strip=True), strip)
                    if text:
                        add("ueberschrift", ebene=f"h{level}", text=text)

        elif preset == "links":
            for node in soup.find_all("a", href=True):
                add(
                    "link",
                    text=_clean(node.get_text(" ", strip=True), strip),
                    url=urljoin(url, node["href"]),
                )

        elif preset == "images":
            for node in soup.find_all("img"):
                src = node.get("src") or node.get("data-src") or ""
                if not src:
                    continue
                add(
                    "bild",
                    url=urljoin(url, src),
                    alt=_clean(node.get("alt", ""), strip),
                    titel=_clean(node.get("title", ""), strip),
                )

        elif preset == "tables":
            for t_index, table in enumerate(soup.find_all("table")):
                headers = [
                    _clean(th.get_text(" ", strip=True), strip)
                    for th in table.find_all("th")
                ]
                for row in table.find_all("tr"):
                    cells = [
                        _clean(td.get_text(" ", strip=True), strip)
                        for td in row.find_all(["td", "th"])
                    ]
                    if not any(cells):
                        continue
                    entry: dict[str, Any] = {"tabelle": t_index + 1}
                    for i, cell in enumerate(cells):
                        key = headers[i] if i < len(headers) and headers[i] else f"spalte_{i + 1}"
                        entry[key] = cell
                    add("tabellenzeile", **entry)

        elif preset == "lists":
            for node in soup.find_all("li"):
                text = _clean(node.get_text(" ", strip=True), strip)
                if text:
                    add("listeneintrag", text=text)

        elif preset == "emails":
            for match in dict.fromkeys(EMAIL_RE.findall(soup.get_text(" "))):
                add("email", wert=match)

        elif preset == "phones":
            for match in dict.fromkeys(PHONE_RE.findall(soup.get_text(" "))):
                cleaned = match.strip()
                if len(re.sub(r"\D", "", cleaned)) >= 7:
                    add("telefon", wert=cleaned)

        elif preset == "prices":
            for match in dict.fromkeys(PRICE_RE.findall(soup.get_text(" "))):
                add("preis", wert=match.strip())

        elif preset == "meta":
            title = soup.find("title")
            if title:
                add("meta", feld="title", wert=_clean(title.get_text(), strip))
            for node in soup.find_all("meta"):
                key = node.get("name") or node.get("property") or ""
                content = node.get("content") or ""
                if key and content:
                    add("meta", feld=key, wert=_clean(content, strip))

        elif preset == "jsonld":
            import json

            for node in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(node.string or "{}")
                except (ValueError, TypeError):
                    continue
                for item in data if isinstance(data, list) else [data]:
                    if isinstance(item, dict):
                        add("jsonld", **{
                            k: v for k, v in item.items()
                            if isinstance(v, (str, int, float, bool))
                        })

    return rows


def extract_by_selectors(
    html: str,
    url: str,
    selectors: dict[str, str],
    container: str = "",
    strip: bool = True,
) -> list[dict[str, Any]]:
    """Benannte CSS-Selektoren anwenden.

    Mit ``container`` wird pro Treffer eine Zeile erzeugt (Produktkarten,
    Suchtreffer, Inserate); ohne Container ergibt jeder Selektor eine
    Spalte einer einzigen Zeile.

    Ein Selektor darf mit ``@attribut`` enden, um statt des Textes ein
    Attribut zu lesen, z. B. ``a.titel@href``.
    """
    soup = BeautifulSoup(html, "lxml")

    def read(node: Any, selector: str) -> str:
        selector, _, attr = selector.partition("@")
        found = node.select_one(selector.strip()) if selector.strip() else node
        if not found:
            return ""
        if attr:
            value = found.get(attr.strip(), "")
            if isinstance(value, list):
                value = " ".join(value)
            if attr.strip() in ("href", "src") and value:
                value = urljoin(url, value)
            return _clean(str(value), strip)
        return _clean(found.get_text(" ", strip=True), strip)

    rows: list[dict[str, Any]] = []
    if container:
        for node in soup.select(container):
            row = {name: read(node, sel) for name, sel in selectors.items()}
            if any(row.values()):
                row["quelle"] = url
                rows.append(row)
    else:
        row = {name: read(soup, sel) for name, sel in selectors.items()}
        if any(row.values()):
            row["quelle"] = url
            rows.append(row)
    return rows


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Doppelte Zeilen entfernen, Reihenfolge bleibt erhalten."""
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = tuple(sorted((k, str(v)) for k, v in row.items() if k != "quelle"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def all_columns(rows: list[dict[str, Any]]) -> list[str]:
    """Spaltennamen in stabiler Reihenfolge über alle Zeilen sammeln."""
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns
