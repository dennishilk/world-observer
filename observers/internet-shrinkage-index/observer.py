"""Observer for the internet-shrinkage-index."""

from __future__ import annotations

import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path


PING_COUNT = 1
PING_TIMEOUT_SECONDS = 2
TCP_TIMEOUT_SECONDS = 3
DNS_TIMEOUT_SECONDS = 3
MIN_SUCCESSES_FOR_REACHABLE = 2


def load_targets(targets_path: Path) -> list[str]:
    """Load a list of target hostnames from the targets.json file."""

    raw = json.loads(targets_path.read_text(encoding="utf-8"))
    hosts: list[str] = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, str):
                hosts.append(entry)
            elif isinstance(entry, dict) and "host" in entry:
                hosts.append(str(entry["host"]))
    return hosts


def check_ping(host: str) -> bool:
    """Return True if an ICMP ping succeeds."""

    try:
        result = subprocess.run(
            [
                "ping",
                "-c",
                str(PING_COUNT),
                "-W",
                str(PING_TIMEOUT_SECONDS),
                host,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=PING_TIMEOUT_SECONDS + 1,
        )
    except (subprocess.SubprocessError, FileNotFoundError, TimeoutError):
        return False
    return result.returncode == 0


def check_tcp_443(host: str) -> bool:
    """Return True if a TCP handshake on port 443 succeeds."""

    try:
        with socket.create_connection((host, 443), timeout=TCP_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


def check_dns(host: str) -> bool:
    """Return True if a DNS A record lookup succeeds."""

    previous_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(DNS_TIMEOUT_SECONDS)
        socket.getaddrinfo(host, None, family=socket.AF_INET)
        return True
    except OSError:
        return False
    finally:
        socket.setdefaulttimeout(previous_timeout)


def evaluate_target(host: str) -> dict:
    """Run reachability checks for a single host."""

    ping_ok = check_ping(host)
    tcp_ok = check_tcp_443(host)
    dns_ok = check_dns(host)
    successes = sum((ping_ok, tcp_ok, dns_ok))
    reachable = successes >= MIN_SUCCESSES_FOR_REACHABLE

    return {
        "host": host,
        "reachable": reachable,
        "checks": {
            "ping": ping_ok,
            "tcp_443": tcp_ok,
            "dns": dns_ok,
        },
    }


def run() -> dict:
    """Run the observer and return the observation payload."""

    targets_path = Path(__file__).with_name("targets.json")
    hosts = load_targets(targets_path)
    results = [evaluate_target(host) for host in hosts]
    reachable_targets = sum(1 for item in results if item["reachable"])
    total_targets = len(results)
    index = reachable_targets / total_targets if total_targets else 0.0

    return {
        "observer": "internet-shrinkage-index",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_targets": total_targets,
        "reachable_targets": reachable_targets,
        "index": index,
        "targets": results,
        "notes": "Reachability is counted when at least two of three checks succeed.",
    }


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
