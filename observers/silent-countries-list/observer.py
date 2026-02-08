"""Observer for identifying countries with minimal network response signals."""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


MODULE_DIR = Path(__file__).resolve().parent
TARGETS_PATH = MODULE_DIR / "targets.json"


@dataclass(frozen=True)
class Observation:
    """Represents the observer output payload."""

    observer: str
    timestamp: str
    countries: List[Dict[str, Any]]
    silent_countries: List[str]
    notes: str


def _load_targets() -> List[Dict[str, Any]]:
    with TARGETS_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("targets.json must contain a list of country entries")
    return payload


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _ping_host(host: str, timeout_s: int = 2) -> bool:
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


def _tcp_handshake(host: str, port: int = 443, timeout_s: float = 3.0) -> bool:
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            _ = time.monotonic() - start
            return True
    except OSError:
        return False


def _dns_a_lookup(host: str, timeout_s: float = 3.0) -> bool:
    if _is_ip_address(host):
        return False

    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_s)
    try:
        answers = socket.getaddrinfo(host, None, family=socket.AF_INET)
    except OSError:
        return False
    finally:
        socket.setdefaulttimeout(previous_timeout)

    return bool(answers)


def _observe_country(entry: Dict[str, Any]) -> Dict[str, Any]:
    country = entry.get("country")
    targets = entry.get("targets", [])

    signals = {
        "ping": False,
        "tcp_443": False,
        "dns": False,
    }

    for target in targets:
        host = target.get("host")
        if not host:
            continue

        if not signals["ping"]:
            signals["ping"] = _ping_host(host)
        if not signals["tcp_443"]:
            signals["tcp_443"] = _tcp_handshake(host)
        if not signals["dns"]:
            signals["dns"] = _dns_a_lookup(host)

        if all(signals.values()):
            break

    silent = not any(signals.values())
    return {
        "country": country,
        "silent": silent,
        "signals": signals,
    }


def run() -> Observation:
    """Run the observer and return a structured observation."""

    timestamp = datetime.now(timezone.utc).isoformat()
    entries = _load_targets()

    countries = [_observe_country(entry) for entry in entries]
    silent_countries = [entry["country"] for entry in countries if entry["silent"]]

    notes = (
        "Single-attempt ICMP, TCP 443 handshake, and DNS A lookups only. "
        "No inference about causes of non-response."
    )

    return Observation(
        observer="silent-countries-list",
        timestamp=timestamp,
        countries=countries,
        silent_countries=silent_countries,
        notes=notes,
    )


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    observation = run()
    print(json.dumps(observation.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    main()
