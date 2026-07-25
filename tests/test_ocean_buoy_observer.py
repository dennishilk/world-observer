from __future__ import annotations
import importlib.util, json
from datetime import datetime, timezone
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ocean_buoy", ROOT / "observers/ocean-buoy-observer/observer.py")
assert SPEC and SPEC.loader
buoy = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(buoy)
TEXT = (ROOT / "tests/fixtures/ocean-buoy-observer/latest_obs.txt").read_text()
NOW = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)


def test_parse_normalize_deduplicate_order_and_partial_rows():
    result = buoy.build_export(TEXT, NOW)
    assert [s["id"] for s in result["stations"]] == ["41001", "46001"]
    assert result["quality"] == {"source_rows": 4, "accepted_stations": 2, "skipped_rows": 1, "duplicate_rows": 1}
    first = result["stations"][0]
    assert first["observed_at"] == "2026-07-25T11:50:00Z"
    assert first["measurements"]["wave_height_m"] == 2.5
    assert first["measurements"]["water_level_m"] is None
    assert first["measurements"]["visibility_km"] == 18.52
    assert first["freshness"] == "fresh"
    assert result["stations"][1]["freshness"] == "aging"
    buoy.validate_payload(result)


def test_conversions_and_classifications():
    assert buoy.knots_to_m_s(10) == 5.144
    assert buoy.nautical_miles_to_km(10) == 18.52
    assert buoy.feet_to_metres(10) == 3.048
    assert buoy.wave_state(0) == "calm" and buoy.wave_state(3) == "rough" and buoy.wave_state(None) is None
    assert buoy.wind_state(0) == "calm" and buoy.wind_state(20) == "gale"
    assert buoy.freshness(3) == "fresh" and buoy.freshness(4) == "aging" and buoy.freshness(7) == "stale"


@pytest.mark.parametrize(("name", "lat", "lon", "expected"), (
    ("offshore California", 34.0, -123.0, "North Pacific"),
    ("Monterey Bay", 36.8, -122.1, "North Pacific"),
    ("offshore Texas", 27.5, -96.5, "Gulf of Mexico"),
    ("offshore Louisiana", 28.5, -90.0, "Gulf of Mexico"),
    ("Lake Superior", 47.5, -87.5, "Great Lakes"),
    ("Lake Michigan", 44.0, -87.0, "Great Lakes"),
    ("Lake Erie", 42.2, -81.2, "Great Lakes"),
    ("offshore New York", 40.5, -72.5, "North Atlantic"),
    ("Florida Atlantic coast", 27.0, -79.8, "North Atlantic"),
    ("Caribbean Sea", 15.0, -75.0, "Caribbean"),
    ("Indian Ocean", -20.0, 80.0, "Indian Ocean"),
    ("South Pacific", -30.0, -120.0, "South Pacific"),
    ("South Atlantic", -30.0, -30.0, "South Atlantic"),
    ("Arctic threshold", 60.0, -30.0, "Arctic"),
    ("Southern Ocean threshold", -60.0, 80.0, "Southern Ocean"),
    ("inland Nevada", 39.0, -117.0, "Inland / Other"),
    ("inland Colorado", 39.0, -105.5, "Inland / Other"),
))
def test_region_classification(name, lat, lon, expected):
    assert buoy.region(lat, lon) == expected, name


@pytest.mark.parametrize("text", ["", "source error", "#STN LAT\n#unit deg\nBAD 91"])
def test_malformed_and_all_invalid_feeds_rejected(text):
    with pytest.raises(buoy.FeedError): buoy.build_export(text, NOW)


def test_validator_rejects_bad_coordinates_duplicates_empty_and_errors():
    payload = buoy.build_export(TEXT, NOW)
    for mutate in (
        lambda p: p.update(stations=[]),
        lambda p: p["stations"].append(p["stations"][0]),
        lambda p: p["stations"][0].update(latitude=91),
        lambda p: p["observer"].update(data_status="error"),
    ):
        candidate = json.loads(json.dumps(payload)); mutate(candidate)
        with pytest.raises(buoy.FeedError): buoy.validate_payload(candidate)


def test_implausible_measurement_is_null_not_zero():
    text = TEXT.replace("2.5 9.0", "99.0 9.0")
    station = buoy.build_export(text, NOW)["stations"][0]
    assert station["measurements"]["wave_height_m"] is None
