"""Live WSV PEGELONLINE REST API v2 adapter for East Frisia water levels."""
from __future__ import annotations

import json
import math
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from config import SOURCES, WSV_CONFIG
from models import AdapterResult

ADAPTER_ID = "wsv"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("malformed timestamp")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("malformed timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _finite_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("measurement value is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("measurement value is not finite")
    return number


def _get_json(url: str, diagnostics: dict[str, Any]) -> Any:
    last_error = None
    for attempt in range(WSV_CONFIG["max_retries"] + 1):
        diagnostics["api_attempts"] += 1
        if attempt:
            diagnostics["retries"] += 1
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "world-observer/1.0"})
            with urllib.request.urlopen(req, timeout=WSV_CONFIG["timeout_seconds"]) as response:
                status = getattr(response, "status", response.getcode())
                if status != 200:
                    raise RuntimeError(f"HTTP status {status}")
                try:
                    return json.loads(response.read().decode("utf-8"))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"malformed JSON: {exc}") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, RuntimeError, ValueError) as exc:
            last_error = exc
    raise RuntimeError(str(last_error))


def _unavailable(diagnostics: dict[str, Any], message: str) -> AdapterResult:
    diagnostics.setdefault("adapter_errors", []).append(message)
    return AdapterResult(
        adapter=ADAPTER_ID,
        status="unavailable",
        data_status="unavailable",
        observations={},
        diagnostics=diagnostics,
        source_research=SOURCES[ADAPTER_ID],
    )


def _extract_station(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("station JSON is not an object")
    if payload.get("uuid") != WSV_CONFIG["station_uuid"]:
        raise ValueError("station UUID mismatch")
    return payload


def _find_timeseries(station: dict[str, Any]) -> dict[str, Any]:
    series = station.get("timeseries")
    if not isinstance(series, list):
        raise ValueError("station timeseries missing")
    for item in series:
        if isinstance(item, dict) and item.get("shortname") == WSV_CONFIG["timeseries_shortname"]:
            if item.get("unit") not in WSV_CONFIG["expected_units"]:
                raise ValueError(f"unexpected unit {item.get('unit')!r}")
            return item
    raise ValueError("expected water-level timeseries missing")


def _valid_measurements(payload: Any) -> list[tuple[datetime, float]]:
    if not isinstance(payload, list):
        raise ValueError("measurements JSON is not a list")
    values: list[tuple[datetime, float]] = []
    seen: set[datetime] = set()
    previous: datetime | None = None
    for item in payload:
        if not isinstance(item, dict) or item.get("value") is None:
            continue
        timestamp = _parse_timestamp(item.get("timestamp"))
        value = _finite_number(item.get("value"))
        if timestamp in seen:
            raise ValueError("duplicate measurement timestamp")
        if previous is not None and timestamp < previous:
            raise ValueError("measurements are not chronological")
        seen.add(timestamp)
        previous = timestamp
        values.append((timestamp, value))
    if not values:
        raise ValueError("no valid measurement exists")
    return values


def _trend(values: list[tuple[datetime, float]], unit: str) -> dict[str, Any]:
    minimum = WSV_CONFIG["trend_minimum_values"]
    if len(values) < minimum:
        return {"direction": "unavailable", "valid_measurement_count": len(values), "minimum_valid_measurements": minimum}
    first_ts, first_value = values[0]
    latest_ts, latest_value = values[-1]
    change = latest_value - first_value
    threshold = WSV_CONFIG["stable_threshold_by_unit"][unit]
    if abs(change) <= threshold:
        direction = "stable"
    elif change > 0:
        direction = "rising"
    else:
        direction = "falling"
    return {
        "direction": direction,
        "first_valid_value": first_value,
        "latest_valid_value": latest_value,
        "signed_change": change,
        "window_start_utc": _iso_z(first_ts),
        "window_end_utc": _iso_z(latest_ts),
        "valid_measurement_count": len(values),
        "minimum_valid_measurements": minimum,
        "stable_threshold": threshold,
        "unit": unit,
    }


def fetch(now: datetime | None = None) -> AdapterResult:
    """Fetch station metadata and recent water-level measurements from PEGELONLINE."""
    now_utc = (now or _utc_now()).astimezone(timezone.utc)
    base = WSV_CONFIG["base_url"].rstrip("/")
    station_url = f"{base}/stations/{WSV_CONFIG['station_uuid']}.json?includeTimeseries=true&includeCurrentMeasurement=true"
    end = _iso_z(now_utc)
    start = _iso_z(now_utc - timedelta(minutes=WSV_CONFIG["trend_window_minutes"]))
    measurements_url = f"{base}/stations/{WSV_CONFIG['station_uuid']}/{WSV_CONFIG['timeseries_shortname']}/measurements.json?start={start}&end={end}"
    diagnostics: dict[str, Any] = {
        "live_adapter_enabled": True,
        "api_attempts": 0,
        "retries": 0,
        "adapter_errors": [],
        "endpoint_types": ["station_metadata", "recent_measurements"],
        "source_endpoint_type": "official_wsv_pegelonline_rest_api_v2_json",
        "live_adapters_enabled": [ADAPTER_ID],
    }
    try:
        station = _extract_station(_get_json(station_url, diagnostics))
        timeseries = _find_timeseries(station)
        measurements = _valid_measurements(_get_json(measurements_url, diagnostics))
        latest_ts, latest_value = measurements[-1]
        age_minutes = (now_utc - latest_ts).total_seconds() / 60
        freshness = "fresh_measurement" if age_minutes <= WSV_CONFIG["freshness_threshold_minutes"] else "stale_measurement"
        trend = _trend(measurements, timeseries["unit"])
    except ValueError as exc:
        kind = "malformed_timestamp" if "timestamp" in str(exc) else "missing_measurement"
        return _unavailable(diagnostics, f"{kind}: {exc}")
    except Exception as exc:
        return _unavailable(diagnostics, f"wsv_fetch_failed: {exc}")

    observations = {
        "source_organization": "Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV)",
        "source_name": "PEGELONLINE REST API v2",
        "station_uuid": station["uuid"],
        "station_number": station.get("number"),
        "station_short_name": station.get("shortname"),
        "station_long_name": station.get("longname"),
        "water_body": station.get("water", {}).get("longname"),
        "responsible_agency": station.get("agency"),
        "station_coordinates": {"latitude": station.get("latitude"), "longitude": station.get("longitude")},
        "timeseries_name": timeseries.get("longname"),
        "timeseries_short_name": timeseries.get("shortname"),
        "unit": timeseries.get("unit"),
        "latest_measurement_value": latest_value,
        "latest_measurement_timestamp_utc": _iso_z(latest_ts),
        "measurement_age_minutes": round(age_minutes, 2),
        "freshness_status": freshness,
        "recent_change": trend.get("signed_change"),
        "trend_direction": trend["direction"],
        "valid_values_used": trend["valid_measurement_count"],
        "trend": trend,
        "source_endpoint_type": diagnostics["source_endpoint_type"],
        "current_values_note": "Unchecked/raw official measurement; not a flood-warning classification.",
    }
    return AdapterResult(adapter=ADAPTER_ID, status="live", data_status="available", observations=observations, diagnostics=diagnostics, source_research=SOURCES[ADAPTER_ID])
