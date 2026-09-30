"""Modellverwaltung: Versionen, Champion, Aufräumen.

Ohne Verwaltung endet jedes selbstlernende System im Chaos aus
`model_final_v2_neu_wirklich.pkl`. Hier bekommt jedes Training eine Version, der
aktuell produktive Stand heißt "Champion", und alte Stände bleiben so lange
liegen, bis sie sicher nicht mehr gebraucht werden.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils import ensure_dir, get_logger, read_json, write_json
from .ensemble import ModelEnsemble

log = get_logger("registry")

CHAMPION_FILE = "champion.json"


class ModelRegistry:
    """Versionierte Ablage der Ensembles."""

    def __init__(self, root: "str | Path" = "runtime/models", keep: int = 10) -> None:
        self.root = ensure_dir(root)
        self.keep = int(keep)

    # ------------------------------------------------------------------ #

    def path_for(self, symbol: str, version: str) -> Path:
        return self.root / _safe(symbol) / version

    def versions(self, symbol: str) -> list[str]:
        base = self.root / _safe(symbol)
        if not base.exists():
            return []
        return sorted(
            (p.name for p in base.iterdir() if p.is_dir() and (p / "ensemble.joblib").exists()),
            reverse=True,
        )

    def save(
        self, ensemble: ModelEnsemble, symbol: str, extra: "dict[str, Any] | None" = None
    ) -> Path:
        """Ein trainiertes Ensemble ablegen."""
        path = self.path_for(symbol, ensemble.version)
        ensemble.save(path)
        write_json(
            path / "info.json",
            {
                "symbol": symbol,
                "version": ensemble.version,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "auc": ensemble.report.auc,
                "members": list(ensemble.models),
                "n_features": len(ensemble.selected_features),
                **(extra or {}),
            },
        )
        self.prune(symbol)
        return path

    def load(self, symbol: str, version: "str | None" = None) -> "ModelEnsemble | None":
        """Eine Version laden. Ohne Angabe wird der Champion genommen."""
        version = version or self.champion(symbol)
        if not version:
            return None
        path = self.path_for(symbol, version)
        if not (path / "ensemble.joblib").exists():
            log.warning("Modellversion %s für %s existiert nicht", version, symbol)
            return None
        try:
            return ModelEnsemble.load(path)
        except Exception as exc:
            log.error("Modell %s/%s nicht ladbar: %s", symbol, version, exc)
            return None

    # ------------------------------------------------------------------ #
    # Champion
    # ------------------------------------------------------------------ #

    def champion(self, symbol: str) -> "str | None":
        data = read_json(self.root / _safe(symbol) / CHAMPION_FILE, {}) or {}
        version = data.get("version")
        if version and (self.path_for(symbol, version) / "ensemble.joblib").exists():
            return version
        # Kein gültiger Champion hinterlegt: auf die neueste Version zurückfallen
        versions = self.versions(symbol)
        return versions[0] if versions else None

    def champion_info(self, symbol: str) -> dict[str, Any]:
        return read_json(self.root / _safe(symbol) / CHAMPION_FILE, {}) or {}

    def promote(self, symbol: str, version: str, reason: str = "", metrics: "dict | None" = None) -> None:
        """Eine Version zum Champion machen - der Wechsel wird protokolliert."""
        path = self.path_for(symbol, version)
        if not (path / "ensemble.joblib").exists():
            raise FileNotFoundError(f"Version {version} für {symbol} existiert nicht")
        previous = self.champion(symbol)
        record = {
            "version": version,
            "previous": previous,
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "metrics": metrics or {},
        }
        base = ensure_dir(self.root / _safe(symbol))
        write_json(base / CHAMPION_FILE, record)
        history = read_json(base / "champion_history.json", []) or []
        history.append(record)
        write_json(base / "champion_history.json", history[-100:])
        log.info("Champion für %s: %s -> %s (%s)", symbol, previous, version, reason or "ohne Angabe")

    def history(self, symbol: str) -> list[dict[str, Any]]:
        return read_json(self.root / _safe(symbol) / "champion_history.json", []) or []

    # ------------------------------------------------------------------ #

    def prune(self, symbol: str) -> list[str]:
        """Alte Versionen löschen - der Champion bleibt immer verschont."""
        versions = self.versions(symbol)
        champion = self.champion(symbol)
        removable = [v for v in versions[self.keep :] if v != champion]
        for v in removable:
            shutil.rmtree(self.path_for(symbol, v), ignore_errors=True)
            log.debug("Alte Modellversion entfernt: %s/%s", symbol, v)
        return removable

    def catalogue(self) -> list[dict[str, Any]]:
        """Übersicht aller Modelle - für die Statusanzeige."""
        rows = []
        for symbol_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            symbol = symbol_dir.name
            champion = self.champion(symbol)
            for version in self.versions(symbol):
                info = read_json(symbol_dir / version / "info.json", {}) or {}
                rows.append(
                    {
                        "symbol": symbol,
                        "version": version,
                        "champion": version == champion,
                        "auc": info.get("auc"),
                        "members": len(info.get("members", [])),
                        "features": info.get("n_features"),
                        "saved_at": info.get("saved_at", "")[:19],
                    }
                )
        return rows


def _safe(name: str) -> str:
    return "".join(ch for ch in name if ch.isalnum() or ch in "._-") or "unbekannt"
