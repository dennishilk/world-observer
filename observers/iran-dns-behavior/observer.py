"""Observer for iran-dns-behavior."""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

if importlib.util.find_spec("dns") is None:
    print(
        json.dumps(
            {
                "observer": "iran-dns-behavior",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "unavailable",
                "data_status": "unavailable",
                "error": "missing optional dependency: dnspython",
                "diagnostics": {
                    "api_attempts": 0,
                    "retries": 0,
                    "http_status": None,
                    "missing_dependency": "dnspython",
                },
                "targets": [],
                "summary": {
                    "total_queries": 0,
                    "answers": 0,
                    "timeouts": 0,
                    "refused": 0,
                    "errors": 0,
                },
                "notes": "Install requirements.txt to enable DNS probes.",
            },
            ensure_ascii=False,
        )
    )
    sys.exit(0)

import dns.exception
import dns.rcode
import dns.resolver


TARGETS_PATH = Path(__file__).with_name("targets.json")
RECORD_TYPES = ("A", "AAAA", "MX", "TXT")
RESOLVER_TIMEOUT_S = 2.0
MAX_RETRIES = 1


@dataclass(frozen=True)
class Observation:
    """Represents a single observation payload."""

    observer: str
    timestamp: str
    status: str
    data_status: str
    targets: List[Dict[str, Any]]
    summary: Dict[str, int]
    diagnostics: Dict[str, Any]
    notes: str


def load_targets() -> List[Dict[str, str]]:
    """Load target definitions from targets.json."""

    with TARGETS_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("targets.json must contain a list of targets")
    return data


def _iter_no_nameserver_errors(errors: Any) -> Iterable[Any]:
    """Yield structured NoNameservers entries from known dnspython shapes."""

    if errors is None:
        return
    if isinstance(errors, dict):
        yield from errors.values()
        return
    try:
        yield from errors
    except TypeError:
        yield errors


def _classify_no_nameservers_text(message: str) -> str:
    """Classify a NoNameservers exception from its text representation."""

    normalized = message.lower()
    if "servfail" in normalized:
        return "servfail"
    if "refused" in normalized:
        return "refused"
    if "timed out" in normalized or "timeout" in normalized or "no response" in normalized:
        return "timeout"
    if "no nameservers" in normalized or "unavailable" in normalized:
        return "no_nameservers"
    return "no_nameservers"


def classify_no_nameservers(error: dns.resolver.NoNameservers) -> str:
    """Classify a NoNameservers error when possible without assuming internals."""

    for entry in _iter_no_nameserver_errors(getattr(error, "errors", None)):
        response = getattr(entry, "response", None)
        if response is None and isinstance(entry, tuple):
            response = next((item for item in entry if hasattr(item, "rcode")), None)
        if response is not None:
            try:
                rcode = response.rcode()
            except TypeError:
                rcode = response.rcode
            if rcode == dns.rcode.REFUSED:
                return "refused"
            if rcode == dns.rcode.SERVFAIL:
                return "servfail"

    return _classify_no_nameservers_text(str(error))


def make_query(resolver: dns.resolver.Resolver, domain: str, record_type: str) -> Dict[str, Any]:
    """Perform a DNS query and return a normalized result."""

    for attempt in range(MAX_RETRIES + 1):
        start = time.perf_counter()
        try:
            answer = resolver.resolve(domain, record_type, lifetime=RESOLVER_TIMEOUT_S)
            elapsed_ms = (time.perf_counter() - start) * 1000
            return {
                "status": "answer",
                "query_ms": round(elapsed_ms, 2),
                "answer_count": len(answer),
                "error": None,
            }
        except dns.resolver.NXDOMAIN:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return {
                "status": "nxdomain",
                "query_ms": round(elapsed_ms, 2),
                "answer_count": 0,
                "error": None,
            }
        except dns.resolver.NoAnswer:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return {
                "status": "noanswer",
                "query_ms": round(elapsed_ms, 2),
                "answer_count": 0,
                "error": None,
            }
        except dns.resolver.NoNameservers as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            status = classify_no_nameservers(exc)
            return {
                "status": status,
                "query_ms": round(elapsed_ms, 2),
                "answer_count": None,
                "error": str(exc),
            }
        except dns.exception.Timeout:
            if attempt < MAX_RETRIES:
                continue
            return {
                "status": "timeout",
                "query_ms": None,
                "answer_count": None,
                "error": "timeout",
            }
        except dns.exception.DNSException as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return {
                "status": "error",
                "query_ms": round(elapsed_ms, 2),
                "answer_count": None,
                "error": str(exc),
            }
    return {
        "status": "error",
        "query_ms": None,
        "answer_count": None,
        "error": "unreachable",
    }


def run() -> Observation:
    """Run the observer and return a structured observation."""

    timestamp = datetime.now(timezone.utc).isoformat()
    resolver = dns.resolver.Resolver(configure=True)
    resolver.timeout = RESOLVER_TIMEOUT_S
    resolver.lifetime = RESOLVER_TIMEOUT_S

    targets_data: List[Dict[str, Any]] = []
    summary = {
        "total_queries": 0,
        "answered": 0,
        "timeouts": 0,
        "refused": 0,
        "servfail": 0,
        "no_nameservers": 0,
        "errors": 0,
    }

    for target in load_targets():
        target_queries: Dict[str, Any] = {}
        domain = target.get("domain")
        for record_type in RECORD_TYPES:
            summary["total_queries"] += 1
            result = make_query(resolver, domain, record_type)
            if result["status"] == "answer":
                summary["answered"] += 1
            if result["status"] == "timeout":
                summary["timeouts"] += 1
            if result["status"] == "refused":
                summary["refused"] += 1
            if result["status"] == "servfail":
                summary["servfail"] += 1
            if result["status"] == "no_nameservers":
                summary["no_nameservers"] += 1
            if result["status"] == "error":
                summary["errors"] += 1
            target_queries[record_type] = result
        targets_data.append(
            {
                "name": target.get("name"),
                "domain": domain,
                "queries": target_queries,
            }
        )

    notes = (
        "Queries are performed with standard recursion via the system resolver. "
        "No censorship circumvention or evasion techniques are used."
    )

    if summary["answered"] == summary["total_queries"]:
        data_status = "ok"
    elif summary["answered"] > 0:
        data_status = "partial"
    else:
        data_status = "unavailable"

    return Observation(
        observer="iran-dns-behavior",
        timestamp=timestamp,
        status="ok",
        data_status=data_status,
        targets=targets_data,
        summary=summary,
        diagnostics={
            "api_attempts": summary["total_queries"],
            "retries": 0,
            "http_status": None,
            "servfail": summary["servfail"],
            "no_nameservers": summary["no_nameservers"],
        },
        notes=notes,
    )


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    observation = run()
    print(json.dumps(observation.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    main()
