"""Shared models for the East Frisia Water Observer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceResearch:
    """Documented official source candidate for future live integration."""

    agency: str
    official_url: str
    available_datasets: list[str]
    update_frequency: str
    access_method: str
    expected_usefulness: str
    licensing: str
    long_term_stability: str


@dataclass(frozen=True)
class AdapterResult:
    """Structured adapter output used before and after live integrations exist."""

    adapter: str
    status: str = "adapter_pending"
    data_status: str = "adapter_pending"
    observations: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    source_research: SourceResearch | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "adapter": self.adapter,
            "status": self.status,
            "data_status": self.data_status,
            "observations": self.observations,
            "diagnostics": self.diagnostics,
        }
        if self.source_research is not None:
            payload["source_research"] = {
                "agency": self.source_research.agency,
                "official_url": self.source_research.official_url,
                "available_datasets": self.source_research.available_datasets,
                "update_frequency": self.source_research.update_frequency,
                "access_method": self.source_research.access_method,
                "expected_usefulness": self.source_research.expected_usefulness,
                "licensing": self.source_research.licensing,
                "long_term_stability": self.source_research.long_term_stability,
            }
        return payload
