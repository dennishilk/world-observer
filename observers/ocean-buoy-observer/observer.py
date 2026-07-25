#!/usr/bin/env python3
"""Collect and normalize NOAA NDBC's latest marine station observations."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OBSERVER_ID = "ocean-buoy-observer"
NAME = "Ocean Buoy Observer"
SCHEMA_VERSION = "1.0.0"
FEED_URL = "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt"
ATTRIBUTION_URL = "https://www.ndbc.noaa.gov/"
TIMEOUT_SECONDS = 25
MAX_BYTES = 8 * 1024 * 1024
MAX_ATTEMPTS = 3
MISSING = {"MM", "N/A", "NA", "-", ""}

MEASUREMENTS = {
    "WDIR": ("wind_direction_deg", 0, 359), "WSPD": ("wind_speed_m_s", 0, 100),
    "GST": ("wind_gust_m_s", 0, 150), "WVHT": ("wave_height_m", 0, 40),
    "DPD": ("dominant_wave_period_s", 0, 40), "APD": ("average_wave_period_s", 0, 40),
    "MWD": ("mean_wave_direction_deg", 0, 359), "PRES": ("pressure_hpa", 850, 1100),
    "PTDY": ("pressure_tendency_hpa", -100, 100), "ATMP": ("air_temperature_c", -80, 60),
    "WTMP": ("sea_surface_temperature_c", -5, 45), "DEWP": ("dew_point_c", -90, 60),
    "VIS": ("visibility_km", 0, 1000), "TIDE": ("water_level_m", -20, 20),
}


class FeedError(ValueError):
    pass


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def number(value: Any) -> float | None:
    if value is None or str(value).strip().upper() in MISSING:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def knots_to_m_s(value: Any) -> float | None:
    parsed = number(value)
    return None if parsed is None else round(parsed * 0.514444, 3)


def nautical_miles_to_km(value: Any) -> float | None:
    parsed = number(value)
    return None if parsed is None else round(parsed * 1.852, 3)


def feet_to_metres(value: Any) -> float | None:
    parsed = number(value)
    return None if parsed is None else round(parsed * 0.3048, 3)


def parse_timestamp(row: dict[str, str]) -> datetime | None:
    try:
        year = int(row.get("YYYY", row.get("YY", "")))
        year = year + 2000 if year < 100 else year
        return datetime(year, int(row["MM"]), int(row["DD"]), int(row["hh"]), int(row["mm"]), tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None


def freshness(age_hours: float) -> str:
    return "fresh" if age_hours <= 3 else "aging" if age_hours <= 6 else "stale"


def wave_state(height: float | None) -> str | None:
    if height is None: return None
    for limit, label in ((0.1, "calm"), (0.5, "smooth"), (1.25, "slight"), (2.5, "moderate"), (4, "rough"), (6, "very_rough"), (9, "high"), (14, "very_high")):
        if height < limit: return label
    return "phenomenal"


def wind_state(speed: float | None) -> str | None:
    if speed is None: return None
    for limit, label in ((0.5, "calm"), (5.5, "light"), (10.8, "moderate"), (17.2, "strong"), (24.5, "gale"), (32.7, "storm")):
        if speed < limit: return label
    return "hurricane_force"


def region(lat: float, lon: float) -> str:
    """Return a conservative display region, not a hydrographic classification."""
    # Sixty degrees is an intentionally simple, deterministic polar threshold.
    if lat >= 60: return "Arctic"
    if lat <= -60: return "Southern Ocean"

    # Use lake-sized boxes rather than one box that would cover most of the Midwest.
    great_lakes = (
        (46.2, 49.0, -92.3, -84.3),  # Superior
        (41.5, 46.2, -88.5, -84.5),  # Michigan
        (43.0, 46.5, -84.9, -79.5),  # Huron
        (41.2, 43.0, -83.6, -78.7),  # Erie
        (43.0, 44.6, -79.9, -75.8),  # Ontario
    )
    if any(south <= lat <= north and west <= lon <= east
           for south, north, west, east in great_lakes):
        return "Great Lakes"

    # These coastal bands include the Gulf shelf without swallowing inland Texas
    # or the inland southeastern United States.
    gulf_bands = (
        (18.0, 29.8, -97.8, -93.5),
        (18.0, 30.7, -93.5, -87.0),
        (18.0, 30.5, -87.0, -81.0),
    )
    if any(south <= lat <= north and west <= lon <= east
           for south, north, west, east in gulf_bands):
        return "Gulf of Mexico"

    if 9.0 <= lat <= 23.5 and -89.0 <= lon <= -59.0:
        return "Caribbean"

    # Narrow extensions cover the US Atlantic and Pacific coasts; the broad
    # boxes cover open water. Unmatched coordinates deliberately remain neutral.
    if ((0 < lat < 60 and -70 <= lon <= 20)
            or (24 <= lat <= 30 and -81.5 <= lon < -77)
            or (30 < lat <= 46 and -76 <= lon < -65)):
        return "North Atlantic"
    if -60 < lat <= 0 and -70 <= lon <= 20:
        return "South Atlantic"
    if ((0 < lat < 60 and (-180 <= lon <= -122 or 120 <= lon <= 180))):
        return "North Pacific"
    if -60 < lat <= 0 and (-180 <= lon < -70 or 120 <= lon <= 180):
        return "South Pacific"
    if -60 < lat < 30 and 20 < lon < 120:
        return "Indian Ocean"
    return "Inland / Other"


def parse_feed(text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3 or not lines[0].startswith("#STN"):
        raise FeedError("NDBC feed has no recognized header")
    headers = lines[0][1:].split()
    rows = []
    for line in lines[2:]:
        values = line.split()
        if len(values) == len(headers):
            rows.append(dict(zip(headers, values)))
    if not rows:
        raise FeedError("NDBC feed contains no parseable station rows")
    return rows


def normalize_row(row: dict[str, str], generated: datetime) -> dict[str, Any] | None:
    station_id = row.get("STN", "").strip().upper()
    lat, lon, observed = number(row.get("LAT")), number(row.get("LON")), parse_timestamp(row)
    if not station_id or lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or observed is None:
        return None
    age = max(0.0, (generated - observed).total_seconds() / 3600)
    if age > 24:
        return None
    values: dict[str, float | None] = {}
    for source, (target, minimum, maximum) in MEASUREMENTS.items():
        value = number(row.get(source))
        if source in {"WSPD", "GST"}:  # NDBC realtime standard meteorological files use m/s.
            value = None if value is None else round(value, 3)
        elif source == "VIS":  # nautical miles in this feed
            value = nautical_miles_to_km(value)
        elif source == "TIDE":  # feet relative to the station datum in this feed
            value = feet_to_metres(value)
        if value is not None and not (minimum <= value <= maximum):
            value = None
        values[target] = value
    available = {key.removesuffix("_m_s").removesuffix("_m").removesuffix("_c").removesuffix("_hpa").removesuffix("_s").removesuffix("_deg"): value is not None for key, value in values.items()}
    return {
        "id": station_id, "name": None, "latitude": lat, "longitude": lon,
        "authority": "NOAA National Data Buoy Center", "country": None, "region": region(lat, lon),
        "observed_at": iso(observed), "source_timestamp": iso(observed), "age_hours": round(age, 2),
        "status": "active", "freshness": freshness(age), "measurements": values,
        "conditions": {"wave": wave_state(values["wave_height_m"]), "wind": wind_state(values["wind_speed_m_s"])},
        "available": available, "source_id": "noaa-ndbc", "source_url": f"https://www.ndbc.noaa.gov/station_page.php?station={station_id.lower()}",
        "attribution": "NOAA National Data Buoy Center",
    }


def build_export(text: str, generated_at: datetime | None = None, diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
    generated = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = parse_feed(text)
    skipped = 0
    by_id: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for row in rows:
        station = normalize_row(row, generated)
        if station is None:
            skipped += 1
            continue
        previous = by_id.get(station["id"])
        if previous is not None:
            duplicates += 1
        if previous is None or (station["observed_at"], json.dumps(station, sort_keys=True)) > (previous["observed_at"], json.dumps(previous, sort_keys=True)):
            by_id[station["id"]] = station
    stations = sorted(by_id.values(), key=lambda item: item["id"])
    if not stations:
        raise FeedError("no valid, recent station observations")
    waves = [s["measurements"]["wave_height_m"] for s in stations if s["measurements"]["wave_height_m"] is not None]
    gusts = [s["measurements"]["wind_gust_m_s"] for s in stations if s["measurements"]["wind_gust_m_s"] is not None]
    temps = [s["measurements"]["sea_surface_temperature_c"] for s in stations if s["measurements"]["sea_surface_temperature_c"] is not None]
    stale = sum(s["freshness"] == "stale" for s in stations)
    status = "partial" if skipped or stale else "healthy"
    regions: dict[str, int] = {}
    for station in stations: regions[station["region"]] = regions.get(station["region"], 0) + 1
    return {
        "observer": {"id": OBSERVER_ID, "name": NAME, "version": SCHEMA_VERSION, "generated_at": iso(generated), "status": status, "data_status": "partial" if status == "partial" else "ok", "summary": f"{len(stations)} recent NOAA NDBC marine station observations."},
        "coverage": {"scope": "NOAA NDBC network; predominantly United States waters, not worldwide completeness", "maximum_observation_age_hours": 24, "regions": dict(sorted(regions.items()))},
        "statistics": {"total_stations": len(stations), "fresh_stations": sum(s["freshness"] == "fresh" for s in stations), "aging_stations": sum(s["freshness"] == "aging" for s in stations), "stale_stations": stale, "stations_with_waves": len(waves), "stations_with_wind": sum(s["measurements"]["wind_speed_m_s"] is not None for s in stations), "stations_with_sea_temperature": len(temps), "median_wave_height_m": round(statistics.median(waves), 3) if waves else None, "maximum_wave_height_m": max(waves) if waves else None, "maximum_wind_gust_m_s": max(gusts) if gusts else None, "average_sea_temperature_c": round(statistics.fmean(temps), 2) if temps else None, "source_success_count": 1, "source_failure_count": 0},
        "conditions": {"wave_scale": "WMO sea-state height thresholds", "wind_scale": "deterministic project thresholds based on sustained wind speed"},
        "stations": stations,
        "sources": [{"id": "noaa-ndbc", "name": "NOAA National Data Buoy Center", "dataset": "Latest observations", "url": FEED_URL, "attribution_url": ATTRIBUTION_URL, "precedence": 1}],
        "quality": {"source_rows": len(rows), "accepted_stations": len(stations), "skipped_rows": skipped, "duplicate_rows": duplicates},
        "diagnostics": diagnostics or {"attempts": 0, "http_status": None},
        "warnings": ([f"Skipped {skipped} malformed, implausible, or older-than-24-hour row(s)."] if skipped else []) + (["Some accepted observations are more than six hours old."] if stale else []),
    }


def validate_payload(payload: Any) -> None:
    if not isinstance(payload, dict): raise FeedError("JSON root is not an object")
    observer = payload.get("observer")
    if not isinstance(observer, dict) or observer.get("id") != OBSERVER_ID: raise FeedError("incorrect observer identity")
    if observer.get("status") == "error" or observer.get("data_status") == "error": raise FeedError("explicit error payload")
    try: datetime.fromisoformat(str(observer["generated_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError): raise FeedError("invalid generated timestamp")
    stations = payload.get("stations")
    if not isinstance(stations, list) or not stations: raise FeedError("payload has zero valid stations")
    ids = set()
    for station in stations:
        if not isinstance(station, dict) or not station.get("id") or station["id"] in ids: raise FeedError("invalid or duplicate station id")
        ids.add(station["id"])
        lat, lon = station.get("latitude"), station.get("longitude")
        if isinstance(lat, bool) or isinstance(lon, bool) or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not (-90 <= lat <= 90 and -180 <= lon <= 180): raise FeedError("invalid station coordinates")
        try: datetime.fromisoformat(str(station["observed_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError): raise FeedError("invalid observation timestamp")
        if not station.get("source_id") or not station.get("attribution"): raise FeedError("missing station provenance")
        measurements = station.get("measurements")
        if not isinstance(measurements, dict) or any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)) for v in measurements.values()): raise FeedError("invalid measurement")


def fetch() -> tuple[str, dict[str, Any]]:
    last = "unknown error"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(FEED_URL, headers={"Accept": "text/plain", "User-Agent": "world-observer/ocean-buoy-observer (+https://github.com/dennishilk/world-observer)"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                if getattr(response, "status", None) != 200: raise FeedError(f"HTTP {response.status}")
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES: raise FeedError("response exceeds size limit")
                return raw.decode("ascii"), {"attempts": attempt, "http_status": 200}
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, FeedError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_ATTEMPTS: time.sleep(0.25 * attempt)
    raise FeedError(f"NDBC download failed after {MAX_ATTEMPTS} attempts: {last}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args()
    try:
        if args.validate:
            validate_payload(json.loads(args.validate.read_text(encoding="utf-8")))
            return 0
        text, diagnostics = fetch()
        payload = build_export(text, diagnostics=diagnostics)
        validate_payload(payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")))
        return 0
    except (OSError, json.JSONDecodeError, FeedError) as exc:
        print(f"{OBSERVER_ID}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())
