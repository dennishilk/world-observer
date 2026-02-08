"""Observer stub for cuba-internet-weather."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict


@dataclass(frozen=True)
class Observation:
    """Represents a single observation payload."""

    timestamp: str
    observer: str
    results: Dict[str, Any]


def run() -> Observation:
    """Run the observer and return a structured observation.

    This stub intentionally performs no active probing. It only returns
    a placeholder structure for future passive aggregation logic.
    """

    timestamp = datetime.now(timezone.utc).isoformat()
    results: Dict[str, Any] = {
        "status": "stub",
        "notes": "No passive data sources configured yet.",
    }
    return Observation(timestamp=timestamp, observer="cuba-internet-weather", results=results)


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    observation = run()
    print(json.dumps(observation.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    main()
