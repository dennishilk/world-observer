"""Live NLWKN Pegelonline public REST adapter for East Frisia water levels."""
from __future__ import annotations

import json
import math
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

from config import NLWKN_CONFIG, SOURCES
from models import AdapterResult

ADAPTER_ID = "nlwkn"
_BERLIN = ZoneInfo("Europe/Berlin")
_MS_JSON_DATE_RE = re.compile(r"^/Date\((?P<milliseconds>-?\d+)(?P<offset>[+-]\d{4})?\)/$")
_GERMAN_LOCAL_DATE_RE = re.compile(r"^(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4}) (?P<hour>\d{2}):(?P<minute>\d{2})$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _remember_raw_timestamp(diagnostics: dict[str, Any] | None, value: Any) -> None:
    if diagnostics is None or not isinstance(value, str):
        return
    diagnostics["raw_measurement_timestamp"] = value


def _parse_timestamp(value: Any, diagnostics: dict[str, Any] | None = None) -> datetime:
    _remember_raw_timestamp(diagnostics, value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("malformed timestamp")
    text = value.strip()
    local_match = _GERMAN_LOCAL_DATE_RE.fullmatch(text)
    if local_match:
        try:
            local = datetime(
                int(local_match.group("year")),
                int(local_match.group("month")),
                int(local_match.group("day")),
                int(local_match.group("hour")),
                int(local_match.group("minute")),
                tzinfo=_BERLIN,
            )
        except ValueError as exc:
            raise ValueError("malformed timestamp") from exc
        return local.astimezone(timezone.utc)

    match = _MS_JSON_DATE_RE.fullmatch(text)
    if match:
        offset_text = match.group("offset")
        if offset_text is None:
            raise ValueError("timestamp is not timezone-aware")
        # The documented NLWKN REST service is JSON; its measurement endpoint
        # currently returns Microsoft JSON date strings such as
        # /Date(1783785600000+0200)/. The epoch milliseconds identify the UTC
        # instant, while the required suffix documents the source civil offset.
        parsed = datetime.fromtimestamp(int(match.group("milliseconds")) / 1000, timezone.utc)
        offset_hours = int(offset_text[1:3])
        offset_minutes = int(offset_text[3:5])
        if offset_hours > 23 or offset_minutes > 59:
            raise ValueError("malformed timestamp")
        offset = timedelta(hours=offset_hours, minutes=offset_minutes)
        if offset_text.startswith("-"):
            offset = -offset
        return parsed.astimezone(timezone(offset)).astimezone(timezone.utc)
    raise ValueError("malformed timestamp")


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
        if _station_id(payload) is not None:
            return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError("station metadata JSON is not an object or list")


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _station_id(station: dict[str, Any]) -> str | None:
    value = _first(station.get("STA_ID"), station.get("ID"), station.get("Id"), station.get("id"), station.get("StationsID"), station.get("StationsId"))
    return str(value) if value is not None else None


def _station_name(station: dict[str, Any]) -> str | None:
    value = _first(station.get("Name"), station.get("Pegelname"), station.get("Stationsname"), station.get("StationName"))
    return str(value) if value is not None else None


def _raw_key_values(item: dict[str, Any]) -> dict[str, str]:
    return {str(key): type(value).__name__ for key, value in item.items()}


def _debug_raw_enabled() -> bool:
    return bool(NLWKN_CONFIG.get("debug_raw_diagnostics", False))


def _metadata_diagnostics(stations: list[dict[str, Any]]) -> dict[str, Any]:
    terms = NLWKN_CONFIG.get("station_search_terms", [])
    matches: dict[str, list[dict[str, Any]]] = {term: [] for term in terms}
    for station in stations:
        haystack = json.dumps(station, ensure_ascii=False).lower()
        for term in terms:
            if term.lower() in haystack:
                matches[term].append({"station_id": _station_id(station), "station_name": _station_name(station), "key_names": list(station.keys())})
    details = {
        "station_count": len(stations),
        "station_name_matches": {
            term: [{"station_id": item["station_id"], "station_name": item["station_name"]} for item in items]
            for term, items in matches.items()
            if items
        },
    }
    if _debug_raw_enabled():
        details.update({
            "first_20_station_ids": [_station_id(station) for station in stations[:20]],
            "first_20_station_key_names": [list(station.keys()) for station in stations[:20]],
            "first_station_key_types": _raw_key_values(stations[0]) if stations else {},
            "debug_first_station_raw_object": stations[0] if stations else None,
        })
    return details


def _find_station(payload: Any, diagnostics: dict[str, Any]) -> dict[str, Any]:
    stations = _station_items(payload)
    diagnostics.update(_metadata_diagnostics(stations))
    configured_id = str(NLWKN_CONFIG["station_id"])
    for item in stations:
        if _station_id(item) == configured_id:
            parameters = _parameter_items(item)
            diagnostics["confirmed_station"] = {"station_id": _station_id(item), "station_name": _station_name(item), "parameter_count": len(parameters)}
            diagnostics["confirmed_parameters"] = [{"parameter_id": _first(param.get("PAT_ID"), param.get("ID"), param.get("Id"), param.get("id"), param.get("ParameterID")), "parameter_name": _first(param.get("Name"), param.get("ParameterName"), param.get("Bezeichnung")), "unit": _first(param.get("Einheit"), param.get("Unit"), param.get("unit")), "datenspuren_count": len(_first(param.get("Datenspuren"), param.get("datenspuren"), []) or []) if isinstance(_first(param.get("Datenspuren"), param.get("datenspuren"), []), list) else 0} for param in parameters]
            if _debug_raw_enabled():
                diagnostics["confirmed_station_key_names"] = list(item.keys())
                diagnostics["confirmed_parameter_key_names"] = [list(param.keys()) for param in parameters]
                diagnostics["debug_confirmed_station_object"] = item
                diagnostics["debug_confirmed_parameter_list"] = parameters
            return item
    raise ValueError(f"pinned NLWKN station ID {configured_id!r} missing from live metadata")


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _expect_equal(label: str, actual: Any, expected: Any) -> None:
    if _normalized_text(actual) != _normalized_text(expected):
        raise ValueError(f"pinned NLWKN station {label} changed: expected {expected!r}, got {actual!r}")


def _validate_pinned_station(station: dict[str, Any], parameter: dict[str, Any], unit: str) -> None:
    _expect_equal("name", _station_name(station), NLWKN_CONFIG["station_name"])
    _expect_equal("water body", station.get("GewaesserName"), NLWKN_CONFIG["water_body"])
    _expect_equal("operator", _first(station.get("Betreiber"), station.get("betreiber")), NLWKN_CONFIG["operator"])
    parameter_id = _first(parameter.get("PAT_ID"), parameter.get("ID"), parameter.get("Id"), parameter.get("id"), parameter.get("ParameterID"))
    _expect_equal("water-level parameter ID", parameter_id, NLWKN_CONFIG["parameter_id"])
    _expect_equal("water-level parameter name", _first(parameter.get("Name"), parameter.get("ParameterName"), parameter.get("Bezeichnung")), NLWKN_CONFIG["parameter_name"])
    _expect_equal("unit", unit, NLWKN_CONFIG["unit"])


def _parameter_items(station: dict[str, Any]) -> list[dict[str, Any]]:
    params = _first(station.get("Parameter"), station.get("parameter"), station.get("parameters"))
    return [item for item in params if isinstance(item, dict)] if isinstance(params, list) else []


def _water_parameter(station: dict[str, Any]) -> dict[str, Any]:
    for param in _parameter_items(station):
        name = str(_first(param.get("Name"), param.get("ParameterName"), param.get("Bezeichnung"), "")).lower()
        ident = str(_first(param.get("PAT_ID"), param.get("ID"), param.get("Id"), param.get("id"), param.get("ParameterID"), ""))
        if ident == NLWKN_CONFIG["parameter_id"] or "wasserstand" in name:
            unit = _first(param.get("Einheit"), param.get("Unit"), param.get("unit"), NLWKN_CONFIG["unit"])
            if unit not in NLWKN_CONFIG["expected_units"]:
                raise ValueError(f"unexpected unit {unit!r}")
            return param
    raise ValueError("configured NLWKN water-level parameter missing")


def _extract_current(station: dict[str, Any], parameter: dict[str, Any], diagnostics: dict[str, Any] | None = None) -> tuple[datetime, float]:
    traces = _first(parameter.get("Datenspuren"), parameter.get("datenspuren"), [])
    containers = traces if isinstance(traces, list) else [parameter]
    for item in containers:
        if not isinstance(item, dict):
            continue
        value = _first(item.get("AktuellerMesswert"), item.get("Messwert"), item.get("value"), item.get("Wert"))
        ts = _first(item.get("AktuellerMesswert_Zeitpunkt"), item.get("Zeitpunkt"), item.get("timestamp"), item.get("Datum"))
        if value is not None and ts is not None:
            return _parse_timestamp(ts, diagnostics), _finite_number(value)
    raise ValueError("current water-level measurement missing")


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _valid_measurements(payload: Any, diagnostics: dict[str, Any] | None = None) -> list[tuple[datetime, float]]:
    values: list[tuple[datetime, float]] = []
    seen: set[datetime] = set()
    for item in _walk_dicts(payload):
        value = _first(item.get("Messwert"), item.get("Wert"), item.get("value"), item.get("AktuellerMesswert"))
        ts = _first(item.get("Zeitpunkt"), item.get("timestamp"), item.get("Datum"), item.get("AktuellerMesswert_Zeitpunkt"))
        if value is None or ts is None:
            continue
        parsed_ts = _parse_timestamp(ts, diagnostics)
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
    measurements_url = None
    diagnostics: dict[str, Any] = {"live_adapter_enabled": True, "api_attempts": 0, "retries": 0, "adapter_errors": [], "endpoint_types": ["station_metadata", "recent_measurements"], "source_endpoint_type": "official_nlwkn_pegelonline_public_rest_json", "timeout_seconds": NLWKN_CONFIG["timeout_seconds"], "max_retries": NLWKN_CONFIG["max_retries"], "live_adapters_enabled": [ADAPTER_ID]}
    try:
        station = _find_station(_get_json(station_url, diagnostics), diagnostics)
        station_id = _station_id(station)
        if not station_id:
            raise ValueError("confirmed NLWKN station has no station ID")
        parameter = _water_parameter(station)
        unit = _first(parameter.get("Einheit"), parameter.get("Unit"), parameter.get("unit"), NLWKN_CONFIG["unit"])
        _validate_pinned_station(station, parameter, unit)
        current_ts, current_value = _extract_current(station, parameter, diagnostics)
        measurements_url = f"{base}/station/{station_id}/datenspuren/parameter/{NLWKN_CONFIG['parameter_id']}/tage/{NLWKN_CONFIG['recent_days']}?key={key}"
        measurements = _valid_measurements(_get_json(measurements_url, diagnostics), diagnostics)
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
        "station_id": station_id,
        "station_name": _first(station.get("Name"), station.get("Pegelname"), station.get("Stationsname"), NLWKN_CONFIG["station_name"]),
        "station_type": NLWKN_CONFIG["station_type"],
        "water_body": _first(station.get("GewaesserName"), NLWKN_CONFIG["water_body"]),
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
