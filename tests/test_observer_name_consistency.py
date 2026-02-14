from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_daily import OBSERVERS


def _observer_dirs_with_entrypoints() -> set[str]:
    observers_dir = Path("observers")
    return {
        path.name
        for path in observers_dir.iterdir()
        if path.is_dir() and path.name != "world-observer-meta" and (path / "observer.py").exists()
    }


def test_observer_name_consistency() -> None:
    observed = _observer_dirs_with_entrypoints()
    configured = set(OBSERVERS)

    assert observed == configured


def test_observer_names_are_valid_unique_and_sorted() -> None:
    assert OBSERVERS == sorted(OBSERVERS)
    assert len(OBSERVERS) == len(set(OBSERVERS))
    assert all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) for name in OBSERVERS)
