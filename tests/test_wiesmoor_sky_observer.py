from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
OBSERVER_PATH = REPO_ROOT / "observers" / "wiesmoor-sky-observer" / "observer.py"


def _load_observer():
    spec = importlib.util.spec_from_file_location("wiesmoor_sky_observer", OBSERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_wiesmoor_sky_observer_calculates_required_geometry_without_weather_api(monkeypatch) -> None:
    observer = _load_observer()
    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", "2026-01-15")
    monkeypatch.setenv("WORLD_OBSERVER_NOW_UTC", "2026-01-15T21:00:00Z")

    payload = observer.build_payload()

    assert payload["observer"] == "wiesmoor-sky-observer"
    assert payload["status"] == "ok"
    assert payload["source"]["network_dependency"] is False
    assert payload["source"]["weather_api_dependency"] is False
    assert "Open-Meteo" not in str(payload)
    assert payload["disclaimer"] == observer.DISCLAIMER
    assert "clear sky" not in payload["summary"].lower()
    assert "Astronomical darkness window" in payload["summary"]
    for key in ("sunrise", "sunset", "civil_twilight_start", "civil_twilight_end", "nautical_twilight_start", "nautical_twilight_end", "astronomical_twilight_start", "astronomical_twilight_end", "current_altitude_degrees"):
        assert key in payload["sun"]
    for key in ("phase_name", "illumination_percent", "age_days", "moonrise", "moonset", "current_altitude_degrees"):
        assert key in payload["moon"]
    assert payload["astronomical_night"]["available"] is True
    assert payload["astronomical_night"]["best_astronomical_darkness_window_tonight"]["start"]
    assert payload["astronomical_night"]["moon_interference_classification"] in {"low", "moderate", "high"}
    assert payload["astronomical_night"]["night_quality_classification"] in {"excellent", "good", "limited", "no astronomical darkness"}
