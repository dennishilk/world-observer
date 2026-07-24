#!/usr/bin/env python3
"""Collect a conservative static-data snapshot for the Time Observer.

This observer does not obtain a clock reading for website visitors.  It fetches
slowly changing reference data so the separate static website can explain the
relationship of TAI, UTC, and UT1 without calling a public time API at runtime.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import Any

OBSERVER = "time-observer"
TIMEOUT_S = 20
# IERS distributes both machine-readable files.  The finals file is a
# combination of observations and predictions; the parser retains that state.
SOURCES = {
    "earth_orientation": "https://maia.usno.navy.mil/ser7/finals2000A.all",
    "leap_seconds": "https://hpiers.obspm.fr/iers/bul/bulc/Leap_Second.dat",
}


def _date_utc() -> date:
    raw = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date()


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fetch_text(url: str, timeout_s: int = TIMEOUT_S) -> tuple[str | None, dict[str, Any]]:
    diagnostic: dict[str, Any] = {"url": url, "ok": False, "http_status": None, "error": None}
    request = urllib.request.Request(url, headers={"User-Agent": "world-observer/time-observer"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            text = response.read().decode("ascii", errors="replace")
            diagnostic["http_status"] = response.status
    except urllib.error.HTTPError as exc:
        diagnostic.update({"http_status": exc.code, "error": f"HTTP {exc.code}"})
        return None, diagnostic
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        diagnostic["error"] = exc.__class__.__name__
        return None, diagnostic
    diagnostic["ok"] = True
    return text, diagnostic


def mjd_for_date(value: date) -> int:
    """Return Modified Julian Date at 00:00 UTC without a third-party library."""
    return (value - date(1858, 11, 17)).days


def date_for_mjd(value: int) -> date:
    return date.fromordinal(date(1858, 11, 17).toordinal() + value)


def parse_finals2000a(text: str) -> list[dict[str, Any]]:
    """Extract UT1−UTC records from IERS finals2000A fixed-width rows.

    The second I/P quality flag in each row belongs to UT1−UTC.  Splitting on
    whitespace is deliberate: the source uses fixed widths but its published
    whitespace is stable and this keeps missing optional trailing fields safe.
    """
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 9:
            continue
        try:
            mjd = int(float(parts[3]))
        except (IndexError, ValueError):
            continue
        flags = [index for index, item in enumerate(parts) if item in {"I", "P"}]
        if len(flags) < 2:
            continue
        flag_index = flags[1]
        try:
            dut1 = float(parts[flag_index + 1])
        except (IndexError, ValueError):
            continue
        records.append({"mjd": mjd, "ut1_minus_utc_seconds": dut1, "status": "observed" if parts[flag_index] == "I" else "predicted"})
    return records


LEAP_SECOND_RE = re.compile(r"^\s*(?P<mjd>\d+(?:\.\d+)?)\s+\d+\s+\d+\s+(?P<year>\d{4})\s+.*?(?P<offset>\d+)s\s*$")


def parse_leap_seconds(text: str) -> list[dict[str, Any]]:
    """Parse IERS Bulletin C's compact TAI−UTC history without guessing dates."""
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = LEAP_SECOND_RE.match(line)
        if not match:
            continue
        mjd = int(float(match.group("mjd")))
        effective_date = date_for_mjd(mjd)
        entries.append({"effective_date": effective_date.isoformat(), "tai_minus_utc_seconds": int(match.group("offset")), "mjd": mjd})
    return sorted(entries, key=lambda item: item["mjd"])


def select_eop_record(records: list[dict[str, Any]], observation_date: date) -> dict[str, Any] | None:
    """Prefer the requested day; otherwise retain the newest available record."""
    if not records:
        return None
    target = mjd_for_date(observation_date)
    exact = next((record for record in records if record["mjd"] == target), None)
    return exact or max(records, key=lambda record: record["mjd"])


def tai_minus_utc(entries: list[dict[str, Any]], observation_date: date) -> int | None:
    applicable = [entry for entry in entries if entry["effective_date"] <= observation_date.isoformat()]
    return applicable[-1]["tai_minus_utc_seconds"] if applicable else None


def build_payload() -> dict[str, Any]:
    observation_date = _date_utc()
    collected_at = _now_utc()
    finals_text, finals_diagnostic = _fetch_text(SOURCES["earth_orientation"])
    leaps_text, leaps_diagnostic = _fetch_text(SOURCES["leap_seconds"])
    eop = select_eop_record(parse_finals2000a(finals_text or ""), observation_date)
    leap_history = parse_leap_seconds(leaps_text or "")
    tai_utc = tai_minus_utc(leap_history, observation_date)
    eop_date = date_for_mjd(eop["mjd"]).isoformat() if eop else None
    age_days = mjd_for_date(observation_date) - eop["mjd"] if eop else None
    eop_status = eop["status"] if eop and eop["mjd"] >= mjd_for_date(observation_date) else ("recent_authoritative_data" if eop else "data_unavailable")
    data_status = "ok" if eop and tai_utc is not None else ("partial" if eop or tai_utc is not None else "unavailable")
    return {
        "observer": OBSERVER,
        "date": observation_date.isoformat(),
        "status": "ok" if data_status != "unavailable" else "unavailable",
        "data_status": data_status,
        "generated_at_utc": collected_at,
        "refresh_cadence": "daily; IERS Earth-orientation data is checked once per daily World Observer run. Leap-second history is revalidated in the same run despite changing only on IERS announcements.",
        "time_scales": {"tai_minus_utc_seconds": tai_utc, "classification": "recent_authoritative_data" if tai_utc is not None else "data_unavailable"},
        "earth_orientation": {
            "ut1_minus_utc_seconds": eop["ut1_minus_utc_seconds"] if eop else None,
            "value_date": eop_date,
            "status": eop_status,
            "age_days": age_days,
            "classification": "recent_authoritative_data" if eop else "data_unavailable",
        },
        "leap_seconds": leap_history,
        "provenance": [
            {"organization": "IERS", "dataset": "finals2000A", "url": SOURCES["earth_orientation"], "purpose": "UT1−UTC Earth-orientation values; observed/predicted flag retained."},
            {"organization": "IERS", "dataset": "Leap_Second.dat / Bulletin C", "url": SOURCES["leap_seconds"], "purpose": "TAI−UTC history and leap-second effective dates."},
            {"organization": "BIPM", "dataset": "UTC and TAI explanatory material", "url": "https://www.bipm.org/en/time-frequency/utc", "purpose": "Civil and atomic-time context; not scraped by this observer."},
            {"organization": "NIST", "dataset": "Time and frequency educational material", "url": "https://www.nist.gov/pml/time-and-frequency-division", "purpose": "Atomic-second educational context; not scraped by this observer."},
            {"organization": "PTB", "dataset": "Time and frequency", "url": "https://www.ptb.de/cms/en/fachabteilungen/abt4/fb-44.html", "purpose": "National-metrology context; not scraped by this observer."},
            {"organization": "IETF", "dataset": "RFC 5905", "url": "https://www.rfc-editor.org/rfc/rfc5905", "purpose": "NTP strata and timestamp-exchange explanation; not scraped by this observer."},
        ],
        "diagnostics": {"api_attempts": 2, "retries": 0, "http_status": {"earth_orientation": finals_diagnostic["http_status"], "leap_seconds": leaps_diagnostic["http_status"]}, "sources": {"earth_orientation": finals_diagnostic, "leap_seconds": leaps_diagnostic}, "eop_records_parsed": len(parse_finals2000a(finals_text or "")), "leap_entries_parsed": len(leap_history)},
        "uncertainty_note": "This snapshot is scientific context, not a clock service. A visitor's browser time must be labelled as a local system value; its offset from UTC is not measured by this export.",
    }


def main() -> int:
    print(json.dumps(build_payload(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
