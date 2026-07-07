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
FUEL_OBSERVER = "germany-fuel-prices"
TEA_OBSERVER = "east-frisian-tea-prices"
SUMMARY_NAME = "summary.json"
OUTPUT_FILES = ("summary.json", "internet.json", "media.json", "society.json", "environment.json", "technology.json", "heartbeat.json")
HISTORY_FILES = ("history/media-language-germany.json", "history/internet-observers.json", "history/geomagnetic-storm-observer.json")
FUEL_HISTORY_LIMIT = 365
METADATA_PATH = "config/observer_metadata.json"


FORBIDDEN_SUMMARY_TERMS = ("cause", "caused", "causal", "manipulation", "manipulate", "manipulated")
MEDIA_IMPORTS_DIR = "imports/media-language-germany"


INTERNET_DASHBOARD_METADATA: dict[str, dict[str, Any]] = {
    "area51-reachability": {"display_name": "Area51 Reachability", "dashboard_priority": 10, "primary_metric": "au.total", "primary_metric_label": "Reachability score", "primary_metric_unit": "score", "secondary_metrics": [("au.janet_like", "JANET-like aircraft", "count"), ("au.other", "Other aircraft", "count"), ("bucket_count", "Time buckets", "count")], "trend_metric": "au.total", "trend_metric_label": "Reachability score", "trend_metric_unit": "score"},
    "cuba-internet-weather": {"display_name": "Cuba Internet Weather", "dashboard_priority": 20, "primary_metric": "targets.1.ping.rtt_avg_ms", "primary_metric_label": "Average ping time", "primary_metric_unit": "ms", "secondary_metrics": [("weather_summary.reachable_targets", "Reachable targets", "count"), ("weather_summary.total_targets", "Targets checked", "count")], "trend_metric": "targets.1.ping.rtt_avg_ms", "trend_metric_label": "Average ping time", "trend_metric_unit": "ms"},
    "dns-time-to-answer-index": {"display_name": "DNS Time To Answer Index", "dashboard_priority": 30, "primary_metric": "summary.avg_query_ms", "primary_metric_label": "Average DNS response", "primary_metric_unit": "ms", "secondary_metrics": [("summary.total_queries", "Queries checked", "count"), ("summary.successful", "Successful queries", "count"), ("summary.timeouts", "DNS timeouts", "count")], "trend_metric": "summary.avg_query_ms", "trend_metric_label": "Average DNS response", "trend_metric_unit": "ms"},
    "dns-tta-stress-index": {"display_name": "DNS TTA Stress Index", "dashboard_priority": 40, "primary_metric": "countries.0.dns_stress_score", "primary_metric_label": "DNS stress score", "primary_metric_unit": "score", "secondary_metrics": [("summary_stats.countries_evaluated", "Countries evaluated", "count"), ("diagnostics.timeouts", "DNS timeouts", "count")], "trend_metric": "countries.0.dns_stress_score", "trend_metric_label": "DNS stress score", "trend_metric_unit": "score"},
    "global-reachability-long-horizon": {"display_name": "Global Reachability Long Horizon", "dashboard_priority": 50, "primary_metric": "global.avg_score_today", "primary_metric_label": "Average reachability score", "primary_metric_unit": "score", "secondary_metrics": [("summary_stats.countries_evaluated", "Countries evaluated", "count"), ("summary_stats.significant_count", "Significant events", "count")], "trend_metric": "global.avg_score_today", "trend_metric_label": "Average reachability score", "trend_metric_unit": "score"},
    "global-reachability-score": {"display_name": "Global Reachability Score", "dashboard_priority": 60, "primary_metric": "countries.0.score", "primary_metric_label": "Reachability score", "primary_metric_unit": "score", "secondary_metrics": [("countries.0.score_percent", "Reachability percent", "%")], "trend_metric": "countries.0.score", "trend_metric_label": "Reachability score", "trend_metric_unit": "score"},
    "http-reachability-index": {"display_name": "HTTP Reachability Index", "dashboard_priority": 70, "primary_metric": "summary.success_rate_percent", "primary_metric_label": "HTTP success rate", "primary_metric_unit": "%", "secondary_metrics": [("summary.avg_response_ms", "Average response time", "ms"), ("summary.targets_reachable", "Reachable targets", "count"), ("summary.targets_checked", "Targets checked", "count")], "trend_metric": "summary.success_rate_percent", "trend_metric_label": "HTTP success rate", "trend_metric_unit": "%"},
    "internet-shrinkage-index": {"display_name": "Internet Shrinkage Index", "dashboard_priority": 80, "primary_metric": "global.global_shrinkage_index", "primary_metric_label": "Shrinkage index", "primary_metric_unit": "score", "secondary_metrics": [("summary_stats.countries_evaluated", "Countries evaluated", "count"), ("summary_stats.significant_count", "Significant events", "count")], "trend_metric": "global.global_shrinkage_index", "trend_metric_label": "Shrinkage index", "trend_metric_unit": "score"},
    "ipv6-adoption-locked-states": {"display_name": "IPv6 Adoption Locked States", "dashboard_priority": 90, "primary_metric": "countries.0.ipv6_capable_rate", "primary_metric_label": "IPv6 capable rate", "primary_metric_unit": "%", "secondary_metrics": [("countries.0.total_domains", "Domains checked", "count")], "trend_metric": "countries.0.ipv6_capable_rate", "trend_metric_label": "IPv6 capable rate", "trend_metric_unit": "%"},
    "ipv6-global-compare": {"display_name": "IPv6 Global Compare", "dashboard_priority": 100, "primary_metric": "summary_stats.countries_evaluated", "primary_metric_label": "Countries evaluated", "primary_metric_unit": "count", "secondary_metrics": [("summary_stats.significant_count", "Significant events", "count"), ("countries.0.ipv6_capable_rate", "IPv6 capable rate", "%")], "trend_metric": "summary_stats.countries_evaluated", "trend_metric_label": "Countries evaluated", "trend_metric_unit": "count"},
    "ipv6-locked-states": {"display_name": "IPv6 Locked States", "dashboard_priority": 110, "primary_metric": "summary_stats.countries_evaluated", "primary_metric_label": "Countries evaluated", "primary_metric_unit": "count", "secondary_metrics": [("summary_stats.significant_count", "Significant events", "count"), ("countries.0.ipv6_capable_rate", "IPv6 capable rate", "%")], "trend_metric": "summary_stats.countries_evaluated", "trend_metric_label": "Countries evaluated", "trend_metric_unit": "count"},
    "iran-dns-behavior": {"display_name": "Iran DNS Behavior", "dashboard_priority": 120, "primary_metric": "summary.answered", "primary_metric_label": "DNS answers", "primary_metric_unit": "count", "secondary_metrics": [("summary.total_queries", "Queries checked", "count"), ("summary.servfail", "SERVFAIL responses", "count")], "trend_metric": "summary.answered", "trend_metric_label": "DNS answers", "trend_metric_unit": "count"},
    "mx-presence-by-country": {"display_name": "MX Presence By Country", "dashboard_priority": 130, "primary_metric": "results.0.mx_present_count", "primary_metric_label": "MX records present", "primary_metric_unit": "count", "secondary_metrics": [("results.0.domain_count", "Domains checked", "count")], "trend_metric": "results.0.mx_present_count", "trend_metric_label": "MX records present", "trend_metric_unit": "count"},
    "mx-presence-per-country": {"display_name": "MX Presence Per Country", "dashboard_priority": 140, "primary_metric": "countries.0.mx_present_count", "primary_metric_label": "MX records present", "primary_metric_unit": "count", "secondary_metrics": [("summary_stats.countries_evaluated", "Countries evaluated", "count")], "trend_metric": "countries.0.mx_present_count", "trend_metric_label": "MX records present", "trend_metric_unit": "count"},
    "north-korea-connectivity": {"display_name": "North Korea Connectivity", "dashboard_priority": 150, "primary_metric": "layers.tcp.probe_count", "primary_metric_label": "TCP probes", "primary_metric_unit": "count", "secondary_metrics": [("layers.tcp.success_count", "Successful TCP probes", "count"), ("layers.icmp.probe_count", "ICMP probes", "count")], "trend_metric": "layers.tcp.probe_count", "trend_metric_label": "TCP probes", "trend_metric_unit": "count"},
    "silent-countries-list": {"display_name": "Silent Countries List", "dashboard_priority": 160, "primary_metric": "summary_stats.countries_evaluated", "primary_metric_label": "Countries evaluated", "primary_metric_unit": "count", "secondary_metrics": [("summary_stats.significant_count", "Significant events", "count"), ("top_silent_countries", "Silent countries listed", "count")], "trend_metric": "summary_stats.countries_evaluated", "trend_metric_label": "Countries evaluated", "trend_metric_unit": "count"},
    "tls-fingerprint-change": {"display_name": "TLS Fingerprint Change", "dashboard_priority": 170, "primary_metric": "summary_stats.significant_count", "primary_metric_label": "Significant events", "primary_metric_unit": "count", "secondary_metrics": [("summary_stats.countries_evaluated", "Countries evaluated", "count"), ("countries.0.tls_change_score", "TLS change score", "score")], "trend_metric": "summary_stats.significant_count", "trend_metric_label": "Significant events", "trend_metric_unit": "count"},
    "traceroute-to-nowhere": {"display_name": "Traceroute To Nowhere", "dashboard_priority": 180, "primary_metric": "metrics.trace_count", "primary_metric_label": "Trace count", "primary_metric_unit": "count", "secondary_metrics": [("metrics.anomaly_count", "Anomaly count", "count")], "trend_metric": "metrics.trace_count", "trend_metric_label": "Trace count", "trend_metric_unit": "count"},
    "undersea-cable-dependency": {"display_name": "Undersea Cable Dependency", "dashboard_priority": 190, "primary_metric": "countries.0.cable_count", "primary_metric_label": "Cable count", "primary_metric_unit": "count", "secondary_metrics": [("countries.0.landing_count", "Landing points", "count")], "trend_metric": "countries.0.cable_count", "trend_metric_label": "Cable count", "trend_metric_unit": "count"},
    "undersea-cable-dependency-map": {"display_name": "Undersea Cable Dependency Map", "dashboard_priority": 200, "primary_metric": "countries.0.cable_count", "primary_metric_label": "Cable count", "primary_metric_unit": "count", "secondary_metrics": [("countries.0.landing_count", "Landing points", "count"), ("summary_stats.countries_evaluated", "Countries evaluated", "count")], "trend_metric": "countries.0.cable_count", "trend_metric_label": "Cable count", "trend_metric_unit": "count"},
}

PREFERRED_INTERNET_HISTORY_METRICS: dict[str, tuple[tuple[str, ...], ...]] = {
    "area51-reachability": (("au", "total"),),
    "dns-time-to-answer-index": (("summary", "avg_query_ms"),),
    "dns-tta-stress-index": (("diagnostics", "timeouts"), ("countries", "0", "dns_stress_score")),
    "global-reachability-long-horizon": (("countries", "0", "score_today"), ("global", "avg_score_today")),
    "global-reachability-score": (("countries", "0", "score"), ("countries", "0", "score_percent")),
    "internet-shrinkage-index": (("global", "global_shrinkage_index"),),
    "cuba-internet-weather": (("targets", "1", "ping", "rtt_avg_ms"),),
    "iran-dns-behavior": (("summary", "answered"),),
    "north-korea-connectivity": (("layers", "tcp", "probe_count"),),
    "silent-countries-list": (("summary_stats", "countries_evaluated"), ("top_silent_countries",),),
    "tls-fingerprint-change": (("countries", "0", "tls_change_score"),),
    "traceroute-to-nowhere": (("metrics", "trace_count"),),
    "undersea-cable-dependency": (("countries", "0", "cable_count"),),
    "undersea-cable-dependency-map": (("countries", "0", "cable_count"),),
    "ipv6-global-compare": (("summary_stats", "countries_evaluated"),),
    "ipv6-locked-states": (("summary_stats", "countries_evaluated"),),
    "ipv6-adoption-locked-states": (("summary_stats", "countries_evaluated"), ("countries", "0", "ipv6_capable_rate")),
    "mx-presence-by-country": (("summary_stats", "countries_evaluated"), ("summary_stats", "unreachable_count"), ("countries",)),
    "mx-presence-per-country": (("countries", "0", "mx_present_count"),),
    "http-reachability-index": (("summary", "success_rate_percent"),),
}


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


def _metadata_active(metadata: Dict[str, Dict[str, Any]], observer: str) -> bool:
    return metadata.get(observer, {}).get("planned") is not True and metadata.get(observer, {}).get("active") is not False


def _metadata_priority(metadata: Dict[str, Dict[str, Any]], observer: str) -> int:
    dashboard_value = INTERNET_DASHBOARD_METADATA.get(observer, {}).get("dashboard_priority")
    if isinstance(dashboard_value, int) and not isinstance(dashboard_value, bool):
        return dashboard_value
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
    categories = {category: 0 for category in ("internet", "media", "society", "environment", "technology")}
    for observer in OBSERVERS:
        category = _metadata_category(metadata, observer)
        categories[category] = categories.get(category, 0) + 1
    last_run_utc, latest_date_utc = _summary_update_timestamps(generated_at, loaded)
    payload: Dict[str, Any] = {
        "generated_at": generated_at,
        "last_run_utc": last_run_utc,
        "latest_date_utc": latest_date_utc,
        "observer_count": len(OBSERVERS),
        "observers_ok": len(ok),
        "degraded_count": len(degraded),
        "missing_count": len(missing),
        "categories": categories,
        "dashboard_version": DASHBOARD_VERSION,
    }
    if missing:
        payload["missing_observers"] = missing
    if degraded:
        payload["degraded_observers"] = degraded
    return payload


def _summary_update_timestamps(generated_at: str, loaded: Dict[str, Dict[str, Any]]) -> tuple[str, str]:
    """Return dashboard summary freshness fields from current export data.

    Older dashboard summary snapshots may contain legacy Internet observer dates.
    Summary freshness should be based on this export and the newest valid date in
    currently loaded observer payloads, never copied from stale summary input.
    """
    generated_date = _date_sort_key(generated_at) or generated_at[:10]
    date_fields = ("date_utc", "date", "timestamp_utc", "timestamp", "last_seen_date", "fetched_at_utc")
    observer_dates = [
        date
        for payload in loaded.values()
        for key in date_fields
        if (date := _date_sort_key(payload.get(key)))
    ]
    latest_date_utc = (
        max([generated_date, *observer_dates])
        if generated_date
        else (max(observer_dates) if observer_dates else generated_at[:10])
    )
    return generated_at, latest_date_utc


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


def _top_term_counts(value: Any) -> dict[str, int | float]:
    counts: dict[str, int | float] = {}
    if not isinstance(value, list):
        return counts
    for item in value:
        if not isinstance(item, dict):
            continue
        term = item.get("term")
        count = _as_number(item.get("count"))
        if isinstance(term, str) and term and count is not None:
            counts[term] = count
    return counts


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
    term_counts = _top_term_counts(payload.get("top_terms"))
    if term_counts:
        point["term_counts"] = term_counts
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


def _media_import_payload_date(payload: Dict[str, Any]) -> str | None:
    value = payload.get("date") or payload.get("date_utc") or payload.get("observation_date")
    if not isinstance(value, str):
        return None
    date = value[:10]
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None
    return date


def _valid_media_import_payload(payload: Dict[str, Any]) -> str | None:
    if payload.get("observer") not in (None, MEDIA_OBSERVER):
        return "observer must be media-language-germany when provided"
    if _media_import_payload_date(payload) is None:
        return "date, date_utc, or observation_date must contain YYYY-MM-DD"
    if _as_number(payload.get("fear_index_overall", payload.get("fear_index"))) is None:
        return "fear_index_overall or fear_index must be numeric"
    for key in ("source_groups", "top_terms"):
        if key in payload and not isinstance(payload[key], (dict if key == "source_groups" else list)):
            return f"{key} has invalid type"
    return None


def _iter_import_media_files(imports_dir: Path) -> Iterable[Path]:
    if not imports_dir.exists():
        return []
    return sorted(path for path in imports_dir.glob("*.json") if path.is_file())


def _media_import_points(imports_dir: Path, existing_dates: set[str]) -> tuple[list[Dict[str, Any]], list[Dict[str, str]]]:
    points: list[Dict[str, Any]] = []
    diagnostics: list[Dict[str, str]] = []
    for path in _iter_import_media_files(imports_dir):
        payload, error = _read_json(path)
        if payload is None:
            diagnostics.append({"file": path.name, "status": "ignored", "reason": error or "invalid JSON"})
            continue
        validation_error = _valid_media_import_payload(payload)
        if validation_error is not None:
            diagnostics.append({"file": path.name, "status": "ignored", "reason": validation_error})
            continue
        date = _media_import_payload_date(payload)
        if date is None:
            diagnostics.append({"file": path.name, "status": "ignored", "reason": "missing valid date"})
            continue
        if date in existing_dates:
            diagnostics.append({"file": path.name, "status": "ignored", "reason": "duplicate date; existing history takes precedence"})
            continue
        points.append(_media_history_point(date, payload))
        existing_dates.add(date)
    return points, diagnostics


def _trend_direction(delta: float | int | None) -> str:
    if delta is None or delta == 0:
        return "flat"
    return "rising" if delta > 0 else "falling"


def _average_latest(points: list[Dict[str, Any]], days: int, key: str = "fear_index_overall") -> float | int | None:
    values = [point[key] for point in points[-days:] if isinstance(point.get(key), (int, float)) and not isinstance(point.get(key), bool)]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _media_trend(points: list[Dict[str, Any]]) -> Dict[str, Any]:
    values = [point for point in points if isinstance(point.get("fear_index_overall"), (int, float))]
    latest = values[-1] if values else None
    previous = values[-2] if len(values) >= 2 else None
    latest_value = latest.get("fear_index_overall") if latest else None
    previous_value = previous.get("fear_index_overall") if previous else None
    delta = round(latest_value - previous_value, 2) if isinstance(latest_value, (int, float)) and isinstance(previous_value, (int, float)) else None
    delta_percent = round((delta / previous_value) * 100, 2) if delta is not None and previous_value not in (None, 0) else None
    all_values = [point["fear_index_overall"] for point in values]
    return {
        "latest_fear_index": latest_value,
        "previous_fear_index": previous_value,
        "delta": delta,
        "delta_percent": delta_percent,
        "trend_direction": _trend_direction(delta),
        "seven_day_average": _average_latest(points, 7),
        "thirty_day_average": _average_latest(points, 30),
        "min_available": round(min(all_values), 2) if all_values else None,
        "max_available": round(max(all_values), 2) if all_values else None,
        "history_points": len(points),
        "latest_date": latest.get("date") if latest else None,
        "previous_date": previous.get("date") if previous else None,
    }


def _public_private_comparison(points: list[Dict[str, Any]]) -> Dict[str, Any]:
    comparable = [p for p in points if isinstance(p.get("public_broadcast"), (int, float)) and isinstance(p.get("private_media"), (int, float))]
    latest = comparable[-1] if comparable else None
    previous = comparable[-2] if len(comparable) >= 2 else None
    spread = round(latest["private_media"] - latest["public_broadcast"], 2) if latest else None
    previous_spread = round(previous["private_media"] - previous["public_broadcast"], 2) if previous else None
    spread_delta = round(spread - previous_spread, 2) if spread is not None and previous_spread is not None else None
    return {
        "public_broadcast_fear_index": latest.get("public_broadcast") if latest else None,
        "private_media_fear_index": latest.get("private_media") if latest else None,
        "public_private_spread": spread,
        "spread_delta": spread_delta,
        "spread_trend_direction": _trend_direction(spread_delta),
    }


def _term_changes(points: list[Dict[str, Any]]) -> Dict[str, list[Dict[str, Any]]]:
    latest_index = next((index for index in range(len(points) - 1, -1, -1) if isinstance(points[index].get("term_counts"), dict)), None)
    latest = points[latest_index] if latest_index is not None else None
    previous = (
        next((points[index] for index in range(latest_index - 1, -1, -1) if isinstance(points[index].get("term_counts"), dict)), None)
        if latest_index is not None
        else None
    )
    current_counts = latest.get("term_counts", {}) if latest else {}
    previous_counts = previous.get("term_counts", {}) if previous else {}

    def item(term: str) -> Dict[str, Any]:
        current = current_counts.get(term, 0)
        previous_count = previous_counts.get(term, 0)
        return {"term": term, "current_count": current, "previous_count": previous_count, "delta": round(current - previous_count, 2)}

    shared = set(current_counts) | set(previous_counts)
    rising = sorted([item(term) for term in shared if item(term)["delta"] > 0], key=lambda x: (-x["delta"], x["term"]))
    falling = sorted([item(term) for term in shared if item(term)["delta"] < 0], key=lambda x: (x["delta"], x["term"]))
    return {
        "rising_terms": rising,
        "falling_terms": falling,
        "new_terms": sorted([item(term) for term in set(current_counts) - set(previous_counts)], key=lambda x: x["term"]),
        "disappeared_terms": sorted([item(term) for term in set(previous_counts) - set(current_counts)], key=lambda x: x["term"]),
    }


def _neutral_summaries(trend: Dict[str, Any], comparison: Dict[str, Any], points: list[Dict[str, Any]]) -> list[str]:
    summaries: list[str] = []
    direction = trend.get("trend_direction")
    if direction == "rising":
        summaries.append("Fear-language indicator increased compared with the previous observation.")
    elif direction == "falling":
        summaries.append("Fear-language indicator decreased compared with the previous observation.")
    elif trend.get("latest_fear_index") is not None:
        summaries.append("Fear-language indicator is flat compared with the previous observation.")
    spread = comparison.get("public_private_spread")
    if isinstance(spread, (int, float)):
        if spread > 0:
            summaries.append("Private media indicator is currently higher than public broadcast indicator.")
        elif spread < 0:
            summaries.append("Public broadcast indicator is currently higher than private media indicator.")
        else:
            summaries.append("Private media and public broadcast indicators are currently equal.")
    latest_terms = points[-1].get("top_terms", []) if points else []
    if latest_terms:
        if len(latest_terms) == 1:
            terms_text = latest_terms[0]
        else:
            terms_text = ", ".join(latest_terms[:-1]) + f", and {latest_terms[-1]}"
        summaries.append(f"Top observed terms include {terms_text}.")
    return [s for s in summaries if not any(term in s.lower() for term in FORBIDDEN_SUMMARY_TERMS)]


def _media_history(daily_dir: Path, generated_at: str, imports_dir: Path | None = None) -> Dict[str, Any]:
    points: list[Dict[str, Any]] = []
    for date, path in _iter_daily_media_files(daily_dir):
        payload, _error = _read_json(path)
        if payload is None:
            continue
        points.append(_media_history_point(date, payload))
    existing_dates = {point["date"] for point in points}
    import_diagnostics: list[Dict[str, str]] = []
    if imports_dir is not None:
        imported_points, import_diagnostics = _media_import_points(imports_dir, existing_dates)
        points.extend(imported_points)
        points.sort(key=lambda point: point["date"])
    trend = _media_trend(points)
    comparison = _public_private_comparison(points)
    term_changes = _term_changes(points)
    return {
        "observer": MEDIA_OBSERVER,
        "generated_at": generated_at,
        "points": points,
        "windows": {
            "7d": _window_summary(points, 7),
            "30d": _window_summary(points, 30),
        },
        "trend": trend,
        "public_private_comparison": comparison,
        "term_changes": term_changes,
        "neutral_summaries": _neutral_summaries(trend, comparison, points),
        "import_diagnostics": import_diagnostics,
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
    dashboard_value = INTERNET_DASHBOARD_METADATA.get(observer, {}).get("display_name")
    if isinstance(dashboard_value, str) and dashboard_value:
        return dashboard_value
    value = _metadata_value(metadata, observer, "display_name")
    return value if isinstance(value, str) and value else _display_name(observer)


def _find_path(payload: Any, path: tuple[str, ...]) -> Any:
    value = payload
    for key in path:
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and key.isdigit():
            index = int(key)
            if index >= len(value):
                return None
            value = value[index]
        else:
            return None
    if isinstance(value, list):
        return len(value)
    return value




def _path_tuple(path: str) -> tuple[str, ...]:
    return tuple(part for part in path.split(".") if part)


def _dashboard_metric_metadata(observer: str, metadata: Dict[str, Dict[str, Any]] | None = None) -> dict[str, Any]:
    configured = dict(metadata.get(observer, {}) if metadata else {})
    configured.update(INTERNET_DASHBOARD_METADATA.get(observer, {}))
    return configured


def _configured_metric_value(observer: str, payload: Dict[str, Any], key: str, metadata: Dict[str, Dict[str, Any]] | None = None) -> tuple[str, float | int] | None:
    path = _dashboard_metric_metadata(observer, metadata).get(key)
    if not isinstance(path, str) or not path:
        return None
    value = _as_number(_find_path(payload, _path_tuple(path)))
    if value is None and observer == "area51-reachability" and path == "au.total":
        buckets = payload.get("buckets")
        if isinstance(buckets, dict):
            bucket_totals = [_as_number(bucket.get("total")) for bucket in buckets.values() if isinstance(bucket, dict)]
            numeric_totals = [total for total in bucket_totals if total is not None]
            if numeric_totals:
                value = round(sum(numeric_totals), 2)
    if value is None:
        return None
    return path, value


def _friendly_label(observer: str, key: str, fallback: str, metadata: Dict[str, Dict[str, Any]] | None = None) -> str:
    value = _dashboard_metric_metadata(observer, metadata).get(key)
    return value if isinstance(value, str) and value else fallback

def _first_numeric_path(payload: Dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> tuple[str, float | int] | None:
    for path in paths:
        value = _as_number(_find_path(payload, path))
        if value is not None:
            return ".".join(path), value
    return None


def _preferred_internet_history_metric(observer: str, payload: Dict[str, Any]) -> tuple[str, float | int] | None:
    return _first_numeric_path(payload, PREFERRED_INTERNET_HISTORY_METRICS.get(observer, ()))


def _internet_history_metric(observer: str, payload: Dict[str, Any]) -> tuple[str, float | int] | None:
    configured = _configured_metric_value(observer, payload, "trend_metric")
    if configured is not None:
        return configured
    preferred = _preferred_internet_history_metric(observer, payload)
    if preferred is not None:
        return preferred
    name, value = _internet_metric(observer, payload)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return name, value
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
        "http-reachability-index": (("summary", "success_rate_percent"), ("summary", "targets_reachable")),
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
        "http-reachability-index": ("success_rate_percent", "targets_reachable", "targets_checked"),
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



def _configured_secondary_metrics(observer: str, payload: Dict[str, Any], primary_path: str, metadata: Dict[str, Dict[str, Any]] | None = None) -> Dict[str, float | int]:
    metrics: Dict[str, float | int] = {}
    configured = _dashboard_metric_metadata(observer, metadata).get("secondary_metrics")
    if not isinstance(configured, list):
        return metrics
    for entry in configured:
        if not isinstance(entry, (tuple, list)) or len(entry) < 2:
            continue
        path, label = entry[0], entry[1]
        if not isinstance(path, str) or not isinstance(label, str) or path == primary_path:
            continue
        value = _as_number(_find_path(payload, _path_tuple(path)))
        if value is not None:
            metrics[label] = value
    return metrics


def _configured_secondary_metric_units(observer: str, primary_path: str, metadata: Dict[str, Dict[str, Any]] | None = None) -> Dict[str, str]:
    units: Dict[str, str] = {}
    configured = _dashboard_metric_metadata(observer, metadata).get("secondary_metrics")
    if not isinstance(configured, list):
        return units
    for entry in configured:
        if not isinstance(entry, (tuple, list)) or len(entry) < 3:
            continue
        path, label, unit = entry[0], entry[1], entry[2]
        if isinstance(path, str) and isinstance(label, str) and isinstance(unit, str) and path != primary_path:
            units[label] = unit
    return units

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
    configured_primary = _configured_metric_value(observer, payload, "primary_metric", metadata)
    if configured_primary is not None:
        primary_path, primary_value = configured_primary
        primary_name = _friendly_label(observer, "primary_metric_label", primary_path, metadata)
    else:
        primary_path, primary_value = _internet_metric(observer, payload)
        primary_name = primary_path
        if payload.get("data_status") == "unavailable" or payload.get("status") == "unavailable":
            primary_path, primary_value, primary_name = "data_status", "unavailable", "data_status"
    status, data_status = _internet_status_fields(observer, payload)
    secondary_metrics = (
        _configured_secondary_metrics(observer, payload, primary_path, metadata)
        if _dashboard_metric_metadata(observer, metadata).get("secondary_metrics")
        else _secondary_metrics(payload, primary_path)
    )
    item: Dict[str, Any] = {
        "observer": observer,
        "display_name": _metadata_display_name(metadata, observer),
        "category": _metadata_category(metadata, observer),
        "dashboard_priority": _metadata_priority(metadata, observer),
        "status": status,
        "data_status": data_status,
        "primary_metric_name": primary_name,
        "primary_metric_value": primary_value,
        "primary_metric_path": primary_path,
        "secondary_metrics": secondary_metrics,
    }
    primary_unit = _dashboard_metric_metadata(observer, metadata).get("primary_metric_unit")
    if configured_primary is not None and isinstance(primary_unit, str) and primary_unit:
        item["primary_metric_unit"] = primary_unit
    secondary_units = {
        label: unit
        for label, unit in _configured_secondary_metric_units(observer, primary_path, metadata).items()
        if label in secondary_metrics
    }
    if secondary_units:
        item["secondary_metric_units"] = secondary_units
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
        if _metadata_category(metadata, observer) == "internet" and _metadata_active(metadata, observer)
    ]
    return {"observer_count": len(observers), "observers": observers}



def _fuel_price_value(item: Any) -> float | int | None:
    if not isinstance(item, dict):
        return None
    value = item.get("current_price")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(value, 3)
    return None


def normalizeFuelHistory(points: Iterable[Dict[str, Any]], limit: int = FUEL_HISTORY_LIMIT) -> list[Dict[str, Any]]:
    latest_by_date: dict[str, tuple[int, float | int]] = {}
    for point in points:
        date = point.get("date")
        value = point.get("value")
        if not isinstance(date, str) or not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            continue
        priority = point.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            priority = 0
        existing = latest_by_date.get(date)
        if existing is None or priority >= existing[0]:
            latest_by_date[date] = (priority, round(value, 3))
    normalized = [{"date": date, "value": value} for date, (_priority, value) in sorted(latest_by_date.items())]
    return normalized[-limit:]


def collectFuelHistory(state_dir: Path, observer: str = FUEL_OBSERVER) -> dict[str, list[Dict[str, Any]]]:
    points_by_fuel: dict[str, list[Dict[str, Any]]] = {}
    for date, path in _iter_state_observer_files(state_dir, observer):
        payload, _error = _read_json(path)
        if payload is None:
            continue
        fuels = payload.get("fuels")
        if not isinstance(fuels, dict):
            continue
        for fuel, item in fuels.items():
            if not isinstance(fuel, str) or not isinstance(item, dict):
                continue
            fuel_points = points_by_fuel.setdefault(fuel, [])
            history = item.get("history")
            if isinstance(history, list):
                for point in history:
                    if not isinstance(point, dict):
                        continue
                    history_date = point.get("date")
                    history_value = point.get("value")
                    fuel_points.append({"date": history_date, "value": history_value, "priority": 0})
            value = _fuel_price_value(item)
            if value is not None:
                fuel_points.append({"date": date, "value": value, "priority": 1})
    return {fuel: history for fuel, points in points_by_fuel.items() if (history := normalizeFuelHistory(points))}


def _date_sort_key(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    candidate = value[:10]
    try:
        datetime.strptime(candidate, "%Y-%m-%d")
    except ValueError:
        return None
    return candidate


def _latest_history_date(history: Any) -> str | None:
    if not isinstance(history, list):
        return None
    dates = [date for date in (_date_sort_key(point.get("date")) for point in history if isinstance(point, dict)) if date]
    return max(dates) if dates else None


def _latest_date(*values: Any) -> Any:
    dated_values = [(date, value) for value in values if (date := _date_sort_key(value))]
    if dated_values:
        return max(dated_values, key=lambda item: item[0])[1]
    return next((value for value in values if value is not None), None)


def buildFuelHistory(fuels: Any, state_dir: Path) -> Dict[str, Any]:
    if not isinstance(fuels, dict):
        return {}
    history_by_fuel = collectFuelHistory(state_dir)
    exported: Dict[str, Any] = {}
    for fuel, item in fuels.items():
        if isinstance(item, dict):
            history = history_by_fuel.get(fuel, [])
            exported_item = {**item, "history": history}
            latest_seen = _latest_date(item.get("last_seen_date"), _latest_history_date(history))
            if latest_seen is not None:
                exported_item["last_seen_date"] = latest_seen
            exported[fuel] = exported_item
        else:
            exported[fuel] = item
    return exported


def _fuel_observer_last_seen(payload: Dict[str, Any], fuels: Dict[str, Any]) -> Any:
    fuel_dates = []
    for item in fuels.values():
        if isinstance(item, dict):
            fuel_dates.append(item.get("last_seen_date"))
            fuel_dates.append(_latest_history_date(item.get("history")))
    return _latest_date(*fuel_dates, payload.get("last_seen_date"), payload.get("date"), payload.get("date_utc"))


def _society(loaded: Dict[str, Dict[str, Any]], metadata: Dict[str, Dict[str, Any]], state_dir: Path) -> Dict[str, Any]:
    observers: list[Dict[str, Any]] = []
    for observer in sorted(
        (item for item in OBSERVERS if _metadata_category(metadata, item) == "society" and _metadata_active(metadata, item)),
        key=lambda item: (_metadata_priority(metadata, item), _metadata_display_name(metadata, item), item),
    ):
        payload = loaded.get(observer)
        if observer == TEA_OBSERVER and isinstance(payload, dict):
            item: Dict[str, Any] = {**payload}
            item["observer"] = observer
            item["display_name"] = _metadata_display_name(metadata, observer)
            item["category"] = "society"
            item["dashboard_priority"] = _metadata_priority(metadata, observer)
            item.setdefault("status", _status(payload))
            item.setdefault("data_status", payload.get("data_status", _status(payload)))
            item.setdefault("last_seen_date", payload.get("date") or payload.get("date_utc"))
            observers.append(item)
        elif observer == FUEL_OBSERVER and isinstance(payload, dict):
            item: Dict[str, Any] = {
                "observer": observer,
                "display_name": _metadata_display_name(metadata, observer),
                "category": "society",
                "dashboard_priority": _metadata_priority(metadata, observer),
                "status": _status(payload),
                "data_status": payload.get("data_status", _status(payload)),
                "fuels": buildFuelHistory(payload.get("fuels", {}), state_dir),
                "source": payload.get("source"),
                "fetch_url": (payload.get("diagnostics") or {}).get("fetch_url") if isinstance(payload.get("diagnostics"), dict) else None,
                "fetched_at_utc": (payload.get("diagnostics") or {}).get("fetched_at_utc") if isinstance(payload.get("diagnostics"), dict) else None,
                "parse_status": (payload.get("diagnostics") or {}).get("parse_status") if isinstance(payload.get("diagnostics"), dict) else None,
                "fallback_used": (payload.get("diagnostics") or {}).get("fallback_used") if isinstance(payload.get("diagnostics"), dict) else None,
                "import_diagnostics": payload.get("import_diagnostics", []),
            }
            item["last_seen_date"] = _fuel_observer_last_seen(payload, item["fuels"])
            degraded_reason = payload.get("degraded_reason") or payload.get("error")
            if degraded_reason:
                item["degraded_reason"] = degraded_reason
            observers.append(item)
        elif isinstance(payload, dict):
            observers.append(_internet_observer(observer, payload, metadata))
    planned = _planned_items(metadata, "society")
    return {"observer_count": len(observers), "observers": observers, "items": planned}


def _history_point_value(observer: str, payload: Dict[str, Any], metadata: Dict[str, Dict[str, Any]]) -> tuple[str, float | int] | None:
    configured = _configured_metric_value(observer, payload, "trend_metric", metadata)
    if configured is not None:
        return configured
    configured = _configured_metric_value(observer, payload, "primary_metric", metadata)
    if configured is not None:
        return configured
    for key in ("value", "current_package_count", "primary_metric_value"):
        value = _as_number(payload.get(key))
        if value is not None:
            return key, value
    return None


def normalizeObserverHistory(points: Iterable[Dict[str, Any]], limit: int = FUEL_HISTORY_LIMIT, metric_name: str | None = None) -> list[Dict[str, Any]]:
    latest_by_date: dict[str, tuple[int, Dict[str, Any]]] = {}
    for index, point in enumerate(points):
        date = _date_sort_key(point.get("date"))
        value = _as_number(point.get("value"))
        if date is None or value is None:
            continue
        normalized: Dict[str, Any] = {"date": date, "value": value}
        current_package_count = _as_number(point.get("current_package_count"))
        if current_package_count is not None:
            normalized["current_package_count"] = current_package_count
        elif metric_name == "current_package_count":
            normalized["current_package_count"] = value
        primary_metric_value = _as_number(point.get("primary_metric_value"))
        if primary_metric_value is not None:
            normalized["primary_metric_value"] = primary_metric_value
        elif metric_name is not None:
            normalized["primary_metric_value"] = value
        latest_by_date[date] = (index, normalized)
    return [point for _date, (_index, point) in sorted(latest_by_date.items())][-limit:]


def collectObserverHistory(observer: str, latest_payload: Dict[str, Any], state_dir: Path, metadata: Dict[str, Dict[str, Any]], limit: int = FUEL_HISTORY_LIMIT) -> list[Dict[str, Any]]:
    points: list[Dict[str, Any]] = []
    configured_metric = _dashboard_metric_metadata(observer, metadata).get("trend_metric")
    history_metric_name = configured_metric if isinstance(configured_metric, str) and configured_metric else None
    for date, path in _iter_state_observer_files(state_dir, observer):
        payload, _error = _read_json(path)
        if payload is None:
            continue
        for point in payload.get("history", []) if isinstance(payload.get("history"), list) else []:
            if isinstance(point, dict):
                points.append(point)
        metric = _history_point_value(observer, payload, metadata)
        if metric is not None:
            metric_name, value = metric
            point = {"date": payload.get("date") or date, "value": value, "primary_metric_value": value}
            if metric_name == "current_package_count":
                point["current_package_count"] = value
            points.append(point)
    for point in latest_payload.get("history", []) if isinstance(latest_payload.get("history"), list) else []:
        if isinstance(point, dict):
            points.append(point)
    metric = _history_point_value(observer, latest_payload, metadata)
    if metric is not None:
        metric_name, value = metric
        point = {"date": latest_payload.get("date") or latest_payload.get("date_utc"), "value": value, "primary_metric_value": value}
        if metric_name == "current_package_count":
            point["current_package_count"] = value
        points.append(point)
    return normalizeObserverHistory(points, limit, history_metric_name)


def _technology_observer(observer: str, payload: Dict[str, Any], metadata: Dict[str, Dict[str, Any]], state_dir: Path | None = None) -> Dict[str, Any]:
    item = _internet_observer(observer, payload, metadata)
    history = collectObserverHistory(observer, payload, state_dir or (_repo_root() / "state"), metadata)
    if history:
        item["history"] = history
    return item


def _category_dashboard(category: str, loaded: Dict[str, Dict[str, Any]], metadata: Dict[str, Dict[str, Any]], state_dir: Path | None = None) -> Dict[str, Any]:
    observers = [
        _technology_observer(observer, loaded[observer], metadata, state_dir) if category == "technology" else _internet_observer(observer, loaded[observer], metadata)
        for observer in sorted(
            loaded,
            key=lambda item: (_metadata_priority(metadata, item), _metadata_display_name(metadata, item), item),
        )
        if _metadata_category(metadata, observer) == category and _metadata_active(metadata, observer)
    ]
    return {"observer_count": len(observers), "observers": observers, "items": _planned_items(metadata, category)}

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


def _iter_state_observer_files(state_dir: Path, observer: str) -> Iterable[tuple[str, Path]]:
    observer_dir = state_dir / observer
    if not observer_dir.exists():
        return []
    files: list[tuple[str, Path]] = []
    for path in observer_dir.glob("*.json"):
        if not path.is_file():
            continue
        date = path.stem[:10]
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            continue
        files.append((date, path))
    return sorted(files)


def _historical_observer_files(daily_dir: Path, state_dir: Path, observer: str) -> list[tuple[str, Path]]:
    files_by_date: dict[str, Path] = {}
    for date, path in _iter_state_observer_files(state_dir, observer):
        files_by_date[date] = path
    for date, path in _iter_daily_observer_files(daily_dir, observer):
        files_by_date[date] = path
    return sorted(files_by_date.items())


def _numeric_history_values(points: list[Dict[str, Any]]) -> list[float | int]:
    return [point["value"] for point in points if isinstance(point.get("value"), (int, float)) and not isinstance(point.get("value"), bool)]


def _delta_percent(latest: float | int, previous: float | int) -> float | None:
    if previous == 0:
        return None
    return round(((latest - previous) / abs(previous)) * 100, 2)


def _direction(delta: float | int) -> str:
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


def _internet_history_stats(points: list[Dict[str, Any]]) -> Dict[str, Any]:
    values = _numeric_history_values(points)
    stats: Dict[str, Any] = {"total_point_count": len(points), "numeric_point_count": len(values)}
    if values:
        stats["latest_value"] = values[-1]
    if len(values) >= 2:
        latest = values[-1]
        previous = values[-2]
        delta = round(latest - previous, 2)
        stats.update({"previous_value": previous, "delta": delta, "direction": _direction(delta)})
        percent = _delta_percent(latest, previous)
        if percent is not None:
            stats["delta_percent"] = percent
    if len(values) >= 7:
        stats["seven_day_average"] = round(sum(values[-7:]) / 7, 2)
    if len(values) >= 30:
        stats["thirty_day_average"] = round(sum(values[-30:]) / 30, 2)
    return stats


def _internet_history(daily_dir: Path, state_dir: Path, generated_at: str, metadata: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    observers: Dict[str, Any] = {}
    for observer in sorted(
        (item for item in OBSERVERS if _metadata_category(metadata, item) == "internet" and _metadata_active(metadata, item)),
        key=lambda item: (_metadata_priority(metadata, item), _metadata_display_name(metadata, item), item),
    ):
        points: list[Dict[str, Any]] = []
        for date, path in _historical_observer_files(daily_dir, state_dir, observer):
            payload, _error = _read_json(path)
            if payload is None:
                continue
            metric = _internet_history_metric(observer, payload)
            point: Dict[str, Any] = {"date": date, "data_status": _status(payload)}
            if metric is not None:
                name, value = metric
                point["metric_name"] = name
                point["metric_label"] = _friendly_label(observer, "trend_metric_label", name)
                unit = INTERNET_DASHBOARD_METADATA.get(observer, {}).get("trend_metric_unit")
                if isinstance(unit, str) and unit:
                    point["metric_unit"] = unit
                point["value"] = value
            points.append(point)
        metric_label = _friendly_label(observer, "trend_metric_label", "value")
        metric_unit = INTERNET_DASHBOARD_METADATA.get(observer, {}).get("trend_metric_unit")
        observer_payload: Dict[str, Any] = {
            "display_name": _metadata_display_name(metadata, observer),
            "metric_label": metric_label,
            **_internet_history_stats(points),
            "points": points,
            "windows": {
                "7d": _window_summary(points, 7, "value"),
                "30d": _window_summary(points, 30, "value"),
                "90d": _window_summary(points, 90, "value"),
            },
        }
        if isinstance(metric_unit, str) and metric_unit:
            observer_payload["metric_unit"] = metric_unit
        configured_trend = INTERNET_DASHBOARD_METADATA.get(observer, {}).get("trend_metric")
        if isinstance(configured_trend, str) and configured_trend:
            observer_payload["preferred_metric_paths"] = [configured_trend]
        else:
            preferred_paths = PREFERRED_INTERNET_HISTORY_METRICS.get(observer)
            if preferred_paths:
                observer_payload["preferred_metric_paths"] = [".".join(path) for path in preferred_paths]
        observers[observer] = observer_payload
    return {"generated_at": generated_at, "observers": observers}



def _geomagnetic_history_point(date: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    kp = payload.get("kp") if isinstance(payload.get("kp"), dict) else {}
    solar_wind = payload.get("solar_wind") if isinstance(payload.get("solar_wind"), dict) else {}
    point: Dict[str, Any] = {"date": date}
    fields = (
        ("kp", _as_number(kp.get("value"))),
        ("max_kp", _as_number(kp.get("max_available"))),
        ("bz_gsm", _as_number(solar_wind.get("bz_gsm"))),
        ("solar_wind_speed", _as_number(solar_wind.get("speed_km_s"))),
    )
    for key, value in fields:
        if value is not None:
            point[key] = value
    scale = payload.get("storm_scale")
    if isinstance(scale, str) and scale:
        point["storm_scale"] = scale
    return point


def _geomagnetic_history(daily_dir: Path, state_dir: Path, generated_at: str) -> Dict[str, Any]:
    observer = "geomagnetic-storm-observer"
    points = []
    for date, path in _historical_observer_files(daily_dir, state_dir, observer):
        payload, _error = _read_json(path)
        if payload is not None:
            points.append(_geomagnetic_history_point(date, payload))
    return {"observer": observer, "generated_at": generated_at, "points": points}

def export_dashboard(
    latest_dir: Path | None = None,
    dashboard_dir: Path | None = None,
    daily_dir: Path | None = None,
    heartbeat_dir: Path | None = None,
    state_dir: Path | None = None,
) -> Dict[str, Path]:
    using_default_daily_dir = daily_dir is None
    latest_dir = latest_dir or (_repo_root() / "data" / "latest")
    dashboard_dir = dashboard_dir or (_repo_root() / "dashboard")
    daily_dir = daily_dir or (_repo_root() / "data" / "daily")
    heartbeat_dir = heartbeat_dir or (_repo_root() / "state" / "heartbeat")
    state_dir = state_dir or ((_repo_root() / "state") if using_default_daily_dir else (daily_dir.parent / "state"))
    media_imports_dir = _repo_root() / MEDIA_IMPORTS_DIR
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    generated_at = _utc_now()
    loaded, _errors = _load_latest(latest_dir)
    metadata = _load_metadata()
    outputs = {
        "summary.json": _summary(latest_dir, generated_at, loaded, metadata),
        "internet.json": _internet(loaded, metadata),
        "media.json": _media(loaded.get(MEDIA_OBSERVER)),
        "society.json": _society(loaded, metadata, state_dir),
        "environment.json": _category_dashboard("environment", loaded, metadata, state_dir),
        "technology.json": _category_dashboard("technology", loaded, metadata, state_dir),
        "heartbeat.json": _heartbeat(heartbeat_dir, generated_at),
        "history/media-language-germany.json": _media_history(daily_dir, generated_at, media_imports_dir),
        "history/internet-observers.json": _internet_history(daily_dir, state_dir, generated_at, metadata),
        "history/geomagnetic-storm-observer.json": _geomagnetic_history(daily_dir, state_dir, generated_at),
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
