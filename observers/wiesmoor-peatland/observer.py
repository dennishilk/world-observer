#!/usr/bin/env python3
"""Wiesmoor Peatland Observer.

Local environmental proxy observer for the Wiesmoor peatland landscape. The
observer is intentionally conservative: it does not report an in-situ peat
water-table measurement and leaves live source values unavailable until robust
source-specific adapters are implemented.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

OBSERVER = "wiesmoor-peatland"
LATITUDE = 53.4167
LONGITUDE = 7.7333


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


def _unavailable_source(name: str, url: str, note: str) -> dict[str, Any]:
    return {"name": name, "url": url, "status": "adapter_pending", "note": note}


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


def weather_pressure() -> dict[str, Any]:
    return {
        "label": "weather pressure",
        "rainfall_7d_mm": None,
        "rainfall_30d_mm": None,
        "temperature_c": None,
        "latest_date": None,
        "data_status": "unavailable",
        "source": _unavailable_source(
            "DWD Climate Data Center daily climate / precipitation",
            "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/",
            "Add nearest suitable DWD daily station selection and rolling 7-day/30-day precipitation totals.",
        ),
    }


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
        state = "normal"
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
            "Hydrological pressure is unavailable until at least one live proxy source is ingested reproducibly.",
            "Groundwater stations, satellite soil-water data and weather totals may describe different depths, footprints and response times.",
        ],
    }


def build_payload() -> dict[str, Any]:
    target_date = _date_utc()
    context = peat_context()
    groundwater = groundwater_proxy()
    soil = regional_soil_water()
    weather = weather_pressure()
    pressure = derive_pressure(soil, groundwater, weather)
    data_status = "unavailable" if pressure["value"] == "unavailable" else "partial"
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
        "summary": "Wiesmoor peatland hydrological pressure is unavailable: proxy adapters are present, but no live values are emitted yet.",
        "sources": [context["source"], groundwater["source"], soil["source"], weather["source"]],
        "diagnostics": {"api_attempts": 0, "retries": 0, "http_status": None, "live_adapters_enabled": []},
    }


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
