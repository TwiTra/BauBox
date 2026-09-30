"""Kreuzvalidierung für Zeitreihen - mit Sperrzonen.

Gewöhnliche K-Fold-Validierung ist bei Handelsdaten schlicht falsch. Zwei Fehler
stecken darin:

1. **Überlappung**: Ein Label bei Balken 100 mit 48 Balken Horizont reicht bis
   Balken 148. Liegt Balken 120 im Test und Balken 100 im Training, kennt das
   Training bereits Kursbewegungen aus dem Testzeitraum.
2. **Serielle Korrelation**: Direkt benachbarte Balken sind fast identisch. Ein
   Testbeispiel unmittelbar nach dem Trainingsende ist kein echter Test.

Die Antwort darauf: alle Trainingsbeispiele entfernen, deren Zeitraum in den
Test hineinreicht (*purging*), und danach eine zusätzliche Sperrfrist einlegen
(*embargo*). Ohne beides sehen Backtests grandios aus und Live-Konten sterben.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pandas as pd


class PurgedKFold:
    """K-Fold über die Zeit mit Purging und Embargo.

    Kompatibel zur sklearn-Schnittstelle (`split`, `get_n_splits`), damit die
    Klasse überall dort einsetzbar ist, wo sonst ein Splitter erwartet wird.
    """

    def __init__(
        self,
        n_splits: int = 5,
        exit_index: "pd.Series | np.ndarray | None" = None,
        embargo_frac: float = 0.01,
        purge: bool = True,
    ) -> None:
        if n_splits < 2:
            raise ValueError("n_splits muss mindestens 2 sein")
        self.n_splits = int(n_splits)
        self.exit_index = exit_index
        self.embargo_frac = float(embargo_frac)
        self.purge = purge

    def get_n_splits(self, X=None, y=None, groups=None) -> int:  # noqa: ARG002
        return self.n_splits

    def split(self, X, y=None, groups=None) -> Iterator[tuple[np.ndarray, np.ndarray]]:  # noqa: ARG002
        n = len(X)
        indices = np.arange(n)
        embargo = int(n * self.embargo_frac)
        ends = self._ends(n)

        # Testfalten liegen zusammenhängend und in zeitlicher Reihenfolge.
        fold_bounds = np.array_split(indices, self.n_splits)
        for fold in fold_bounds:
            if len(fold) == 0:
                continue
            test_start, test_end = int(fold[0]), int(fold[-1])
            train_mask = np.ones(n, dtype=bool)
            train_mask[test_start : test_end + 1] = False

            if self.purge:
                # Alles entfernen, dessen Label-Zeitraum in den Test ragt.
                overlaps = (indices <= test_end) & (ends >= test_start)
                train_mask &= ~overlaps

            # Embargo hinter dem Test: die unmittelbar folgenden Balken sind
            # durch serielle Korrelation faktisch noch Teil des Tests.
            if embargo > 0:
                stop = min(n, test_end + 1 + embargo)
                train_mask[test_end + 1 : stop] = False

            train_idx = indices[train_mask]
            if len(train_idx) == 0:
                continue
            yield train_idx, fold

    def _ends(self, n: int) -> np.ndarray:
        """Letzter von jedem Beispiel beanspruchter Balken."""
        if self.exit_index is None:
            return np.arange(n)
        ends = np.asarray(
            self.exit_index.to_numpy() if isinstance(self.exit_index, pd.Series) else self.exit_index,
            dtype=float,
        )
        if len(ends) != n:
            ends = np.resize(ends, n)
        ends = np.where(np.isfinite(ends) & (ends >= 0), ends, np.arange(n))
        return np.maximum(ends, np.arange(n)).astype(int)


def purged_train_test_split(
    n: int,
    test_frac: float = 0.25,
    exit_index: "pd.Series | np.ndarray | None" = None,
    embargo_frac: float = 0.01,
) -> tuple[np.ndarray, np.ndarray]:
    """Einfache zeitliche Aufteilung: alt trainieren, neu testen - mit Sperrzone."""
    split = int(n * (1.0 - test_frac))
    embargo = int(n * embargo_frac)
    train_end = max(1, split - embargo)
    train = np.arange(0, train_end)
    test = np.arange(split, n)

    if exit_index is not None and len(train):
        ends = np.asarray(
            exit_index.to_numpy() if isinstance(exit_index, pd.Series) else exit_index, dtype=float
        )[:train_end]
        ends = np.where(np.isfinite(ends) & (ends >= 0), ends, np.arange(train_end))
        train = train[ends < split]
    return train, test


def walk_forward_windows(
    n: int,
    folds: int = 5,
    train_frac: float = 0.6,
    anchored: bool = True,
    embargo_frac: float = 0.01,
    exit_index: "pd.Series | np.ndarray | None" = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Vorwärtstest: wiederholt auf Vergangenem trainieren, auf Folgendem testen.

    Das ist die einzige Auswertung, die dem Livebetrieb wirklich entspricht -
    trainiert wird nur mit Daten, die zum jeweiligen Zeitpunkt vorlagen.

    `anchored=True` lässt das Trainingsfenster mitwachsen (mehr Daten),
    `anchored=False` schiebt ein Fenster fester Länge weiter (aktueller, passt
    sich Regimewechseln schneller an).
    """
    if folds < 1:
        raise ValueError("folds muss mindestens 1 sein")
    initial_train = int(n * train_frac)
    if initial_train < 50 or initial_train >= n:
        raise ValueError(
            f"Zu wenige Daten: {n} Zeilen ergeben bei train_frac={train_frac} kein sinnvolles Fenster"
        )
    remaining = n - initial_train
    test_size = max(1, remaining // folds)
    embargo = int(n * embargo_frac)

    ends = None
    if exit_index is not None:
        ends = np.asarray(
            exit_index.to_numpy() if isinstance(exit_index, pd.Series) else exit_index, dtype=float
        )
        ends = np.where(np.isfinite(ends) & (ends >= 0), ends, np.arange(len(ends)))

    windows: list[tuple[np.ndarray, np.ndarray]] = []
    for k in range(folds):
        test_start = initial_train + k * test_size
        test_end = min(n, test_start + test_size)
        if test_start >= n or test_end - test_start < 1:
            break
        train_end = max(1, test_start - embargo)
        train_start = 0 if anchored else max(0, train_end - initial_train)
        train = np.arange(train_start, train_end)
        if ends is not None and len(train):
            train = train[ends[train_start:train_end] < test_start]
        if len(train) < 50:
            continue
        windows.append((train, np.arange(test_start, test_end)))
    return windows


def check_no_overlap(
    train: np.ndarray, test: np.ndarray, exit_index: "pd.Series | np.ndarray | None" = None
) -> bool:
    """Prüft, dass kein Trainingsbeispiel in den Testzeitraum hineinreicht."""
    if len(train) == 0 or len(test) == 0:
        return True
    if set(train.tolist()) & set(test.tolist()):
        return False
    if exit_index is None:
        return True
    ends = np.asarray(
        exit_index.to_numpy() if isinstance(exit_index, pd.Series) else exit_index, dtype=float
    )
    lo, hi = int(test.min()), int(test.max())
    for i in train:
        end = ends[i] if i < len(ends) and np.isfinite(ends[i]) and ends[i] >= 0 else i
        if i <= hi and end >= lo:
            return False
    return True
