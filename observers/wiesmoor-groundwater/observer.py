#!/usr/bin/env python3
"""Regional groundwater reference-station observer for Wiesmoor."""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

OBSERVER = "wiesmoor-groundwater"
LATITUDE = 53.4167
LONGITUDE = 7.7333
PUBLIC_API_KEY = os.environ.get("NLWKN_GROUNDWATER_PUBLIC_KEY", "9dc05f4e3b4a43a9988d747825b39f43")
API_BASE = "https://bis.azure-api.net/GrundwasserstandonlinePublic/REST"
STATIONS_URL = f"{API_BASE}/stammdaten/stationen/allegrundwasserstationen?key={PUBLIC_API_KEY}"
PORTAL_URL = "https://www.grundwasserstandonline.nlwkn.niedersachsen.de/"
MANUAL_URL = "https://www.grundwasserstandonline.nlwkn.niedersachsen.de/pdf/BenutzerhandbuchWebserviceGrundwasserstandonline.pdf"
TIME_RANGE_DAYS = -90
PARAMETER_ID = 536
MAX_CANDIDATES = 3
MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 30
USER_AGENT = "world-observer/wiesmoor-groundwater (+https://github.com/dennishilk/world-observer)"
MISSING_SENTINELS = {-777.0, -888.0, -999.0, -9999.0}


def _date_utc() -> str:
    raw = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip().replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    return None if number in MISSING_SENTINELS else number


def _dotnet_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/", value.strip())
    if not match:
        return None
    try:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _station_coordinates(record: dict[str, Any]) -> tuple[float | None, float | None]:
    """NLWKN documents that the WGS84 easting/northing fields are swapped."""
    latitude = _number(record.get("WGS84Rechtswert"))
    longitude = _number(record.get("WGS84Hochwert"))
    if latitude is not None and longitude is not None and 47 <= latitude <= 56 and 5 <= longitude <= 16:
        return latitude, longitude
    labeled_latitude = _number(record.get("Latitude"))
    labeled_longitude = _number(record.get("Longitude"))
    if labeled_longitude is not None and labeled_latitude is not None and 47 <= labeled_longitude <= 56 and 5 <= labeled_latitude <= 16:
        return labeled_longitude, labeled_latitude
    return None, None


def normalize_stations(payload: Any) -> list[dict[str, Any]]:
    records = payload.get("getStammdatenResult") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return []
    stations: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        latitude, longitude = _station_coordinates(record)
        station_id = record.get("STA_ID")
        if latitude is None or longitude is None or station_id in (None, ""):
            continue
        stations.append({
            "station_id": str(station_id),
            "station_number": str(record.get("STA_Nummer") or "") or None,
            "station_name": str(record.get("Name") or record.get("STA_Name") or "Unnamed station").strip(),
            "locality": str(record.get("Ort") or "").strip() or None,
            "latitude": latitude,
            "longitude": longitude,
            "distance_from_wiesmoor_km": round(haversine_km(LATITUDE, LONGITUDE, latitude, longitude), 2),
        })
    return sorted(stations, key=lambda item: (item["distance_from_wiesmoor_km"], item["station_name"]))


def extract_time_series(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = payload.get("getPegelDatenspurenResult") if isinstance(payload, dict) else None
    if not isinstance(root, dict):
        return [], {}
    observations: dict[str, dict[str, Any]] = {}
    parameters = root.get("Parameter") if isinstance(root.get("Parameter"), list) else []
    for parameter in parameters:
        traces = parameter.get("Datenspuren") if isinstance(parameter, dict) and isinstance(parameter.get("Datenspuren"), list) else []
        for trace in traces:
            levels = trace.get("Pegelstaende") if isinstance(trace, dict) and isinstance(trace.get("Pegelstaende"), list) else []
            for item in levels:
                if not isinstance(item, dict):
                    continue
                value = _number(item.get("Wert"))
                observed_on = _dotnet_date(item.get("DatumUTC")) or _dotnet_date(item.get("Datum"))
                if value is None or not observed_on:
                    continue
                source_class = str(item.get("Grundwasserstandsklasse") or "").strip()
                if source_class in {"", "-", "Keine Daten"}:
                    source_class = None
                observations[observed_on] = {
                    "date": observed_on,
                    "water_level_m_nhn": round(value, 3),
                    "official_groundwater_class": source_class,
                }
    metadata = {
        "station_name": root.get("Name"),
        "locality": root.get("Ort"),
        "operator": root.get("Betreiber"),
        "district": root.get("Landkreis"),
        "hydrogeological_area": root.get("Hydrogeologischer_Teilraum"),
        "ground_surface_m_nhn": _number(root.get("MS_GOK_mNHN")),
    }
    return [observations[key] for key in sorted(observations)], metadata


def _fetch_json(url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    attempts = 0
    retries = 0
    last_status: int | None = None
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        attempts += 1
        if attempt:
            retries += 1
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                last_status = getattr(response, "status", None)
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("NLWKN response root is not an object")
            return payload, {"api_attempts": attempts, "retries": retries, "http_status": last_status}
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
        if attempt + 1 < MAX_ATTEMPTS:
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"NLWKN public groundwater request failed: {last_error.__class__.__name__ if last_error else 'unknown error'}")


def _time_series_url(station_id: str) -> str:
    return f"{API_BASE}/station/{station_id}/datenspuren/parameter/{PARAMETER_ID}/tage/{TIME_RANGE_DAYS}?key={PUBLIC_API_KEY}"


def _base_payload() -> dict[str, Any]:
    return {
        "observer": OBSERVER,
        "display_name": "Wiesmoor Groundwater Observer",
        "category": "environment",
        "date": _date_utc(),
        "date_utc": _date_utc(),
        "collected_at_utc": _now_utc(),
        "observation_mode": "regional_proxy",
        "proxy_label": "Regional reference station / Regionale Referenzmessstelle",
        "geography": {
            "reference_place": "Wiesmoor",
            "reference_latitude": LATITUDE,
            "reference_longitude": LONGITUDE,
            "state": "Lower Saxony",
            "country": "Germany",
        },
        "sources": [
            {"name": "NLWKN Grundwasserstandonline", "url": PORTAL_URL, "role": "official public measurements"},
            {"name": "NLWKN public web-service manual", "url": MANUAL_URL, "role": "field and API methodology"},
        ],
        "limitations": [
            "No station explicitly named or located as Wiesmoor is present in the official station list at collection time.",
            "The selected station is a regional reference only and may not represent groundwater conditions within Wiesmoor.",
            "Daily values are official raw values and may not yet have passed final quality control.",
            "Missing-value sentinels such as -777 and -888 are excluded and never published as measurements.",
            "Any groundwater class shown is copied from NLWKN; this observer creates no warning, critical, or danger class.",
        ],
        "do_not_interpret_as": [
            "a groundwater measurement inside Wiesmoor",
            "a peat water-table measurement",
            "a flood, drought, or drinking-water warning",
        ],
        "update_policy": {"cadence": "daily", "history_window_days": abs(TIME_RANGE_DAYS)},
    }


def build_payload(fetch_json: Callable[[str], tuple[dict[str, Any], dict[str, Any]]] = _fetch_json) -> dict[str, Any]:
    payload = _base_payload()
    diagnostics = {"api_attempts": 0, "retries": 0, "http_status": None, "candidate_stations_checked": 0}
    try:
        stations_payload, station_diag = fetch_json(STATIONS_URL)
        for key in ("api_attempts", "retries"):
            diagnostics[key] += int(station_diag.get(key) or 0)
        diagnostics["http_status"] = station_diag.get("http_status")
        stations = normalize_stations(stations_payload)
        if not stations:
            raise ValueError("official station list contained no usable coordinates")
        selected: dict[str, Any] | None = None
        observations: list[dict[str, Any]] = []
        station_metadata: dict[str, Any] = {}
        for candidate in stations[:MAX_CANDIDATES]:
            diagnostics["candidate_stations_checked"] += 1
            series_payload, series_diag = fetch_json(_time_series_url(candidate["station_id"]))
            for key in ("api_attempts", "retries"):
                diagnostics[key] += int(series_diag.get(key) or 0)
            diagnostics["http_status"] = series_diag.get("http_status")
            candidate_observations, candidate_metadata = extract_time_series(series_payload)
            if candidate_observations:
                selected = candidate
                observations = candidate_observations
                station_metadata = candidate_metadata
                break
        if selected is None or not observations:
            raise ValueError("nearby official stations returned no valid values in the requested window")
    except Exception as exc:
        payload.update({
            "status": "unavailable",
            "data_status": "unavailable",
            "reference_station": None,
            "latest_official_observation": None,
            "history": [],
            "diagnostics": {**diagnostics, "error_type": exc.__class__.__name__},
        })
        return payload

    latest = dict(observations[-1])
    ground_surface = _number(station_metadata.get("ground_surface_m_nhn"))
    if ground_surface is not None:
        latest["derived_depth_below_ground_m"] = round(ground_surface - latest["water_level_m_nhn"], 3)
        latest["derived_depth_method"] = "ground_surface_m_nhn minus water_level_m_nhn"
    local_name_text = f"{selected['station_name']} {selected.get('locality') or ''}".casefold()
    explicitly_wiesmoor = "wiesmoor" in local_name_text
    payload.update({
        "status": "ok",
        "data_status": "ok",
        "observation_mode": "local_station" if explicitly_wiesmoor else "regional_proxy",
        "proxy_label": None if explicitly_wiesmoor else "Regional reference station / Regionale Referenzmessstelle",
        "reference_station": {
            "name": selected["station_name"],
            "station_number": selected["station_number"],
            "locality": selected["locality"],
            "operator": station_metadata.get("operator"),
            "district": station_metadata.get("district"),
            "hydrogeological_area": station_metadata.get("hydrogeological_area"),
            "latitude": selected["latitude"],
            "longitude": selected["longitude"],
            "distance_from_wiesmoor_km": selected["distance_from_wiesmoor_km"],
            "explicitly_identified_as_wiesmoor_station": explicitly_wiesmoor,
            "ground_surface_m_nhn": ground_surface,
        },
        "nearby_station_candidates": [
            {
                "name": item["station_name"],
                "locality": item["locality"],
                "distance_from_wiesmoor_km": item["distance_from_wiesmoor_km"],
            }
            for item in stations[:MAX_CANDIDATES]
        ],
        "latest_official_observation": latest,
        "history": observations,
        "measurement_definition": {
            "water_level": "official daily groundwater level in metres above Normalhöhennull (m NHN)",
            "official_groundwater_class": "source-native NLWKN class; null when the source publishes no class",
            "derived_depth": "calculated only when the source provides ground-surface elevation",
        },
        "diagnostics": {
            **diagnostics,
            "valid_history_points": len(observations),
            "missing_sentinels_excluded": sorted(MISSING_SENTINELS),
        },
    })
    return payload


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
