#!/usr/bin/env python3
"""NOAA SWPC geomagnetic storm observer.

Collects current public space-weather measurements and emits a compact,
descriptive JSON snapshot. The observer intentionally does not predict storm
activity or make aurora-visibility claims.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

OBSERVER = "geomagnetic-storm-observer"
TIMEOUT_S = 20
SOURCES = {
    "kp": "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
    "mag": "https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json",
    "plasma": "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json",
}


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


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, "", "null"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 2)


def _fetch_json(url: str, timeout_s: int = TIMEOUT_S) -> tuple[Any | None, dict[str, Any]]:
    diagnostic: dict[str, Any] = {"url": url, "ok": False, "http_status": None, "error": None}
    request = urllib.request.Request(url, headers={"User-Agent": "world-observer/geomagnetic-storm-observer"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            diagnostic["http_status"] = response.status
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        diagnostic.update({"http_status": exc.code, "error": f"HTTP {exc.code}"})
        return None, diagnostic
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        diagnostic["error"] = exc.__class__.__name__
        return None, diagnostic
    diagnostic["ok"] = True
    return payload, diagnostic


def _rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or not payload:
        return []
    header = payload[0]
    if not isinstance(header, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in payload[1:]:
        if isinstance(item, list):
            rows.append({str(key): value for key, value in zip(header, item)})
    return rows


def latest_kp(payload: Any) -> tuple[dict[str, Any] | None, float | None, int]:
    rows = _rows(payload)
    parsed = [row for row in rows if _to_float(row.get("Kp")) is not None]
    if not parsed:
        return None, None, len(rows)
    latest = parsed[-1]
    latest_value = _to_float(latest.get("Kp"))
    max_kp = max(_to_float(row.get("Kp")) or 0 for row in parsed)
    return {"observed_at_utc": latest.get("time_tag"), "value": latest_value, "max_available": round(max_kp, 2)}, round(max_kp, 2), len(rows)


def latest_bz_gsm(payload: Any) -> tuple[float | None, str | None, int]:
    rows = _rows(payload)
    for row in reversed(rows):
        value = _to_float(row.get("bz_gsm"))
        if value is not None:
            return value, row.get("time_tag"), len(rows)
    return None, None, len(rows)


def latest_solar_wind_speed(payload: Any) -> tuple[float | None, str | None, int]:
    rows = _rows(payload)
    for row in reversed(rows):
        value = _to_float(row.get("speed"))
        if value is not None:
            return value, row.get("time_tag"), len(rows)
    return None, None, len(rows)


def storm_scale(kp: float | int | None) -> str | None:
    if kp is None:
        return None
    if kp < 5:
        return "G0"
    if kp < 6:
        return "G1"
    if kp < 7:
        return "G2"
    if kp < 8:
        return "G3"
    if kp < 9:
        return "G4"
    return "G5"


def condition(kp: float | int | None) -> str:
    if kp is None:
        return "unavailable"
    if kp < 2:
        return "quiet"
    if kp < 3:
        return "unsettled"
    if kp < 5:
        return "active"
    if kp < 6:
        return "minor storm"
    if kp < 7:
        return "moderate storm"
    if kp < 8:
        return "strong storm"
    if kp < 9:
        return "severe storm"
    return "extreme storm"


def build_payload() -> dict[str, Any]:
    collected_at = _now_utc()
    fetched: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {"api_attempts": 0, "retries": 0, "http_status": {}, "sources": {}, "row_counts": {}}
    for name, url in SOURCES.items():
        diagnostics["api_attempts"] += 1
        fetched[name], source_diag = _fetch_json(url)
        diagnostics["sources"][name] = source_diag
        diagnostics["http_status"][name] = source_diag.get("http_status")

    kp, max_kp, kp_rows = latest_kp(fetched.get("kp"))
    bz_value, bz_time, mag_rows = latest_bz_gsm(fetched.get("mag"))
    speed_value, speed_time, plasma_rows = latest_solar_wind_speed(fetched.get("plasma"))
    diagnostics["row_counts"] = {"kp": kp_rows, "mag": mag_rows, "plasma": plasma_rows}

    kp_value = kp.get("value") if kp else None
    data_status = "ok" if kp_value is not None else ("partial" if any(fetched.values()) else "unavailable")
    status = "ok" if data_status in {"ok", "partial"} else "unavailable"
    scale = storm_scale(kp_value)
    cond = condition(kp_value)
    source = {"name": "NOAA Space Weather Prediction Center", "urls": SOURCES}
    summary = (
        f"Latest NOAA planetary Kp is {kp_value:g} ({scale}, {cond}); available-window maximum is {max_kp:g}."
        if kp_value is not None and max_kp is not None and scale is not None
        else "NOAA geomagnetic data was unavailable or incomplete at collection time."
    )
    return {
        "observer": OBSERVER,
        "date": _date_utc(),
        "status": status,
        "data_status": data_status,
        "source": source,
        "collected_at_utc": collected_at,
        "kp": kp,
        "storm_scale": scale,
        "condition": cond,
        "solar_wind": {"bz_gsm": bz_value, "bz_gsm_observed_at_utc": bz_time, "speed_km_s": speed_value, "speed_observed_at_utc": speed_time},
        "diagnostics": diagnostics,
        "summary": summary,
    }


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
