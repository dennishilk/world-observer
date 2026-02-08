"""TLS certificate fingerprint change watcher."""

from __future__ import annotations

import hashlib
import json
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

MODULE_DIR = Path(__file__).resolve().parent
TARGETS_PATH = MODULE_DIR / "targets.json"
FINGERPRINTS_PATH = MODULE_DIR / "fingerprints.json"
OBSERVER_NAME = "tls-fingerprint-change-watcher"
DEFAULT_PORT = 443
MAX_ATTEMPTS = 2
TIMEOUT_SECONDS = 5


@dataclass
class TargetResult:
    """Result for a single target."""

    name: str
    host: str
    fingerprint_sha256: Optional[str]
    valid_from: Optional[str]
    valid_to: Optional[str]
    changed: bool
    error: Optional[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "fingerprint_sha256": self.fingerprint_sha256,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "changed": self.changed,
            "error": self.error,
        }


def load_targets() -> List[Dict[str, str]]:
    if not TARGETS_PATH.exists():
        raise FileNotFoundError(f"targets.json not found at {TARGETS_PATH}")
    data = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("targets.json must contain a list of targets")
    return data


def load_fingerprints() -> Dict[str, str]:
    if not FINGERPRINTS_PATH.exists():
        return {}
    data = json.loads(FINGERPRINTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def save_fingerprints(data: Dict[str, str]) -> None:
    FINGERPRINTS_PATH.write_text(
        json.dumps(data, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def parse_cert_time(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%b %d %H:%M:%S %Y %Z")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc).isoformat()


def fetch_certificate(host: str) -> Dict[str, Optional[str]]:
    context = ssl.create_default_context()
    last_error: Optional[str] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with socket.create_connection((host, DEFAULT_PORT), timeout=TIMEOUT_SECONDS) as sock:
                with context.wrap_socket(sock, server_hostname=host) as tls_sock:
                    cert_bytes = tls_sock.getpeercert(binary_form=True)
                    cert_info = tls_sock.getpeercert() or {}
            if not cert_bytes:
                raise ValueError("No certificate received")
            fingerprint = hashlib.sha256(cert_bytes).hexdigest()
            return {
                "fingerprint": fingerprint,
                "valid_from": parse_cert_time(cert_info.get("notBefore")),
                "valid_to": parse_cert_time(cert_info.get("notAfter")),
                "error": None,
            }
        except (socket.timeout, ssl.SSLError, OSError, ValueError) as exc:
            last_error = f"attempt {attempt}: {exc}"
    return {"fingerprint": None, "valid_from": None, "valid_to": None, "error": last_error}


def run() -> Dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    targets = load_targets()
    fingerprints = load_fingerprints()

    results: List[TargetResult] = []
    updated_fingerprints = dict(fingerprints)

    for target in targets:
        name = str(target.get("name", ""))
        host = str(target.get("host", ""))
        if not name or not host:
            results.append(
                TargetResult(
                    name=name or "unknown",
                    host=host or "unknown",
                    fingerprint_sha256=None,
                    valid_from=None,
                    valid_to=None,
                    changed=False,
                    error="invalid target entry",
                )
            )
            continue

        cert_data = fetch_certificate(host)
        fingerprint = cert_data["fingerprint"]
        error = cert_data["error"]

        previous = fingerprints.get(host)
        changed = bool(previous and fingerprint and previous != fingerprint)

        if fingerprint and not error:
            updated_fingerprints[host] = fingerprint

        results.append(
            TargetResult(
                name=name,
                host=host,
                fingerprint_sha256=fingerprint,
                valid_from=cert_data["valid_from"],
                valid_to=cert_data["valid_to"],
                changed=changed,
                error=error,
            )
        )

    if updated_fingerprints != fingerprints:
        save_fingerprints(updated_fingerprints)

    return {
        "observer": OBSERVER_NAME,
        "timestamp": timestamp,
        "targets": [result.as_dict() for result in results],
        "notes": "TLS handshake only; stores last known fingerprint per target.",
    }


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
