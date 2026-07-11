"""Live DWD CDC recent daily KL precipitation adapter for East Frisia."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from observers.shared import dwd_daily_kl
from config import DWD_CONFIG, SOURCES
from models import AdapterResult

ADAPTER_ID = "dwd"
USER_AGENT = "WorldObserver/1.0 EastFrisiaWaterObserver"


def _unavailable(diagnostics: dict[str, Any], message: str) -> AdapterResult:
    diagnostics.setdefault("adapter_errors", []).append(message)
    return AdapterResult(
        adapter=ADAPTER_ID,
        status="unavailable",
        data_status="unavailable",
        observations={},
        diagnostics=diagnostics,
        source_research=SOURCES[ADAPTER_ID],
    )


def _station_metadata() -> dict[str, Any]:
    return {
        "station_id": DWD_CONFIG["station_id"],
        "station_name": DWD_CONFIG["station_name"],
        "latitude": DWD_CONFIG["station_latitude"],
        "longitude": DWD_CONFIG["station_longitude"],
        "state": DWD_CONFIG["station_state"],
        "selection_method": DWD_CONFIG["station_selection_reason"],
    }


def build_observations(rows: list[dict[str, Any]], source_url: str) -> dict[str, Any]:
    if not rows:
        raise ValueError("DWD daily climate product contained no observations")
    if not any(row.get("precip_mm") is not None for row in rows):
        raise ValueError("DWD daily climate product contained no valid precipitation values")
    latest = rows[-1]
    latest_date = latest["date"]
    total_7d, valid_7d, expected_7d = dwd_daily_kl.rolling_total(rows, latest_date, 7, DWD_CONFIG["min_coverage_7d"])
    total_30d, valid_30d, expected_30d = dwd_daily_kl.rolling_total(rows, latest_date, 30, DWD_CONFIG["min_coverage_30d"])
    return {
        "source_organization": "Deutscher Wetterdienst (DWD)",
        "source_name": "CDC recent daily climate observations Germany (KL)",
        "source_endpoint_type": "official_dwd_cdc_recent_daily_kl_zip_csv",
        "source_url": source_url,
        "proxy_label": "inland/central East Frisia rainfall proxy",
        "proxy_note": "DWD station daily precipitation is meteorological context for inland/central East Frisia, not an in-situ water-level or flood-warning measurement.",
        "station": _station_metadata(),
        "latest_date": latest_date.isoformat(),
        "latest_rainfall_mm": latest["precip_mm"],
        "rainfall_7d_total_mm": total_7d,
        "rainfall_30d_total_mm": total_30d,
        "coverage": {
            "valid_days_7d": valid_7d,
            "expected_days_7d": expected_7d,
            "minimum_valid_days_7d": DWD_CONFIG["min_coverage_7d"],
            "valid_days_30d": valid_30d,
            "expected_days_30d": expected_30d,
            "minimum_valid_days_30d": DWD_CONFIG["min_coverage_30d"],
        },
        "quality_rules": {
            "missing_markers": sorted(dwd_daily_kl.MISSING_VALUES),
            "valid_zero_rainfall_mm": True,
            "seven_day_total_requires_valid_days": DWD_CONFIG["min_coverage_7d"],
            "thirty_day_total_minimum_valid_days": DWD_CONFIG["min_coverage_30d"],
        },
    }


def fetch() -> AdapterResult:
    """Fetch daily rainfall from official DWD CDC recent KL ZIP/CSV."""
    diag = dwd_daily_kl.DwdDiagnostics(adapter_errors=[])
    url = dwd_daily_kl.station_zip_url(DWD_CONFIG["station_id"], DWD_CONFIG["base_url"])
    diagnostics: dict[str, Any] = {
        "live_adapter_enabled": True,
        "api_attempts": 0,
        "retries": 0,
        "adapter_errors": [],
        "endpoint_types": ["recent_daily_kl_zip_csv"],
        "source_endpoint_type": "official_dwd_cdc_recent_daily_kl_zip_csv",
        "timeout_seconds": DWD_CONFIG["timeout_seconds"],
        "max_retries": DWD_CONFIG["max_retries"],
        "live_adapters_enabled": [ADAPTER_ID],
    }
    try:
        data = dwd_daily_kl.fetch_url(
            url,
            diag,
            timeout_seconds=DWD_CONFIG["timeout_seconds"],
            max_retries=DWD_CONFIG["max_retries"],
            user_agent=USER_AGENT,
        )
        rows = dwd_daily_kl.parse_daily_product(data)
        observations = build_observations(rows, url)
    except Exception as exc:
        diagnostics.update(diag.as_dict())
        return _unavailable(diagnostics, f"dwd_fetch_failed: {exc}")
    diagnostics.update(diag.as_dict())
    return AdapterResult(adapter=ADAPTER_ID, status="live", data_status="available", observations=observations, diagnostics=diagnostics, source_research=SOURCES[ADAPTER_ID])
