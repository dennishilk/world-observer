"""IPv6 adoption observer for locked states.

This observer checks native IPv6 availability by performing two measurements:
1) DNS AAAA lookup
2) TCP handshake to port 443 using IPv6
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import socket
from typing import Any, Dict, List, Tuple

MODULE_DIR = Path(__file__).resolve().parent
TARGETS_PATH = MODULE_DIR / "targets.json"
OBSERVER_NAME = "ipv6-adoption-locked-states"
TCP_PORT = 443
TCP_TIMEOUT_SECONDS = 3.0


def load_targets() -> List[Dict[str, Any]]:
    """Load country target definitions from targets.json."""

    if not TARGETS_PATH.exists():
        raise FileNotFoundError(f"Missing targets.json at {TARGETS_PATH}")
    with TARGETS_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("targets.json must contain a list of country entries")
    return data


def resolve_ipv6(host: str) -> Tuple[List[str], str | None]:
    """Resolve IPv6 addresses (AAAA) for a host."""

    try:
        addrinfo = socket.getaddrinfo(host, None, socket.AF_INET6, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return [], f"DNS AAAA lookup failed: {exc}"

    addresses = []
    for entry in addrinfo:
        sockaddr = entry[4]
        if sockaddr and isinstance(sockaddr, tuple):
            addresses.append(sockaddr[0])

    unique_addresses = sorted(set(addresses))
    if not unique_addresses:
        return [], "No AAAA records returned"
    return unique_addresses, None


def tcp_handshake_ipv6(address: str, port: int = TCP_PORT) -> Tuple[bool, str | None]:
    """Attempt a single TCP handshake over IPv6."""

    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
            sock.settimeout(TCP_TIMEOUT_SECONDS)
            sock.connect((address, port, 0, 0))
        return True, None
    except OSError as exc:
        return False, f"TCP handshake failed: {exc}"


def evaluate_target(host: str) -> Dict[str, Any]:
    """Evaluate a target host for IPv6 availability."""

    addresses, dns_error = resolve_ipv6(host)
    if not addresses:
        return {
            "aaaa_present": False,
            "tcp_443": False,
            "ipv6_available": False,
            "error": dns_error,
        }

    tcp_success, tcp_error = tcp_handshake_ipv6(addresses[0])
    return {
        "aaaa_present": True,
        "tcp_443": tcp_success,
        "ipv6_available": tcp_success,
        "error": tcp_error,
    }


def run() -> Dict[str, Any]:
    """Run the observer and return a structured observation."""

    timestamp = datetime.now(timezone.utc).isoformat()
    country_entries = load_targets()
    countries: List[Dict[str, Any]] = []

    for entry in country_entries:
        country_code = entry.get("country", "XX")
        targets = entry.get("targets", [])
        if not isinstance(targets, list):
            targets = []

        targets_tested = 0
        ipv6_available_targets = 0

        for target in targets:
            host = target.get("host", "")
            targets_tested += 1
            if not host:
                continue
            evaluation = evaluate_target(host)
            if evaluation["ipv6_available"]:
                ipv6_available_targets += 1

        countries.append(
            {
                "country": country_code,
                "targets_tested": targets_tested,
                "ipv6_available_targets": ipv6_available_targets,
                "ipv6_available": ipv6_available_targets > 0,
            }
        )

    return {
        "observer": OBSERVER_NAME,
        "timestamp": timestamp,
        "countries": countries,
        "notes": (
            "IPv6 availability requires both AAAA resolution and a single TCP 443 "
            "handshake over native IPv6. No retries, tunneling, NAT64, or IPv4 fallback."
        ),
    }


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    print(json.dumps(run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
