#!/usr/bin/env python3
"""Debian package count observer."""
from __future__ import annotations

import json
import lzma
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OBSERVER = "debian-package-count"
CATEGORY = "technology"
DISTRIBUTION = "Debian"
SUITE = "stable"
ARCHITECTURE = "amd64"
COMPONENT = "main"
SOURCE_URL = f"https://deb.debian.org/debian/dists/{SUITE}/{COMPONENT}/binary-{ARCHITECTURE}/Packages.xz"
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


def fetch_package_index(url: str = SOURCE_URL) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream,*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
        return response.read(MAX_BYTES + 1)


def parse_package_count(index_bytes: bytes) -> int:
    if len(index_bytes) > MAX_BYTES:
        raise ValueError("Debian Packages index exceeded safety limit")
    text = lzma.decompress(index_bytes).decode("utf-8", errors="replace")
    count = sum(1 for line in text.splitlines() if line.startswith("Package: "))
    if count <= 0:
        raise ValueError("no Package entries found in Debian Packages index")
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


def build_payload(date: str, package_count: int | None, diagnostics: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = root or _repo_root()
    status = "ok" if isinstance(package_count, int) and package_count > 0 else "unavailable"
    history = _history_points(root)
    if isinstance(package_count, int) and package_count > 0:
        history = [point for point in history if point.get("date") != date]
        history.append({"date": date, "value": package_count, "source": "Debian Packages index"})
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
        "suite": SUITE,
        "architecture": ARCHITECTURE,
        "component": COMPONENT,
        "source": "Official Debian repository Packages index",
        "source_url": SOURCE_URL,
        "history": history,
        "average_30d": _avg(history, 30),
        "average_365d": _avg(history, 365),
        "historical_min": min(values) if values else None,
        "historical_max": max(values) if values else None,
        "trend_delta": delta,
        "trend_delta_percent": round((delta / previous) * 100, 2) if delta is not None and previous not in (None, 0) else None,
        "observed_changes": [] if delta in (None, 0) else [{"metric": "current_package_count", "delta": delta, "unit": "packages"}],
        "diagnostics": diagnostics,
    }


def run(date: str | None = None, root: Path | None = None) -> dict[str, Any]:
    date = date or _date_utc()
    diagnostics: dict[str, Any] = {"api_attempts": 0, "retries": 0, "http_status": None, "fetch_url": SOURCE_URL}
    package_count: int | None = None
    try:
        diagnostics["api_attempts"] += 1
        index_bytes = fetch_package_index(SOURCE_URL)
        diagnostics["compressed_bytes"] = len(index_bytes)
        package_count = parse_package_count(index_bytes)
        diagnostics["parse_status"] = "ok"
    except (OSError, urllib.error.URLError, lzma.LZMAError, UnicodeDecodeError, ValueError) as exc:
        diagnostics["parse_status"] = "unavailable"
        diagnostics["reason"] = f"Debian Packages index fetch/parse failed: {type(exc).__name__}: {exc}"
    payload = build_payload(date, package_count, diagnostics, root=root)
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
