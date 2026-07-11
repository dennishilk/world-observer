#!/usr/bin/env python3
"""East Frisia Water Observer.

Architectural scaffold for an Environment observer covering water-related
signals in East Frisia. This first version performs no live downloads; every
adapter returns a structured pending result while preserving the final observer
payload shape and diagnostics expected by long-term integrations.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from adapters import bsh, dwd, nlwkn, wsv
from config import CATEGORY, LIVE_ADAPTERS_ENABLED, MAX_RETRIES, OBSERVER, OBSERVER_NAME, REGION
from models import AdapterResult

AdapterFetch = Callable[[], AdapterResult]
ADAPTERS: tuple[AdapterFetch, ...] = (dwd.fetch, nlwkn.fetch, wsv.fetch, bsh.fetch)


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


def _run_adapter(fetch: AdapterFetch) -> dict[str, Any]:
    try:
        return fetch().to_payload()
    except Exception as exc:  # defensive diagnostics boundary between adapters
        adapter_name = getattr(fetch, "__module__", "unknown").split(".")[-1]
        return {
            "adapter": adapter_name,
            "status": "adapter_error",
            "data_status": "unavailable",
            "observations": {},
            "diagnostics": {
                "live_adapter_enabled": LIVE_ADAPTERS_ENABLED,
                "api_attempts": 0,
                "retries": 0,
                "adapter_errors": [f"{exc.__class__.__name__}: {exc}"],
            },
        }


def build_payload() -> dict[str, Any]:
    adapter_payloads = [_run_adapter(fetch) for fetch in ADAPTERS]
    adapter_errors = {
        item["adapter"]: item.get("diagnostics", {}).get("adapter_errors", [])
        for item in adapter_payloads
        if item.get("diagnostics", {}).get("adapter_errors")
    }
    api_attempts = sum(int(item.get("diagnostics", {}).get("api_attempts", 0)) for item in adapter_payloads)
    retries = sum(int(item.get("diagnostics", {}).get("retries", 0)) for item in adapter_payloads)
    data_status = "adapter_pending" if all(item.get("data_status") == "adapter_pending" for item in adapter_payloads) else "partial"

    return {
        "observer": OBSERVER,
        "name": OBSERVER_NAME,
        "category": CATEGORY,
        "region": REGION,
        "date": _date_utc(),
        "date_utc": _date_utc(),
        "generated_at_utc": _now_utc(),
        "data_status": data_status,
        "live_adapters_enabled": LIVE_ADAPTERS_ENABLED,
        "adapters": adapter_payloads,
        "diagnostics": {
            "data_status": data_status,
            "live_adapters_enabled": LIVE_ADAPTERS_ENABLED,
            "adapter_errors": adapter_errors,
            "api_attempts": api_attempts,
            "retries": retries,
            "max_retries": MAX_RETRIES,
        },
        "recommendation": {
            "integrate_first": "nlwkn",
            "reason": "NLWKN Pegelonline is the most local official hydrological source for Lower Saxony inland and coastal gauges; integrate DWD next for meteorological context and WSV/BSH after station selection is settled.",
        },
    }


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
