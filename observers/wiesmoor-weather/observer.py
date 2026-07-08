#!/usr/bin/env python3
"""Wiesmoor local weather observer using the Open-Meteo Forecast API.

The observer emits a descriptive snapshot only. It reports current API values
and forecast fields returned by Open-Meteo without making independent weather
predictions.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

OBSERVER = "wiesmoor-weather"
LATITUDE = 53.4167
LONGITUDE = 7.7333
TIMEZONE = "Europe/Berlin"
TIMEOUT_S = 20
MAX_ATTEMPTS = 3
BASE_URL = "https://api.open-meteo.com/v1/forecast"
CURRENT_FIELDS = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "cloud_cover",
    "pressure_msl",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
)
DAILY_FIELDS = (
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_gusts_10m_max",
)
HOURLY_FIELDS = CURRENT_FIELDS + ("precipitation_probability",)


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


def _to_number(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 2)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _open_meteo_url(target_date: str) -> str:
    params = {
        "latitude": str(LATITUDE),
        "longitude": str(LONGITUDE),
        "timezone": TIMEZONE,
        "current": ",".join(CURRENT_FIELDS),
        "hourly": ",".join(HOURLY_FIELDS),
        "daily": ",".join(DAILY_FIELDS),
        "start_date": target_date,
        "end_date": target_date,
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "temperature_unit": "celsius",
    }
    return f"{BASE_URL}?{urllib.parse.urlencode(params)}"


def _fetch_json(url: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    last_status: int | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        detail: dict[str, Any] = {"attempt": attempt, "http_status": None, "ok": False, "error": None}
        request = urllib.request.Request(url, headers={"User-Agent": "world-observer/wiesmoor-weather"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                detail["http_status"] = response.status
                last_status = response.status
                payload = json.loads(response.read().decode("utf-8"))
            detail["ok"] = True
            attempts.append(detail)
            return payload if isinstance(payload, dict) else None, {
                "url": url,
                "status": "ok" if isinstance(payload, dict) else "error",
                "api_attempts": len(attempts),
                "retries": len(attempts) - 1,
                "http_status": last_status,
                "attempts": attempts,
            }
        except urllib.error.HTTPError as exc:
            detail.update({"http_status": exc.code, "error": f"HTTP {exc.code}"})
            last_status = exc.code
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            detail["error"] = exc.__class__.__name__
        attempts.append(detail)
        if attempt < MAX_ATTEMPTS:
            time.sleep(0.5 * attempt)
    return None, {
        "url": url,
        "status": "unavailable",
        "api_attempts": len(attempts),
        "retries": max(0, len(attempts) - 1),
        "http_status": last_status,
        "attempts": attempts,
    }


def _extract_current(payload: dict[str, Any]) -> dict[str, Any]:
    current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
    return {field: _to_number(current.get(field)) for field in CURRENT_FIELDS} | {"time": current.get("time")}


def _extract_today_daily(payload: dict[str, Any], target_date: str) -> dict[str, Any]:
    daily = payload.get("daily") if isinstance(payload.get("daily"), dict) else {}
    times = daily.get("time") if isinstance(daily.get("time"), list) else []
    index = times.index(target_date) if target_date in times else 0 if times else None
    result: dict[str, Any] = {"date": target_date if index is not None else None}
    for field in DAILY_FIELDS:
        values = daily.get(field)
        result[field] = _to_number(values[index]) if index is not None and isinstance(values, list) and index < len(values) else None
    return result


def _extract_hourly(payload: dict[str, Any]) -> dict[str, Any]:
    hourly = payload.get("hourly") if isinstance(payload.get("hourly"), dict) else {}
    times = hourly.get("time") if isinstance(hourly.get("time"), list) else []
    hours: list[dict[str, Any]] = []
    for index, stamp in enumerate(times[:24]):
        row: dict[str, Any] = {"time": stamp}
        for field in HOURLY_FIELDS:
            values = hourly.get(field)
            row[field] = _to_number(values[index]) if isinstance(values, list) and index < len(values) else None
        hours.append(row)
    return {"hours_returned": len(hours), "first_24h": hours}


def _data_status(current: dict[str, Any], daily: dict[str, Any], hourly: dict[str, Any]) -> str:
    current_values = [current.get(field) for field in CURRENT_FIELDS]
    daily_values = [daily.get(field) for field in DAILY_FIELDS]
    has_current = any(value is not None for value in current_values)
    has_daily = any(value is not None for value in daily_values)
    has_hourly = bool(hourly.get("first_24h"))
    if has_current and has_daily and has_hourly:
        return "ok"
    if has_current or has_daily or has_hourly:
        return "partial"
    return "unavailable"


def _summary(current: dict[str, Any], daily: dict[str, Any]) -> str:
    temp = current.get("temperature_2m")
    feels = current.get("apparent_temperature")
    clouds = current.get("cloud_cover")
    wind = current.get("wind_speed_10m")
    rain = current.get("rain")
    high = daily.get("temperature_2m_max")
    low = daily.get("temperature_2m_min")
    if temp is None:
        return "Open-Meteo weather data for Wiesmoor is unavailable."
    parts = [f"Wiesmoor is {temp} °C"]
    if feels is not None:
        parts.append(f"feels like {feels} °C")
    if clouds is not None:
        parts.append(f"cloud cover {clouds}%")
    if rain is not None:
        parts.append(f"rain {rain} mm")
    if wind is not None:
        parts.append(f"wind {wind} km/h")
    if high is not None and low is not None:
        parts.append(f"today {low}–{high} °C")
    return "; ".join(parts) + "."


def build_payload() -> dict[str, Any]:
    target_date = _date_utc()
    url = _open_meteo_url(target_date)
    payload, source_diag = _fetch_json(url)
    diagnostics = {
        "api_attempts": source_diag["api_attempts"],
        "retries": source_diag["retries"],
        "http_status": source_diag["http_status"],
        "source": {"url": source_diag["url"], "status": source_diag["status"]},
        "attempts": source_diag["attempts"],
    }
    if payload is None:
        return {
            "observer": OBSERVER,
            "date": target_date,
            "status": "unavailable",
            "data_status": "unavailable",
            "source": {"name": "Open-Meteo Forecast API", "url": url, "status": source_diag["status"]},
            "collected_at_utc": _now_utc(),
            "location": {"name": "Wiesmoor, Lower Saxony, Germany", "latitude": LATITUDE, "longitude": LONGITUDE, "timezone": TIMEZONE},
            "current": {},
            "today": {},
            "hourly": {"hours_returned": 0, "first_24h": []},
            "diagnostics": diagnostics,
            "summary": "Open-Meteo weather data for Wiesmoor is unavailable.",
        }
    current = _extract_current(payload)
    today = _extract_today_daily(payload, target_date)
    hourly = _extract_hourly(payload)
    data_status = _data_status(current, today, hourly)
    status = "ok" if data_status in {"ok", "partial"} else "unavailable"
    return {
        "observer": OBSERVER,
        "date": target_date,
        "status": status,
        "data_status": data_status,
        "source": {"name": "Open-Meteo Forecast API", "url": url, "status": source_diag["status"]},
        "collected_at_utc": _now_utc(),
        "location": {"name": "Wiesmoor, Lower Saxony, Germany", "latitude": LATITUDE, "longitude": LONGITUDE, "timezone": TIMEZONE},
        "current": current,
        "today": today,
        "hourly": hourly,
        "diagnostics": diagnostics,
        "summary": _summary(current, today),
    }


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
