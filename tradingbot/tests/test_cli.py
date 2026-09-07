"""Kommandozeile: laufen die Befehle durch und melden sie Sinnvolles?"""

from __future__ import annotations

import pytest

from pax.cli import build_parser, main


def _cfg_datei(config, tmp_path) -> str:
    pfad = tmp_path / "config.yaml"
    config.save(pfad, redact=False)
    return str(pfad)


def test_parser_kennt_alle_befehle():
    parser = build_parser()
    hilfe = parser.format_help()
    for befehl in ("init", "status", "connect", "fetch", "analyse", "backtest",
                   "train", "walkforward", "evolve", "feedback", "live", "journal", "selftest"):
        assert befehl in hilfe


def test_init_legt_datei_an(tmp_path):
    pfad = tmp_path / "neu.yaml"
    assert main(["-c", str(pfad), "init"]) == 0
    assert pfad.exists()
    assert main(["-c", str(pfad), "init"]) == 1          # ohne --force verweigert
    assert main(["-c", str(pfad), "init", "--force"]) == 0


def test_status_laeuft_ohne_daten(config, tmp_path, capsys):
    assert main(["-c", _cfg_datei(config, tmp_path), "status"]) == 0
    ausgabe = capsys.readouterr().out
    assert "Status" in ausgabe and "KONFIGURATION" in ausgabe


def test_connect_meldet_fehlendes_terminal_klar(config, tmp_path, capsys):
    from pax.data import MT5Client

    if MT5Client.available():
        pytest.skip("MetaTrader5 ist installiert")
    assert main(["-c", _cfg_datei(config, tmp_path), "connect"]) == 1
    assert "Windows" in capsys.readouterr().out


def test_selftest_besteht(config, tmp_path, capsys):
    rc = main(["-c", _cfg_datei(config, tmp_path), "selftest", "-n", "3000"])
    ausgabe = capsys.readouterr().out
    assert "ALLE PRÜFUNGEN BESTANDEN" in ausgabe
    assert rc == 0


def test_backtest_ohne_modell(config, tmp_path, capsys):
    assert main(["-c", _cfg_datei(config, tmp_path), "backtest", "--rules-only", "-n", "3000"]) == 0
    assert "BACKTEST" in capsys.readouterr().out


def test_analyse_liefert_eine_einschaetzung(config, tmp_path, capsys):
    assert main(["-c", _cfg_datei(config, tmp_path), "analyse", "-n", "3000"]) == 0
    ausgabe = capsys.readouterr().out
    assert "ZEITEBENEN" in ausgabe and "SIGNAL" in ausgabe


def test_journal_ohne_eintraege(config, tmp_path, capsys):
    assert main(["-c", _cfg_datei(config, tmp_path), "journal"]) == 0
    assert "keine Trades" in capsys.readouterr().out


def test_feedback_ohne_trades(config, tmp_path, capsys):
    assert main(["-c", _cfg_datei(config, tmp_path), "feedback"]) == 0
    assert "Keine Trades" in capsys.readouterr().out


def test_ungueltige_konfiguration_bricht_ab(config, tmp_path, capsys):
    config.risk.risk_per_trade = 0.9
    with pytest.raises(SystemExit) as exc:
        main(["-c", _cfg_datei(config, tmp_path), "status"])
    assert exc.value.code == 2
    assert "Probleme" in capsys.readouterr().out
