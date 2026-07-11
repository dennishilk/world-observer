"""Placeholder wsv adapter for East Frisia Water Observer."""
from __future__ import annotations

from config import SOURCES
from models import AdapterResult

ADAPTER_ID = "wsv"


def fetch() -> AdapterResult:
    """Return a structured pending result until live official-data integration exists."""
    return AdapterResult(
        adapter=ADAPTER_ID,
        status="adapter_pending",
        data_status="adapter_pending",
        observations={},
        diagnostics={
            "live_adapter_enabled": False,
            "api_attempts": 0,
            "retries": 0,
            "adapter_errors": [],
            "note": "Research documented; live downloads intentionally not implemented in this scaffolding task.",
        },
        source_research=SOURCES[ADAPTER_ID],
    )
