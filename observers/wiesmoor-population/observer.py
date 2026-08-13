#!/usr/bin/env python3
"""Publish an official, annual population snapshot for Wiesmoor."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OBSERVER = "wiesmoor-population"
SOURCE_DATA = Path(__file__).with_name("source_data.json")


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


def load_reference(path: Path = SOURCE_DATA) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("population reference root must be an object")
    observations = payload.get("observations")
    if not isinstance(observations, list) or len(observations) < 2:
        raise ValueError("population reference must contain at least two observations")
    dates = [item.get("reference_date") for item in observations if isinstance(item, dict)]
    if len(dates) != len(observations) or dates != sorted(dates) or len(dates) != len(set(dates)):
        raise ValueError("population reference dates must be unique and sorted")
    for item in observations:
        if not isinstance(item.get("population"), int) or item["population"] <= 0:
            raise ValueError("population values must be positive integers")
        if item.get("male", 0) + item.get("female", 0) != item["population"]:
            raise ValueError("sex totals must equal the population total")
        if not item.get("census_basis") or not item.get("source_url"):
            raise ValueError("each population observation needs basis and provenance")
    return payload


def latest_comparable_change(observations: list[dict[str, Any]]) -> dict[str, Any]:
    for previous, current in reversed(list(zip(observations, observations[1:]))):
        if previous["census_basis"] != current["census_basis"]:
            continue
        change = current["population"] - previous["population"]
        return {
            "status": "comparable",
            "from_reference_date": previous["reference_date"],
            "to_reference_date": current["reference_date"],
            "absolute_change": change,
            "percent_change": round(change / previous["population"] * 100, 2),
            "census_basis": current["census_basis"],
        }
    return {"status": "unavailable"}


def build_payload(path: Path = SOURCE_DATA) -> dict[str, Any]:
    reference = load_reference(path)
    observations = reference["observations"]
    latest = observations[-1]
    previous = observations[-2]
    basis_break = previous["census_basis"] != latest["census_basis"]
    return {
        "observer": OBSERVER,
        "display_name": "Wiesmoor Population Observer",
        "category": "society",
        "date": _date_utc(),
        "date_utc": _date_utc(),
        "collected_at_utc": _now_utc(),
        "status": "ok",
        "data_status": "ok",
        "observation_mode": "annual_official_snapshot",
        "geography": reference["geography"],
        "latest_official_observation": latest,
        "history": observations,
        "year_on_year": {
            "latest_interval_status": "not_comparable_due_to_census_basis_change" if basis_break else "comparable",
            "suppressed_interval": {
                "from_reference_date": previous["reference_date"],
                "to_reference_date": latest["reference_date"],
                "reason": "census_basis_change",
                "from_basis": previous["census_basis"],
                "to_basis": latest["census_basis"],
            } if basis_break else None,
            "latest_comparable_change": latest_comparable_change(observations),
        },
        "update_policy": {
            "cadence": "annual",
            "trigger": "new official municipal year-end population publication",
            "latest_reference_date": latest["reference_date"],
        },
        "sources": [
            {
                "name": "Landesamt für Statistik Niedersachsen — population tables",
                "url": reference["source_landing_page"],
                "role": "official methodology and latest-publication index",
            },
            {
                "name": "Statistisches Bundesamt — Gemeindeverzeichnis annual snapshots",
                "url": latest["source_url"],
                "role": "official municipality-level values",
            },
        ],
        "limitations": [
            reference["method_note"],
            "This is an official year-end statistical population, not a live residents-register count.",
            "No demographic characteristic smaller than municipality-level male/female totals is published.",
        ],
        "do_not_interpret_as": [
            "real-time population",
            "municipal residents-register total",
            "a causal explanation of population change",
        ],
        "diagnostics": {
            "api_attempts": 0,
            "retries": 0,
            "http_status": None,
            "reference_records": len(observations),
            "reference_retrieved_at_utc": reference.get("retrieved_at_utc"),
        },
    }


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
