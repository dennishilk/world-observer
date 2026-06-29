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
OUTPUT_FILES = ("summary.json", "internet.json", "media.json", "society.json", "environment.json", "heartbeat.json")
HISTORY_FILES = ("history/media-language-germany.json", "history/internet-observers.json")
METADATA_PATH = "config/observer_metadata.json"


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


def _load_metadata(path: Path | None = None) -> Dict[str, Dict[str, Any]]:
    path = path or (_repo_root() / METADATA_PATH)
    payload, _error = _read_json(path) if path.exists() else (None, None)
    if payload is None:
        return {}
    entries = payload.get("observers")
    if not isinstance(entries, list):
        return {}
    metadata: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        observer = entry.get("observer")
        if isinstance(observer, str) and observer:
            metadata[observer] = entry
    return metadata


def _status(payload: Dict[str, Any] | None) -> str:
    if payload is None:
        return "missing"
    if payload.get("status") == "error" or payload.get("data_status") == "error":
        return "error"
    return str(payload.get("status") or payload.get("data_status") or "ok")


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


def _metadata_value(metadata: Dict[str, Dict[str, Any]], observer: str, key: str, fallback: Any = None) -> Any:
    value = metadata.get(observer, {}).get(key)
    return fallback if value is None else value


def _metadata_category(metadata: Dict[str, Dict[str, Any]], observer: str) -> str:
    value = _metadata_value(metadata, observer, "category")
    if isinstance(value, str) and value:
        return value
    return "media" if observer == MEDIA_OBSERVER else "internet"


def _metadata_priority(metadata: Dict[str, Dict[str, Any]], observer: str) -> int:
    value = _metadata_value(metadata, observer, "dashboard_priority")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 10_000


def _summary(
    latest_dir: Path,
    generated_at: str,
    loaded: Dict[str, Dict[str, Any]],
    metadata: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    observer_statuses = {
        observer: (
            _internet_status_fields(observer, loaded[observer])[0]
            if observer in loaded and _metadata_category(metadata, observer) == "internet"
            else _status(loaded.get(observer))
        )
        for observer in OBSERVERS
    }
    missing = sorted(observer for observer in OBSERVERS if observer not in loaded)
    degraded = sorted(observer for observer, status in observer_statuses.items() if _is_degraded(status))
    ok = sorted(observer for observer, status in observer_statuses.items() if _is_ok(status))
    categories = {category: 0 for category in ("internet", "media", "society", "environment")}
    for observer in OBSERVERS:
        category = _metadata_category(metadata, observer)
        categories[category] = categories.get(category, 0) + 1
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


def _window_summary(points: list[Dict[str, Any]], days: int, value_key: str = "fear_index_overall") -> Dict[str, Any]:
    window = points[-days:]
    values = [point[value_key] for point in window if isinstance(point.get(value_key), (int, float))]
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


def _parse_utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _heartbeat_freshness(latest_heartbeat_utc: str | None, generated_at: str) -> str:
    latest = _parse_utc_datetime(latest_heartbeat_utc)
    generated = _parse_utc_datetime(generated_at)
    if latest is None or generated is None:
        return "unavailable"
    age_hours = max(0.0, (generated - latest).total_seconds() / 3600)
    if age_hours <= 2:
        return "alive"
    if age_hours <= 6:
        return "delayed"
    if age_hours <= 24:
        return "old"
    return "offline"


def _heartbeat(heartbeat_dir: Path, generated_at: str) -> Dict[str, Any]:
    files = sorted(path for path in heartbeat_dir.glob("*.json") if path.is_file()) if heartbeat_dir.exists() else []
    if not files:
        return {
            "status": "unavailable",
            "freshness_status": "unavailable",
            "latest_heartbeat_utc": None,
            "heartbeat_file": None,
            "generated_at": generated_at,
        }

    path = files[-1]
    payload, _error = _read_json(path)
    status = "unavailable"
    latest_heartbeat_utc = None
    if payload is not None:
        status_value = payload.get("status")
        if isinstance(status_value, str) and status_value:
            status = status_value
        timestamp_value = payload.get("timestamp_utc")
        if isinstance(timestamp_value, str) and timestamp_value:
            latest_heartbeat_utc = timestamp_value

    return {
        "status": status,
        "freshness_status": _heartbeat_freshness(latest_heartbeat_utc, generated_at),
        "latest_heartbeat_utc": latest_heartbeat_utc,
        "heartbeat_file": path.name,
        "generated_at": generated_at,
    }


def _display_name(observer: str) -> str:
    return " ".join(part.upper() if part in {"dns", "ipv6", "tls", "mx"} else part.capitalize() for part in observer.split("-"))


def _metadata_display_name(metadata: Dict[str, Dict[str, Any]], observer: str) -> str:
    value = _metadata_value(metadata, observer, "display_name")
    return value if isinstance(value, str) and value else _display_name(observer)


def _find_path(payload: Any, path: tuple[str, ...]) -> Any:
    value = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _first_numeric_path(payload: Dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> tuple[str, float | int] | None:
    for path in paths:
        value = _as_number(_find_path(payload, path))
        if value is not None:
            return ".".join(path), value
    return None


def _iter_named_numbers(value: Any, names: tuple[str, ...]) -> Iterable[tuple[str, float | int]]:
    if isinstance(value, dict):
        for key, child in value.items():
            number = _as_number(child)
            if number is not None and any(name in key.lower() for name in names):
                yield key, number
            elif isinstance(child, (dict, list)):
                for child_key, child_number in _iter_named_numbers(child, names):
                    yield f"{key}.{child_key}", child_number
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                for child_key, child_number in _iter_named_numbers(child, names):
                    yield f"{index}.{child_key}", child_number


def _find_named_number(value: Any, name: str, prefix: str = "") -> tuple[str, float | int] | None:
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            number = _as_number(child)
            if number is not None and key.lower() == name:
                return path, number
            if isinstance(child, (dict, list)):
                found = _find_named_number(child, name, path)
                if found is not None:
                    return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                path = f"{prefix}.{index}" if prefix else str(index)
                found = _find_named_number(child, name, path)
                if found is not None:
                    return found
    return None


def _internet_metric(observer: str, payload: Dict[str, Any]) -> tuple[str, float | int | str]:
    summary_stats = payload.get("summary_stats")
    if observer in {"asn-visibility-by-country", "ipv6-global-compare", "ipv6-locked-states"} and isinstance(summary_stats, dict):
        countries_evaluated = _as_number(summary_stats.get("countries_evaluated"))
        if countries_evaluated is not None:
            return "countries evaluated", countries_evaluated
        significant_count = _as_number(summary_stats.get("significant_count"))
        if significant_count is not None:
            return "significant events", significant_count

    rules: dict[str, tuple[tuple[str, ...], ...]] = {
        "area51-reachability": (("au", "total"), ("bucket_count",)),
        "global-reachability-score": (("score",), ("score_percent",)),
        "internet-shrinkage-index": (("score",), ("index",)),
        "asn-visibility-by-country": (("summary_stats", "countries_evaluated"), ("summary_stats", "significant_count")),
        "ipv6-global-compare": (("summary_stats", "countries_evaluated"), ("summary_stats", "significant_count"), ("percentage",), ("score",), ("score_percent",)),
        "ipv6-locked-states": (("summary_stats", "countries_evaluated"), ("summary_stats", "significant_count")),
        "dns-time-to-answer-index": (("median_response_ms",), ("avg_response_ms",), ("median_ms",), ("avg_ms",)),
        "dns-tta-stress-index": (("stress",), ("timeout_count",), ("timeouts",)),
        "tls-fingerprint-change": (("change_count",), ("changes",)),
        "mx-presence-by-country": (("countries",), ("coverage_count",), ("coverage",)),
        "mx-presence-per-country": (("countries",), ("coverage_count",), ("coverage",)),
        "silent-countries-list": (("silent_country_count",), ("silent_countries",), ("count",)),
        "traceroute-to-nowhere": (("anomaly_count",), ("anomalies",)),
        "north-korea-connectivity": (("probes_succeeded",), ("reachability_count",), ("reachable_count",)),
        "iran-dns-behavior": (("answered",), ("servfail",), ("answered_count",), ("servfail_count",)),
        "undersea-cable-dependency": (("score",), ("count",)),
        "undersea-cable-dependency-map": (("score",), ("count",)),
    }
    direct = _first_numeric_path(payload, rules.get(observer, ()))
    if direct is not None:
        return direct
    ordered_names = {
        "global-reachability-score": ("score", "score_percent"),
        "internet-shrinkage-index": ("score", "index", "global_shrinkage_index", "shrinkage_score"),
        "asn-visibility-by-country": ("countries_evaluated", "significant_count", "asn_visible_count"),
        "ipv6-global-compare": ("countries_evaluated", "significant_count", "percentage", "score", "score_percent"),
        "ipv6-locked-states": ("countries_evaluated", "significant_count", "ipv6_capable_rate"),
        "dns-time-to-answer-index": ("median_response_ms", "avg_response_ms", "median_ms", "avg_ms", "avg_query_ms", "query_ms"),
        "dns-tta-stress-index": ("stress", "timeout_count", "timeouts", "timeout_rate", "dns_stress_score"),
        "tls-fingerprint-change": ("change_count", "changes", "tls_change_score"),
        "mx-presence-by-country": ("countries", "coverage_count", "coverage", "mx_present_count"),
        "mx-presence-per-country": ("countries", "coverage_count", "coverage", "mx_present_count"),
        "silent-countries-list": ("silent_country_count", "silent_countries", "count", "countries_evaluated", "silence_score"),
        "traceroute-to-nowhere": ("anomaly_count", "anomalies", "trace_count", "count"),
        "north-korea-connectivity": ("probes_succeeded", "reachability_count", "reachable_count", "probe_count"),
        "iran-dns-behavior": ("answered", "servfail", "answered_count", "servfail_count"),
        "undersea-cable-dependency": ("score", "count", "cable_count"),
        "undersea-cable-dependency-map": ("score", "count", "cable_count", "landing_count"),
    }.get(observer, ("score", "index", "count", "percentage"))
    for name in ordered_names:
        found = _find_named_number(payload, name)
        if found is not None:
            return found
    keywords = {
        "dns-time-to-answer-index": ("median", "avg", "response", "query_ms"),
        "dns-tta-stress-index": ("stress", "timeout"),
        "tls-fingerprint-change": ("change",),
        "mx-presence-by-country": ("countries", "coverage", "count"),
        "mx-presence-per-country": ("countries", "coverage", "count"),
        "silent-countries-list": ("silent", "count"),
        "traceroute-to-nowhere": ("anomaly", "count"),
        "north-korea-connectivity": ("succeeded", "reachability", "reachable"),
        "iran-dns-behavior": ("answered", "servfail"),
        "undersea-cable-dependency": ("score", "count"),
        "undersea-cable-dependency-map": ("score", "count"),
    }.get(observer, ("score", "index", "count", "percentage"))
    for name, value in _iter_named_numbers(payload, keywords):
        return name, value
    return "data_status", _status(payload)


def _secondary_metrics(payload: Dict[str, Any], primary_name: str, limit: int = 3) -> Dict[str, float | int]:
    metrics: Dict[str, float | int] = {}
    for name, value in _iter_named_numbers(payload, ("score", "index", "count", "percent", "total", "median", "avg", "evaluated", "significant")):
        display_name = name.replace("summary_stats.", "")
        normalized_display = display_name.replace("_", " ")
        if name == primary_name or display_name == primary_name or normalized_display == primary_name or name.startswith("diagnostics."):
            continue
        metrics[display_name] = value
        if len(metrics) >= limit:
            break
    return metrics


def _last_seen_date(payload: Dict[str, Any]) -> Any:
    return payload.get("date_utc") or payload.get("date") or payload.get("timestamp")


def _internet_status_fields(observer: str, payload: Dict[str, Any]) -> tuple[str, str]:
    status = _status(payload)
    data_status = str(payload.get("data_status") or payload.get("status") or status)
    summary_stats = payload.get("summary_stats")
    if observer in {"ipv6-global-compare", "ipv6-locked-states"} and isinstance(summary_stats, dict):
        countries_evaluated = _as_number(summary_stats.get("countries_evaluated"))
        significant_count = _as_number(summary_stats.get("significant_count"))
        if countries_evaluated is not None and countries_evaluated > 0:
            status = "ok"
            if observer == "ipv6-locked-states" and significant_count == 0:
                data_status = "ok"
            elif data_status == "unavailable":
                data_status = "partial"
    return status, data_status


def _default_degraded_reason(observer: str, payload: Dict[str, Any], status: str, data_status: str) -> str | None:
    if status != "unavailable" and data_status != "unavailable":
        return None
    summary_stats = payload.get("summary_stats")
    if observer == "asn-visibility-by-country" and isinstance(summary_stats, dict):
        countries_evaluated = _as_number(summary_stats.get("countries_evaluated"))
        if countries_evaluated == 0:
            return "No countries were evaluated; ASN visibility data is not yet producing a usable dashboard signal."
    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, dict) and isinstance(diagnostics.get("reason"), str):
        return diagnostics["reason"]
    return "Observer data is unavailable in the latest output."


def _normalized_internet_payload(
    observer: str, payload: Dict[str, Any], loaded: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    if observer != "ipv6-global-compare":
        return payload
    summary_stats = payload.get("summary_stats")
    if not isinstance(summary_stats, dict):
        return payload
    countries_evaluated = _as_number(summary_stats.get("countries_evaluated"))
    if countries_evaluated is not None and countries_evaluated > 0:
        return payload
    source_summary = loaded.get("ipv6-locked-states", {}).get("summary_stats")
    if not isinstance(source_summary, dict):
        return payload
    source_countries_evaluated = _as_number(source_summary.get("countries_evaluated"))
    if source_countries_evaluated is None or source_countries_evaluated <= 0:
        return payload
    normalized = dict(payload)
    normalized_summary = dict(summary_stats)
    normalized_summary["countries_evaluated"] = source_countries_evaluated
    normalized["summary_stats"] = normalized_summary
    return normalized


def _internet_observer(observer: str, payload: Dict[str, Any], metadata: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    primary_name, primary_value = _internet_metric(observer, payload)
    status, data_status = _internet_status_fields(observer, payload)
    item: Dict[str, Any] = {
        "observer": observer,
        "display_name": _metadata_display_name(metadata, observer),
        "category": _metadata_category(metadata, observer),
        "dashboard_priority": _metadata_priority(metadata, observer),
        "status": status,
        "data_status": data_status,
        "primary_metric_name": primary_name,
        "primary_metric_value": primary_value,
        "secondary_metrics": _secondary_metrics(payload, primary_name),
    }
    last_seen = _last_seen_date(payload)
    if last_seen is not None:
        item["last_seen_date"] = last_seen
    degraded_reason = payload.get("degraded_reason") or payload.get("error") or payload.get("reason") or _default_degraded_reason(observer, payload, status, data_status)
    if degraded_reason:
        item["degraded_reason"] = degraded_reason
    return item


def _internet(loaded: Dict[str, Dict[str, Any]], metadata: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    observers = [
        _internet_observer(observer, _normalized_internet_payload(observer, loaded[observer], loaded), metadata)
        for observer in sorted(
            loaded,
            key=lambda item: (_metadata_priority(metadata, item), _metadata_display_name(metadata, item), item),
        )
        if _metadata_category(metadata, observer) == "internet"
    ]
    return {"observer_count": len(observers), "observers": observers}


def _planned_items(metadata: Dict[str, Dict[str, Any]], category: str) -> list[Dict[str, Any]]:
    items: list[Dict[str, Any]] = []
    for observer, entry in sorted(
        metadata.items(),
        key=lambda item: (_metadata_priority(metadata, item[0]), _metadata_display_name(metadata, item[0]), item[0]),
    ):
        if _metadata_category(metadata, observer) != category or entry.get("planned") is not True:
            continue
        items.append(
            {
                "observer": observer,
                "display_name": _metadata_display_name(metadata, observer),
                "category": category,
                "dashboard_priority": _metadata_priority(metadata, observer),
                "planned": True,
                "description": entry.get("description", ""),
                "tags": entry.get("tags", []),
            }
        )
    return items


def _iter_daily_observer_files(daily_dir: Path, observer: str) -> Iterable[tuple[str, Path]]:
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
        path = date_dir / f"{observer}.json"
        if path.exists():
            files.append((date_dir.name, path))
    return sorted(files)


def _internet_history(daily_dir: Path, generated_at: str, metadata: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    observers: Dict[str, Any] = {}
    for observer in sorted(
        (item for item in OBSERVERS if _metadata_category(metadata, item) == "internet"),
        key=lambda item: (_metadata_priority(metadata, item), _metadata_display_name(metadata, item), item),
    ):
        points: list[Dict[str, Any]] = []
        for date, path in _iter_daily_observer_files(daily_dir, observer):
            payload, _error = _read_json(path)
            if payload is None:
                continue
            _name, value = _internet_metric(observer, payload)
            point: Dict[str, Any] = {"date": date, "value": value, "data_status": _status(payload)}
            points.append(point)
        observers[observer] = {
            "display_name": _metadata_display_name(metadata, observer),
            "points": points,
            "windows": {
                "7d": _window_summary(points, 7, "value"),
                "30d": _window_summary(points, 30, "value"),
                "90d": _window_summary(points, 90, "value"),
            },
        }
    return {"generated_at": generated_at, "observers": observers}


def export_dashboard(
    latest_dir: Path | None = None,
    dashboard_dir: Path | None = None,
    daily_dir: Path | None = None,
    heartbeat_dir: Path | None = None,
) -> Dict[str, Path]:
    latest_dir = latest_dir or (_repo_root() / "data" / "latest")
    dashboard_dir = dashboard_dir or (_repo_root() / "dashboard")
    daily_dir = daily_dir or (_repo_root() / "data" / "daily")
    heartbeat_dir = heartbeat_dir or (_repo_root() / "state" / "heartbeat")
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    generated_at = _utc_now()
    loaded, _errors = _load_latest(latest_dir)
    metadata = _load_metadata()
    outputs = {
        "summary.json": _summary(latest_dir, generated_at, loaded, metadata),
        "internet.json": _internet(loaded, metadata),
        "media.json": _media(loaded.get(MEDIA_OBSERVER)),
        "society.json": {"status": "placeholder", "items": _planned_items(metadata, "society")},
        "environment.json": {"status": "placeholder", "items": _planned_items(metadata, "environment")},
        "heartbeat.json": _heartbeat(heartbeat_dir, generated_at),
        "history/media-language-germany.json": _media_history(daily_dir, generated_at),
        "history/internet-observers.json": _internet_history(daily_dir, generated_at, metadata),
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
    parser.add_argument("--heartbeat-dir", type=Path, default=None, help="Input heartbeat state directory.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    written = export_dashboard(args.latest_dir, args.dashboard_dir, args.daily_dir, args.heartbeat_dir)
    for path in written.values():
        print(path)


if __name__ == "__main__":
    main()
