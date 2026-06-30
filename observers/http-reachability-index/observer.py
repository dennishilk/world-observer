#!/usr/bin/env python3
"""HTTP reachability index observer.

Performs bounded HTTP/HTTPS reachability checks against a small fixed target set.
The observer does not scrape, use a browser, or call external APIs.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OBSERVER = "http-reachability-index"
TARGETS = [
    "https://example.com",
    "https://www.wikipedia.org",
    "https://github.com",
    "https://www.cloudflare.com",
    "https://www.debian.org",
    "https://www.kernel.org",
    "https://www.gnu.org",
    "https://archive.org",
]
TARGET_TIMEOUT_S = 5.0
TOTAL_RUNTIME_BUDGET_S = 30.0
USER_AGENT = "world-observer/http-reachability-index (+https://github.com/dennishilk/world-observer)"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _date_utc(now: datetime) -> str:
    return os.environ.get("WORLD_OBSERVER_DATE_UTC") or now.date().isoformat()


def _remaining_budget(start: float, total_budget_s: float) -> float:
    return max(0.0, total_budget_s - (time.monotonic() - start))


def _request_once(url: str, timeout_s: float, method: str = "HEAD") -> tuple[bool, int | None, float | None, str | None]:
    started = time.monotonic()
    request = Request(url, method=method, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout_s) as response:
            elapsed_ms = round((time.monotonic() - started) * 1000, 2)
            status_code = int(getattr(response, "status", response.getcode()))
            return 200 <= status_code < 400, status_code, elapsed_ms, None
    except HTTPError as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000, 2)
        # HTTP errors still prove the origin is reachable, but are counted as
        # failed checks for the index because the target did not return a
        # successful page status.
        return False, int(exc.code), elapsed_ms, f"http_error:{exc.code}"
    except (TimeoutError, URLError, OSError) as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000, 2)
        return False, None, elapsed_ms, exc.__class__.__name__


def check_target(url: str, timeout_s: float) -> dict[str, Any]:
    reachable, status_code, response_ms, error = _request_once(url, timeout_s, "HEAD")
    if not reachable and status_code in {405, 403}:
        reachable, status_code, response_ms, error = _request_once(url, timeout_s, "GET")
    return {
        "url": url,
        "reachable": reachable,
        "http_status": status_code,
        "response_ms": response_ms,
        "error": error,
    }


def run(
    targets: list[str] | None = None,
    target_timeout_s: float = TARGET_TIMEOUT_S,
    total_runtime_budget_s: float = TOTAL_RUNTIME_BUDGET_S,
) -> dict[str, Any]:
    now = _utc_now()
    started = time.monotonic()
    target_results: list[dict[str, Any]] = []
    api_attempts = 0

    for url in targets or TARGETS:
        remaining = _remaining_budget(started, total_runtime_budget_s)
        if remaining <= 0:
            target_results.append({
                "url": url,
                "reachable": False,
                "http_status": None,
                "response_ms": None,
                "error": "total_runtime_budget_exhausted",
            })
            continue
        api_attempts += 1
        target_results.append(check_target(url, min(target_timeout_s, remaining)))

    reachable = sum(1 for target in target_results if target.get("reachable") is True)
    checked = len(target_results)
    failed = checked - reachable
    response_times = [target["response_ms"] for target in target_results if target.get("reachable") is True and isinstance(target.get("response_ms"), (int, float))]
    if reachable == 0:
        data_status = "unavailable"
    elif failed > 0:
        data_status = "partial"
    else:
        data_status = "ok"

    return {
        "observer": OBSERVER,
        "timestamp": now.isoformat(),
        "date_utc": _date_utc(now),
        "status": "ok",
        "data_status": data_status,
        "targets": target_results,
        "summary": {
            "targets_checked": checked,
            "targets_reachable": reachable,
            "targets_failed": failed,
            "success_rate_percent": round((reachable / checked) * 100, 2) if checked else 0.0,
            "avg_response_ms": round(sum(response_times) / len(response_times), 2) if response_times else None,
        },
        "diagnostics": {
            "api_attempts": api_attempts,
            "retries": 0,
            "http_status": None,
            "duration_s": round(time.monotonic() - started, 3),
            "timeout_s": target_timeout_s,
        },
    }


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
