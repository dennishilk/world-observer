"""Reachability scoring observer for global-reachability-score."""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


MODULE_DIR = Path(__file__).resolve().parent
TARGETS_PATH = MODULE_DIR / "targets.json"


@dataclass(frozen=True)
class Observation:
    """Represents a single observation payload."""

    timestamp: str
    observer: str
    countries: List[Dict[str, Any]]
    notes: str


def _load_targets() -> List[Dict[str, Any]]:
    if not TARGETS_PATH.exists():
        raise FileNotFoundError(f"Missing targets.json at {TARGETS_PATH}")

    with TARGETS_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if isinstance(payload, dict):
        payload = [payload]

    if not isinstance(payload, list):
        raise ValueError("targets.json must contain a list of country entries")

    for entry in payload:
        if "country" not in entry or "targets" not in entry:
            raise ValueError("Each entry must include 'country' and 'targets'")
        if not isinstance(entry["targets"], list):
            raise ValueError("'targets' must be a list")

    return payload


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _ping_success(host: str, timeout_s: int = 2) -> bool:
    command = ["ping", "-c", "1", "-W", str(timeout_s), host]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False

    output = (result.stdout or "") + (result.stderr or "")
    if "Operation not permitted" in output or "Permission denied" in output:
        return False

    return result.returncode == 0


def _tcp_handshake_success(host: str, port: int = 443, timeout_s: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _dns_a_success(host: str, timeout_s: float = 3.0) -> bool:
    if _is_ip_address(host):
        return False

    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_s)
    try:
        results = socket.getaddrinfo(host, None, family=socket.AF_INET)
    except OSError:
        return False
    finally:
        socket.setdefaulttimeout(previous_timeout)

    return len(results) > 0


def _score_target(host: str) -> int:
    points = 0
    if _ping_success(host):
        points += 1
    if _tcp_handshake_success(host):
        points += 1
    if _dns_a_success(host):
        points += 1
    return points


def _score_country(entry: Dict[str, Any]) -> Dict[str, Any]:
    targets = entry.get("targets", [])
    total_points = 0

    for target in targets:
        host = target.get("host")
        if not host:
            continue
        total_points += _score_target(host)

    targets_tested = len(targets)
    max_score = targets_tested * 3
    score_percent = round((total_points / max_score) * 100, 2) if max_score else 0.0

    return {
        "country": entry.get("country", ""),
        "targets_tested": targets_tested,
        "max_score": max_score,
        "score": total_points,
        "score_percent": score_percent,
    }


def run() -> Observation:
    """Run the observer and return a structured observation."""

    timestamp = datetime.now(timezone.utc).isoformat()
    entries = _load_targets()

    countries = [_score_country(entry) for entry in entries]

    notes = (
        "Each target scores 1 point for ICMP ping, TCP 443 handshake, and DNS A lookup. "
        "Country score_percent = (score / max_score) * 100."
    )

    return Observation(
        timestamp=timestamp,
        observer="global-reachability-score",
        countries=countries,
        notes=notes,
    )


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    observation = run()
    print(json.dumps(observation.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    main()
