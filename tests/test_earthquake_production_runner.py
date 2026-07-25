from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_earthquake_observer_production.sh"


def _environment(tmp_path: Path, observer: Path, hour: str = "2026-07-25T12") -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHON": sys.executable,
            "WORLD_OBSERVER_EARTHQUAKE_OBSERVER": str(observer),
            "WORLD_OBSERVER_LATEST_DIR": str(tmp_path / "latest"),
            "WORLD_OBSERVER_DASHBOARD_DIR": str(tmp_path / "dashboard"),
            "WORLD_OBSERVER_EARTHQUAKE_HOURLY_DIR": str(tmp_path / "hourly"),
            "WORLD_OBSERVER_STATE_DIR": str(tmp_path / "state"),
            "WORLD_OBSERVER_HOUR_UTC": hour,
        }
    )
    return environment


def _observer(tmp_path: Path, payload: object, *, sleep: float = 0) -> Path:
    path = tmp_path / "observer.py"
    path.write_text(
        "import json, time\n"
        f"time.sleep({sleep!r})\n"
        f"print(json.dumps({payload!r}))\n",
        encoding="utf-8",
    )
    return path


def _run(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(RUNNER)], cwd=ROOT, env=environment, text=True, capture_output=True)


def test_valid_output_updates_latest_snapshot_and_dashboard(tmp_path: Path) -> None:
    payload = {"observer": "earthquake-observer", "status": "live", "events": [{"id": "test"}]}
    result = _run(_environment(tmp_path, _observer(tmp_path, payload)))

    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "latest/earthquake-observer.json").read_text()) == payload
    assert json.loads((tmp_path / "hourly/2026-07-25T12.json").read_text()) == payload
    assert json.loads((tmp_path / "dashboard/latest/earthquake-observer.json").read_text()) == payload


def test_invalid_json_and_error_payload_preserve_latest(tmp_path: Path) -> None:
    latest = tmp_path / "latest/earthquake-observer.json"
    latest.parent.mkdir()
    known_good = '{"events":[{"id":"known-good"}]}\n'
    latest.write_text(known_good, encoding="utf-8")
    malformed = tmp_path / "malformed.py"
    malformed.write_text("print('{bad json')\n", encoding="utf-8")

    assert _run(_environment(tmp_path, malformed)).returncode != 0
    assert latest.read_text(encoding="utf-8") == known_good
    error = _observer(tmp_path, {"status": "error", "events": []})
    assert _run(_environment(tmp_path, error)).returncode != 0
    assert latest.read_text(encoding="utf-8") == known_good


def test_retention_is_scoped_to_old_earthquake_snapshots(tmp_path: Path) -> None:
    hourly = tmp_path / "hourly"
    hourly.mkdir()
    old = hourly / "2026-07-01T01.json"
    recent = hourly / "2026-07-24T01.json"
    unrelated = tmp_path / "other-observer/2026-07-01T01.json"
    unrelated.parent.mkdir()
    for path in (old, recent, unrelated):
        path.write_text("{}", encoding="utf-8")
    eight_days_ago = time.time() - 8 * 24 * 60 * 60
    os.utime(old, (eight_days_ago, eight_days_ago))
    os.utime(unrelated, (eight_days_ago, eight_days_ago))

    result = _run(_environment(tmp_path, _observer(tmp_path, {"events": []})))

    assert result.returncode == 0, result.stderr
    assert not old.exists()
    assert recent.exists()
    assert unrelated.exists()
    assert "removed 1 snapshot(s)" in result.stdout


def test_overlapping_execution_is_prevented(tmp_path: Path) -> None:
    environment = _environment(tmp_path, _observer(tmp_path, {"events": []}, sleep=1.5))
    first = subprocess.Popen([str(RUNNER)], cwd=ROOT, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lock = tmp_path / "state/earthquake_observer.lock"
    for _ in range(50):
        if lock.exists():
            break
        time.sleep(0.02)

    second = _run(environment)
    first_stdout, first_stderr = first.communicate(timeout=10)

    assert first.returncode == 0, first_stderr
    assert second.returncode == 0
    assert "another Earthquake Observer run is active" in second.stdout
    assert "updated latest" in first_stdout
