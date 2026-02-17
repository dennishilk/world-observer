from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.error import URLError


MODULE_PATH = Path("observers/area51-reachability/observer.py")
SPEC = importlib.util.spec_from_file_location("area51_observer", MODULE_PATH)
assert SPEC and SPEC.loader
area51_observer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = area51_observer
SPEC.loader.exec_module(area51_observer)


def test_current_bucket_start_for_past_day_is_bucket_aligned() -> None:
    bucket_minutes = 15
    target_day = date.today() - timedelta(days=1)

    bucket_start = area51_observer._current_bucket_start(target_day, bucket_minutes)

    assert bucket_start.hour == 23
    assert bucket_start.minute == 45
    assert bucket_start.minute % bucket_minutes == 0


def test_fetch_aircraft_retries_emit_stderr_only(monkeypatch, capsys) -> None:
    def _raise_url_error(*args, **kwargs):
        raise URLError("blocked")

    monkeypatch.setattr(area51_observer, "urlopen", _raise_url_error)
    monkeypatch.setattr(area51_observer.time_module, "sleep", lambda *_: None)

    result = area51_observer._fetch_aircraft("https://example.com", timeout_s=1)

    captured = capsys.readouterr()
    assert result is None
    assert "fetch attempt 1/3 failed" in captured.err
    assert captured.out == ""
