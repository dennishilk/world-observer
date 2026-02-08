"""Traceroute-to-nowhere observer.

Runs constrained traceroutes to understand how far packets travel before
paths stop responding. This module intentionally records only coarse
termination details.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

MODULE_DIR = Path(__file__).resolve().parent
TARGETS_PATH = MODULE_DIR / "targets.json"
OBSERVER_NAME = "traceroute-to-nowhere"
MAX_TTL = 20
PROBE_DELAY_SECONDS = 1.5
SILENCE_THRESHOLD = 3


def load_targets() -> List[Dict[str, str]]:
    """Load traceroute targets from targets.json."""

    if not TARGETS_PATH.exists():
        raise FileNotFoundError(f"Missing targets.json at {TARGETS_PATH}")
    with TARGETS_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("targets.json must contain a list of targets")
    return data


def classify_stop_zone(hops_reached: int) -> str:
    """Classify where paths appear to stop based on hop count."""

    if hops_reached <= 0:
        return "unknown"
    if hops_reached <= 3:
        return "local"
    if hops_reached <= 7:
        return "regional"
    if hops_reached <= 12:
        return "international"
    return "transit"


def run_traceroute(host: str) -> Dict[str, Any]:
    """Run a constrained traceroute and return a summary."""

    if not shutil.which("traceroute"):
        return {
            "hops_reached": 0,
            "termination": "timeout",
            "stop_zone": "unknown",
            "error": "traceroute command not available",
        }

    try:
        destination_ip = socket.gethostbyname(host)
    except socket.gaierror as exc:
        return {
            "hops_reached": 0,
            "termination": "timeout",
            "stop_zone": "unknown",
            "error": f"DNS resolution failed: {exc}",
        }

    command = [
        "traceroute",
        "-n",
        "-m",
        str(MAX_TTL),
        "-q",
        "1",
        "-w",
        "2",
        host,
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return {
            "hops_reached": 0,
            "termination": "timeout",
            "stop_zone": "unknown",
            "error": f"Failed to run traceroute: {exc}",
        }

    hops_reached = 0
    termination: Optional[str] = None
    trailing_silence = 0

    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped or not stripped[0].isdigit():
            continue

        parts = stripped.split()
        try:
            hop_number = int(parts[0])
        except ValueError:
            continue

        is_silent = len(parts) > 1 and parts[1] == "*"
        has_response = not is_silent

        if has_response:
            hops_reached = hop_number
            trailing_silence = 0
        else:
            trailing_silence += 1

        if any(marker in stripped for marker in ("!N", "!H", "!P", "!X", "!S")):
            termination = "unreachable"
            break

        if destination_ip in stripped:
            termination = "completed"
            break

    if termination is None:
        if trailing_silence >= SILENCE_THRESHOLD:
            termination = "filtered"
        else:
            termination = "timeout"

    return {
        "hops_reached": hops_reached,
        "termination": termination,
        "stop_zone": classify_stop_zone(hops_reached),
        "error": None,
    }


def run() -> Dict[str, Any]:
    """Execute traceroute measurements for configured targets."""

    timestamp = datetime.now(timezone.utc).isoformat()
    targets = load_targets()
    results: List[Dict[str, Any]] = []

    for index, target in enumerate(targets):
        name = target.get("name", "unknown")
        host = target.get("host", "")
        if not host:
            results.append(
                {
                    "name": name,
                    "host": host,
                    "hops_reached": 0,
                    "termination": "timeout",
                    "stop_zone": "unknown",
                    "error": "Missing host",
                }
            )
            continue

        summary = run_traceroute(host)
        results.append(
            {
                "name": name,
                "host": host,
                **summary,
            }
        )

        if index < len(targets) - 1:
            time.sleep(PROBE_DELAY_SECONDS)

    return {
        "observer": OBSERVER_NAME,
        "timestamp": timestamp,
        "targets": results,
        "notes": "Traceroute limited to low TTL with minimal probes per hop.",
    }


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    print(json.dumps(run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
