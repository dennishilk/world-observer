#!/usr/bin/env python3
"""Linux Kernel Size Observer."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OBSERVER = "linux-kernel-size"
CATEGORY = "technology"
RELEASES_URL = "https://www.kernel.org/releases.json"
USER_AGENT = "world-observer/1.0 (+https://github.com/dennishilk/world-observer)"
TIMEOUT_S = 20


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


def fetch_json(url: str = RELEASES_URL) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
        return json.loads(response.read(2_000_000).decode("utf-8", errors="replace"))


def head_content_length(url: str) -> tuple[int | None, int | None]:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
        length = response.headers.get("Content-Length")
        status = getattr(response, "status", None)
    try:
        return (int(length), status) if length is not None else (None, status)
    except ValueError:
        return None, status


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version)[:4])


def _tarball_url(version: str, source: str | None = None) -> str:
    if source and source.startswith("http"):
        return source
    major = _version_key(version)[0] if _version_key(version) else 0
    return f"https://cdn.kernel.org/pub/linux/kernel/v{major}.x/linux-{version}.tar.xz"


def _release_date(release: dict[str, Any] | None) -> str | None:
    if not isinstance(release, dict):
        return None
    released = release.get("released")
    if isinstance(released, dict):
        for key in ("timestamp", "isodate", "date"):
            value = released.get(key)
            if isinstance(value, str) and value:
                return value
    for key in ("release_date", "date"):
        value = release.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def latest_stable_release(payload: dict[str, Any]) -> dict[str, Any] | None:
    releases = payload.get("releases")
    if not isinstance(releases, list):
        return None
    stable: list[dict[str, Any]] = []
    for item in releases:
        if not isinstance(item, dict):
            continue
        moniker = str(item.get("moniker") or item.get("name") or "").lower()
        version = item.get("version")
        if isinstance(version, str) and moniker == "stable":
            stable.append(item)
    if not stable:
        return None
    return max(stable, key=lambda item: _version_key(str(item.get("version") or "0")))


def _history_points(root: Path) -> list[dict[str, Any]]:
    points: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "state" / OBSERVER).glob("*.json")):
        payload = _read_json(path)
        if not payload:
            continue
        value = payload.get("current_size_mb")
        date = str(payload.get("date") or payload.get("date_utc") or path.stem)[:10]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            points[date] = {"date": date, "value": round(float(value), 2), "version": payload.get("version"), "source": payload.get("source")}
    return [points[key] for key in sorted(points)]


def _avg(points: list[dict[str, Any]], days: int) -> float | None:
    vals = [p["value"] for p in points[-days:] if isinstance(p.get("value"), (int, float))]
    return round(sum(vals) / len(vals), 2) if vals else None


def build_payload(date: str, release: dict[str, Any] | None, size_bytes: int | None, diagnostics: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = root or _repo_root()
    status = "ok" if release and isinstance(size_bytes, int) and size_bytes > 0 else "unavailable"
    version = str(release.get("version")) if release and release.get("version") else None
    source_url = _tarball_url(version, release.get("source") if isinstance(release.get("source"), str) else None) if version else None
    current_mb = round(size_bytes / 1_000_000, 2) if isinstance(size_bytes, int) and size_bytes > 0 else None
    history = _history_points(root)
    if current_mb is not None:
        history = [p for p in history if p.get("date") != date]
        history.append({"date": date, "value": current_mb, "version": version, "source": "kernel.org"})
        history.sort(key=lambda p: p["date"])
    values = [p["value"] for p in history if isinstance(p.get("value"), (int, float))]
    previous = values[-2] if len(values) >= 2 else None
    delta = round(current_mb - previous, 2) if current_mb is not None and previous is not None else None
    return {
        "observer": OBSERVER,
        "category": CATEGORY,
        "date": date,
        "status": status,
        "data_status": status,
        "current_size_mb": current_mb,
        "current_size_bytes": size_bytes if isinstance(size_bytes, int) and size_bytes > 0 else None,
        "unit": "MB",
        "version": version,
        "release_date": _release_date(release),
        "source": "kernel.org releases.json and tarball HEAD Content-Length",
        "source_url": source_url,
        "history": history,
        "average_30d": _avg(history, 30),
        "average_365d": _avg(history, 365),
        "historical_min": round(min(values), 2) if values else None,
        "historical_max": round(max(values), 2) if values else None,
        "trend_delta": delta,
        "trend_delta_percent": round((delta / previous) * 100, 2) if delta is not None and previous not in (None, 0) else None,
        "observed_changes": [] if delta in (None, 0) else [{"metric": "current_size_mb", "delta": delta, "unit": "MB"}],
        "diagnostics": diagnostics,
    }


def run(date: str | None = None, root: Path | None = None) -> dict[str, Any]:
    date = date or _date_utc()
    diagnostics: dict[str, Any] = {"api_attempts": 0, "retries": 0, "http_status": None, "metadata_url": RELEASES_URL}
    release = None
    size_bytes = None
    try:
        diagnostics["api_attempts"] += 1
        metadata = fetch_json(RELEASES_URL)
        release = latest_stable_release(metadata)
        if release is None:
            diagnostics["reason"] = "no stable release in kernel.org metadata"
        else:
            source_url = _tarball_url(str(release.get("version")), release.get("source") if isinstance(release.get("source"), str) else None)
            diagnostics["tarball_url"] = source_url
            size_bytes, diagnostics["http_status"] = head_content_length(source_url)
            if size_bytes is None:
                diagnostics["reason"] = "tarball HEAD did not include numeric Content-Length"
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        diagnostics["reason"] = f"kernel.org fetch failed: {type(exc).__name__}: {exc}"
    payload = build_payload(date, release, size_bytes, diagnostics, root=root)
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
