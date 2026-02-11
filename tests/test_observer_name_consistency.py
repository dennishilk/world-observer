from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_daily import OBSERVERS


def _load_meta_observer_module():
    module_path = REPO_ROOT / "observers" / "world-observer-meta" / "observer.py"
    spec = importlib.util.spec_from_file_location("world_observer_meta_observer", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load world-observer-meta observer module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_observer_name_consistency(tmp_path, monkeypatch):
    test_date = "2099-01-01"
    fake_repo = tmp_path / "repo"
    daily_dir = fake_repo / "data" / "daily" / test_date
    observers_dir = fake_repo / "observers"

    daily_dir.mkdir(parents=True)
    observers_dir.mkdir(parents=True)

    for observer in OBSERVERS:
        (observers_dir / observer).mkdir(parents=True)
        payload = {
            "observer": observer,
            "date": test_date,
            "status": "ok",
        }
        (daily_dir / f"{observer}.json").write_text(json.dumps(payload), encoding="utf-8")

    (observers_dir / "world-observer-meta").mkdir(parents=True)

    expected_artifacts = {f"{observer}.json" for observer in OBSERVERS}
    generated_artifacts = {p.name for p in daily_dir.glob("*.json")}
    assert generated_artifacts == expected_artifacts

    assert all(not name.endswith("-watcher") for name in OBSERVERS)

    meta_observer = _load_meta_observer_module()
    monkeypatch.setattr(meta_observer, "_repo_root", lambda: fake_repo)

    summary = meta_observer.run(test_date)
    observers_run = set(summary["observers_run"])
    observers_missing = set(summary["observers_missing"])
    expected_names = set(OBSERVERS)

    assert observers_run == expected_names
    assert observers_missing == set()

    reported_names = observers_run | observers_missing
    assert reported_names == expected_names

    unknown_names = reported_names - expected_names
    assert not unknown_names

    legacy_watcher_names = [name for name in reported_names if name.endswith("-watcher")]
    assert not legacy_watcher_names

    summary_payload = json.loads((daily_dir / "summary.json").read_text(encoding="utf-8"))
    assert set(summary_payload["observers_run"]) == expected_names
    assert summary_payload["observers_missing"] == []
