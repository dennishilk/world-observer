#!/usr/bin/env python3
"""Wiesmoor Peatland Observer.

Local environmental proxy observer for the Wiesmoor peatland landscape. The
observer is intentionally conservative: it does not report an in-situ peat
water-table measurement. The DWD daily climate adapter provides a regional
weather proxy only; groundwater and satellite soil-water adapters remain
pending.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

OBSERVER = "wiesmoor-peatland"
LATITUDE = 53.4167
LONGITUDE = 7.7333
DWD_KL_RECENT_BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/recent/"
DWD_STATION_DESCRIPTION = "KL_Tageswerte_Beschreibung_Stationen.txt"
DWD_ADAPTER_ID = "dwd_cdc_daily_climate_kl_recent"
USER_AGENT = "WorldObserver/0.14 WiesmoorPeatlandObserver (+https://github.com/)"
REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 2
RECENT_OBSERVATION_MAX_AGE_DAYS = 14
MIN_COVERAGE_7D = 7
MIN_COVERAGE_30D = 27
MISSING_VALUES = {"", "-999", "-999.0"}

@dataclass(frozen=True)
class DwdStation:
    station_id: str
    from_date: date
    to_date: date
    latitude: float
    longitude: float
    name: str
    state: str
    distance_km: float

@dataclass
class AdapterDiagnostics:
    api_attempts: int = 0
    retries: int = 0
    http_status: int | None = None
    error: str | None = None

_RUN_CACHE: dict[str, bytes | str] = {}

def _date_utc() -> str:
    raw = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if raw:
        try: return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
        except ValueError: pass
    return datetime.now(timezone.utc).date().isoformat()

def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _unavailable_source(name: str, url: str, note: str) -> dict[str, Any]:
    return {"name": name, "url": url, "status": "adapter_pending", "note": note}

def _parse_dwd_date(raw: str) -> date:
    return datetime.strptime(raw.strip(), "%Y%m%d").date()

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km using the documented haversine formula."""
    radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def _fetch_url(url: str, diagnostics: AdapterDiagnostics) -> bytes:
    if url in _RUN_CACHE and isinstance(_RUN_CACHE[url], bytes):
        return _RUN_CACHE[url]  # type: ignore[return-value]
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        diagnostics.api_attempts += 1
        if attempt: diagnostics.retries += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                diagnostics.http_status = getattr(response, "status", None)
                data = response.read()
                _RUN_CACHE[url] = data
                return data
        except urllib.error.HTTPError as exc:
            diagnostics.http_status = exc.code; last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt < MAX_RETRIES:
            time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"DWD request failed for {url}: {last_error}")

def parse_station_description(text: str, today: date | None = None) -> list[DwdStation]:
    today = today or datetime.now(timezone.utc).date()
    stations: list[DwdStation] = []
    for line in text.splitlines():
        if not re.match(r"^\s*\d{5}\s+\d{8}\s+\d{8}\s+", line):
            continue
        parts = line.split()
        try:
            station_id = parts[0].zfill(5)
            from_date, to_date = _parse_dwd_date(parts[1]), _parse_dwd_date(parts[2])
            lat, lon = float(parts[4]), float(parts[5])
        except (ValueError, IndexError):
            continue
        name = parts[6].replace("_", " ")
        state = " ".join(parts[7:-1]) if len(parts) > 8 else ""
        stations.append(DwdStation(station_id, from_date, to_date, lat, lon, name, state, round(haversine_km(LATITUDE, LONGITUDE, lat, lon), 2)))
    return sorted(stations, key=lambda s: (s.distance_km, s.station_id))

def _station_zip_url(station_id: str) -> str:
    return f"{DWD_KL_RECENT_BASE_URL}tageswerte_KL_{station_id}_akt.zip"

def select_station(stations: list[DwdStation], today: date | None = None) -> DwdStation | None:
    today = today or datetime.now(timezone.utc).date()
    recent_cutoff = today - timedelta(days=RECENT_OBSERVATION_MAX_AGE_DAYS)
    suitable = [s for s in stations if s.to_date >= recent_cutoff]
    return suitable[0] if suitable else None

def _parse_float(raw: str | None) -> float | None:
    if raw is None or raw.strip() in MISSING_VALUES: return None
    try: return float(raw.strip())
    except ValueError: return None

def parse_daily_product(zip_bytes: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.lower().startswith("produkt_klima_tag_") and n.lower().endswith(".txt")]
        if not names: raise ValueError("DWD ZIP did not contain a daily climate product file")
        with zf.open(sorted(names)[0]) as fh:
            text = fh.read().decode("latin1")
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for raw in reader:
        row = {str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items() if k is not None}
        try: obs_date = _parse_dwd_date(row["MESS_DATUM"])
        except (KeyError, ValueError): continue
        rows.append({"date": obs_date, "precip_mm": _parse_float(row.get("RSK")), "temperature_c": _parse_float(row.get("TMK"))})
    return sorted(rows, key=lambda r: r["date"])

def rolling_total(rows: list[dict[str, Any]], latest: date, days: int, min_valid: int) -> tuple[float | None, int, int]:
    # Coverage rule: only sum observations inside the calendar window. Missing DWD values (-999/null)
    # and absent days reduce valid_days; they are never treated as dry 0.0 mm days.
    start = latest - timedelta(days=days - 1)
    by_date = {r["date"]: r for r in rows if start <= r["date"] <= latest}
    values = [by_date[d]["precip_mm"] for d in (start + timedelta(days=i) for i in range(days)) if d in by_date and by_date[d]["precip_mm"] is not None]
    return (round(sum(values), 1) if len(values) >= min_valid else None, len(values), days)

def _station_metadata(station: DwdStation | None) -> dict[str, Any] | None:
    if station is None: return None
    return {"station_id": station.station_id, "station_name": station.name, "latitude": station.latitude, "longitude": station.longitude, "distance_km": station.distance_km, "selection_method": f"Nearest DWD CDC recent daily climate station to Wiesmoor ({LATITUDE}, {LONGITUDE}) with station metadata end date within {RECENT_OBSERVATION_MAX_AGE_DAYS} days; distance uses haversine great-circle calculation."}

# keep existing context funcs
def peat_context() -> dict[str, Any]:
    return {
        "area_name": "Wiesmoor-Nord / Wiesmoor peatland landscape",
        "location": {
            "municipality": "Wiesmoor",
            "district": "Aurich",
            "state": "Lower Saxony",
            "country": "Germany",
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
        },
        "context_note": (
            "Wiesmoor is a settlement and landscape shaped by raised-bog peat extraction, drainage, "
            "peat-fired industry and subsequent agricultural/horticultural use. MoorIS Niedersachsen "
            "maps the Wiesmoor-Nord peatland context, including peat-thickness information; this "
            "observer carries that context as static source metadata rather than as a live sensor."
        ),
        "peat_thickness_context": {
            "status": "context_available_from_source_not_live_ingested",
            "description": "MoorIS Niedersachsen / Wiesmoor-Nord provides local peat-thickness context for the mapped peatland area.",
            "value": None,
            "unit": None,
            "precision_note": "No numeric peat-thickness value is emitted until a reproducible MoorIS data extraction is added.",
        },
        "source": {
            "name": "MoorIS Niedersachsen / Wiesmoor-Nord",
            "url": "https://mooris-niedersachsen.de/",
            "status": "static_context",
        },
    }


def groundwater_proxy() -> dict[str, Any]:
    return {
        "label": "groundwater proxy",
        "interpretation_note": (
            "Nearby groundwater stations can indicate regional groundwater behaviour but are not an "
            "in-situ peat water-table sensor for Wiesmoor-Nord."
        ),
        "stations": [
            {
                "station_name": "NLWKN nearby groundwater station (to be resolved)",
                "distance_km": None,
                "status_category": "candidate_source_not_live_ingested",
                "latest_value": None,
                "latest_value_unit": None,
                "latest_date": None,
                "data_status": "unavailable",
            }
        ],
        "source": _unavailable_source(
            "NLWKN groundwater monitoring data",
            "https://www.nlwkn.niedersachsen.de/",
            "Add a deterministic station selection and latest-value adapter before emitting station values.",
        ),
        "data_status": "unavailable",
    }


def regional_soil_water() -> dict[str, Any]:
    return {
        "label": "regional satellite-derived soil-water condition",
        "dataset": "Copernicus Soil Water Index Europe 1 km v2",
        "spatial_resolution_km": 1,
        "temporal_resolution": "daily",
        "latest_value": None,
        "latest_date": None,
        "status": "unavailable",
        "trend": "unavailable",
        "source": _unavailable_source(
            "Copernicus Soil Water Index Europe 1 km v2",
            "https://land.copernicus.eu/en/products/soil-water-index",
            "Implement Copernicus download/API extraction for the Wiesmoor grid cell or a documented regional buffer.",
        ),
    }


def weather_pressure() -> tuple[dict[str, Any], AdapterDiagnostics]:
    diagnostics = AdapterDiagnostics()
    source_url = DWD_KL_RECENT_BASE_URL
    source = {
        "name": "Deutscher Wetterdienst (DWD) Climate Data Center",
        "url": source_url,
        "status": "live_adapter",
        "dataset": "Recent daily climate observations Germany (KL), daily precipitation RSK and daily mean temperature TMK",
        "station_description_url": DWD_KL_RECENT_BASE_URL + DWD_STATION_DESCRIPTION,
    }
    base: dict[str, Any] = {
        "label": "weather pressure",
        "rainfall_7d_mm": None,
        "rainfall_30d_mm": None,
        "temperature_c": None,
        "temperature_label": "latest valid daily mean temperature (TMK), not an instantaneous/current temperature",
        "latest_date": None,
        "data_status": "unavailable",
        "station": None,
        "coverage": {
            "valid_days_7d": 0,
            "expected_days_7d": 7,
            "valid_days_30d": 0,
            "expected_days_30d": 30,
            "minimum_coverage_rule": f"7-day total requires {MIN_COVERAGE_7D}/7 valid precipitation days; 30-day total requires at least {MIN_COVERAGE_30D}/30 valid precipitation days. DWD -999/missing and absent dates are unavailable, not zero.",
        },
        "source": source,
    }
    station: DwdStation | None = None
    try:
        station_text = _fetch_url(DWD_KL_RECENT_BASE_URL + DWD_STATION_DESCRIPTION, diagnostics).decode("latin1")
        station = select_station(parse_station_description(station_text))
        base["station"] = _station_metadata(station)
        if station is None:
            raise RuntimeError("No suitable recent DWD KL station found in station description")
        source["selected_station_zip_url"] = _station_zip_url(station.station_id)
        zip_bytes = _fetch_url(_station_zip_url(station.station_id), diagnostics)
        rows = parse_daily_product(zip_bytes)
        valid_precip_rows = [r for r in rows if r["precip_mm"] is not None]
        if not valid_precip_rows:
            raise RuntimeError("Selected DWD station has no valid precipitation observations")
        latest = max(r["date"] for r in valid_precip_rows)
        rainfall_7d, valid_7d, expected_7d = rolling_total(rows, latest, 7, MIN_COVERAGE_7D)
        rainfall_30d, valid_30d, expected_30d = rolling_total(rows, latest, 30, MIN_COVERAGE_30D)
        latest_temp = next((r["temperature_c"] for r in reversed(rows) if r["date"] <= latest and r["temperature_c"] is not None), None)
        base.update({
            "rainfall_7d_mm": rainfall_7d,
            "rainfall_30d_mm": rainfall_30d,
            "temperature_c": latest_temp,
            "latest_date": latest.isoformat(),
            "data_status": "ok" if rainfall_7d is not None and rainfall_30d is not None else "partial",
            "coverage": {
                **base["coverage"],
                "valid_days_7d": valid_7d,
                "expected_days_7d": expected_7d,
                "valid_days_30d": valid_30d,
                "expected_days_30d": expected_30d,
            },
        })
        source["observation_date"] = latest.isoformat()
    except Exception as exc:
        diagnostics.error = str(exc)
        if station is not None:
            base["station"] = _station_metadata(station)
            source["selected_station_zip_url"] = _station_zip_url(station.station_id)
        source["status"] = "temporarily_unavailable"
        source["note"] = "DWD adapter failed gracefully; no live weather values were fabricated."
    return base, diagnostics


def derive_pressure(soil: dict[str, Any], groundwater: dict[str, Any], weather: dict[str, Any]) -> dict[str, Any]:
    rainfall_7d = weather.get("rainfall_7d_mm")
    rainfall_30d = weather.get("rainfall_30d_mm")
    soil_trend = soil.get("trend") or "unavailable"
    groundwater_status = groundwater.get("data_status") or "unavailable"
    available = [value for value in (rainfall_7d, rainfall_30d) if isinstance(value, (int, float))]
    if not available and soil_trend == "unavailable" and groundwater_status == "unavailable":
        state = "unavailable"
        confidence = "low"
    else:
        state = "unavailable"
        confidence = "low"
    return {
        "value": state,
        "rainfall_7d": rainfall_7d,
        "rainfall_30d": rainfall_30d,
        "soil_water_trend": soil_trend,
        "groundwater_proxy_status": groundwater_status,
        "confidence": confidence,
        "limitations": [
            "Regional proxy observation — not an in-situ peat water-table sensor.",
            "DWD daily rainfall is one regional proxy component only and is not an in-situ peat water-table measurement.",
            "Groundwater stations, satellite soil-water data and weather totals may describe different depths, footprints and response times.",
        ],
    }


def build_payload() -> dict[str, Any]:
    target_date = _date_utc()
    context = peat_context()
    groundwater = groundwater_proxy()
    soil = regional_soil_water()
    weather, weather_diagnostics = weather_pressure()
    pressure = derive_pressure(soil, groundwater, weather)
    data_status = "partial" if weather.get("data_status") in {"ok", "partial"} else "unavailable"
    return {
        "observer": OBSERVER,
        "display_name": "Wiesmoor Peatland Observer",
        "category": "environment",
        "date": target_date,
        "date_utc": target_date,
        "collected_at_utc": _now_utc(),
        "status": "ok",
        "data_status": data_status,
        "location": context["location"],
        "observation_type": "regional_proxy_not_in_situ_sensor",
        "peat_context": context,
        "groundwater_proxy": groundwater,
        "regional_soil_water": soil,
        "weather_pressure": weather,
        "peatland_hydrological_pressure": pressure,
        "primary_metric_value": pressure["value"],
        "summary": "Wiesmoor peatland hydrological pressure remains unavailable as an in-situ conclusion; DWD daily rainfall is emitted when available as a regional weather proxy component only.",
        "sources": [context["source"], groundwater["source"], soil["source"], weather["source"]],
        "diagnostics": {"api_attempts": weather_diagnostics.api_attempts, "retries": weather_diagnostics.retries, "http_status": weather_diagnostics.http_status, "live_adapters_enabled": [DWD_ADAPTER_ID], "adapter_errors": ([weather_diagnostics.error] if weather_diagnostics.error else [])},
    }


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
