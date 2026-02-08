"""DNS time-to-answer observer for dns-time-to-answer-index."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional

import dns.exception
import dns.resolver

MODULE_DIR = Path(__file__).resolve().parent
TARGETS_PATH = MODULE_DIR / "targets.json"


@dataclass(frozen=True)
class Observation:
    """Represents a single observation payload."""

    observer: str
    timestamp: str
    targets: List[Dict[str, Any]]
    summary: Dict[str, Any]
    notes: str


def _load_targets() -> List[Dict[str, str]]:
    if not TARGETS_PATH.exists():
        raise FileNotFoundError(f"Missing targets.json at {TARGETS_PATH}")

    with TARGETS_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if isinstance(payload, dict):
        payload = [payload]

    if not isinstance(payload, list):
        raise ValueError("targets.json must contain a list of entries")

    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError("Each targets.json entry must be an object")
        if "name" not in entry or "domain" not in entry:
            raise ValueError("Each entry must include 'name' and 'domain'")

    return payload


def _build_result(status: str, query_ms: Optional[float], error: Optional[str]) -> Dict[str, Any]:
    return {
        "status": status,
        "query_ms": query_ms,
        "error": error,
    }


def _query_dns(
    resolver: dns.resolver.Resolver,
    domain: str,
    record_type: str,
) -> Dict[str, Any]:
    start = perf_counter()
    try:
        answer = resolver.resolve(domain, record_type, raise_on_no_answer=False)
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        if answer.rrset is None:
            return _build_result("no_answer", elapsed_ms, "no_answer")
        return _build_result("success", elapsed_ms, None)
    except dns.resolver.NXDOMAIN:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        return _build_result("nxdomain", elapsed_ms, "nxdomain")
    except dns.exception.Timeout:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        return _build_result("timeout", elapsed_ms, "timeout")
    except dns.resolver.NoNameservers:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        return _build_result("servfail", elapsed_ms, "servfail")
    except dns.resolver.NoAnswer:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        return _build_result("no_answer", elapsed_ms, "no_answer")
    except dns.exception.DNSException:
        elapsed_ms = round((perf_counter() - start) * 1000, 2)
        return _build_result("error", elapsed_ms, "dns_error")


def _build_summary(targets: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_queries = 0
    successful = 0
    timeouts = 0
    success_times: List[float] = []

    for target in targets:
        queries = target.get("queries", {})
        for query_result in queries.values():
            total_queries += 1
            status = query_result.get("status")
            query_ms = query_result.get("query_ms")
            if status == "success":
                successful += 1
                if isinstance(query_ms, (int, float)):
                    success_times.append(float(query_ms))
            if status == "timeout":
                timeouts += 1

    avg_query_ms = round(sum(success_times) / len(success_times), 2) if success_times else None

    return {
        "total_queries": total_queries,
        "successful": successful,
        "timeouts": timeouts,
        "avg_query_ms": avg_query_ms,
    }


def run() -> Observation:
    """Run the observer and return a structured observation."""

    timestamp = datetime.now(timezone.utc).isoformat()
    targets = _load_targets()

    resolver = dns.resolver.Resolver()
    resolver.timeout = 3.0
    resolver.lifetime = 3.0
    resolver.retry_servfail = False
    resolver.rotate = False

    target_results: List[Dict[str, Any]] = []

    for target in targets:
        domain = target.get("domain", "")
        target_result = {
            "name": target.get("name", ""),
            "domain": domain,
            "queries": {
                "A": _query_dns(resolver, domain, "A"),
                "AAAA": _query_dns(resolver, domain, "AAAA"),
            },
        }
        target_results.append(target_result)

    summary = _build_summary(target_results)
    notes = (
        "Sequential DNS A and AAAA lookups with a conservative timeout. "
        "No answers, resolver identities, or TTL values are stored."
    )

    return Observation(
        observer="dns-time-to-answer-index",
        timestamp=timestamp,
        targets=target_results,
        summary=summary,
        notes=notes,
    )


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    observation = run()
    print(json.dumps(observation.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    main()
