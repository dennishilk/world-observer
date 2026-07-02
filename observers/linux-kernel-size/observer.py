#!/usr/bin/env python3
"""Linux Kernel Size Observer."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse
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


ARCHIVE_EXTENSIONS = (".tar.xz", ".tar.gz", ".tar.bz2")
PATCH_EXTENSIONS = (".xz", ".gz", ".bz2", "")


def _walk_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for nested in value.values():
            values.extend(_walk_values(nested))
        return values
    if isinstance(value, list):
        values = []
        for nested in value:
            values.extend(_walk_values(nested))
        return values
    return []


def _dedupe(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url not in seen:
            unique.append(url)
            seen.add(url)
    return unique


def _official_urls(release: dict[str, Any] | None) -> list[str]:
    if not isinstance(release, dict):
        return []
    return _dedupe([value for value in _walk_values(release) if value.startswith(("https://", "http://"))])


def _is_tarball_url(url: str, version: str) -> bool:
    path = urlparse(url).path
    filename = path.rsplit("/", 1)[-1]
    return filename == f"linux-{version}.tar.xz" or any(filename == f"linux-{version}{ext}" for ext in ARCHIVE_EXTENSIONS)


def _is_patch_url(url: str, version: str) -> bool:
    filename = urlparse(url).path.rsplit("/", 1)[-1]
    return any(filename == f"patch-{version}{ext}" for ext in PATCH_EXTENSIONS)


def _tarball_candidates_from_patch_url(url: str, version: str) -> list[str]:
    parsed = urlparse(url)
    directory = url.rsplit("/", 1)[0]
    candidates = [f"{directory}/linux-{version}{ext}" for ext in ARCHIVE_EXTENSIONS]

    # kernel.org commonly exposes equivalent CDN and www archive hosts.  Only
    # try this documented archive host fallback after a release metadata patch
    # URL has established the archive directory for this version.
    if parsed.netloc == "www.kernel.org":
        candidates.extend(candidate.replace("https://www.kernel.org/", "https://cdn.kernel.org/") for candidate in candidates.copy())
    elif parsed.netloc == "cdn.kernel.org":
        candidates.extend(candidate.replace("https://cdn.kernel.org/", "https://www.kernel.org/") for candidate in candidates.copy())
    return _dedupe(candidates)


def tarball_candidates(release: dict[str, Any] | None) -> list[str]:
    """Return official or safely-derived kernel source archive candidates.

    Direct archive links from releases.json are authoritative.  If releases.json
    only exposes patch links, derive source archive URLs within the same
    kernel.org archive directory and let HEAD verification select a usable URL.
    """
    version = str(release.get("version") or "") if isinstance(release, dict) else ""
    if not version:
        return []
    urls = _official_urls(release)
    direct = [url for url in urls if _is_tarball_url(url, version)]
    if direct:
        return direct
    candidates: list[str] = []
    for url in urls:
        if _is_patch_url(url, version):
            candidates.extend(_tarball_candidates_from_patch_url(url, version))
    return _dedupe(candidates)


def _tarball_url(version: str, source: str | None = None) -> str | None:
    if source and source.startswith("http") and _is_tarball_url(source, version):
        return source
    return None


def resolve_tarball_head(release: dict[str, Any]) -> tuple[int | None, int | None, str | None, str | None, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for url in tarball_candidates(release):
        try:
            size_bytes, status = head_content_length(url)
        except urllib.error.HTTPError as exc:
            attempts.append({"url": url, "http_status": exc.code, "error": f"HTTPError: {exc}"})
            continue
        except (OSError, urllib.error.URLError) as exc:
            attempts.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
            continue
        attempts.append({"url": url, "http_status": status, "content_length": size_bytes})
        if isinstance(size_bytes, int) and size_bytes > 0:
            return size_bytes, status, url, None, attempts
    if attempts:
        return None, attempts[-1].get("http_status"), attempts[-1].get("url"), "no verified kernel source archive URL with numeric Content-Length", attempts
    return None, None, None, "no kernel source archive URL available in release metadata", attempts


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


SUPPORTED_RELEASE_MONIKERS = ("stable", "longterm")


def _is_supported_release(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    moniker = str(item.get("moniker") or item.get("name") or "").lower()
    version = item.get("version")
    if moniker not in SUPPORTED_RELEASE_MONIKERS or not isinstance(version, str) or not version:
        return False
    if item.get("iseol") is True:
        return False
    return not re.search(r"(?:^|[-.])(?:rc|pre|next)", version, flags=re.IGNORECASE)


def supported_release_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    releases = payload.get("releases")
    if not isinstance(releases, list):
        return []
    return [item for item in releases if _is_supported_release(item)]


def stable_release_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Backward-compatible alias for supported release candidates."""
    return supported_release_candidates(payload)


def latest_stable_release(payload: dict[str, Any]) -> dict[str, Any] | None:
    stable = [item for item in supported_release_candidates(payload) if str(item.get("moniker") or item.get("name") or "").lower() == "stable"]
    if not stable:
        return None
    return max(stable, key=lambda item: _version_key(str(item.get("version") or "0")))


def select_verified_stable_release(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, int | None, dict[str, Any]]:
    diagnostics: dict[str, Any] = {"tarball_head_attempts": []}
    candidates = supported_release_candidates(payload)
    if not candidates:
        diagnostics["reason"] = "no supported stable or longterm release in kernel.org metadata"
        return None, None, diagnostics

    for release in candidates:
        size_bytes, http_status, source_url, reason, attempts = resolve_tarball_head(release)
        diagnostics["tarball_head_attempts"].extend(
            {"moniker": release.get("moniker") or release.get("name"), "version": release.get("version"), **attempt} for attempt in attempts
        )
        diagnostics["http_status"] = http_status
        if isinstance(size_bytes, int) and size_bytes > 0 and isinstance(source_url, str):
            diagnostics["tarball_url"] = source_url
            return release, size_bytes, diagnostics
        diagnostics["reason"] = reason or "no verified kernel source archive URL with numeric Content-Length"

    diagnostics.pop("tarball_url", None)
    if len(candidates) != 1 or diagnostics.get("tarball_head_attempts"):
        diagnostics["reason"] = "no verified supported stable or longterm kernel source archive URL with numeric Content-Length"
    return None, None, diagnostics


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
    verified = status == "ok"
    version = str(release.get("version")) if verified and release and release.get("version") else None
    source_url = diagnostics.get("tarball_url") if verified and isinstance(diagnostics.get("tarball_url"), str) else None
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
        "release_date": _release_date(release) if verified else None,
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
        release, size_bytes, release_diagnostics = select_verified_stable_release(metadata)
        diagnostics.update(release_diagnostics)
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
