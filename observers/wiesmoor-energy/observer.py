#!/usr/bin/env python3
"""Aggregate public MaStR electricity-unit data for Wiesmoor.

Raw unit rows exist only in memory. The emitted JSON contains municipality-level
counts and installed power totals, never unit, address, or operator records.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable

OBSERVER = "wiesmoor-energy"
OVERVIEW_URL = "https://www.marktstammdatenregister.de/MaStR/Einheit/Einheiten/OeffentlicheEinheitenuebersicht"
DOWNLOAD_URL = "https://www.marktstammdatenregister.de/MaStR/Datendownload"
ENDPOINT = "https://www.marktstammdatenregister.de/MaStR/Einheit/EinheitJson/GetVerkleinerteOeffentlicheEinheitStromerzeugung"
LOCALITY = "Wiesmoor"
POSTAL_CODE = "26639"
PAGE_SIZE = 5000
MAX_PAGES = 10
MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 45
USER_AGENT = "world-observer/wiesmoor-energy (+https://github.com/dennishilk/world-observer)"
OPERATING_STATUS = "In Betrieb"

CARRIER_IDS = {
    "Solare Strahlungsenergie": "solar",
    "Wind": "wind",
    "Biomasse": "biomass",
    "Erdgas": "natural_gas",
    "Speicher": "storage",
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
    return number if number >= 0 else None


def parse_mastr_date(value: Any) -> str | None:
    """Return an ISO date from MaStR's public JSON date representation."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/", value.strip())
    if match:
        try:
            return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _request_page(page: int, page_size: int) -> tuple[dict[str, Any], dict[str, Any]]:
    params = {
        "sort": "EinheitMeldeDatum-desc",
        "page": str(page),
        "pageSize": str(page_size),
        "group": "",
        "filter": f"Ort~eq~'{LOCALITY}'",
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
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
            if not isinstance(payload, dict) or not isinstance(payload.get("Data"), list):
                raise ValueError("MaStR response has no Data list")
            return payload, {
                "api_attempts": attempts,
                "retries": retries,
                "http_status": last_status,
            }
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
        if attempt + 1 < MAX_ATTEMPTS:
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"MaStR public overview request failed: {last_error.__class__.__name__ if last_error else 'unknown error'}")


def collect_rows(fetch_page: Callable[[int, int], tuple[dict[str, Any], dict[str, Any]]] = _request_page) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_total = 0
    diagnostics = {"api_attempts": 0, "retries": 0, "http_status": None, "pages_fetched": 0}
    for page in range(1, MAX_PAGES + 1):
        payload, page_diagnostics = fetch_page(page, PAGE_SIZE)
        batch = [item for item in payload.get("Data", []) if isinstance(item, dict)]
        source_total = int(payload.get("Total") or len(batch))
        rows.extend(batch)
        diagnostics["api_attempts"] += int(page_diagnostics.get("api_attempts") or 0)
        diagnostics["retries"] += int(page_diagnostics.get("retries") or 0)
        diagnostics["http_status"] = page_diagnostics.get("http_status")
        diagnostics["pages_fetched"] += 1
        if len(rows) >= source_total or len(batch) < PAGE_SIZE:
            break
    if len(rows) < source_total:
        raise RuntimeError("MaStR result exceeded the bounded pagination limit")
    return rows[:source_total], source_total, diagnostics


def aggregate_rows(rows: list[dict[str, Any]], source_total: int) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {}
    commissioning: dict[int, dict[str, float | int]] = defaultdict(
        lambda: {"operational_units": 0, "installed_net_nominal_capacity_kw": 0.0}
    )
    retained = 0

    for row in rows:
        if str(row.get("Ort") or "").strip().casefold() != LOCALITY.casefold():
            continue
        if str(row.get("Plz") or "").strip() != POSTAL_CODE:
            continue
        retained += 1
        carrier_label = str(row.get("EnergietraegerName") or "Other / unspecified").strip()
        carrier_id = CARRIER_IDS.get(carrier_label, "other")
        category = categories.setdefault(
            carrier_id,
            {
                "id": carrier_id,
                "source_label": carrier_label,
                "listed_units": 0,
                "operational_units": 0,
                "installed_gross_capacity_kw_operational": 0.0,
                "installed_net_nominal_capacity_kw_operational": 0.0,
                "status_counts": Counter(),
                "commissioning_years": Counter(),
            },
        )
        category["listed_units"] += 1
        status = str(row.get("BetriebsStatusName") or "Unspecified").strip()
        category["status_counts"][status] += 1
        if status != OPERATING_STATUS:
            continue
        category["operational_units"] += 1
        gross = _number(row.get("Bruttoleistung"))
        net = _number(row.get("Nettonennleistung"))
        if gross is not None:
            category["installed_gross_capacity_kw_operational"] += gross
        if net is not None:
            category["installed_net_nominal_capacity_kw_operational"] += net
        commissioning_date = parse_mastr_date(row.get("InbetriebnahmeDatum"))
        if commissioning_date:
            year = int(commissioning_date[:4])
            category["commissioning_years"][year] += 1
            commissioning[year]["operational_units"] += 1
            if net is not None:
                commissioning[year]["installed_net_nominal_capacity_kw"] += net

    published_categories: list[dict[str, Any]] = []
    for category in categories.values():
        years = sorted(category.pop("commissioning_years"))
        category["status_counts"] = dict(sorted(category["status_counts"].items()))
        category["installed_gross_capacity_kw_operational"] = round(category["installed_gross_capacity_kw_operational"], 2)
        category["installed_net_nominal_capacity_kw_operational"] = round(category["installed_net_nominal_capacity_kw_operational"], 2)
        category["commissioning_year_range_for_operational_units"] = {
            "from": years[0] if years else None,
            "to": years[-1] if years else None,
        }
        published_categories.append(category)
    published_categories.sort(
        key=lambda item: (-item["installed_net_nominal_capacity_kw_operational"], item["id"])
    )

    history = [
        {
            "year": year,
            "operational_units": int(values["operational_units"]),
            "installed_net_nominal_capacity_kw": round(float(values["installed_net_nominal_capacity_kw"]), 2),
        }
        for year, values in sorted(commissioning.items())
    ]
    return {
        "source_rows_for_locality": source_total,
        "rows_retained_after_postal_code_filter": retained,
        "totals": {
            "listed_units": sum(item["listed_units"] for item in published_categories),
            "operational_units": sum(item["operational_units"] for item in published_categories),
            "installed_gross_capacity_kw_operational": round(sum(item["installed_gross_capacity_kw_operational"] for item in published_categories), 2),
            "installed_net_nominal_capacity_kw_operational": round(sum(item["installed_net_nominal_capacity_kw_operational"] for item in published_categories), 2),
        },
        "categories": published_categories,
        "commissioning_history": history,
    }


def _base_payload() -> dict[str, Any]:
    return {
        "observer": OBSERVER,
        "display_name": "Wiesmoor Energy Observer",
        "category": "technology",
        "date": _date_utc(),
        "date_utc": _date_utc(),
        "collected_at_utc": _now_utc(),
        "observation_mode": "daily_aggregate_of_public_register_rows",
        "geography": {
            "municipality": LOCALITY,
            "postal_code": POSTAL_CODE,
            "state": "Lower Saxony",
            "country": "Germany",
            "filter_note": "Exact locality and postal-code match; no address is retained or published.",
        },
        "measurement_definition": {
            "headline": "installed net nominal electrical capacity of units currently marked operational",
            "capacity_unit": "kW",
            "commissioning_history_definition": "currently operational units grouped by their source-listed commissioning year",
            "not_production": True,
        },
        "sources": [
            {
                "name": "Marktstammdatenregister — public units overview",
                "url": OVERVIEW_URL,
                "role": "official public register interface",
            },
            {
                "name": "Marktstammdatenregister — public data download",
                "url": DOWNLOAD_URL,
                "role": "official dataset and licence documentation",
                "licence": "Datenlizenz Deutschland – Namensnennung – Version 2.0",
            },
        ],
        "privacy": {
            "aggregation_level": "municipality and energy-carrier category",
            "unit_records_published": False,
            "addresses_published": False,
            "operator_names_published": False,
            "unit_identifiers_published": False,
        },
        "limitations": [
            "Installed capacity is not electricity production, generation, feed-in, or consumption.",
            "Register status and commissioning dates are source-reported public records and may be corrected later.",
            "The commissioning series is a grouping of currently operational units, not a historical snapshot of capacity that existed in each year.",
            "Storage values describe installed electrical power in kW, not stored energy in kWh.",
        ],
        "do_not_interpret_as": [
            "electricity production",
            "renewable share of local consumption",
            "grid feed-in",
            "a unit-level installation register",
        ],
        "update_policy": {"cadence": "daily", "source_mode": "official public no-login overview"},
    }


def build_payload(fetch_page: Callable[[int, int], tuple[dict[str, Any], dict[str, Any]]] = _request_page) -> dict[str, Any]:
    payload = _base_payload()
    try:
        rows, source_total, diagnostics = collect_rows(fetch_page)
        aggregate = aggregate_rows(rows, source_total)
    except Exception as exc:
        payload.update({
            "status": "unavailable",
            "data_status": "unavailable",
            "totals": {},
            "categories": [],
            "commissioning_history": [],
            "diagnostics": {
                "api_attempts": 0,
                "retries": 0,
                "http_status": None,
                "error_type": exc.__class__.__name__,
            },
        })
        return payload
    payload.update(aggregate)
    payload.update({
        "status": "ok",
        "data_status": "ok",
        "diagnostics": {
            **diagnostics,
            "raw_rows_retained_after_aggregation": 0,
            "published_category_count": len(aggregate["categories"]),
        },
    })
    return payload


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
