from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import run_daily
from scripts import run_daily_cron


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


def test_run_observer_timeout_writes_structured_error_and_can_continue(tmp_path, monkeypatch) -> None:
    date_str = "2099-01-04"
    daily_dir = tmp_path / "data" / "daily" / date_str
    daily_dir.mkdir(parents=True)
    observers_root = tmp_path / "observers"
    hanging_dir = observers_root / "hanging-observer"
    hanging_dir.mkdir(parents=True)
    (hanging_dir / "observer.py").write_text("import time; time.sleep(999)\n", encoding="utf-8")
    ok_dir = observers_root / "ok-observer"
    ok_dir.mkdir(parents=True)
    (ok_dir / "observer.py").write_text("print('{}')\n", encoding="utf-8")

    calls = []

    class DummyCompletedProcess:
        returncode = 0
        stdout = '{"observer":"ok-observer","date_utc":"2099-01-04"}'
        stderr = ""

    def _fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if "hanging-observer" in str(args[1]):
            raise run_daily.subprocess.TimeoutExpired(args, kwargs.get("timeout"), stderr="still running")
        return DummyCompletedProcess()

    monkeypatch.setattr(run_daily, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(run_daily.subprocess, "run", _fake_run)
    monkeypatch.setenv("WORLD_OBSERVER_OBSERVER_TIMEOUT_S", "3")

    ok, detail = run_daily._run_observer("hanging-observer", date_str, daily_dir)
    assert ok is False
    assert detail == "timeout 3s"
    payload = json.loads((daily_dir / "hanging-observer.json").read_text(encoding="utf-8"))
    assert payload["status"] == "error"
    assert payload["data_status"] == "error"
    assert payload["diagnostics"]["timeout"] is True
    assert payload["diagnostics"]["timeout_s"] == 3.0

    ok, detail = run_daily._run_observer("ok-observer", date_str, daily_dir)
    assert ok is True
    assert detail == "ok"
    assert json.loads((daily_dir / "ok-observer.json").read_text(encoding="utf-8"))["observer"] == "ok-observer"
    assert calls[0][1]["timeout"] == 3.0
    assert calls[1][1]["timeout"] == 3.0


def test_run_observer_overrides_stale_world_observer_date_env(tmp_path, monkeypatch) -> None:
    date_str = "2026-07-02"
    stale_date = "2026-07-01"
    daily_dir = tmp_path / "data" / "daily" / date_str
    daily_dir.mkdir(parents=True)
    observer_dir = tmp_path / "observers" / "date-echo"
    observer_dir.mkdir(parents=True)
    observer_dir.joinpath("observer.py").write_text(
        "import json, os; print(json.dumps({'observer': 'date-echo', 'date_utc': os.environ['WORLD_OBSERVER_DATE_UTC']}))\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(run_daily, "_repo_root", lambda: tmp_path)
    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", stale_date)

    ok, detail = run_daily._run_observer("date-echo", date_str, daily_dir)

    assert ok is True
    assert detail == "ok"
    payload = json.loads((daily_dir / "date-echo.json").read_text(encoding="utf-8"))
    assert payload["date_utc"] == date_str


def test_run_daily_default_uses_current_utc_date(monkeypatch) -> None:
    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            from datetime import datetime

            return datetime(2026, 7, 2, 8, 16, tzinfo=tz)

    monkeypatch.setattr(run_daily, "datetime", FixedDateTime)

    assert run_daily._current_date_utc() == "2026-07-02"


def test_run_daily_cron_default_uses_current_utc_date(monkeypatch) -> None:
    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            from datetime import datetime

            return datetime(2026, 7, 2, 8, 16, tzinfo=tz)

        @classmethod
        def strptime(cls, value, fmt):
            from datetime import datetime

            return datetime.strptime(value, fmt)

    monkeypatch.setattr(run_daily_cron, "datetime", FixedDateTime)

    assert run_daily_cron._target_date(None) == "2026-07-02"
    assert run_daily_cron._target_date("2026-07-01") == "2026-07-01"


def test_run_daily_cron_script_env_replaces_stale_date(monkeypatch, tmp_path) -> None:
    calls = []

    class DummyCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, *, env=None):
        calls.append((args, env))
        return DummyCompletedProcess()

    class DummyLogger:
        def info(self, *args, **kwargs):
            pass

    monkeypatch.setattr(run_daily_cron, "_run", fake_run)
    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", "2026-07-01")

    run_daily_cron._run_python_script(tmp_path / "script.py", [], DummyLogger(), "2026-07-02")

    assert calls[0][1]["WORLD_OBSERVER_DATE_UTC"] == "2026-07-02"
