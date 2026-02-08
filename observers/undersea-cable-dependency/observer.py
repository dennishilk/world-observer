"""Observer for undersea-cable-dependency.

This observer combines static undersea cable data with minimal reachability
checks to provide a structural dependency signal. It does not monitor live
cable status or infer outages.
"""

from __future__ import annotations

import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

OBSERVER_NAME = "undersea-cable-dependency"
MODULE_DIR = Path(__file__).resolve().parent
CABLES_PATH = MODULE_DIR / "cables.json"
TARGETS_PATH = MODULE_DIR / "targets.json"


def _iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _icmp_ping(hostname: str, timeout_s: int = 2) -> Optional[bool]:
    """Return True/False for ping reachability, or None if ping is unavailable."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout_s), hostname],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s + 1,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return result.returncode == 0


def _tcp_handshake(hostname: str, port: int = 443, timeout_s: int = 3) -> Optional[bool]:
    """Return True/False for TCP reachability, or None if unavailable."""
    try:
        with socket.create_connection((hostname, port), timeout=timeout_s):
            return True
    except (socket.timeout, OSError):
        return False


def _country_reachability(targets: List[str]) -> bool:
    """Return True if any target is reachable via ICMP or TCP 443."""
    for target in targets:
        ping_ok = _icmp_ping(target)
        tcp_ok = _tcp_handshake(target)
        if (ping_ok is True) or (tcp_ok is True):
            return True
    return False


def _summarize_country(entry: Dict[str, Any], targets: List[str]) -> Dict[str, Any]:
    cables = entry.get("cables", [])
    regions = {cable.get("region") for cable in cables if cable.get("region")}

    return {
        "country": entry.get("country"),
        "cable_count": len(cables),
        "distinct_regions": len(regions),
        "reachable": _country_reachability(targets),
    }


def run() -> Dict[str, Any]:
    """Run the observer and return the structured observation."""
    cable_entries = _load_json(CABLES_PATH)
    targets_payload = _load_json(TARGETS_PATH)
    targets = targets_payload.get("targets", [])

    countries = [_summarize_country(entry, targets) for entry in cable_entries]

    observation = {
        "observer": OBSERVER_NAME,
        "timestamp": _iso_timestamp(),
        "countries": countries,
        "notes": (
            "This output summarizes static undersea cable infrastructure and a "
            "minimal reachability check. It does not measure live cable status, "
            "route paths, or outages."
        ),
    }

    return observation


def main() -> None:
    """Serialize the observation to JSON on stdout."""
    observation = run()
    print(json.dumps(observation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
