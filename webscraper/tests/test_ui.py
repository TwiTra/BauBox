"""Oberflächen-Test: baut das echte Fenster und klickt es durch.

Braucht eine Anzeige. Ohne Bildschirm mit Xvfb starten:

    xvfb-run -a python3 tests/test_ui.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Eigenes Verzeichnis, damit der Test keine echten Einstellungen anfasst.
_tmp = tempfile.mkdtemp(prefix="scrapestudio-test-")
os.environ["SCRAPESTUDIO_HOME"] = _tmp
os.environ.pop("ANTHROPIC_API_KEY", None)

_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  OK   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        _failures.append(name)


def main() -> int:
    print("[Oberfläche]")

    from scrapestudio.models import ScrapeOptions
    from scrapestudio.ui.app import ScrapeStudio

    app = ScrapeStudio()
    app.update()
    check("Fenster gebaut", app.winfo_exists() == 1)
    check("Fünf Ansichten", len(app.views) == 5, f"-> {len(app.views)}")

    # -- Navigation ---------------------------------------------------
    for key in ("results", "team", "history", "settings", "scrape"):
        app.show(key)
        app.update()
        check(f"Ansicht '{key}' zeigt", app.views[key].winfo_ismapped() == 1)

    # -- Formular füllen und auslesen ---------------------------------
    view = app.scrape_view
    view.url_box.insert("1.0", "example.com/a\nhttps://example.com/b\n")
    view._count_urls()
    app.update()
    check("Adressen gezählt", "2 Adressen" in view.url_count.cget("text"),
          f"-> {view.url_count.cget('text')}")

    options = view.options()
    check("URLs übernommen", options.urls == ["example.com/a", "https://example.com/b"])
    check("Standardmodus Presets", options.mode == "preset", f"-> {options.mode}")

    # Moduswechsel
    for label, expected in (("Eigene Selektoren", "selectors"), ("KI-Agenten", "agent"),
                            ("Presets", "preset")):
        view.mode_switch.set(label)
        view._on_mode_change(label)
        app.update()
        check(f"Modus '{label}'", view.options().mode == expected)

    # Selektoren aus dem Textfeld
    view.mode_switch.set("Eigene Selektoren")
    view._on_mode_change("Eigene Selektoren")
    view.selector_box.delete("1.0", "end")
    view.selector_box.insert("1.0", "titel = h1\n# Kommentar\nlink = a@href\nkaputt\n")
    parsed = view.parse_selectors()
    check("Selektoren gelesen", parsed == {"titel": "h1", "link": "a@href"},
          f"-> {parsed}")

    # Zahlenfelder mit Unsinn füllen -> Standardwert statt Absturz
    view.delay.delete(0, "end")
    view.delay.insert(0, "keine zahl")
    check("Ungültige Zahl abgefangen", view.options().delay == 0.5,
          f"-> {view.options().delay}")

    # -- Optionen laden (Vorlage/Verlauf) ------------------------------
    loaded = ScrapeOptions(
        urls=["https://test.de"], mode="agent", instruction="Preise finden",
        follow_links=True, max_depth=3, max_pages=50, delay=1.5, workers=2,
        selectors={"a": "b"}, dedupe=False, respect_robots=False,
    )
    view.load_options(loaded)
    app.update()
    back = view.options()
    check("Vorlage: Modus", back.mode == "agent")
    check("Vorlage: Auftrag", back.instruction == "Preise finden")
    check("Vorlage: Tiefe", back.max_depth == 3, f"-> {back.max_depth}")
    check("Vorlage: Seiten", back.max_pages == 50)
    check("Vorlage: Pause", back.delay == 1.5, f"-> {back.delay}")
    check("Vorlage: robots aus", back.respect_robots is False)
    check("Vorlage: Duplikate aus", back.dedupe is False)

    # -- Ergebnisse ----------------------------------------------------
    rows = [
        {"name": "Hammer", "preis": "19,99 €", "quelle": "https://a.de"},
        {"name": "Säge", "preis": "34,50 €", "quelle": "https://a.de"},
        {"name": "Zange", "preis": "12,00 €", "quelle": "https://b.de"},
    ]
    app.results_view.set_rows(rows, "Drei Werkzeuge gefunden.")
    app.update()
    check("Tabelle gefüllt", app.results_view.table.total == 3)
    check("Zähler stimmt", "3 Datensätze" in app.results_view.counter.cget("text"),
          f"-> {app.results_view.counter.cget('text')}")

    # Filtern
    app.results_view.search.insert(0, "Säge")
    app.results_view._on_search()
    app.update()
    check("Filter greift", app.results_view.table.count == 1,
          f"-> {app.results_view.table.count}")
    app.results_view._clear_search()
    app.update()
    check("Filter zurückgesetzt", app.results_view.table.count == 3)

    # Sortieren
    app.results_view.table.sort_by("name")
    app.update()
    first = app.results_view.table.visible_rows()[0]["name"]
    check("Sortierung aufsteigend", first == "Hammer", f"-> {first}")
    app.results_view.table.sort_by("name")
    app.update()
    first = app.results_view.table.visible_rows()[0]["name"]
    check("Sortierung absteigend", first == "Zange", f"-> {first}")

    # Preise numerisch sortieren
    app.results_view.table.sort_by("preis")
    app.update()
    order = [r["preis"] for r in app.results_view.table.visible_rows()]
    check("Preise numerisch sortiert", order[0] == "12,00 €", f"-> {order}")

    # Detailansicht
    app.results_view._show_detail(rows[0])
    app.update()
    detail = app.results_view.detail.get("1.0", "end")
    check("Detail zeigt Werte", "Hammer" in detail and "19,99" in detail)

    # Formatwechsel
    for fmt in ("JSON", "PDF-Bericht", "Excel-Mappe"):
        matching = [f for f in __import__(
            "scrapestudio.exporters", fromlist=["FORMATS"]).FORMATS if f.label == fmt]
        if matching:
            app.results_view.format_menu.set(f"{matching[0].label}  ({matching[0].suffix})")
            app.results_view._on_format_change("")
            app.update()
    check("Formatwechsel ohne Fehler", True)

    # Export in eine echte Datei
    from scrapestudio import exporters as ex
    app.results_view.format_menu.set(f"{ex.FORMATS[0].label}  ({ex.FORMATS[0].suffix})")
    app.settings.export_dir = _tmp
    app.results_view._quick_export()
    app.update()
    written = list(Path(_tmp).glob("*.csv"))
    check("Schnellablage schreibt Datei", len(written) == 1, f"-> {written}")

    # -- Team-Ansicht --------------------------------------------------
    from scrapestudio.models import TaskRecord, Usage
    record = TaskRecord(id="L1", agent="Selektor-Sucher", goal="Selektoren ableiten",
                        model="claude-haiku-4-5-20251001")
    app.team_view.update_task(record)
    app.update()
    check("Board zeigt Aufgabe", "L1" in app.team_view._rows)

    record.state = "PASS"
    record.usage = Usage(input_tokens=3000, output_tokens=200, calls=1, cost_usd=0.004)
    app.team_view.update_task(record)
    app.update()
    check("Aufgabe aktualisiert statt verdoppelt", len(app.team_view._rows) == 1)

    usage = Usage(input_tokens=3000, output_tokens=200, calls=1, cost_usd=0.004,
                  saved_calls=99)
    app.team_view.update_usage(usage, 1.0)
    app.update()
    check("Ersparnis angezeigt", "99" in app.team_view.tile_saved.value_label.cget("text"))
    check("Sparhinweis gesetzt", "vermieden" in app.team_view.saving_note.cget("text"))

    app.team_view.clear()
    app.update()
    check("Board geleert", len(app.team_view._rows) == 0)

    # -- Verlauf und Vorlagen ------------------------------------------
    from scrapestudio.models import JobResult, PageResult, Template
    job = JobResult(name="Testlauf", options=ScrapeOptions(urls=["https://a.de"]))
    job.pages = [PageResult(url="https://a.de", status=200, rows=rows)]
    job.summary_text = "Zusammenfassung."
    app.storage.save_job(job)
    app.storage.save_template(Template(name="Meine Vorlage",
                                       options=ScrapeOptions(urls=["https://x.de"])))
    app.history_view.refresh()
    app.update()
    check("Verlauf listet Lauf", len(app.storage.list_jobs()) == 1)
    check("Vorlagen gelistet", len(app.storage.list_templates()) == 1)

    app.history_view._load(job.id)
    app.update()
    check("Lauf geladen", app.results_view.table.total == 3)

    app.history_view._use_template(app.storage.list_templates()[0])
    app.update()
    check("Vorlage angewandt", app.scrape_view.urls() == ["https://x.de"])

    # -- Einstellungen -------------------------------------------------
    app.show("settings")
    app.update()
    settings_view = app.settings_view
    settings_view.budget_usd.delete(0, "end")
    settings_view.budget_usd.insert(0, "2,50")   # Komma muss gehen
    settings_view.budget_calls.delete(0, "end")
    settings_view.budget_calls.insert(0, "abc")  # Unsinn -> Standard
    settings_view.max_chars.delete(0, "end")
    settings_view.max_chars.insert(0, "8000")
    settings_view._save()
    app.update()
    check("Budget mit Komma gelesen", app.settings.budget_usd == 2.5,
          f"-> {app.settings.budget_usd}")
    check("Unsinn abgefangen", app.settings.budget_calls == 60,
          f"-> {app.settings.budget_calls}")
    check("Zeichengrenze übernommen", app.settings.max_chars_per_page == 8000)

    settings_view._toggle_key()
    app.update()
    check("Schlüssel-Sichtbarkeit umschaltbar",
          settings_view.key_entry.cget("show") == "")

    settings_view._on_theme("Hell")
    app.update()
    check("Thema wechselbar", app.settings.theme == "light")
    settings_view._on_theme("Dunkel")
    app.update()

    # -- Ohne Schlüssel gesperrter Agentenmodus ------------------------
    check("Agenten nicht bereit ohne Schlüssel", app.agents_ready() is False)
    app.scrape_view.load_options(ScrapeOptions(urls=["https://a.de"], mode="agent",
                                               instruction="Test"))
    app.start_job()
    app.update()
    check("Agentenlauf ohne Schlüssel blockiert",
          app._thread is None or not app._thread.is_alive())

    # -- Leere Adresse blockiert ---------------------------------------
    app.scrape_view.url_box.delete("1.0", "end")
    app.start_job()
    app.update()
    check("Leerer Auftrag blockiert", app._thread is None or not app._thread.is_alive())

    # -- Protokoll -----------------------------------------------------
    app.log("Testmeldung", "ok")
    app.update()
    check("Protokoll schreibt", "Testmeldung" in app.scrape_view.log.text())
    app.scrape_view.log.clear()
    app.update()
    check("Protokoll leerbar", app.scrape_view.log.text() == "")

    # -- Laufzustand ---------------------------------------------------
    app.scrape_view.set_running(True)
    app.update()
    check("Startknopf gesperrt während Lauf",
          app.scrape_view.start_button.cget("state") == "disabled")
    app.scrape_view.set_running(False)
    app.update()
    check("Startknopf wieder frei",
          app.scrape_view.start_button.cget("state") == "normal")

    app.storage.close()
    app.destroy()
    return 0


if __name__ == "__main__":
    main()
    print("\n" + "=" * 58)
    if _failures:
        print(f"{len(_failures)} Prüfung(en) fehlgeschlagen: {', '.join(_failures)}")
        sys.exit(1)
    print("Oberfläche: alle Prüfungen bestanden.")
