from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import run_daily
from scripts.export_dashboard import _internet_status_fields

REPO_ROOT = Path(__file__).resolve().parents[1]
OBSERVER_PATH = REPO_ROOT / "observers" / "wiesmoor-weather" / "observer.py"


def _load_observer():
    spec = importlib.util.spec_from_file_location("wiesmoor_weather_observer", OBSERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _api_payload(temp: float = 18.5) -> dict[str, Any]:
    hours = [f"2026-07-08T{hour:02d}:00" for hour in range(24)]
    return {
        "current": {"time": "2026-07-08T10:00", "temperature_2m": temp, "apparent_temperature": temp, "relative_humidity_2m": 70, "precipitation": 0, "rain": 0, "cloud_cover": 20, "pressure_msl": 1010, "surface_pressure": 1008, "wind_speed_10m": 12, "wind_direction_10m": 270, "wind_gusts_10m": 24},
        "hourly": {"time": hours, **{field: [1] * 24 for field in ("temperature_2m", "apparent_temperature", "relative_humidity_2m", "precipitation", "rain", "cloud_cover", "pressure_msl", "surface_pressure", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation_probability")}},
        "daily": {"time": ["2026-07-08"], "temperature_2m_max": [22], "temperature_2m_min": [12], "precipitation_sum": [0], "precipitation_probability_max": [10], "wind_gusts_10m_max": [30], "sunrise": ["2026-07-08T05:00"], "sunset": ["2026-07-08T22:00"]},
    }


def test_temporary_503_preserves_last_successful_weather_data(tmp_path, monkeypatch) -> None:
    observer = _load_observer()
    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", "2026-07-08")
    latest = tmp_path / "latest.json"
    monkeypatch.setenv("WORLD_OBSERVER_WIESMOOR_LATEST_PATH", str(latest))
    monkeypatch.setattr(observer.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(observer, "_fetch_json", lambda _url: (_api_payload(18.5), {"url": _url, "status": "ok", "api_attempts": 1, "retries": 0, "http_status": 200, "attempts": [{"attempt": 1, "http_status": 200, "ok": True, "error": None}]}))

    successful = observer.build_payload()
    latest.write_text(json.dumps(successful), encoding="utf-8")

    failure_diag = {"url": "https://example.invalid", "status": "unavailable", "temporary_failure": True, "failed_at_utc": "2026-07-08T11:00:00Z", "api_attempts": 3, "retries": 2, "http_status": 503, "attempts": [{"attempt": 1, "http_status": 503, "ok": False, "error": "HTTP 503"}, {"attempt": 2, "http_status": 503, "ok": False, "error": "HTTP 503"}, {"attempt": 3, "http_status": 503, "ok": False, "error": "HTTP 503"}]}
    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", "2026-07-09")
    monkeypatch.setattr(observer, "_fetch_json", lambda _url: (None, {**failure_diag, "url": _url}))

    stale = observer.build_payload()

    assert stale["status"] == "degraded"
    assert stale["data_status"] == "partial"
    assert stale["stale"] is True
    assert stale["date"] == successful["date"]
    assert stale["collected_at_utc"] == successful["collected_at_utc"]
    assert stale["current"]["temperature_2m"] == 18.5
    assert stale["diagnostics"]["http_status"] == 503
    assert stale["diagnostics"]["api_attempts"] == 3
    assert stale["diagnostics"]["retries"] == 2
    assert stale["diagnostics"]["latest_refresh_failed_at_utc"] == "2026-07-08T11:00:00Z"


def test_recovery_replaces_stale_data_and_restores_ok(tmp_path, monkeypatch) -> None:
    observer = _load_observer()
    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", "2026-07-09")
    monkeypatch.setenv("WORLD_OBSERVER_WIESMOOR_LATEST_PATH", str(tmp_path / "latest.json"))
    monkeypatch.setattr(observer, "_fetch_json", lambda _url: (_api_payload(20.25), {"url": _url, "status": "ok", "api_attempts": 1, "retries": 0, "http_status": 200, "attempts": []}))

    payload = observer.build_payload()

    assert payload["status"] == "ok"
    assert payload["data_status"] == "ok"
    assert "stale" not in payload
    assert payload["current"]["temperature_2m"] == 20.25
    assert payload["diagnostics"]["http_status"] == 200


def test_valid_weather_data_cannot_remain_data_status_unavailable() -> None:
    payload = {"observer": "wiesmoor-weather", "status": "ok", "data_status": "unavailable", "current": {"temperature_2m": 18}, "today": {"temperature_2m_max": 22}, "hourly": {"time": ["2026-07-08T10:00"]}}
    normalized = run_daily._normalize_payload("wiesmoor-weather", payload, run_daily.logging.getLogger("test"))
    assert normalized["data_status"] == "ok"
    assert _internet_status_fields("wiesmoor-weather", normalized) == ("ok", "ok")


def test_invalid_success_payload_is_unavailable_not_fresh_success(monkeypatch) -> None:
    observer = _load_observer()
    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", "2026-07-08")
    monkeypatch.setenv("WORLD_OBSERVER_WIESMOOR_LATEST_PATH", "/tmp/does-not-exist-wiesmoor.json")
    monkeypatch.setattr(observer, "_fetch_json", lambda _url: ({"current": {}, "hourly": {}, "daily": {}}, {"url": _url, "status": "ok", "api_attempts": 1, "retries": 0, "http_status": 200, "attempts": []}))

    payload = observer.build_payload()

    assert payload["status"] == "unavailable"
    assert payload["data_status"] == "unavailable"
    assert payload["current"]
