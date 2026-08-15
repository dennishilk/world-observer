#!/usr/bin/env python3
"""Collect a small, policy-conscious snapshot of selected CelesTrak GP groups.

The observer deliberately treats each CelesTrak group as its own observation
surface. Group membership may overlap, so record counts are never summed into a
claimed global satellite population.
"""

from __future__ import annotations

import csv
import io
import json
import os
import statistics
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

OBSERVER = "space-satellites"
CATEGORY = "technology"
BASE_URL = "https://celestrak.org/NORAD/elements/gp.php"
DOCUMENTATION_URL = "https://celestrak.org/NORAD/documentation/gp-data-formats.php"
USAGE_POLICY_URL = "https://celestrak.org/usage-policy.php"
USER_AGENT = "WorldObserver/1.0"
TIMEOUT_S = 30
MAX_RESPONSE_BYTES = 20_000_000
HISTORY_LIMIT = 365

GROUPS: tuple[dict[str, str], ...] = (
    {"key": "stations", "query": "STATIONS", "label": "Space Stations"},
    {"key": "starlink", "query": "STARLINK", "label": "Starlink"},
    {"key": "oneweb", "query": "ONEWEB", "label": "OneWeb"},
    {"key": "gps_ops", "query": "GPS-OPS", "label": "GPS Operational"},
    {"key": "galileo", "query": "GALILEO", "label": "Galileo"},
    {"key": "cubesat", "query": "CUBESAT", "label": "CubeSats"},
)


class SourceFetchError(RuntimeError):
    """Raised for a source request that must stop the current collection run."""

    def __init__(self, message: str, *, url: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.http_status = http_status


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _date_utc() -> str:
    return os.environ.get("WORLD_OBSERVER_DATE_UTC") or datetime.now(timezone.utc).date().isoformat()


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_epoch(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _group_url(query_group: str) -> str:
    query = urllib.parse.urlencode({"GROUP": query_group, "FORMAT": "CSV"})
    return f"{BASE_URL}?{query}"


def fetch_group_csv(query_group: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Fetch one CelesTrak GP group once, using compact OMM-keyword CSV."""
    url = _group_url(query_group)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            status = int(getattr(response, "status", 200))
            if status != 200:
                raise SourceFetchError(
                    f"CelesTrak returned HTTP {status}",
                    url=url,
                    http_status=status,
                )
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except SourceFetchError:
        raise
    except urllib.error.HTTPError as exc:
        raise SourceFetchError(
            f"CelesTrak returned HTTP {exc.code}",
            url=url,
            http_status=exc.code,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceFetchError(f"CelesTrak request failed: {exc}", url=url) from exc

    if len(raw) > MAX_RESPONSE_BYTES:
        raise SourceFetchError("CelesTrak response exceeded safety limit", url=url, http_status=200)

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceFetchError("CelesTrak response was not UTF-8 CSV", url=url, http_status=200) from exc

    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(row) for row in reader]
    fields = set(reader.fieldnames or [])
    required = {"NORAD_CAT_ID", "EPOCH"}
    if not required.issubset(fields):
        missing = ", ".join(sorted(required - fields))
        raise SourceFetchError(
            f"CelesTrak CSV missing required fields: {missing}",
            url=url,
            http_status=200,
        )

    return rows, {"url": url, "http_status": 200, "bytes": len(raw), "record_count": len(rows)}


def summarize_group(records: Iterable[dict[str, Any]], collected_at: datetime) -> dict[str, Any]:
    rows = list(records)
    catalog_ids = {
        str(row.get("NORAD_CAT_ID")).strip()
        for row in rows
        if row.get("NORAD_CAT_ID") is not None and str(row.get("NORAD_CAT_ID")).strip()
    }
    epochs = [epoch for row in rows if (epoch := _parse_epoch(row.get("EPOCH"))) is not None]
    inclinations = [value for row in rows if (value := _as_float(row.get("INCLINATION"))) is not None]

    summary: dict[str, Any] = {
        "status": "ok",
        "record_count": len(rows),
        "unique_catalog_ids": len(catalog_ids),
        "epoch_count": len(epochs),
        "mean_inclination_deg": round(statistics.fmean(inclinations), 4) if inclinations else None,
    }
    if epochs:
        ages = [(collected_at - epoch).total_seconds() / 3600 for epoch in epochs]
        summary.update(
            {
                "oldest_epoch_utc": _iso_utc(min(epochs)),
                "newest_epoch_utc": _iso_utc(max(epochs)),
                "median_epoch_age_hours": round(statistics.median(ages), 2),
            }
        )
    else:
        summary.update(
            {
                "oldest_epoch_utc": None,
                "newest_epoch_utc": None,
                "median_epoch_age_hours": None,
            }
        )
    return summary


def _history(root: Path, current_date: str, current_groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    state_dir = root / "state" / OBSERVER
    points: list[dict[str, Any]] = []
    if state_dir.exists():
        for path in sorted(state_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            date = str(payload.get("date") or path.stem)[:10]
            groups = payload.get("groups") if isinstance(payload.get("groups"), dict) else {}
            point: dict[str, Any] = {"date": date}
            for key in ("stations", "starlink", "oneweb", "gps_ops", "galileo", "cubesat"):
                group = groups.get(key) if isinstance(groups.get(key), dict) else {}
                count = group.get("record_count")
                if isinstance(count, int) and not isinstance(count, bool):
                    point[f"{key}_records"] = count
            if len(point) > 1:
                points.append(point)

    current: dict[str, Any] = {"date": current_date}
    for key, group in current_groups.items():
        count = group.get("record_count")
        if isinstance(count, int) and not isinstance(count, bool):
            current[f"{key}_records"] = count
    if len(current) > 1:
        points.append(current)

    latest_by_date: dict[str, dict[str, Any]] = {}
    for point in points:
        date = point.get("date")
        if isinstance(date, str):
            latest_by_date[date] = point
    return [latest_by_date[date] for date in sorted(latest_by_date)][-HISTORY_LIMIT:]


def build_payload(
    date_str: str,
    *,
    root: Path,
    fetcher: Callable[[str], tuple[list[dict[str, str]], dict[str, Any]]] = fetch_group_csv,
    collected_at: datetime | None = None,
) -> dict[str, Any]:
    collected_at = (collected_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    groups: dict[str, dict[str, Any]] = {}
    requests: list[dict[str, Any]] = []
    stop_reason: str | None = None
    stop_http_status: int | None = None

    for index, spec in enumerate(GROUPS):
        try:
            rows, request_diag = fetcher(spec["query"])
        except SourceFetchError as exc:
            requests.append(
                {
                    "group": spec["query"],
                    "url": exc.url,
                    "http_status": exc.http_status,
                    "status": "error",
                    "reason": str(exc),
                }
            )
            groups[spec["key"]] = {
                "label": spec["label"],
                "query_group": spec["query"],
                "status": "unavailable",
                "reason": str(exc),
            }
            stop_reason = str(exc)
            stop_http_status = exc.http_status
            for remaining in GROUPS[index + 1 :]:
                groups[remaining["key"]] = {
                    "label": remaining["label"],
                    "query_group": remaining["query"],
                    "status": "not_attempted",
                    "reason": "collection stopped after the first source error",
                }
            break

        summary = summarize_group(rows, collected_at)
        groups[spec["key"]] = {
            "label": spec["label"],
            "query_group": spec["query"],
            **summary,
        }
        requests.append({"group": spec["query"], "status": "ok", **request_diag})

    groups_ok = sum(1 for group in groups.values() if group.get("status") == "ok")
    newest_epochs = [
        epoch
        for group in groups.values()
        if isinstance((epoch := group.get("newest_epoch_utc")), str)
    ]
    if groups_ok == len(GROUPS):
        status = "ok"
    elif groups_ok > 0:
        status = "partial"
    else:
        status = "unavailable"

    payload: dict[str, Any] = {
        "observer": OBSERVER,
        "category": CATEGORY,
        "date": date_str,
        "collected_at_utc": _iso_utc(collected_at),
        "status": status,
        "data_status": status,
        "summary": {
            "groups_requested": len(GROUPS),
            "groups_available": groups_ok,
            "groups_unavailable_or_not_attempted": len(GROUPS) - groups_ok,
            "freshest_selected_group_epoch_utc": max(newest_epochs) if newest_epochs else None,
            "group_counts_are_memberships": True,
            "groups_may_overlap": True,
            "global_satellite_total_calculated": False,
        },
        "groups": groups,
        "source": {
            "provider": "CelesTrak",
            "dataset": "Current GP Element Sets",
            "format": "CSV with OMM keywords",
            "documentation_url": DOCUMENTATION_URL,
            "usage_policy_url": USAGE_POLICY_URL,
        },
        "methodology": {
            "collection_cadence": "daily",
            "requests_per_run_max": len(GROUPS),
            "one_request_per_selected_group": True,
            "stop_after_first_source_error": True,
            "counts_are_per_group_records": True,
            "groups_are_not_assumed_disjoint": True,
            "no_global_total_from_group_sums": True,
            "no_orbit_propagation": True,
            "no_real_time_position_claims": True,
        },
        "diagnostics": {
            "api_attempts": len(requests),
            "retries": 0,
            "http_status": stop_http_status if stop_reason else 200,
            "stop_reason": stop_reason,
            "requests": requests,
        },
    }
    payload["history"] = _history(root, date_str, groups)
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def persist(payload: dict[str, Any], root: Path) -> None:
    date_str = str(payload.get("date") or _date_utc())[:10]
    _write_json(root / "state" / OBSERVER / f"{date_str}.json", payload)
    _write_json(root / "data" / "latest" / f"{OBSERVER}.json", payload)
    _write_json(root / "dashboard" / "latest" / f"{OBSERVER}.json", payload)


def _cached_payload(root: Path, date_str: str) -> dict[str, Any] | None:
    path = root / "state" / OBSERVER / f"{date_str}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("observer") != OBSERVER:
        return None
    return payload


def run(
    date_str: str | None = None,
    *,
    root: Path | None = None,
    fetcher: Callable[[str], tuple[list[dict[str, str]], dict[str, Any]]] = fetch_group_csv,
    collected_at: datetime | None = None,
) -> dict[str, Any]:
    root = root or _repo_root()
    date_str = date_str or _date_utc()
    cached = _cached_payload(root, date_str)
    if cached is not None:
        persist(cached, root)
        return cached
    payload = build_payload(date_str, root=root, fetcher=fetcher, collected_at=collected_at)
    persist(payload, root)
    return payload


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
