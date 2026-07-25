from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("earthquake_observer", ROOT / "observers/earthquake-observer/observer.py")
assert SPEC and SPEC.loader
earthquake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(earthquake)


def fixture(name: str = "mixed.geojson") -> dict:
    return json.loads((ROOT / "tests/fixtures/earthquake-observer" / name).read_text(encoding="utf-8"))


def feature(event_id: str, magnitude: float, depth: float, timestamp: int = 1767222000000, **properties):
    props = {"mag": magnitude, "time": timestamp, "updated": timestamp, "type": "earthquake", **properties}
    return {"type": "Feature", "id": event_id, "properties": props, "geometry": {"type": "Point", "coordinates": [123.5, -45.25, depth]}}


def feed(features, generated=1767225600000):
    return {"type": "FeatureCollection", "metadata": {"generated": generated}, "features": features}


def test_mixed_feed_normalizes_filters_deduplicates_and_sorts():
    result = earthquake.build_export(fixture(), datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert result["status"] == "partial"
    assert [item["id"] for item in result["events"]] == ["shallow", "intermediate", "deep", "duplicate"]
    assert result["events"][0]["longitude"] == 120.5
    assert result["events"][0]["latitude"] == -35.25
    assert result["events"][1]["place"] == "Region not provided"
    assert result["events"][1]["event_url"] is None
    assert result["events"][3]["magnitude"] == 4.0
    assert result["quality"]["duplicate_event_count"] == 1
    assert result["quality"]["outside_window_count"] == 1
    assert result["quality"]["skipped_non_earthquake_count"] == 1
    assert result["summary"] == {"event_count": 4, "latest_event_time": "2025-12-31T23:00:00.000Z", "latest_event_id": "shallow", "largest_magnitude": 6.0, "largest_event_id": "deep"}


def test_magnitude_boundaries_and_depth_boundaries():
    magnitudes = [-0.5, 1, 2, 3, 4, 5, 6]
    depths = [0, 70, 70.1, 300, 300.1, 700, 700.1]
    result = earthquake.build_export(feed([feature(str(i), mag, depths[i]) for i, mag in enumerate(magnitudes)]))
    assert [item["count"] for item in result["magnitude_distribution"]] == [1, 1, 1, 1, 1, 1, 1]
    assert result["depth_distribution"] == {"shallow": 2, "intermediate": 2, "deep": 2, "out_of_range": 1, "total": 7}


def test_activity_has_24_half_open_buckets_including_empty_buckets():
    # Window is [2025-12-31T00:00Z, 2026-01-01T00:00Z).
    features = [feature("start", 1, 1, 1767139200000), feature("boundary", 1, 1, 1767142800000), feature("end", 1, 1, 1767225600000)]
    result = earthquake.build_export(feed(features))
    buckets = result["activity"]["buckets"]
    assert len(buckets) == 24
    assert [bucket["count"] for bucket in buckets[:2]] == [1, 1]
    assert sum(bucket["count"] for bucket in buckets) == 2
    assert result["quality"]["outside_window_count"] == 1


def test_empty_and_missing_source_time_statuses():
    empty = earthquake.build_export(feed([]))
    assert empty["status"] == "empty"
    assert empty["summary"]["event_count"] == 0
    fallback = earthquake.build_export({"type": "FeatureCollection", "metadata": {"generated": "bad"}, "features": []}, datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert fallback["status"] == "partial"
    assert fallback["data_status"] == "partial"
    assert fallback["window"]["timing_source"] == "collector"
    assert fallback["source_generated_at"] is None


@pytest.mark.parametrize("document", [None, [], {}, {"type": "FeatureCollection", "features": {}}, {"type": "Other", "features": []}])
def test_malformed_top_level_rejected(document):
    with pytest.raises(earthquake.FeedError):
        earthquake.build_export(document)


def test_invalid_longitude_and_https_host_are_rejected_independently():
    bad = feature("bad", 1, 1, url="https://earthquake.usgs.gov.evil.test/event")
    bad["geometry"]["coordinates"][0] = 181
    valid = feature("valid", 1, 1, url="https://earthquake.usgs.gov/earthquakes/eventpage/valid")
    result = earthquake.build_export(feed([bad, valid]))
    assert result["quality"]["skipped_invalid_coordinate_count"] == 1
    assert result["events"][0]["event_url"].startswith("https://earthquake.usgs.gov/")


def test_deterministic_largest_tie_breaking_and_serialization():
    result = earthquake.build_export(feed([feature("a", 5, 1), feature("b", 5, 1)]))
    assert result["summary"]["largest_event_id"] == "b"
    encoded = json.dumps(result, allow_nan=False, sort_keys=True)
    assert "prediction_probability" not in encoded
    assert result["context"]["classification"] is None
    assert set(result["events"][0]) == {"id", "time", "updated_at", "latitude", "longitude", "depth_km", "magnitude", "magnitude_type", "place", "event_url", "review_status", "network"}


def test_dashboard_export_and_publisher_paths_include_earthquake(tmp_path):
    from scripts.export_dashboard import export_dashboard
    from scripts.publish_dashboard_to_pages import publish_dashboard_to_pages

    latest = tmp_path / "latest"
    latest.mkdir()
    (latest / "earthquake-observer.json").write_text(json.dumps(earthquake.build_export(feed([]))), encoding="utf-8")
    dashboard = tmp_path / "dashboard"
    export_dashboard(latest_dir=latest, dashboard_dir=dashboard, daily_dir=tmp_path / "daily", heartbeat_dir=tmp_path / "heartbeat")
    assert (dashboard / "latest/earthquake-observer.json").is_file()
    pages = tmp_path / "dennishilk.github.io"
    pages.mkdir()
    (pages / "index.html").write_text("home", encoding="utf-8")
    (pages / "world-observer.html").write_text("observer", encoding="utf-8")
    publish_dashboard_to_pages(pages, dashboard)
    assert (pages / "world-observer/dashboard/latest/earthquake-observer.json").is_file()


def test_daily_latest_preserves_last_good_earthquake_on_error(tmp_path, monkeypatch):
    from scripts import run_daily

    daily = tmp_path / "data/daily/2026-01-01"
    latest = tmp_path / "data/latest"
    daily.mkdir(parents=True)
    latest.mkdir(parents=True)
    known_good = earthquake.build_export(feed([feature("good", 2, 10)]))
    (latest / "earthquake-observer.json").write_text(json.dumps(known_good), encoding="utf-8")
    (daily / "earthquake-observer.json").write_text(json.dumps({"observer": "earthquake-observer", "status": "error", "data_status": "error"}), encoding="utf-8")
    monkeypatch.setattr(run_daily, "_repo_root", lambda: tmp_path)
    run_daily._update_latest(daily)
    assert json.loads((latest / "earthquake-observer.json").read_text(encoding="utf-8"))["status"] == "live"
