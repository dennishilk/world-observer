from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import run_daily


def _write_observer_payload(daily_dir: Path, observer: str, payload: object) -> None:
    (daily_dir / f"{observer}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_run_meta_observer_good_case(tmp_path, monkeypatch) -> None:
    date_str = "2099-01-01"
    daily_dir = tmp_path / "data" / "daily" / date_str
    daily_dir.mkdir(parents=True)
    observers_dir = tmp_path / "observers"
    observers_dir.mkdir(parents=True)

    for observer in run_daily.OBSERVERS:
        (observers_dir / observer).mkdir(parents=True)
        (observers_dir / observer / "observer.py").write_text("print('{}')\n", encoding="utf-8")
        _write_observer_payload(daily_dir, observer, {"observer": observer, "value": 1})

    monkeypatch.setattr(run_daily, "_repo_root", lambda: Path.cwd())

    ok, detail = run_daily._run_meta_observer(date_str, daily_dir)
    assert ok is True
    assert detail == "ok"

    summary = json.loads((daily_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["observers_run"] == sorted(run_daily.OBSERVERS)
    assert summary["observers_missing"] == []


def test_run_meta_observer_missing_and_invalid(tmp_path, monkeypatch) -> None:
    date_str = "2099-01-02"
    daily_dir = tmp_path / "data" / "daily" / date_str
    daily_dir.mkdir(parents=True)
    observers_dir = tmp_path / "observers"
    observers_dir.mkdir(parents=True)

    observers = sorted(run_daily.OBSERVERS)
    missing_observer = observers[0]
    invalid_observer = observers[1]
    for observer in observers:
        (observers_dir / observer).mkdir(parents=True)
        (observers_dir / observer / "observer.py").write_text("print('{}')\n", encoding="utf-8")

    for observer in observers[2:]:
        _write_observer_payload(daily_dir, observer, {"observer": observer, "status": "ok"})

    # exists but invalid root (list) -> should count as missing
    _write_observer_payload(daily_dir, invalid_observer, [{"bad": True}])

    monkeypatch.setattr(run_daily, "_repo_root", lambda: Path.cwd())

    ok, detail = run_daily._run_meta_observer(date_str, daily_dir)
    assert ok is True
    assert detail == "ok"

    summary = json.loads((daily_dir / "summary.json").read_text(encoding="utf-8"))
    assert missing_observer in summary["observers_missing"]
    assert invalid_observer in summary["observers_missing"]
    assert missing_observer not in summary["observers_run"]
    assert invalid_observer not in summary["observers_run"]


def test_run_meta_observer_rejects_invalid_meta_stdout(tmp_path, monkeypatch) -> None:
    date_str = "2099-01-03"
    daily_dir = tmp_path / "data" / "daily" / date_str
    daily_dir.mkdir(parents=True)

    class DummyCompletedProcess:
        def __init__(self):
            self.returncode = 0
            self.stdout = "not-json"
            self.stderr = ""

    def _fake_run(*args, **kwargs):
        return DummyCompletedProcess()

    monkeypatch.setattr(run_daily, "_repo_root", lambda: Path.cwd())
    monkeypatch.setattr(run_daily.subprocess, "run", _fake_run)

    ok, detail = run_daily._run_meta_observer(date_str, daily_dir)
    assert ok is False
    assert detail == "invalid JSON"
    assert not (daily_dir / "summary.json").exists()
