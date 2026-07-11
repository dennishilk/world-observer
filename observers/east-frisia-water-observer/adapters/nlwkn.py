"""Live NLWKN Pegelonline public REST adapter for East Frisia water levels."""
from __future__ import annotations

import json
import math
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from config import NLWKN_CONFIG, SOURCES
from models import AdapterResult

ADAPTER_ID = "nlwkn"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("malformed timestamp")
    text = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(text.replace("Z", "+0000"), fmt).astimezone(timezone.utc)
        except ValueError:
            pass
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"):
        try:
            # NLWKN public pages and API examples use Lower Saxony local civil time.
            return datetime.strptime(text, fmt).replace(tzinfo=NLWKN_CONFIG["source_timezone"]).astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("malformed timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _finite_number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("measurement value is not numeric")
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("measurement value is not numeric") from exc
    if not math.isfinite(number):
        raise ValueError("measurement value is not finite")
    return number


def _get_json(url: str, diagnostics: dict[str, Any]) -> Any:
    last_error = None
    for attempt in range(NLWKN_CONFIG["max_retries"] + 1):
        diagnostics["api_attempts"] += 1
        if attempt:
            diagnostics["retries"] += 1
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "world-observer/1.0"})
            with urllib.request.urlopen(req, timeout=NLWKN_CONFIG["timeout_seconds"]) as response:
                status = getattr(response, "status", response.getcode())
                if status != 200:
                    raise RuntimeError(f"HTTP status {status}")
                return json.loads(response.read().decode("utf-8-sig"))
        except (urllib.error.URLError, TimeoutError, socket.timeout, RuntimeError, ValueError) as exc:
            last_error = exc
    raise RuntimeError(str(last_error))


def _unavailable(diagnostics: dict[str, Any], message: str) -> AdapterResult:
    diagnostics.setdefault("adapter_errors", []).append(message)
    return AdapterResult(ADAPTER_ID, "unavailable", "unavailable", {}, diagnostics, SOURCES[ADAPTER_ID])


def _station_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("getStammdatenResult", "stations", "Stationen", "stationen"):
            if isinstance(payload.get(key), list):
                return [item for item in payload[key] if isinstance(item, dict)]
        if str(payload.get("ID") or payload.get("Id") or payload.get("id")) == NLWKN_CONFIG["station_id"]:
            return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError("station metadata JSON is not an object or list")


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _find_station(payload: Any) -> dict[str, Any]:
    for item in _station_items(payload):
        station_id = str(_first(item.get("ID"), item.get("Id"), item.get("id"), item.get("StationsID"), item.get("StationsId")))
        if station_id == NLWKN_CONFIG["station_id"]:
            return item
    raise ValueError("configured NLWKN station ID missing from metadata")


def _parameter_items(station: dict[str, Any]) -> list[dict[str, Any]]:
    params = _first(station.get("Parameter"), station.get("parameter"), station.get("parameters"))
    return [item for item in params if isinstance(item, dict)] if isinstance(params, list) else []


def _water_parameter(station: dict[str, Any]) -> dict[str, Any]:
    for param in _parameter_items(station):
        name = str(_first(param.get("Name"), param.get("ParameterName"), param.get("Bezeichnung"), "")).lower()
        ident = str(_first(param.get("ID"), param.get("Id"), param.get("id"), param.get("ParameterID"), ""))
        if ident == NLWKN_CONFIG["parameter_id"] or "wasserstand" in name:
            unit = _first(param.get("Einheit"), param.get("Unit"), param.get("unit"), NLWKN_CONFIG["unit"])
            if unit not in NLWKN_CONFIG["expected_units"]:
                raise ValueError(f"unexpected unit {unit!r}")
            return param
    raise ValueError("configured NLWKN water-level parameter missing")


def _extract_current(station: dict[str, Any], parameter: dict[str, Any]) -> tuple[datetime, float]:
    traces = _first(parameter.get("Datenspuren"), parameter.get("datenspuren"), [])
    containers = traces if isinstance(traces, list) else [parameter]
    for item in containers:
        if not isinstance(item, dict):
            continue
        value = _first(item.get("AktuellerMesswert"), item.get("Messwert"), item.get("value"), item.get("Wert"))
        ts = _first(item.get("AktuellerMesswert_Zeitpunkt"), item.get("Zeitpunkt"), item.get("timestamp"), item.get("Datum"))
        if value is not None and ts is not None:
            return _parse_timestamp(ts), _finite_number(value)
    raise ValueError("current water-level measurement missing")


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _valid_measurements(payload: Any) -> list[tuple[datetime, float]]:
    values: list[tuple[datetime, float]] = []
    seen: set[datetime] = set()
    for item in _walk_dicts(payload):
        value = _first(item.get("Messwert"), item.get("Wert"), item.get("value"), item.get("AktuellerMesswert"))
        ts = _first(item.get("Zeitpunkt"), item.get("timestamp"), item.get("Datum"), item.get("AktuellerMesswert_Zeitpunkt"))
        if value is None or ts is None:
            continue
        parsed_ts = _parse_timestamp(ts)
        if parsed_ts in seen:
            raise ValueError("duplicate measurement timestamp")
        seen.add(parsed_ts)
        values.append((parsed_ts, _finite_number(value)))
    values.sort(key=lambda item: item[0])
    if not values:
        raise ValueError("no valid measurement exists")
    return values


def _trend(values: list[tuple[datetime, float]], unit: str) -> dict[str, Any]:
    minimum = NLWKN_CONFIG["trend_minimum_values"]
    if len(values) < minimum:
        return {"direction": "unavailable", "valid_measurement_count": len(values), "minimum_valid_measurements": minimum}
    first_ts, first_value = values[0]
    latest_ts, latest_value = values[-1]
    change = latest_value - first_value
    threshold = NLWKN_CONFIG["stable_threshold_by_unit"][unit]
    direction = "stable" if abs(change) <= threshold else ("rising" if change > 0 else "falling")
    return {"direction": direction, "first_valid_value": first_value, "latest_valid_value": latest_value, "signed_change": change, "window_start_utc": _iso_z(first_ts), "window_end_utc": _iso_z(latest_ts), "valid_measurement_count": len(values), "minimum_valid_measurements": minimum, "stable_threshold": threshold, "unit": unit}


def fetch(now: datetime | None = None) -> AdapterResult:
    now_utc = (now or _utc_now()).astimezone(timezone.utc)
    base = NLWKN_CONFIG["base_url"].rstrip("/")
    key = NLWKN_CONFIG["public_key"]
    station_url = f"{base}/stammdaten/stationen/All?key={key}"
    measurements_url = f"{base}/station/{NLWKN_CONFIG['station_id']}/datenspuren/parameter/{NLWKN_CONFIG['parameter_id']}/tage/{NLWKN_CONFIG['recent_days']}?key={key}"
    diagnostics: dict[str, Any] = {"live_adapter_enabled": True, "api_attempts": 0, "retries": 0, "adapter_errors": [], "endpoint_types": ["station_metadata", "recent_measurements"], "source_endpoint_type": "official_nlwkn_pegelonline_public_rest_json", "timeout_seconds": NLWKN_CONFIG["timeout_seconds"], "max_retries": NLWKN_CONFIG["max_retries"], "live_adapters_enabled": [ADAPTER_ID]}
    try:
        station = _find_station(_get_json(station_url, diagnostics))
        parameter = _water_parameter(station)
        unit = _first(parameter.get("Einheit"), parameter.get("Unit"), parameter.get("unit"), NLWKN_CONFIG["unit"])
        current_ts, current_value = _extract_current(station, parameter)
        measurements = _valid_measurements(_get_json(measurements_url, diagnostics))
        if measurements[-1][0] >= current_ts:
            current_ts, current_value = measurements[-1]
        age_minutes = (now_utc - current_ts).total_seconds() / 60
        freshness = "fresh_measurement" if age_minutes <= NLWKN_CONFIG["freshness_threshold_minutes"] else "stale_measurement"
        trend = _trend(measurements, unit)
    except ValueError as exc:
        kind = "malformed_timestamp" if "timestamp" in str(exc) else "missing_measurement"
        return _unavailable(diagnostics, f"{kind}: {exc}")
    except Exception as exc:
        return _unavailable(diagnostics, f"nlwkn_fetch_failed: {exc}")

    observations = {
        "source_organization": "Niedersächsischer Landesbetrieb für Wasserwirtschaft, Küsten- und Naturschutz (NLWKN)",
        "source_name": "NLWKN Pegelonline public REST service",
        "station_id": NLWKN_CONFIG["station_id"],
        "station_name": _first(station.get("Name"), station.get("Pegelname"), station.get("Stationsname"), NLWKN_CONFIG["station_name"]),
        "station_type": NLWKN_CONFIG["station_type"],
        "water_body": _first(station.get("Gewaesser"), station.get("Gewässer"), station.get("gewaesser"), NLWKN_CONFIG["water_body"]),
        "operator": _first(station.get("Betreiber"), station.get("betreiber"), NLWKN_CONFIG["operator"]),
        "station_code": _first(station.get("Code"), station.get("code"), NLWKN_CONFIG["station_code"]),
        "unit": unit,
        "latest_measurement_value": current_value,
        "latest_measurement_timestamp_utc": _iso_z(current_ts),
        "measurement_age_minutes": round(age_minutes, 2),
        "freshness_status": freshness,
        "recent_change": trend.get("signed_change"),
        "trend_direction": trend["direction"],
        "valid_values_used": trend["valid_measurement_count"],
        "trend": trend,
        "source_endpoint_type": diagnostics["source_endpoint_type"],
        "current_values_note": "Unchecked/raw official NLWKN measurement; not a flood-warning classification.",
    }
    return AdapterResult(ADAPTER_ID, "live", "available", observations, diagnostics, SOURCES[ADAPTER_ID])
