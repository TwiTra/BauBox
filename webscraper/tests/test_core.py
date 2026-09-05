"""Rauchtest der Logik-Module - läuft ohne Netz, ohne Oberfläche, ohne API.

Aufruf:  python -m pytest tests/ -q      (oder direkt: python tests/test_core.py)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrapestudio import compress, exporters, extractors  # noqa: E402
from scrapestudio.agents.base import BudgetExceeded, BudgetGuard, parse_json  # noqa: E402
from scrapestudio.config import Settings, cost_of  # noqa: E402
from scrapestudio.engine import normalise_url, page_title  # noqa: E402
from scrapestudio.models import JobResult, ScrapeOptions, Usage  # noqa: E402
from scrapestudio.storage import Storage  # noqa: E402

SAMPLE = """
<!doctype html><html><head>
  <title>Testshop</title>
  <meta name="description" content="Ein Laden">
  <style>.x{color:red}</style><script>var tracking=1;</script>
</head><body>
  <nav><a href="/start">Start</a></nav>
  <h1>Angebote</h1>
  <div class="produkt-liste">
    <article class="karte"><h2 class="name">Hammer</h2>
      <span class="preis">19,99 €</span><a class="mehr" href="/p/1">Details</a>
      <img src="/img/1.jpg" alt="Hammer"></article>
    <article class="karte"><h2 class="name">Säge</h2>
      <span class="preis">34,50 €</span><a class="mehr" href="/p/2">Details</a>
      <img src="/img/2.jpg" alt="Säge"></article>
    <article class="karte"><h2 class="name">Zange</h2>
      <span class="preis">12,00 €</span><a class="mehr" href="/p/3">Details</a>
      <img src="/img/3.jpg" alt="Zange"></article>
  </div>
  <table><tr><th>Art</th><th>Lager</th></tr><tr><td>Hammer</td><td>5</td></tr></table>
  <p>Kontakt: info@testshop.de oder +49 30 1234567</p>
</body></html>
"""
URL = "https://testshop.example/angebote"

_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  OK   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        _failures.append(name)


# --------------------------------------------------------------------------
def test_compress() -> None:
    print("\n[Kompression]")
    compressed = compress.compress_html(SAMPLE, max_chars=8000)
    check("Skript entfernt", "tracking" not in compressed)
    check("Style entfernt", "color:red" not in compressed)
    check("Struktur erhalten", "karte" in compressed and "preis" in compressed)
    check("kleiner als Original", len(compressed) < len(SAMPLE))

    text = compress.to_readable_text(SAMPLE)
    check("Fliesstext enthält Inhalt", "Hammer" in text)
    check("Fliesstext ohne Navigation", "Start" not in text)

    structure = compress.structure_sample(SAMPLE)
    check("Wiederholung erkannt", "karte" in structure and "3x" in structure,
          f"-> {structure!r}")
    check("Token-Schätzung plausibel", compress.estimate_tokens("abcd" * 25) == 25)


def test_presets() -> None:
    print("\n[Presets]")
    rows = extractors.extract_presets(SAMPLE, URL, ["headings"])
    check("Überschriften", any(r.get("text") == "Angebote" for r in rows))

    rows = extractors.extract_presets(SAMPLE, URL, ["links"])
    check("Links absolut", any(r.get("url", "").startswith("https://testshop.example/p/")
                               for r in rows))

    rows = extractors.extract_presets(SAMPLE, URL, ["images"])
    check("Bilder mit Alt", any(r.get("alt") == "Säge" for r in rows))

    rows = extractors.extract_presets(SAMPLE, URL, ["emails"])
    check("E-Mail gefunden", any(r.get("wert") == "info@testshop.de" for r in rows))

    rows = extractors.extract_presets(SAMPLE, URL, ["prices"])
    check("Preise gefunden", len(rows) >= 3, f"-> {len(rows)}")

    rows = extractors.extract_presets(SAMPLE, URL, ["tables"])
    check("Tabellenzeile mit Kopf", any(r.get("Art") == "Hammer" for r in rows),
          f"-> {rows}")

    rows = extractors.extract_presets(SAMPLE, URL, ["meta"])
    check("Meta-Beschreibung", any(r.get("feld") == "description" for r in rows))


def test_selectors() -> None:
    print("\n[Selektoren - der Weg ohne Token]")
    learned = {
        "container": "article.karte",
        "felder": {"name": "h2.name", "preis": ".preis", "link": "a.mehr@href",
                   "bild": "img@src"},
    }
    rows = extractors.extract_by_selectors(
        SAMPLE, URL, learned["felder"], container=learned["container"]
    )
    check("drei Datensätze", len(rows) == 3, f"-> {len(rows)}")
    check("Namen korrekt", [r["name"] for r in rows] == ["Hammer", "Säge", "Zange"])
    check("Preis korrekt", rows[1]["preis"] == "34,50 €")
    check("Attribut @href absolut",
          rows[0]["link"] == "https://testshop.example/p/1", f"-> {rows[0]['link']}")
    check("Attribut @src absolut",
          rows[2]["bild"] == "https://testshop.example/img/3.jpg")
    check("Quelle gesetzt", all(r["quelle"] == URL for r in rows))

    # ohne Container: eine Zeile
    single = extractors.extract_by_selectors(SAMPLE, URL, {"titel": "h1"})
    check("ohne Container eine Zeile", len(single) == 1 and single[0]["titel"] == "Angebote")

    doubled = extractors.dedupe_rows(rows + rows)
    check("Duplikate entfernt", len(doubled) == 3, f"-> {len(doubled)}")


def test_exports() -> None:
    print("\n[Export]")
    rows = [
        {"name": "Hammer", "preis": "19,99 €", "quelle": URL},
        {"name": "Säge", "preis": "34,50 €", "notiz": "Umlaut-Test äöüß", "quelle": URL},
    ]
    meta = {"zusammenfassung": "Zwei Werkzeuge gefunden.", "auftrag": "Preise"}

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for fmt in exporters.FORMATS:
            target = base / f"test{fmt.suffix}"
            if not exporters.available(fmt):
                print(f"  --   {fmt.label} übersprungen (Paket '{fmt.needs}' fehlt)")
                continue
            try:
                written = exporters.export(rows, target, fmt.key, meta)
                check(f"{fmt.label} geschrieben",
                      written.exists() and written.stat().st_size > 0)
            except Exception as exc:
                check(f"{fmt.label} geschrieben", False, f"-> {type(exc).__name__}: {exc}")

        data = json.loads((base / "test.json").read_text("utf-8"))
        check("JSON enthält Umlaute", data["daten"][1]["notiz"] == "Umlaut-Test äöüß")

        csv_text = (base / "test.csv").read_text("utf-8-sig")
        check("CSV hat alle Spalten", "notiz" in csv_text.splitlines()[0])

        html_text = (base / "test.html").read_text("utf-8")
        check("HTML enthält Zusammenfassung", "Zwei Werkzeuge" in html_text)

    clip = exporters.to_clipboard_text(rows)
    check("Zwischenablage tabgetrennt", clip.splitlines()[0].count("\t") >= 2)
    check("Dateiname sinnvoll",
          exporters.suggest_filename("Mein Test!", "csv").endswith(".csv"))


def test_storage() -> None:
    print("\n[Speicher]")
    with tempfile.TemporaryDirectory() as tmp:
        store = Storage(Path(tmp) / "t.db")

        job = JobResult(name="Testlauf", options=ScrapeOptions(urls=[URL]))
        job.summary_text = "Alles gut."
        from scrapestudio.models import PageResult
        job.pages = [PageResult(url=URL, status=200, rows=[{"a": 1}, {"a": 2}])]
        store.save_job(job)

        listed = store.list_jobs()
        check("Auftrag gespeichert", len(listed) == 1 and listed[0]["row_count"] == 2)

        loaded = store.load_job(job.id)
        check("Auftrag geladen", loaded is not None and loaded["summary"] == "Alles gut.")
        check("Zeilen erhalten", len(loaded["rows"]) == 2)

        from scrapestudio.models import Template
        store.save_template(Template(name="Shop", options=ScrapeOptions(urls=[URL]),
                                     note="Notiz"))
        templates = store.list_templates()
        check("Vorlage gespeichert", len(templates) == 1 and templates[0].name == "Shop")
        check("Vorlage trägt Optionen", templates[0].options.urls == [URL])

        check("Cache leer", store.get("m", "s", "p") is None)
        store.put("m", "s", "p", "antwort")
        check("Cache trifft", store.get("m", "s", "p") == "antwort")
        check("Cache unterscheidet Modelle", store.get("anderes", "s", "p") is None)
        check("Cache-Statistik", store.cache_stats()["eintraege"] == 1)
        check("Cache leeren", store.clear_cache() == 1)

        store.delete_job(job.id)
        check("Auftrag gelöscht", store.list_jobs() == [])
        store.close()


def test_budget_and_parsing() -> None:
    print("\n[Budget und Antwort-Auswertung]")
    guard = BudgetGuard(max_usd=0.01, max_calls=2)
    guard.check()
    guard.record(Usage(input_tokens=1000, output_tokens=100, calls=1, cost_usd=0.002))
    guard.check()
    guard.record(Usage(calls=1, cost_usd=0.002))
    try:
        guard.check()
        check("Aufruf-Grenze stoppt", False, "-> keine Ausnahme")
    except BudgetExceeded:
        check("Aufruf-Grenze stoppt", True)

    soft = BudgetGuard(max_usd=0.0001, max_calls=1, stop=False)
    soft.record(Usage(calls=5, cost_usd=1.0))
    soft.check()
    check("ohne Stopp läuft weiter", True)

    check("Kosten Haiku < Opus",
          cost_of("claude-haiku-4-5-20251001", 10000, 1000)
          < cost_of("claude-opus-5", 10000, 1000))

    check("JSON blank", parse_json('{"a": 1}') == {"a": 1})
    check("JSON im Code-Zaun", parse_json('```json\n{"a": 2}\n```') == {"a": 2})
    check("JSON mit Vortext", parse_json('Hier:\n[1, 2, 3]\nfertig') == [1, 2, 3])
    check("JSON kaputt -> None", parse_json("gar kein json") is None)


def test_models_and_urls() -> None:
    print("\n[Modelle und URLs]")
    check("URL ohne Schema", normalise_url("example.com/x") == "https://example.com/x")
    check("Fragment entfernt",
          normalise_url("https://a.de/b#c") == "https://a.de/b")
    check("Titel gelesen", page_title(SAMPLE) == "Testshop")

    options = ScrapeOptions(urls=[URL], mode="agent", instruction="Preise")
    restored = ScrapeOptions.from_dict(options.to_dict())
    check("Optionen rund", restored.instruction == "Preise" and restored.mode == "agent")
    check("Unbekannte Felder ignoriert",
          ScrapeOptions.from_dict({"urls": [], "quatsch": 1}).urls == [])

    usage = Usage(input_tokens=10, calls=1, cost_usd=0.5)
    usage.add(Usage(input_tokens=5, calls=1, cost_usd=0.25))
    check("Verbrauch summiert", usage.input_tokens == 15 and usage.cost_usd == 0.75)

    settings = Settings.from_dict(Settings().to_dict())
    check("Einstellungen rund", settings.budget_usd == 1.00)


if __name__ == "__main__":
    for test in (test_compress, test_presets, test_selectors, test_exports,
                 test_storage, test_budget_and_parsing, test_models_and_urls):
        test()

    print("\n" + "=" * 58)
    if _failures:
        print(f"{len(_failures)} Prüfung(en) fehlgeschlagen: {', '.join(_failures)}")
        sys.exit(1)
    print("Alle Prüfungen bestanden.")
