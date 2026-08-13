#!/usr/bin/env python3
"""Publish source-labelled Wiesmoor municipal finance values."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OBSERVER = "wiesmoor-finance"
SOURCE_DATA = Path(__file__).with_name("source_data.json")
VALID_STATUSES = {"PLAN", "ACTUAL", "FORECAST"}


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
        raise ValueError("finance reference root must be an object")
    periods = payload.get("reporting_periods")
    if not isinstance(periods, list) or not periods:
        raise ValueError("finance reference must contain reporting periods")
    years = []
    for period in periods:
        if not isinstance(period, dict) or period.get("value_status") not in VALID_STATUSES:
            raise ValueError("every finance period needs an explicit PLAN, ACTUAL, or FORECAST status")
        year = period.get("fiscal_year")
        if not isinstance(year, int):
            raise ValueError("finance period year must be an integer")
        years.append(year)
        result = period.get("result_budget_eur")
        cash = period.get("cash_flow_eur")
        if not isinstance(result, dict) or not isinstance(cash, dict):
            raise ValueError("every finance period needs result-budget and cash-flow objects")
        if round(result["ordinary_revenue"] - result["ordinary_expense"], 2) != round(result["ordinary_result"], 2):
            raise ValueError(f"ordinary result does not reconcile for {year}")
        if round(result["ordinary_result"] + result["extraordinary_result"], 2) != round(result["overall_result"], 2):
            raise ValueError(f"overall result does not reconcile for {year}")
        if round(cash["total_inflows"] - cash["total_outflows"], 2) != round(cash["total_balance"], 2):
            raise ValueError(f"cash-flow balance does not reconcile for {year}")
    if years != sorted(years) or len(years) != len(set(years)):
        raise ValueError("finance years must be unique and sorted")
    document = payload.get("document")
    if not isinstance(document, dict) or not document.get("source_url") or not document.get("source_index_url"):
        raise ValueError("finance reference needs official document provenance")
    return payload


def build_payload(path: Path = SOURCE_DATA) -> dict[str, Any]:
    reference = load_reference(path)
    periods = reference["reporting_periods"]
    plan_2026 = next(item for item in periods if item["fiscal_year"] == 2026 and item["value_status"] == "PLAN")
    return {
        "observer": OBSERVER,
        "display_name": "Wiesmoor City Finance Observer",
        "category": "society",
        "date": _date_utc(),
        "date_utc": _date_utc(),
        "collected_at_utc": _now_utc(),
        "status": "ok",
        "data_status": "ok",
        "observation_mode": "official_budget_document_snapshot",
        "geography": {
            "municipality": "Wiesmoor",
            "municipality_code_ags": "03452025",
            "state": "Lower Saxony",
            "country": "Germany",
        },
        "document": reference["document"],
        "status_taxonomy": {
            "ACTUAL": "audited/accounting result labelled Rechnungsergebnis in the source document",
            "PLAN": "budget appropriation labelled Ansatz for the budget year",
            "FORECAST": "medium-term financial-planning amount for a future year",
        },
        "latest_budget_plan": {
            "fiscal_year": 2026,
            "value_status": "PLAN",
            "result_budget_eur": plan_2026["result_budget_eur"],
            "cash_flow_eur": plan_2026["cash_flow_eur"],
            **reference["headline_plan_2026_eur"],
        },
        "reporting_periods": periods,
        "sources": [
            {"name": "City of Wiesmoor — Finanzen", "url": reference["document"]["source_index_url"], "role": "official budget-document index"},
            {"name": reference["document"]["title"], "url": reference["document"]["source_url"], "role": "official values and status labels"},
        ],
        "update_policy": {
            "cadence": "on publication of a new official budget or annual result",
            "current_document_fiscal_year": reference["document"]["fiscal_year"],
        },
        "limitations": [
            "PLAN, ACTUAL, and FORECAST values are never merged or presented as the same measurement status.",
            "The 2024 ACTUAL values and 2025-2029 PLAN/FORECAST values are transcribed from the official 2026 budget document and may be superseded by later official documents.",
            "Budget values do not describe live bank balances or current spending execution.",
        ],
        "do_not_interpret_as": [
            "2026 actual spending or revenue",
            "a live municipal cash position",
            "a prediction by World Observer",
            "financial advice or a credit rating",
        ],
        "diagnostics": {
            "api_attempts": 0,
            "retries": 0,
            "http_status": None,
            "reporting_period_count": len(periods),
            "reconciliation_checks": "passed",
        },
    }


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
