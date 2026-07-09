#!/usr/bin/env python3
"""Wiesmoor Sky Observer.

Calculates local Sun/Moon geometry for Wiesmoor without weather APIs or
external network dependencies.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

OBSERVER = "wiesmoor-sky-observer"
LATITUDE = 53.4167
LONGITUDE = 7.7333
TIMEZONE = "Europe/Berlin"
DISCLAIMER = "Astronomical darkness is calculated from Sun/Moon geometry only. Clouds, fog and local weather are not included."
J2000 = 2451545.0
ZENITH_THRESHOLDS = {
    "sunrise_sunset": -0.833,
    "civil": -6.0,
    "nautical": -12.0,
    "astronomical": -18.0,
}


def _date_utc() -> str:
    raw = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def _now_utc() -> datetime:
    raw = os.environ.get("WORLD_OBSERVER_NOW_UTC", "").strip()
    if raw:
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc).replace(microsecond=0)


def _jd(dt: datetime) -> float:
    dt = dt.astimezone(timezone.utc)
    y, m = dt.year, dt.month
    d = dt.day + (dt.hour + (dt.minute + (dt.second + dt.microsecond / 1_000_000) / 60) / 60) / 24
    if m <= 2:
        y -= 1
        m += 12
    a = math.floor(y / 100)
    b = 2 - a + math.floor(a / 4)
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5


def _norm(deg: float) -> float:
    return deg % 360.0


def _sun_ra_dec(jd: float) -> tuple[float, float, float]:
    n = jd - J2000
    l = _norm(280.460 + 0.9856474 * n)
    g = math.radians(_norm(357.528 + 0.9856003 * n))
    lam = math.radians(_norm(l + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)))
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360
    dec = math.degrees(math.asin(math.sin(eps) * math.sin(lam)))
    ecl_lon = math.degrees(lam) % 360
    return ra, dec, ecl_lon


def _moon_ra_dec(jd: float) -> tuple[float, float, float]:
    d = jd - J2000
    l = _norm(218.316 + 13.176396 * d)
    m = math.radians(_norm(134.963 + 13.064993 * d))
    f = math.radians(_norm(93.272 + 13.229350 * d))
    lon = math.radians(_norm(l + 6.289 * math.sin(m)))
    lat = math.radians(5.128 * math.sin(f))
    eps = math.radians(23.439 - 0.0000004 * d)
    x = math.cos(lon) * math.cos(lat)
    y = math.sin(lon) * math.cos(lat) * math.cos(eps) - math.sin(lat) * math.sin(eps)
    z = math.sin(lon) * math.cos(lat) * math.sin(eps) + math.sin(lat) * math.cos(eps)
    ra = math.degrees(math.atan2(y, x)) % 360
    dec = math.degrees(math.asin(z))
    return ra, dec, math.degrees(lon) % 360


def _altitude(dt: datetime, body: str) -> float:
    jd = _jd(dt)
    ra, dec, _lon = _sun_ra_dec(jd) if body == "sun" else _moon_ra_dec(jd)
    t = (jd - J2000) / 36525.0
    gmst = _norm(280.46061837 + 360.98564736629 * (jd - J2000) + 0.000387933 * t * t - t * t * t / 38710000)
    lst = _norm(gmst + LONGITUDE)
    ha = math.radians(((lst - ra + 540) % 360) - 180)
    lat = math.radians(LATITUDE)
    dec_r = math.radians(dec)
    return math.degrees(math.asin(math.sin(lat) * math.sin(dec_r) + math.cos(lat) * math.cos(dec_r) * math.cos(ha)))


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(ZoneInfo(TIMEZONE)).replace(microsecond=0).isoformat()


def _events(local_day: date, body: str, threshold: float) -> list[datetime]:
    tz = ZoneInfo(TIMEZONE)
    start = datetime.combine(local_day, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    step = timedelta(minutes=5)
    events: list[datetime] = []
    prev_t = start
    prev_v = _altitude(prev_t, body) - threshold
    t = start + step
    while t <= end:
        v = _altitude(t, body) - threshold
        if prev_v == 0 or (prev_v < 0 <= v) or (prev_v > 0 >= v):
            lo, hi = prev_t, t
            for _ in range(24):
                mid = lo + (hi - lo) / 2
                mv = _altitude(mid, body) - threshold
                if (prev_v <= 0 < mv) or (prev_v >= 0 > mv):
                    hi = mid
                else:
                    lo = mid
                    prev_v = mv
            events.append(hi)
        prev_t, prev_v = t, v
        t += step
    return events


def _rise_set(local_day: date, body: str, threshold: float) -> tuple[datetime | None, datetime | None]:
    ev = _events(local_day, body, threshold)
    if not ev:
        return None, None
    pairs = [(e, _altitude(e + timedelta(minutes=1), body) > threshold) for e in ev]
    rise = next((e for e, rising in pairs if rising), None)
    set_ = next((e for e, rising in pairs if not rising), None)
    return rise, set_


def _sun_morning_evening(local_day: date, threshold: float) -> tuple[datetime | None, datetime | None]:
    """Return morning upward and following evening/downward Sun threshold crossings."""
    events = _events(local_day, "sun", threshold) + _events(local_day + timedelta(days=1), "sun", threshold)
    pairs = [(e, _altitude(e + timedelta(minutes=1), "sun") > threshold) for e in sorted(events)]
    morning = next((e for e, rising in pairs if rising and e.astimezone(ZoneInfo(TIMEZONE)).date() == local_day), None)
    evening = next((e for e, rising in pairs if not rising and (morning is None or e > morning)), None)
    return morning, evening


def _phase(age: float) -> str:
    names = [(1.845, "New Moon"), (5.536, "Waxing Crescent"), (9.228, "First Quarter"), (12.919, "Waxing Gibbous"), (16.611, "Full Moon"), (20.302, "Waning Gibbous"), (23.994, "Last Quarter"), (27.685, "Waning Crescent"), (29.531, "New Moon")]
    return next(name for limit, name in names if age < limit)


def _moon_details(now: datetime) -> dict[str, Any]:
    synodic = 29.53058867
    age = ((_jd(now) - 2451550.1) % synodic)
    illum = (1 - math.cos(2 * math.pi * age / synodic)) / 2 * 100
    return {"phase_name": _phase(age), "illumination_percent": round(illum, 1), "age_days": round(age, 2)}


def _interval_overlap(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> tuple[datetime, datetime] | None:
    start, end = max(a[0], b[0]), min(a[1], b[1])
    return (start, end) if start < end else None


def build_payload() -> dict[str, Any]:
    target = datetime.strptime(_date_utc(), "%Y-%m-%d").date()
    now = _now_utc()
    sunrise, sunset = _sun_morning_evening(target, ZENITH_THRESHOLDS["sunrise_sunset"])
    civil_start, civil_end = _sun_morning_evening(target, ZENITH_THRESHOLDS["civil"])
    nautical_start, nautical_end = _sun_morning_evening(target, ZENITH_THRESHOLDS["nautical"])
    astro_start, astro_end = _sun_morning_evening(target, ZENITH_THRESHOLDS["astronomical"])
    moonrise, moonset = _rise_set(target, "moon", 0.125)

    # Tonight means from today's astronomical twilight end to tomorrow's astronomical twilight start.
    tomorrow = target + timedelta(days=1)
    next_astro_start, _ = _sun_morning_evening(tomorrow, ZENITH_THRESHOLDS["astronomical"])
    darkness = (astro_end, next_astro_start) if astro_end and next_astro_start and astro_end < next_astro_start else None
    moon_up_events = _events(target, "moon", 0.125) + _events(tomorrow, "moon", 0.125)
    boundaries = [darkness[0], darkness[1]] + [e for e in moon_up_events if darkness and darkness[0] < e < darkness[1]] if darkness else []
    windows: list[tuple[datetime, datetime]] = []
    if darkness:
        for a, b in zip(boundaries, boundaries[1:]):
            mid = a + (b - a) / 2
            if _altitude(mid, "moon") <= 0.125:
                windows.append((a, b))
    best = max(windows, key=lambda w: w[1] - w[0], default=darkness)
    moon = _moon_details(now)
    moon_alt = _altitude(now, "moon")
    interference = "low" if moon_alt <= 0 or moon["illumination_percent"] < 25 else "moderate" if moon["illumination_percent"] < 70 else "high"
    quality = "excellent" if darkness and interference == "low" else "good" if darkness and interference == "moderate" else "limited" if darkness else "no astronomical darkness"
    return {
        "observer": OBSERVER,
        "date": target.isoformat(),
        "status": "ok",
        "data_status": "ok",
        "description": "Local astronomical conditions above Wiesmoor.",
        "collected_at_utc": now.isoformat().replace("+00:00", "Z"),
        "location": {"name": "Wiesmoor, Lower Saxony, Germany", "latitude": LATITUDE, "longitude": LONGITUDE, "timezone": TIMEZONE},
        "source": {"name": "Local Sun/Moon geometry calculation", "network_dependency": False, "weather_api_dependency": False},
        "disclaimer": DISCLAIMER,
        "sun": {"sunrise": _iso(sunrise), "sunset": _iso(sunset), "civil_twilight_start": _iso(civil_start), "civil_twilight_end": _iso(civil_end), "nautical_twilight_start": _iso(nautical_start), "nautical_twilight_end": _iso(nautical_end), "astronomical_twilight_start": _iso(astro_start), "astronomical_twilight_end": _iso(astro_end), "current_altitude_degrees": round(_altitude(now, "sun"), 2)},
        "moon": {**moon, "moonrise": _iso(moonrise), "moonset": _iso(moonset), "current_altitude_degrees": round(moon_alt, 2)},
        "astronomical_night": {"available": darkness is not None, "astronomical_darkness_window": {"start": _iso(darkness[0]) if darkness else None, "end": _iso(darkness[1]) if darkness else None}, "best_astronomical_darkness_window_tonight": {"start": _iso(best[0]) if best else None, "end": _iso(best[1]) if best else None}, "moon_interference_classification": interference, "night_quality_classification": quality},
        "diagnostics": {"api_attempts": 0, "retries": 0, "http_status": None, "calculation": "local", "weather_api_dependency": False},
        "summary": f"Astronomical darkness window for Wiesmoor is {'available' if darkness else 'not available'}; moon interference is {interference}. {DISCLAIMER}",
    }


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
