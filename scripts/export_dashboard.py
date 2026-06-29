#!/usr/bin/env python3
"""Export stable website dashboard JSON from data/latest observer snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_daily import OBSERVERS

DASHBOARD_VERSION = 1
MEDIA_OBSERVER = "media-language-germany"
SUMMARY_NAME = "summary.json"
OUTPUT_FILES = ("summary.json", "internet.json", "media.json", "society.json", "environment.json")
HISTORY_FILES = ("history/media-language-germany.json",)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> Tuple[Dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "JSON root is not an object"
    return payload, None


def _status(payload: Dict[str, Any] | None) -> str:
    if payload is None:
        return "missing"
    if payload.get("status") == "error" or payload.get("data_status") == "error":
        return "error"
    return str(payload.get("data_status") or payload.get("status") or "ok")


def _is_ok(status: str) -> bool:
    return status == "ok"


def _is_degraded(status: str) -> bool:
    return status in {"partial", "unavailable", "error"}


def _compact_write(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _load_latest(latest_dir: Path) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    loaded: Dict[str, Dict[str, Any]] = {}
    errors: Dict[str, str] = {}
    for observer in OBSERVERS:
        path = latest_dir / f"{observer}.json"
        if not path.exists():
            errors[observer] = "missing"
            continue
        payload, error = _read_json(path)
        if payload is None:
            errors[observer] = error or "invalid JSON"
            continue
        loaded[observer] = payload
    return loaded, errors


def _summary(latest_dir: Path, generated_at: str, loaded: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    observer_statuses = {observer: _status(loaded.get(observer)) for observer in OBSERVERS}
    missing = sorted(observer for observer in OBSERVERS if observer not in loaded)
    degraded = sorted(observer for observer, status in observer_statuses.items() if _is_degraded(status))
    ok = sorted(observer for observer, status in observer_statuses.items() if _is_ok(status))
    categories = {
        "internet": sum(1 for observer in OBSERVERS if observer != MEDIA_OBSERVER),
        "media": 1 if MEDIA_OBSERVER in OBSERVERS else 0,
        "society": 0,
        "environment": 0,
    }
    latest_summary, _ = _read_json(latest_dir / SUMMARY_NAME) if (latest_dir / SUMMARY_NAME).exists() else (None, None)
    payload: Dict[str, Any] = {
        "generated_at": generated_at,
        "observer_count": len(OBSERVERS),
        "observers_ok": len(ok),
        "degraded_count": len(degraded),
        "missing_count": len(missing),
        "categories": categories,
        "dashboard_version": DASHBOARD_VERSION,
    }
    if latest_summary:
        for key in ("last_run_utc", "latest_date_utc"):
            if key in latest_summary:
                payload[key] = latest_summary[key]
    if missing:
        payload["missing_observers"] = missing
    if degraded:
        payload["degraded_observers"] = degraded
    return payload


def _media(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    if not payload:
        return {"status": "missing"}
    source_groups = payload.get("source_groups") if isinstance(payload.get("source_groups"), dict) else {}
    return {
        "fear_index_overall": payload.get("fear_index_overall", payload.get("fear_index")),
        "headline_count": payload.get("headline_count"),
        "public_broadcast": source_groups.get("public_broadcast", {}),
        "private_media": source_groups.get("private_media", {}),
        "top_terms": payload.get("top_terms", []),
        "category_counts": payload.get("category_counts", {}),
    }


def _as_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(value, 2)
    return None


def _group_fear_index(source_groups: Dict[str, Any], name: str) -> float | int | None:
    group = source_groups.get(name)
    if isinstance(group, dict):
        return _as_number(group.get("fear_index") or group.get("fear_index_overall"))
    return _as_number(group)


def _top_term_strings(value: Any, limit: int = 3) -> list[str]:
    terms: list[str] = []
    if not isinstance(value, list):
        return terms
    for item in value:
        term = item.get("term") if isinstance(item, dict) else item
        if isinstance(term, str) and term:
            terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def _media_history_point(date: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    source_groups = payload.get("source_groups") if isinstance(payload.get("source_groups"), dict) else {}
    point: Dict[str, Any] = {"date": date}
    fields = (
        ("fear_index_overall", _as_number(payload.get("fear_index_overall", payload.get("fear_index")))),
        ("public_broadcast", _group_fear_index(source_groups, "public_broadcast")),
        ("private_media", _group_fear_index(source_groups, "private_media")),
        ("headline_count", _as_number(payload.get("headline_count"))),
    )
    for key, value in fields:
        if value is not None:
            point[key] = value
    terms = _top_term_strings(payload.get("top_terms"))
    if terms:
        point["top_terms"] = terms
    return point


def _window_summary(points: list[Dict[str, Any]], days: int) -> Dict[str, Any]:
    window = points[-days:]
    values = [point["fear_index_overall"] for point in window if isinstance(point.get("fear_index_overall"), (int, float))]
    summary: Dict[str, Any] = {"count": len(window)}
    if values:
        latest = values[-1]
        summary.update(
            {
                "latest": latest,
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "avg": round(sum(values) / len(values), 2),
            }
        )
        if len(values) >= 2:
            previous = values[-2]
            summary["previous"] = previous
            summary["delta"] = round(latest - previous, 2)
    return summary


def _iter_daily_media_files(daily_dir: Path) -> Iterable[tuple[str, Path]]:
    if not daily_dir.exists():
        return []
    files: list[tuple[str, Path]] = []
    for date_dir in daily_dir.iterdir():
        if not date_dir.is_dir():
            continue
        try:
            datetime.strptime(date_dir.name, "%Y-%m-%d")
        except ValueError:
            continue
        path = date_dir / f"{MEDIA_OBSERVER}.json"
        if path.exists():
            files.append((date_dir.name, path))
    return sorted(files)


def _media_history(daily_dir: Path, generated_at: str) -> Dict[str, Any]:
    points: list[Dict[str, Any]] = []
    for date, path in _iter_daily_media_files(daily_dir):
        payload, _error = _read_json(path)
        if payload is None:
            continue
        points.append(_media_history_point(date, payload))
    return {
        "observer": MEDIA_OBSERVER,
        "generated_at": generated_at,
        "points": points,
        "windows": {
            "7d": _window_summary(points, 7),
            "30d": _window_summary(points, 30),
        },
    }


def _internet_observer(observer: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    item: Dict[str, Any] = {"observer": observer, "status": _status(payload)}
    for key in ("timestamp", "date_utc", "date", "summary", "highlights", "score", "score_percent", "notes"):
        value = payload.get(key)
        if value is not None:
            item[key] = value
    return item


def _internet(loaded: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    observers = [
        _internet_observer(observer, loaded[observer])
        for observer in sorted(loaded)
        if observer != MEDIA_OBSERVER
    ]
    return {"observer_count": len(observers), "observers": observers}


def export_dashboard(
    latest_dir: Path | None = None, dashboard_dir: Path | None = None, daily_dir: Path | None = None
) -> Dict[str, Path]:
    latest_dir = latest_dir or (_repo_root() / "data" / "latest")
    dashboard_dir = dashboard_dir or (_repo_root() / "dashboard")
    daily_dir = daily_dir or (_repo_root() / "data" / "daily")
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    generated_at = _utc_now()
    loaded, _errors = _load_latest(latest_dir)
    outputs = {
        "summary.json": _summary(latest_dir, generated_at, loaded),
        "internet.json": _internet(loaded),
        "media.json": _media(loaded.get(MEDIA_OBSERVER)),
        "society.json": {"status": "placeholder", "items": []},
        "environment.json": {"status": "placeholder", "items": []},
        "history/media-language-germany.json": _media_history(daily_dir, generated_at),
    }
    written: Dict[str, Path] = {}
    for name in (*OUTPUT_FILES, *HISTORY_FILES):
        path = dashboard_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _compact_write(path, outputs[name])
        written[name] = path
    return written


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export compact dashboard JSON from data/latest.")
    parser.add_argument("--latest-dir", type=Path, default=None, help="Input latest data directory.")
    parser.add_argument("--dashboard-dir", type=Path, default=None, help="Output dashboard directory.")
    parser.add_argument("--daily-dir", type=Path, default=None, help="Input daily data directory for history exports.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    written = export_dashboard(args.latest_dir, args.dashboard_dir, args.daily_dir)
    for path in written.values():
        print(path)


if __name__ == "__main__":
    main()
