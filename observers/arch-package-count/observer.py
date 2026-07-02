#!/usr/bin/env python3
"""Arch Linux package count observer."""
from __future__ import annotations

import gzip
import io
import json
import os
import sys
import tarfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OBSERVER = "arch-package-count"
CATEGORY = "technology"
DISTRIBUTION = "Arch Linux"
REPOSITORIES = ("core", "extra")
ARCHITECTURE = "x86_64"
MIRROR_BASE_URL = "https://geo.mirror.pkgbuild.com"
SOURCE_URLS = {repo: f"{MIRROR_BASE_URL}/{repo}/os/{ARCHITECTURE}/{repo}.db" for repo in REPOSITORIES}
USER_AGENT = "WorldObserver/1.0"
TIMEOUT_S = 30
MAX_BYTES = 80_000_000


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _date_utc() -> str:
    raw = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch_repository_database(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream,*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
        return response.read(MAX_BYTES + 1)


def parse_repository_package_count(database_bytes: bytes) -> int:
    """Count packages in an official Arch sync database archive."""
    if len(database_bytes) > MAX_BYTES:
        raise ValueError("Arch repository database exceeded safety limit")
    try:
        stream = gzip.GzipFile(fileobj=io.BytesIO(database_bytes))
        tar_bytes = stream.read(MAX_BYTES + 1)
    except OSError:
        tar_bytes = database_bytes
    if len(tar_bytes) > MAX_BYTES:
        raise ValueError("decompressed Arch repository database exceeded safety limit")

    count = 0
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        for member in archive.getmembers():
            if member.isfile() and member.name.endswith("/desc"):
                count += 1
    if count <= 0:
        raise ValueError("no package desc entries found in Arch repository database")
    return count


def _history_points(root: Path) -> list[dict[str, Any]]:
    points: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "state" / OBSERVER).glob("*.json")):
        payload = _read_json(path)
        if not payload:
            continue
        value = payload.get("current_package_count")
        date = str(payload.get("date") or payload.get("date_utc") or path.stem)[:10]
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            points[date] = {"date": date, "value": value, "source": payload.get("source")}
    return [points[key] for key in sorted(points)]


def _avg(points: list[dict[str, Any]], days: int) -> float | None:
    values = [p["value"] for p in points[-days:] if isinstance(p.get("value"), (int, float)) and not isinstance(p.get("value"), bool)]
    return round(sum(values) / len(values), 2) if values else None


def build_payload(date: str, package_count: int | None, repository_counts: dict[str, int], diagnostics: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = root or _repo_root()
    status = "ok" if isinstance(package_count, int) and package_count > 0 else "unavailable"
    history = _history_points(root)
    if status == "ok":
        history = [point for point in history if point.get("date") != date]
        history.append({"date": date, "value": package_count, "source": "Official Arch Linux repository databases"})
        history.sort(key=lambda point: point["date"])
    values = [p["value"] for p in history if isinstance(p.get("value"), (int, float)) and not isinstance(p.get("value"), bool)]
    previous = values[-2] if len(values) >= 2 else None
    delta = package_count - previous if isinstance(package_count, int) and previous is not None else None
    return {
        "observer": OBSERVER,
        "category": CATEGORY,
        "date": date,
        "status": status,
        "data_status": status,
        "current_package_count": package_count if status == "ok" else None,
        "unit": "packages",
        "distribution": DISTRIBUTION,
        "repositories": list(REPOSITORIES),
        "repository_counts": repository_counts if status == "ok" else {},
        "architecture": ARCHITECTURE,
        "source": "Official Arch Linux repository databases",
        "source_url": SOURCE_URLS,
        "history": history,
        "averages": {"30d": _avg(history, 30), "365d": _avg(history, 365)},
        "average_30d": _avg(history, 30),
        "average_365d": _avg(history, 365),
        "historical_min": min(values) if values else None,
        "historical_max": max(values) if values else None,
        "trend_delta": delta,
        "trend_delta_percent": round((delta / previous) * 100, 2) if delta is not None and previous not in (None, 0) else None,
        "trend_direction": "up" if isinstance(delta, int) and delta > 0 else ("down" if isinstance(delta, int) and delta < 0 else "flat" if delta == 0 else None),
        "observed_changes": [] if delta in (None, 0) else [{"metric": "current_package_count", "delta": delta, "unit": "packages"}],
        "diagnostics": diagnostics,
    }


def run(date: str | None = None, root: Path | None = None) -> dict[str, Any]:
    date = date or _date_utc()
    diagnostics: dict[str, Any] = {"api_attempts": 0, "retries": 0, "http_status": None, "fetch_urls": SOURCE_URLS}
    repository_counts: dict[str, int] = {}
    package_count: int | None = None
    try:
        for repo, url in SOURCE_URLS.items():
            diagnostics["api_attempts"] += 1
            database_bytes = fetch_repository_database(url)
            diagnostics.setdefault("compressed_bytes", {})[repo] = len(database_bytes)
            repository_counts[repo] = parse_repository_package_count(database_bytes)
        package_count = sum(repository_counts.values())
        diagnostics["parse_status"] = "ok"
    except (OSError, urllib.error.URLError, tarfile.TarError, ValueError) as exc:
        diagnostics["parse_status"] = "unavailable"
        diagnostics["reason"] = f"Arch repository database fetch/parse failed: {type(exc).__name__}: {exc}"
        repository_counts = {}
    payload = build_payload(date, package_count, repository_counts, diagnostics, root=root)
    if root is None:
        root = _repo_root()
    _write_json(root / "state" / OBSERVER / f"{date}.json", payload)
    _write_json(root / "data" / "latest" / f"{OBSERVER}.json", payload)
    return payload


def main() -> None:
    json.dump(run(), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
