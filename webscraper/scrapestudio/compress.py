"""HTML für die KI eindampfen.

Der grösste Hebel beim Token-Sparen: eine typische Seite bringt 200-500 KB
HTML mit, davon sind 90-98 % Skripte, Styles, SVG-Pfade, Tracking und
Navigation. Was ein Modell zum Ableiten von Selektoren braucht, ist das
Gerüst mit ein paar Beispieltexten - selten mehr als 10 KB.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, Tag

# Tags ohne jeden Nutzen für die Extraktion
JUNK_TAGS = (
    "script", "style", "noscript", "svg", "canvas", "iframe", "template",
    "link", "meta", "picture", "source", "track", "object", "embed",
)

# Attribute, die für Selektoren zählen. Alles andere fliegt raus -
# vor allem inline-styles und data-* Ketten, die enorm viel Platz fressen.
KEEP_ATTRS = ("class", "id", "href", "src", "type", "name", "itemprop", "role")

MAX_CLASSES = 4  # Utility-Frameworks hängen 30 Klassen an ein div
MAX_ATTR_LEN = 120


def _clean_attrs(tag: Tag) -> None:
    attrs = {}
    for key, value in tag.attrs.items():
        if key not in KEEP_ATTRS:
            continue
        if key == "class" and isinstance(value, list):
            value = value[:MAX_CLASSES]
        elif isinstance(value, str) and len(value) > MAX_ATTR_LEN:
            value = value[:MAX_ATTR_LEN] + "..."
        attrs[key] = value
    tag.attrs = attrs


def compress_html(html: str, max_chars: int = 12000, keep_links: bool = True) -> str:
    """HTML auf ein token-armes Gerüst reduzieren.

    Erhält Struktur und Klassen (damit ein Modell CSS-Selektoren ableiten
    kann), wirft Ballast weg und kürzt auf ``max_chars``.
    """
    if not html:
        return ""

    soup = BeautifulSoup(html, "lxml")

    for tag in soup(list(JUNK_TAGS)):
        tag.decompose()
    for node in soup.find_all(string=lambda t: isinstance(t, Comment)):
        node.extract()

    body = soup.body or soup
    for tag in body.find_all(True):
        _clean_attrs(tag)
        if not keep_links and tag.name == "a":
            tag.attrs.pop("href", None)

    text = str(body)
    text = re.sub(r"\n\s*\n+", "\n", text)
    text = re.sub(r">\s+<", "><", text)

    if len(text) > max_chars:
        # Kopf und Fuss behalten: oben steht meist die Struktur, unten
        # Paginierung und Fusszeilen-Links.
        head = text[: int(max_chars * 0.75)]
        tail = text[-int(max_chars * 0.25):]
        text = f"{head}\n<!-- ... {len(text) - max_chars} Zeichen gekürzt ... -->\n{tail}"
    return text


def to_readable_text(html: str, max_chars: int = 12000) -> str:
    """Reiner Fliesstext ohne Markup - für Zusammenfassungen."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(list(JUNK_TAGS) + ["nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:max_chars]


def structure_sample(html: str, limit: int = 40) -> str:
    """Kurzer Struktur-Abriss: welche Container wiederholen sich wie oft.

    Hilft dem Modell, Listen zu erkennen, ohne die ganze Seite zu lesen -
    und kostet nur ein paar hundert Token.
    """
    soup = BeautifulSoup(html, "lxml")
    counts: dict[str, int] = {}
    for tag in soup.find_all(True):
        if tag.name in JUNK_TAGS:
            continue
        classes = tag.get("class") or []
        if not classes:
            continue
        key = f"{tag.name}.{'.'.join(classes[:MAX_CLASSES])}"
        counts[key] = counts.get(key, 0) + 1

    repeated = sorted(
        ((k, v) for k, v in counts.items() if v > 1),
        key=lambda kv: kv[1],
        reverse=True,
    )[:limit]
    return "\n".join(f"{count}x  {selector}" for selector, count in repeated)


def estimate_tokens(text: str) -> int:
    """Grobe Schätzung (~4 Zeichen je Token) für Anzeige und Budgetprüfung."""
    return max(1, len(text) // 4)
