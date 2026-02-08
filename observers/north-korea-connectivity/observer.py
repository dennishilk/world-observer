"""Passive reachability observer for north-korea-connectivity."""

from __future__ import annotations

import importlib
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
    """Represents a single observation payload."""

    timestamp: str
    observer: str
    targets: List[Dict[str, Any]]
    notes: str


def _load_targets() -> List[Dict[str, str]]:
    with TARGETS_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _ping_host(host: str, timeout_s: int = 2) -> Dict[str, Any]:
    """Attempt a single ICMP echo request.

    ICMP often requires elevated privileges or capabilities. When unavailable,
    return an explicit error rather than failing hard.
    """

    command = ["ping", "-c", "1", "-W", str(timeout_s), host]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "rtt_ms": None, "error": "ping_not_available"}

    output = (result.stdout or "") + (result.stderr or "")
    if "Operation not permitted" in output or "Permission denied" in output:
        return {"ok": False, "rtt_ms": None, "error": "permission_denied"}

    if result.returncode == 0:
        rtt_ms = None
        for token in output.split():
            if token.startswith("time="):
                try:
                    rtt_ms = float(token.split("=", 1)[1])
                except ValueError:
                    rtt_ms = None
                break
        return {"ok": True, "rtt_ms": rtt_ms, "error": None}

    return {"ok": False, "rtt_ms": None, "error": "no_reply"}


def _tcp_handshake(host: str, port: int = 443, timeout_s: float = 3.0) -> Dict[str, Any]:
    """Attempt a TCP handshake only (no data exchange)."""

    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            connect_ms = (time.monotonic() - start) * 1000
            return {"ok": True, "connect_ms": round(connect_ms, 2), "error": None}
    except OSError as exc:
        return {"ok": False, "connect_ms": None, "error": exc.__class__.__name__}


def _dns_query(host: str, record_type: str) -> Dict[str, Any]:
    """Query DNS for A/AAAA using dnspython if available."""

    if _is_ip_address(host):
        return {"status": "noanswer", "answers": [], "error": "not_hostname"}

    if importlib.util.find_spec("dns") is None:
        return {"status": "error", "answers": [], "error": "dnspython_not_installed"}

    dns_resolver = importlib.import_module("dns.resolver")
    dns_exception = importlib.import_module("dns.exception")
    dns_name = importlib.import_module("dns.name")

    resolver = dns_resolver.Resolver(configure=True)
    resolver.lifetime = 3.0

    try:
        answers = resolver.resolve(dns_name.from_text(host), record_type)
    except dns_resolver.NXDOMAIN:
        return {"status": "nxdomain", "answers": [], "error": None}
    except dns_resolver.NoAnswer:
        return {"status": "noanswer", "answers": [], "error": None}
    except dns_exception.Timeout:
        return {"status": "timeout", "answers": [], "error": None}
    except dns_exception.DNSException as exc:
        return {"status": "error", "answers": [], "error": exc.__class__.__name__}

    resolved = [item.to_text() for item in answers]
    return {"status": "answer", "answers": resolved, "error": None}


def _observe_target(target: Dict[str, str]) -> Dict[str, Any]:
    host = target["host"]
    return {
        "name": target["name"],
        "host": host,
        "ping": _ping_host(host),
        "tcp_443": _tcp_handshake(host),
        "dns": {
            "a": _dns_query(host, "A"),
            "aaaa": _dns_query(host, "AAAA"),
        },
    }


def run() -> Observation:
    """Run the observer and return a structured observation."""

    timestamp = datetime.now(timezone.utc).isoformat()
    targets = _load_targets()

    # NOTE: These measurements are intentionally minimal. Many targets will
    # appear silent due to filtering, rate limiting, or the absence of public
    # services. Silence is a valid signal, not an invitation to probe further.
    observations = [_observe_target(target) for target in targets]

    notes = (
        "Passive reachability snapshot only: ICMP, TCP 443 handshake, and DNS A/AAAA."
    )
    return Observation(
        timestamp=timestamp,
        observer="north-korea-connectivity",
        targets=observations,
        notes=notes,
    )


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    observation = run()
    print(json.dumps(observation.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    main()
