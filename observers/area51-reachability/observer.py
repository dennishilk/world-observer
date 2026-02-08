"""Observer for area51-reachability.

This module uses intentionally boring, repeatable measurements that stay within
publicly visible boundaries. It avoids collecting any identifying details.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

OBSERVER_NAME = "area51-reachability"
OUTPUT_DIR = os.path.join("data", OBSERVER_NAME)
BASELINE_WINDOW_DAYS = 30
REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "visualizations" / "significant_state.json"

# Public, stable targets used only for reachability and DNS behavior.
# The point is to show that public endpoints behave normally and consistently.
TARGETS = [
    "www.nellis.af.mil",
    "www.dreamlandresort.com",
]

TRACEROUTE_TARGET = "www.nellis.af.mil"
TRACEROUTE_MAX_HOPS = 20
TRACEROUTE_TIMEOUT_S = 2


def _iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _icmp_ping(hostname: str, timeout_s: int = 2) -> Optional[bool]:
    """Return True/False for ping reachability, or None if ping is unavailable."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout_s), hostname],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s + 2,
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


def _dns_lookup_status(hostname: str, record_type: str) -> str:
    """Return one of: answer, timeout, NXDOMAIN.

    The implementation prefers dnspython when available. It intentionally reduces
    detail to avoid retaining any sensitive information.
    """
    try:
        import dns.resolver  # type: ignore

        resolver = dns.resolver.Resolver()
        resolver.lifetime = 3.0
        try:
            resolver.resolve(hostname, record_type)
            return "answer"
        except dns.resolver.NXDOMAIN:
            return "NXDOMAIN"
        except dns.resolver.NoAnswer:
            return "answer"
        except dns.exception.Timeout:
            return "timeout"
        except dns.exception.DNSException:
            return "timeout"
    except ImportError:
        try:
            socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
            return "answer"
        except socket.gaierror as exc:
            if exc.errno == socket.EAI_NONAME:
                return "NXDOMAIN"
            return "timeout"


def _classify_ip(ip_address: str) -> str:
    """Classify an IP address without storing it."""
    if ip_address.startswith("10."):
        return "private_network_edge"
    if ip_address.startswith("192.168."):
        return "private_network_edge"
    if ip_address.startswith("172."):
        try:
            second_octet = int(ip_address.split(".")[1])
        except (IndexError, ValueError):
            return "public_transit"
        if 16 <= second_octet <= 31:
            return "private_network_edge"
    return "public_transit"


def _parse_traceroute(output: str, destination_ip: Optional[str]) -> Tuple[int, str, bool]:
    """Parse traceroute output without retaining individual IPs."""
    last_response_hop = 0
    last_classification = "no_response"
    destination_reached = False
    for line in output.splitlines():
        parts = line.split()
        if not parts or not parts[0].isdigit():
            continue
        hop_number = int(parts[0])
        hop_ips = [part for part in parts[1:] if part.count(".") == 3]
        if hop_ips:
            last_response_hop = hop_number
            last_classification = _classify_ip(hop_ips[0])
            if destination_ip and destination_ip in hop_ips:
                destination_reached = True
    return last_response_hop, last_classification, destination_reached


def _traceroute_summary(hostname: str) -> Dict[str, Any]:
    """Run traceroute and summarize without storing hop addresses."""
    destination_ip: Optional[str] = None
    try:
        destination_ip = socket.gethostbyname(hostname)
    except OSError:
        destination_ip = None
    try:
        result = subprocess.run(
            [
                "traceroute",
                "-n",
                "-m",
                str(TRACEROUTE_MAX_HOPS),
                "-q",
                "1",
                "-w",
                str(TRACEROUTE_TIMEOUT_S),
                hostname,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=TRACEROUTE_MAX_HOPS * (TRACEROUTE_TIMEOUT_S + 1),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {
            "max_hops_reached": 0,
            "stop_classification": "unavailable",
            "destination_reached": False,
        }

    if result.returncode != 0 and not result.stdout:
        return {
            "max_hops_reached": 0,
            "stop_classification": "unavailable",
            "destination_reached": False,
        }

    max_hops, classification, destination_reached = _parse_traceroute(
        result.stdout, destination_ip
    )

    return {
        "max_hops_reached": max_hops,
        "stop_classification": classification,
        "destination_reached": destination_reached,
    }


def _load_json_from_path(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_json_from_url(url: str) -> Optional[Dict[str, Any]]:
    try:
        with urlopen(url, timeout=10) as response:  # nosec - open data aggregation only
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    payload = _load_json_from_path(STATE_PATH)
    return payload or {}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _load_flight_counts() -> Tuple[Optional[int], Optional[int], str]:
    path_env = os.getenv("AREA51_FLIGHT_ACTIVITY_PATH")
    url_env = os.getenv("AREA51_FLIGHT_ACTIVITY_URL")
    payload: Optional[Dict[str, Any]] = None

    if path_env:
        payload = _load_json_from_path(Path(path_env))
    elif url_env:
        payload = _load_json_from_url(url_env)
    else:
        return None, None, "unavailable"

    if not payload:
        return None, None, "unavailable"

    janet_like = payload.get("janet_like")
    other = payload.get("other")
    if not isinstance(janet_like, int) or not isinstance(other, int):
        return None, None, "unavailable"

    return janet_like, other, "available"


def _compute_flight_baseline(
    state: Dict[str, Any],
    janet_like_today: Optional[int],
) -> Tuple[Optional[float], int, Optional[int], Optional[float], str, Dict[str, Any]]:
    baseline_state = state.setdefault("area51_flight_baseline", {})
    window_days = baseline_state.get("window_days")
    if not isinstance(window_days, int) or window_days <= 0:
        window_days = BASELINE_WINDOW_DAYS

    values = baseline_state.get("values")
    if not isinstance(values, list):
        values = []
    values = [value for value in values if isinstance(value, int)]

    baseline_avg = round(sum(values) / len(values), 2) if values else None
    deviation_abs: Optional[int] = None
    deviation_percent: Optional[float] = None
    significance = "low"

    if janet_like_today is not None and baseline_avg is not None and baseline_avg > 0:
        raw_delta = janet_like_today - baseline_avg
        deviation_abs = int(round(raw_delta))
        deviation_percent = round((raw_delta / baseline_avg) * 100, 2)
        if (
            len(values) >= 14
            and janet_like_today >= (2 * baseline_avg)
            and raw_delta >= 5
        ):
            significance = "high"

    if janet_like_today is not None:
        values.append(janet_like_today)
        if len(values) > window_days:
            values = values[-window_days:]
        baseline_state["window_days"] = window_days
        baseline_state["values"] = values

    return baseline_avg, window_days, deviation_abs, deviation_percent, significance, state


def _flight_activity_summary() -> Dict[str, Any]:
    """Return daily aggregated ADS-B counts when available.

    No callsigns, routes, times, or identifiers are retained. If no data source
    is configured, we explicitly state that the count is unavailable.
    """
    janet_like, other, data_status = _load_flight_counts()
    state = _load_state()
    baseline_avg, window_days, deviation_abs, deviation_percent, significance, state = (
        _compute_flight_baseline(state, janet_like)
    )
    if janet_like is not None:
        _save_state(state)

    return {
        "data_status": data_status,
        "source": "opensky_network",
        "aggregation": "daily",
        "airspace": "southern_nevada_public",
        "classification_method": "icao_hex_prefix + operator_pattern",
        "counts": {
            "janet_like": janet_like,
            "other": other,
        },
        "baseline": {
            "window_days": window_days,
            "janet_like_avg": baseline_avg,
        },
        "deviation": {
            "absolute": deviation_abs,
            "percent": deviation_percent,
            "significance": significance,
        },
        "notes": (
            "Aggregated daily activity only. No routes, timestamps, identifiers, "
            "or destinations are collected."
        ),
    }


def run() -> Dict[str, Any]:
    """Run the observer and write a JSON artifact for this run."""
    timestamp = _iso_timestamp()
    network_results: Dict[str, Any] = {}
    dns_results: Dict[str, Any] = {}

    for target in TARGETS:
        network_results[target] = {
            "icmp_ping": _icmp_ping(target),
            "tcp_443": _tcp_handshake(target),
        }
        dns_results[target] = {
            "A": _dns_lookup_status(target, "A"),
            "AAAA": _dns_lookup_status(target, "AAAA"),
        }

    observation = {
        "observer": OBSERVER_NAME,
        "date": timestamp,
        "network": {
            "targets": network_results,
            # Results are expected to be flat because public endpoints are stable,
            # and temporary failures are routine internet noise rather than signals.
        },
        "dns": {
            "targets": dns_results,
            # DNS answers usually stay consistent; we only keep coarse outcomes.
        },
        "traceroute": {
            "target": TRACEROUTE_TARGET,
            **_traceroute_summary(TRACEROUTE_TARGET),
            # Traceroute often stops early due to filtering; this is normal.
        },
        "flight_activity": _flight_activity_summary(),
        "notes": (
            "These measurements are intentionally bland: they show that publicly "
            "reachable systems around Groom Lake behave like ordinary internet "
            "endpoints. Failures are expected noise, not evidence of hidden activity."
        ),
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = os.path.join(OUTPUT_DIR, f"{filename}.json")
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(observation, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    return observation


def main() -> None:
    """Serialize the observation to JSON on stdout."""
    observation = run()
    print(json.dumps(observation, ensure_ascii=False))


if __name__ == "__main__":
    main()
