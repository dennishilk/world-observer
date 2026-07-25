#!/usr/bin/env python3
"""Normalize the USGS all-earthquakes past-day GeoJSON feed."""
from __future__ import annotations

import json
import math
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

OBSERVER = "earthquake-observer"
SCHEMA_VERSION = 1
FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
ATTRIBUTION_URL = "https://earthquake.usgs.gov/"
TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_ATTEMPTS = 3


class FeedError(ValueError):
    """The source could not produce a scientifically usable export."""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _epoch_ms(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _official_event_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443):
        return None
    host = (parsed.hostname or "").lower()
    return value if host == "earthquake.usgs.gov" or host.endswith(".earthquake.usgs.gov") else None


def _fetch_json(url: str = FEED_URL) -> tuple[Any, dict[str, Any]]:
    last_error = "unknown source error"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/geo+json, application/json", "User-Agent": "world-observer/earthquake-observer"},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", None)
                if status != 200:
                    raise FeedError(f"unexpected HTTP status {status}")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise FeedError("source response exceeds size limit")
                return json.loads(raw.decode("utf-8")), {
                    "api_attempts": attempt,
                    "retries": attempt - 1,
                    "http_status": status,
                }
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, FeedError) as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(0.25 * attempt)
    raise FeedError(f"USGS feed download failed after {MAX_ATTEMPTS} attempts: {last_error}")


def _normalize_feature(feature: Any, quality: dict[str, int]) -> dict[str, Any] | None:
    if not isinstance(feature, dict):
        quality["skipped_malformed_feature_count"] += 1
        return None
    properties = feature.get("properties")
    geometry = feature.get("geometry")
    if not isinstance(properties, dict) or not isinstance(geometry, dict):
        quality["skipped_malformed_feature_count"] += 1
        return None
    if properties.get("type") != "earthquake":
        quality["skipped_non_earthquake_count"] += 1
        return None
    event_id = _optional_text(feature.get("id"))
    if event_id is None:
        quality["skipped_missing_id_count"] += 1
        return None
    event_time = _epoch_ms(properties.get("time"))
    if event_time is None:
        quality["skipped_invalid_time_count"] += 1
        return None
    coordinates = geometry.get("coordinates")
    if geometry.get("type") != "Point" or not isinstance(coordinates, list) or len(coordinates) < 3:
        quality["skipped_invalid_coordinate_count"] += 1
        return None
    longitude, latitude, depth = (_number(coordinates[index]) for index in range(3))
    if longitude is None or latitude is None or not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        quality["skipped_invalid_coordinate_count"] += 1
        return None
    if depth is None or depth < 0:
        quality["skipped_invalid_depth_count"] += 1
        return None
    magnitude = _number(properties.get("mag"))
    if magnitude is None:
        quality["skipped_invalid_magnitude_count"] += 1
        return None
    updated = _epoch_ms(properties.get("updated"))
    return {
        "id": event_id,
        "time": _iso(event_time),
        "updated_at": _iso(updated) if updated else None,
        "latitude": latitude,
        "longitude": longitude,
        "depth_km": depth,
        "magnitude": magnitude,
        "magnitude_type": _optional_text(properties.get("magType")),
        "place": _optional_text(properties.get("place")) or "Region not provided",
        "event_url": _official_event_url(properties.get("url")),
        "review_status": _optional_text(properties.get("status")),
        "network": _optional_text(properties.get("net")),
        "_time": event_time,
        "_updated": updated,
    }


def _magnitude_distribution(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    definitions = [
        ("lt_1", "< 1.0", None, 1.0), ("1_to_lt_2", "1.0–< 2.0", 1.0, 2.0),
        ("2_to_lt_3", "2.0–< 3.0", 2.0, 3.0), ("3_to_lt_4", "3.0–< 4.0", 3.0, 4.0),
        ("4_to_lt_5", "4.0–< 5.0", 4.0, 5.0), ("5_to_lt_6", "5.0–< 6.0", 5.0, 6.0),
        ("gte_6", "≥ 6.0", 6.0, None),
    ]
    result = []
    for key, label, minimum, maximum in definitions:
        count = sum(1 for event in events if (minimum is None or event["magnitude"] >= minimum) and (maximum is None or event["magnitude"] < maximum))
        result.append({"key": key, "label": label, "minimum": minimum, "maximum": maximum, "count": count})
    return result


def _depth_distribution(events: list[dict[str, Any]]) -> dict[str, int]:
    result = {"shallow": 0, "intermediate": 0, "deep": 0, "out_of_range": 0, "total": len(events)}
    for event in events:
        depth = event["depth_km"]
        key = "shallow" if depth <= 70 else "intermediate" if depth <= 300 else "deep" if depth <= 700 else "out_of_range"
        result[key] += 1
    return result


def _activity(events: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    buckets = []
    for index in range(24):
        bucket_start = start + timedelta(hours=index)
        bucket_end = min(bucket_start + timedelta(hours=1), end)
        count = sum(1 for event in events if bucket_start <= event["_time"] < bucket_end)
        buckets.append({"start": _iso(bucket_start), "end": _iso(bucket_end), "count": count})
    return {"bucket_duration": "PT1H", "buckets": buckets}


def build_export(feed: Any, collected_at: datetime | None = None, diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(feed, dict) or feed.get("type") != "FeatureCollection" or not isinstance(feed.get("features"), list):
        raise FeedError("USGS document is not a valid GeoJSON FeatureCollection")
    collected_at = (collected_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    metadata = feed.get("metadata") if isinstance(feed.get("metadata"), dict) else {}
    source_generated = _epoch_ms(metadata.get("generated"))
    timing_fallback = source_generated is None
    window_end = source_generated or collected_at
    window_start = window_end - timedelta(hours=24)
    quality = {key: 0 for key in (
        "skipped_malformed_feature_count", "skipped_non_earthquake_count", "skipped_missing_id_count",
        "skipped_invalid_coordinate_count", "skipped_invalid_time_count", "skipped_invalid_depth_count",
        "skipped_invalid_magnitude_count", "duplicate_event_count", "outside_window_count",
    )}
    quality["source_feature_count"] = len(feed["features"])
    normalized = [event for feature in feed["features"] if (event := _normalize_feature(feature, quality)) is not None]
    deduplicated: dict[str, dict[str, Any]] = {}
    for event in normalized:
        previous = deduplicated.get(event["id"])
        if previous is not None:
            quality["duplicate_event_count"] += 1
        rank = (event["_updated"] or datetime.min.replace(tzinfo=timezone.utc), event["_time"], event["id"], json.dumps(event, sort_keys=True, default=str))
        previous_rank = None if previous is None else (previous["_updated"] or datetime.min.replace(tzinfo=timezone.utc), previous["_time"], previous["id"], json.dumps(previous, sort_keys=True, default=str))
        if previous_rank is None or rank > previous_rank:
            deduplicated[event["id"]] = event
    events = []
    for event in deduplicated.values():
        if window_start <= event["_time"] < window_end:
            events.append(event)
        else:
            quality["outside_window_count"] += 1
    events.sort(key=lambda item: (-item["_time"].timestamp(), item["id"]))
    quality["accepted_event_count"] = len(events)
    quality["skipped_feature_count"] = quality["source_feature_count"] - len(events) - quality["duplicate_event_count"]
    skipped = quality["skipped_feature_count"] > 0
    status = "partial" if timing_fallback else "empty" if not events else "partial" if skipped else "live"
    latest = events[0] if events else None
    largest = max(events, key=lambda item: (item["magnitude"], item["_time"], item["id"])) if events else None
    activity = _activity(events, window_start, window_end)
    public_events = [{key: value for key, value in event.items() if not key.startswith("_")} for event in events]
    return {
        "observer": OBSERVER, "schema_version": SCHEMA_VERSION, "status": status, "data_status": "ok" if status in {"live", "empty"} else "partial",
        "generated_at": _iso(collected_at), "collected_at": _iso(collected_at), "source_generated_at": _iso(source_generated) if source_generated else None,
        "source": {"name": "USGS Earthquake Hazards Program", "dataset": "USGS real-time GeoJSON summary feed — all earthquakes, past day", "url": FEED_URL, "attribution_url": ATTRIBUTION_URL},
        "window": {"label": "Past 24 hours", "start": _iso(window_start), "end": _iso(window_end), "timing_source": "collector" if timing_fallback else "source"},
        "summary": {"event_count": len(events), "latest_event_time": latest["time"] if latest else None, "latest_event_id": latest["id"] if latest else None, "largest_magnitude": largest["magnitude"] if largest else None, "largest_event_id": largest["id"] if largest else None},
        "events": public_events, "activity": activity, "magnitude_distribution": _magnitude_distribution(events), "depth_distribution": _depth_distribution(events),
        "context": {"status": "unavailable", "baseline_available": False, "classification": None, "message": "A verified historical comparison is not available yet."},
        "quality": quality, "diagnostics": diagnostics or {"api_attempts": 0, "retries": 0, "http_status": None},
        "notes": ["Catalog completeness varies by region, network coverage and magnitude.", "This export contains observations, not earthquake predictions."],
    }


def main() -> int:
    try:
        feed, diagnostics = _fetch_json()
        payload = build_export(feed, diagnostics=diagnostics)
    except FeedError as exc:
        print(f"earthquake-observer: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
