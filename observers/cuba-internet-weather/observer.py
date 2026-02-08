"""Passive observer for Cuba internet weather measurements."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

PING_COUNT = 4
PING_TIMEOUT_SEC = 2
TCP_TIMEOUT_SEC = 3
DNS_TIMEOUT_SEC = 3
HIGH_LATENCY_MS = 300.0


@dataclass(frozen=True)
class Observation:
    """Represents a single observation payload."""

    observer: str
    timestamp: str
    targets: List[Dict[str, Any]]
    weather_summary: Dict[str, Any]
    notes: str


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _parse_ping_output(output: str) -> Dict[str, Any]:
    summary_match = re.search(
        r"(\d+) packets transmitted, (\d+) received, .*?(\d+)% packet loss",
        output,
    )
    if not summary_match:
        return {
            "sent": PING_COUNT,
            "received": 0,
            "loss_percent": 100.0,
            "rtt_min_ms": None,
            "rtt_avg_ms": None,
            "rtt_max_ms": None,
            "error": "Unable to parse ping output",
        }

    sent = int(summary_match.group(1))
    received = int(summary_match.group(2))
    loss_percent = float(summary_match.group(3))

    rtt_match = re.search(
        r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/",
        output,
    )
    if rtt_match and received > 0:
        rtt_min = float(rtt_match.group(1))
        rtt_avg = float(rtt_match.group(2))
        rtt_max = float(rtt_match.group(3))
    else:
        rtt_min = None
        rtt_avg = None
        rtt_max = None

    return {
        "sent": sent,
        "received": received,
        "loss_percent": loss_percent,
        "rtt_min_ms": rtt_min,
        "rtt_avg_ms": rtt_avg,
        "rtt_max_ms": rtt_max,
        "error": None,
    }


def _run_ping(host: str) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            [
                "ping",
                "-c",
                str(PING_COUNT),
                "-W",
                str(PING_TIMEOUT_SEC),
                host,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {
            "sent": PING_COUNT,
            "received": 0,
            "loss_percent": 100.0,
            "rtt_min_ms": None,
            "rtt_avg_ms": None,
            "rtt_max_ms": None,
            "error": "ping command not available",
        }

    output = "\n".join([completed.stdout, completed.stderr]).strip()
    parsed = _parse_ping_output(output)
    if completed.returncode != 0 and parsed["received"] == 0:
        parsed["error"] = "Ping failed"
    return parsed


def _tcp_handshake(host: str) -> Dict[str, Any]:
    start = time.monotonic()
    try:
        with socket.create_connection((host, 443), timeout=TCP_TIMEOUT_SEC):
            connect_ms = (time.monotonic() - start) * 1000
            return {"ok": True, "connect_ms": round(connect_ms, 2), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "connect_ms": None, "error": str(exc)}


def _dns_lookup(host: str) -> Dict[str, Any]:
    if _is_ip_address(host):
        return {
            "status": "noanswer",
            "query_ms": None,
            "error": "host is an IP address",
        }

    start = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                socket.getaddrinfo,
                host,
                None,
                socket.AF_INET,
                socket.SOCK_STREAM,
            )
            records = future.result(timeout=DNS_TIMEOUT_SEC)
    except FuturesTimeout:
        return {"status": "timeout", "query_ms": None, "error": "DNS lookup timed out"}
    except socket.gaierror as exc:
        if exc.errno == socket.EAI_NONAME:
            return {"status": "nxdomain", "query_ms": None, "error": str(exc)}
        if exc.errno == socket.EAI_AGAIN:
            return {"status": "timeout", "query_ms": None, "error": str(exc)}
        return {"status": "error", "query_ms": None, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "query_ms": None, "error": str(exc)}

    query_ms = (time.monotonic() - start) * 1000
    if records:
        return {"status": "answer", "query_ms": round(query_ms, 2), "error": None}
    return {"status": "noanswer", "query_ms": round(query_ms, 2), "error": None}


def _summarize_weather(targets: List[Dict[str, Any]]) -> Dict[str, Any]:
    any_ping_success = any(target["ping"]["received"] > 0 for target in targets)
    any_tcp_success = any(target["tcp_443"]["ok"] for target in targets)

    if not any_ping_success and not any_tcp_success:
        return {
            "classification": "offline",
            "reason": "No successful ping replies or TCP handshakes.",
        }

    losses = [
        target["ping"]["loss_percent"]
        for target in targets
        if target["ping"]["loss_percent"] is not None
    ]
    rtts = [
        target["ping"]["rtt_avg_ms"]
        for target in targets
        if target["ping"]["rtt_avg_ms"] is not None
    ]

    tcp_ok_count = sum(1 for target in targets if target["tcp_443"]["ok"])
    tcp_fail_count = len(targets) - tcp_ok_count

    if any(loss > 40 for loss in losses) or any(rtt > HIGH_LATENCY_MS for rtt in rtts):
        return {
            "classification": "degraded",
            "reason": "High packet loss or elevated latency detected.",
        }

    if any(10 <= loss <= 40 for loss in losses) or (
        tcp_ok_count > 0 and tcp_fail_count > 0
    ):
        return {
            "classification": "unstable",
            "reason": "Moderate packet loss or intermittent TCP success detected.",
        }

    if losses and all(loss < 10 for loss in losses) and tcp_fail_count == 0:
        return {
            "classification": "clear",
            "reason": "Low packet loss and all TCP handshakes succeeded.",
        }

    return {
        "classification": "unstable",
        "reason": "Mixed results without sustained high loss or latency.",
    }


def _load_targets() -> List[Dict[str, Any]]:
    with open("observers/cuba-internet-weather/targets.json", "r", encoding="utf-8") as handle:
        return json.load(handle)


def run() -> Dict[str, Any]:
    """Run the observer and return a structured observation."""

    targets = []
    for target in _load_targets():
        host = target["host"]
        ping_result = _run_ping(host)
        tcp_result = _tcp_handshake(host)
        dns_result = {"a": _dns_lookup(host)}

        targets.append(
            {
                "name": target["name"],
                "host": host,
                "ping": ping_result,
                "tcp_443": tcp_result,
                "dns": dns_result,
            }
        )

    weather_summary = _summarize_weather(targets)
    notes = (
        "Passive measurement of packet loss, TCP 443 handshake, and DNS A lookups for Cuba. "
        "Values represent point-in-time signals only."
    )
    return {
        "observer": "cuba-internet-weather",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "targets": targets,
        "weather_summary": weather_summary,
        "notes": notes,
    }


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    observation = run()
    print(json.dumps(observation, ensure_ascii=False))


if __name__ == "__main__":
    main()
