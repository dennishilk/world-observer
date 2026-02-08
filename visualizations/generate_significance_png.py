#!/usr/bin/env python3
"""Generate a single daily PNG for rare, high-significance deviations.

This script reads existing observer outputs and the daily meta summary,
then emits at most one conservative, historically oriented alert image.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
DAILY_DIR = REPO_ROOT / "data" / "daily"
OUTPUT_DIR = REPO_ROOT / "visualizations" / "significant"
STATE_PATH = REPO_ROOT / "visualizations" / "significant_state.json"
SUMMARY_FILENAME = "summary.json"


@dataclass
class SignificanceEvent:
    observer: str
    title: str
    bullets: List[str]
    special_values: Dict[str, Any]


PRIORITY_ORDER = [
    "north-korea-connectivity",
    "internet-shrinkage-index",
    "silent-countries-list",
    "tls-fingerprint-change-watcher",
    "cuba-internet-weather",
    "iran-dns-behavior",
    "area51-reachability",
    "traceroute-to-nowhere",
    "asn-visibility-by-country",
    "ipv6-adoption-locked-states",
    "global-reachability-score",
    "undersea-cable-dependency",
    "dns-time-to-answer-index",
    "mx-presence-by-country",
    "world-observer-meta",
]


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _parse_date(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def _coerce_date(date_value: Optional[str]) -> str:
    if not date_value:
        return _today_utc()
    try:
        parsed = datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError:
        return _today_utc()
    return parsed.date().isoformat()


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _collect_observations(daily_dir: Path) -> Dict[str, Dict[str, Any]]:
    observations: Dict[str, Dict[str, Any]] = {}
    if not daily_dir.exists():
        return observations
    for path in sorted(daily_dir.iterdir()):
        if path.suffix != ".json" or path.name == SUMMARY_FILENAME:
            continue
        payload = _load_json(path)
        if not payload:
            continue
        observer_name = payload.get("observer")
        if isinstance(observer_name, str) and observer_name:
            observations[observer_name] = payload
    return observations


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    payload = _load_json(STATE_PATH)
    return payload or {}


def _save_state(state: Dict[str, Any]) -> None:
    _ensure_state_comments(state)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _nk_is_silent(payload: Dict[str, Any]) -> bool:
    # Rule: treat silence as all targets failing ping, TCP 443, and DNS (timeout/error).
    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        return False
    for target in targets:
        if not isinstance(target, dict):
            return False
        ping_ok = target.get("ping", {}).get("ok")
        tcp_ok = target.get("tcp_443", {}).get("ok")
        dns_a = target.get("dns", {}).get("a", {}).get("status")
        dns_aaaa = target.get("dns", {}).get("aaaa", {}).get("status")
        dns_failed = dns_a in {"timeout", "error"} and dns_aaaa in {"timeout", "error"}
        if not (ping_ok is False and tcp_ok is False and dns_failed):
            return False
    return True


def _nk_any_success(payload: Dict[str, Any]) -> bool:
    # Rule: any successful ping, TCP handshake, or DNS answer counts as a response.
    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        return False
    for target in targets:
        if not isinstance(target, dict):
            continue
        ping_ok = target.get("ping", {}).get("ok")
        tcp_ok = target.get("tcp_443", {}).get("ok")
        dns_a = target.get("dns", {}).get("a", {}).get("status")
        dns_aaaa = target.get("dns", {}).get("aaaa", {}).get("status")
        if ping_ok is True or tcp_ok is True or dns_a == "answer" or dns_aaaa == "answer":
            return True
    return False


def _looks_like_ip_or_asn(value: str) -> bool:
    if not value:
        return False
    if value.lower().startswith("as") and value[2:].isdigit():
        return True
    if ":" in value and all(part for part in value.split(":")):
        return True
    parts = value.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        return True
    return False


def _map_origin_context(value: str) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    if _looks_like_ip_or_asn(value):
        return None
    normalized = value.lower()
    if "domestic" in normalized or "internal" in normalized or "local" in normalized:
        return "domestic_network"
    if "international" in normalized or "transit" in normalized or "external" in normalized:
        return "international_transit"
    if "unknown" in normalized:
        return "unknown"
    return None


def _map_country_hint(value: str) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    if _looks_like_ip_or_asn(value):
        return None
    normalized = value.strip().lower()
    north_korea_values = {
        "kp",
        "prk",
        "north korea",
        "democratic people's republic of korea",
        "democratic peoples republic of korea",
    }
    if normalized in north_korea_values:
        return "domestic_network"
    return "international_transit"


def _map_response_path(value: Any) -> Optional[str]:
    if isinstance(value, list):
        countries: List[str] = []
        for hop in value:
            if isinstance(hop, dict):
                for key in ("country", "country_code", "asn_country"):
                    hop_value = hop.get(key)
                    if isinstance(hop_value, str):
                        countries.append(hop_value)
            elif isinstance(hop, str):
                countries.append(hop)
        mapped = [_map_country_hint(country) for country in countries]
        mapped = [item for item in mapped if item]
        if not mapped:
            return None
        if "international_transit" in mapped:
            return "international_transit"
        return "domestic_network"
    if isinstance(value, str):
        return _map_origin_context(value)
    return None


def _nk_origin_context(payload: Dict[str, Any]) -> str:
    for candidate in [payload.get("origin_context"), payload.get("asn_country")]:
        mapped = _map_origin_context(candidate) or _map_country_hint(candidate)
        if mapped:
            return mapped
    response_path = payload.get("response_path")
    mapped_path = _map_response_path(response_path)
    if mapped_path:
        return mapped_path
    targets = payload.get("targets")
    if isinstance(targets, list):
        for target in targets:
            if not isinstance(target, dict):
                continue
            for key in ("origin_context", "asn_country", "response_path"):
                mapped = _map_origin_context(target.get(key)) or _map_country_hint(
                    target.get(key)
                )
                if mapped:
                    return mapped
                mapped_path = _map_response_path(target.get(key))
                if mapped_path:
                    return mapped_path
    return "unknown"


def _cuba_classification(payload: Dict[str, Any]) -> Optional[str]:
    summary = payload.get("weather_summary")
    if not isinstance(summary, dict):
        return None
    classification = summary.get("classification")
    if isinstance(classification, str):
        return classification
    return None


def _cuba_classification_label(value: Optional[str]) -> str:
    if not value:
        return "unknown"
    normalized = value.strip().lower()
    if normalized == "offline":
        return "no response"
    if normalized == "online":
        return "responsive"
    return value


def _iran_behavior_class(payload: Dict[str, Any]) -> Optional[str]:
    # Rule: categorize DNS behavior from summary counts (responsive/silent/refused/mixed).
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return None
    total = summary.get("total_queries")
    answered = summary.get("answered")
    timeouts = summary.get("timeouts")
    refused = summary.get("refused")
    if not all(isinstance(value, int) for value in [total, answered, timeouts, refused]):
        return None
    if total <= 0:
        return "unknown"
    if answered == total:
        return "responsive"
    if timeouts == total:
        return "silent"
    if refused == total:
        return "refused"
    return "mixed"


def _area51_state(payload: Dict[str, Any]) -> Optional[str]:
    # Rule: derive reachability from any ping/TCP success across targets.
    network = payload.get("network", {})
    targets = network.get("targets", {})
    if not isinstance(targets, dict) or not targets:
        return None
    any_reachable = False
    any_unreachable = False
    for details in targets.values():
        if not isinstance(details, dict):
            continue
        ping_ok = details.get("ping")
        tcp_ok = details.get("tcp_443")
        if ping_ok is True or tcp_ok is True:
            any_reachable = True
        if ping_ok is False and tcp_ok is False:
            any_unreachable = True
    if any_reachable and not any_unreachable:
        return "reachable"
    if any_unreachable and not any_reachable:
        return "unreachable"
    if any_reachable or any_unreachable:
        return "mixed"
    return None


def _traceroute_targets(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    targets = payload.get("targets")
    if not isinstance(targets, list):
        return {}
    result = {}
    for target in targets:
        if not isinstance(target, dict):
            continue
        key = str(target.get("name") or target.get("host") or "")
        if not key:
            continue
        result[key] = target
    return result


def _shrinkage_index(payload: Dict[str, Any]) -> Optional[float]:
    index = payload.get("index")
    if isinstance(index, (int, float)):
        return float(index)
    return None


def _silent_countries_count(payload: Dict[str, Any]) -> Optional[int]:
    silent = payload.get("silent_countries")
    if isinstance(silent, list):
        return len(silent)
    return None


def _asn_countries(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    countries = payload.get("countries")
    if not isinstance(countries, list):
        return {}
    result = {}
    for entry in countries:
        if not isinstance(entry, dict):
            continue
        country = entry.get("country")
        if isinstance(country, str) and country:
            result[country] = entry
    return result


def _ipv6_countries(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    countries = payload.get("countries")
    if not isinstance(countries, list):
        return {}
    result = {}
    for entry in countries:
        if not isinstance(entry, dict):
            continue
        country = entry.get("country")
        if isinstance(country, str) and country:
            result[country] = entry
    return result


def _global_reachability_score(payload: Dict[str, Any]) -> Optional[float]:
    # Rule: use the reported global score if present; otherwise average country scores.
    direct_score = payload.get("global_reachability_score")
    if isinstance(direct_score, (int, float)):
        return float(direct_score)
    countries = payload.get("countries")
    if not isinstance(countries, list) or not countries:
        return None
    scores = [
        entry.get("score_percent")
        for entry in countries
        if isinstance(entry, dict) and isinstance(entry.get("score_percent"), (int, float))
    ]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 2)


def _undersea_countries(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    countries = payload.get("countries")
    if not isinstance(countries, list):
        return {}
    result = {}
    for entry in countries:
        if not isinstance(entry, dict):
            continue
        country = entry.get("country")
        if isinstance(country, str) and country:
            result[country] = entry
    return result


def _dns_avg_latency(payload: Dict[str, Any]) -> Optional[float]:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return None
    avg = summary.get("avg_query_ms")
    if isinstance(avg, (int, float)):
        return float(avg)
    return None


def _mx_country_transition(payload: Dict[str, Any], previous: Dict[str, Any]) -> Optional[Tuple[str, int]]:
    # Rule: trigger only if explicit MX counts transition from zero to non-zero.
    today_countries = payload.get("countries")
    yesterday_countries = previous.get("countries")
    if not isinstance(today_countries, list) or not isinstance(yesterday_countries, list):
        return None

    def build_map(entries: List[Dict[str, Any]]) -> Dict[str, int]:
        result = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            country = entry.get("country")
            if not isinstance(country, str) or not country:
                continue
            mx_count = entry.get("mx_count")
            if isinstance(mx_count, int):
                result[country] = mx_count
        return result

    today_map = build_map(today_countries)
    yesterday_map = build_map(yesterday_countries)
    for country, mx_count in today_map.items():
        if mx_count > 0 and yesterday_map.get(country, 0) == 0:
            return country, mx_count
    return None


def _select_event(events: List[SignificanceEvent]) -> Optional[SignificanceEvent]:
    if not events:
        return None
    priority_map = {name: index for index, name in enumerate(PRIORITY_ORDER)}
    return sorted(events, key=lambda event: priority_map.get(event.observer, 9999))[0]


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        tentative = f"{current} {word}".strip()
        if draw.textlength(tentative, font=font) <= max_width or not current:
            current = tentative
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _render_png(date_str: str, event: SignificanceEvent) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{date_str}-{event.observer}.png"
    output_path = OUTPUT_DIR / filename

    width, height = 1000, 600
    background = (18, 20, 24)
    text_color = (235, 235, 235)
    muted_color = (180, 180, 180)

    image = Image.new("RGB", (width, height), color=background)
    draw = ImageDraw.Draw(image)

    def load_font(preferred_names: List[str], size: int) -> ImageFont.FreeTypeFont:
        for name in preferred_names:
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    title_font = load_font(["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"], 45)
    body_font = load_font(["DejaVuSans.ttf"], 24)
    header_font = load_font(["DejaVuSans.ttf"], 18)
    footer_font = load_font(["DejaVuSans.ttf"], 18)

    x_margin = 60
    y = 40
    content_width = width - (x_margin * 2)

    draw.text(
        (x_margin, y),
        "WORLD OBSERVER — SIGNIFICANT EVENT",
        fill=muted_color,
        font=header_font,
    )
    y += 24
    draw.text((x_margin, y), date_str, fill=muted_color, font=header_font)
    y += 50

    title_lines = _wrap_text(draw, event.title, title_font, content_width)
    for line in title_lines:
        draw.text((x_margin, y), line, fill=text_color, font=title_font)
        y += 54
    y += 10

    for bullet in event.bullets:
        bullet_lines = _wrap_text(draw, f"• {bullet}", body_font, content_width)
        for index, line in enumerate(bullet_lines):
            draw.text((x_margin, y), line, fill=text_color, font=body_font)
            y += 32 if index == len(bullet_lines) - 1 else 28
        y += 6

    footer_text = "Deviation from long-term baseline"
    draw.text((x_margin, height - 60), footer_text, fill=muted_color, font=footer_font)

    image.save(output_path)
    return output_path


def _ensure_state_comments(state: Dict[str, Any]) -> None:
    state.setdefault(
        "_comment_last_generated_date",
        "Records the most recent PNG date to prevent duplicate renders for the same day.",
    )
    state.setdefault(
        "_comment_last_generated_observer",
        "Records which observer produced the last PNG for audit and deduplication checks.",
    )
    state.setdefault(
        "_comment_area51",
        "Baseline memory for Area 51 reachability to avoid false shifts during short-term noise.",
    )
    state.setdefault(
        "_comment_cuba_internet",
        "Baseline memory for Cuba classification to measure extended non-response periods.",
    )
    state.setdefault(
        "_comment_tls_fingerprints",
        "Baseline memory for TLS fingerprints to avoid single-day noise and detect long-term changes.",
    )
    state.setdefault(
        "_comment_ipv6_states",
        "Baseline memory for IPv6 availability to prevent duplicate first-seen notices.",
    )
    state.setdefault(
        "_comment_global_reachability",
        "Baseline memory for global reachability to prevent single-day baselines from triggering events.",
    )

    area_state = state.setdefault("area51", {})
    if isinstance(area_state, dict):
        area_state.setdefault(
            "_comment_last_state",
            "Stores the last reachability state for stability comparisons.",
        )
        area_state.setdefault(
            "_comment_last_change_date",
            "Stores the date of the last reachability change to compute stability.",
        )

    cuba_state = state.setdefault("cuba_internet", {})
    if isinstance(cuba_state, dict):
        cuba_state.setdefault(
            "_comment_outage_start_date",
            "Stores the start date of a non-response stretch to measure duration.",
        )
        cuba_state.setdefault(
            "_comment_last_classification",
            "Stores the most recent classification for continuity checks.",
        )

    tls_state = state.setdefault("tls_fingerprints", {})
    if isinstance(tls_state, dict):
        tls_state.setdefault(
            "_comment_hosts",
            "Stores per-host fingerprints with first-seen dates for change detection.",
        )

    ipv6_state = state.setdefault("ipv6_states", {})
    if isinstance(ipv6_state, dict):
        ipv6_state.setdefault(
            "_comment_countries",
            "Stores per-country IPv6 availability with stability timestamps.",
        )

    reach_state = state.setdefault("global_reachability", {})
    if isinstance(reach_state, dict):
        reach_state.setdefault(
            "_comment_lowest_score",
            "Stores the lowest observed score for historical comparison after baselines exist.",
        )
        reach_state.setdefault(
            "_comment_date",
            "Stores the date when the lowest score was observed to avoid repeats.",
        )


def _update_area51_state(state: Dict[str, Any], today_state: Optional[str], today_str: str) -> None:
    area_state = state.setdefault("area51", {})
    last_state = area_state.get("last_state")
    last_change = area_state.get("last_change_date")
    if today_state is None:
        return
    if last_state != today_state:
        area_state["last_state"] = today_state
        area_state["last_change_date"] = today_str
    else:
        if not last_change:
            area_state["last_change_date"] = today_str


def _update_cuba_state(state: Dict[str, Any], classification: Optional[str], today: date) -> None:
    cuba_state = state.setdefault("cuba_internet", {})
    outage_start = cuba_state.get("outage_start_date")
    if classification == "offline":
        if outage_start is None:
            cuba_state["outage_start_date"] = today.isoformat()
    else:
        cuba_state["outage_start_date"] = None
    if classification:
        cuba_state["last_classification"] = classification


def _update_tls_state(state: Dict[str, Any], payload: Dict[str, Any], today_str: str) -> None:
    tls_state = state.setdefault("tls_fingerprints", {})
    hosts = tls_state.setdefault("hosts", {})
    targets = payload.get("targets")
    if not isinstance(targets, list):
        return
    for target in targets:
        if not isinstance(target, dict):
            continue
        host = target.get("host")
        fingerprint = target.get("fingerprint_sha256")
        if not isinstance(host, str) or not host:
            continue
        if not isinstance(fingerprint, str) or not fingerprint:
            continue
        existing = hosts.get(host)
        if not isinstance(existing, dict) or existing.get("fingerprint") != fingerprint:
            hosts[host] = {"fingerprint": fingerprint, "first_seen": today_str}


def _update_ipv6_state(state: Dict[str, Any], payload: Dict[str, Any], today_str: str) -> None:
    ipv6_state = state.setdefault("ipv6_states", {})
    countries_state = ipv6_state.setdefault("countries", {})
    countries = _ipv6_countries(payload)
    for country, entry in countries.items():
        ipv6_available = entry.get("ipv6_available")
        if not isinstance(ipv6_available, bool):
            continue
        existing = countries_state.get(country, {})
        last_state = existing.get("last_state")
        stable_since = existing.get("stable_since")
        if last_state == ipv6_available:
            if not stable_since:
                existing["stable_since"] = today_str
        else:
            existing["stable_since"] = today_str
        existing["last_state"] = ipv6_available
        countries_state[country] = existing


def _update_global_reachability_state(state: Dict[str, Any], score: Optional[float], today_str: str) -> None:
    if score is None:
        return
    reach_state = state.setdefault("global_reachability", {})
    lowest_score = reach_state.get("lowest_score")
    if lowest_score is None or score < float(lowest_score):
        reach_state["lowest_score"] = score
        reach_state["date"] = today_str


def evaluate_significance(
    today_str: str,
    yesterday_str: str,
    today_obs: Dict[str, Dict[str, Any]],
    yesterday_obs: Dict[str, Dict[str, Any]],
    state: Dict[str, Any],
) -> Tuple[List[SignificanceEvent], Dict[str, Any]]:
    events: List[SignificanceEvent] = []
    today = _parse_date(today_str)
    yesterday = _parse_date(yesterday_str)

    # 1) north-korea-connectivity: trigger on silence-to-response transition.
    nk_today = today_obs.get("north-korea-connectivity")
    nk_yesterday = yesterday_obs.get("north-korea-connectivity")
    if nk_today and nk_yesterday:
        if _nk_is_silent(nk_yesterday) and _nk_any_success(nk_today):
            origin_context = _nk_origin_context(nk_today)
            events.append(
                SignificanceEvent(
                    observer="north-korea-connectivity",
                    title="North Korea connectivity response detected",
                    bullets=[
                        "Yesterday: complete silence across monitored targets.",
                        "Today: at least one successful response observed.",
                        f"Response observed via {origin_context}.",
                    ],
                    special_values={"origin_context": origin_context},
                )
            )

    # 2) cuba-internet-weather: trigger on zero availability or recovery after >= 7 days.
    cuba_today = today_obs.get("cuba-internet-weather")
    cuba_yesterday = yesterday_obs.get("cuba-internet-weather")
    if cuba_today and cuba_yesterday:
        today_class = _cuba_classification(cuba_today)
        yesterday_class = _cuba_classification(cuba_yesterday)
        cuba_state = state.get("cuba_internet", {})
        outage_start = cuba_state.get("outage_start_date")
        outage_days = None
        if outage_start:
            outage_days = (today - _parse_date(outage_start)).days + 1
        if today_class == "offline" and yesterday_class != "offline":
            events.append(
                SignificanceEvent(
                    observer="cuba-internet-weather",
                    title="Cuba availability classification changed to no response",
                    bullets=[
                        f"Classification today: {_cuba_classification_label(today_class)}.",
                        "Yesterday: response observed.",
                        "Non-response duration: 1 day (start of stretch).",
                    ],
                    special_values={"outage_duration_days": 1},
                )
            )
        if (
            today_class
            and today_class != "offline"
            and yesterday_class == "offline"
            and outage_days
            and outage_days >= 7
        ):
            events.append(
                SignificanceEvent(
                    observer="cuba-internet-weather",
                    title="Cuba availability classification changed after prolonged non-response period",
                    bullets=[
                        f"Non-response duration: {outage_days} days.",
                        f"Classification today: {_cuba_classification_label(today_class)}.",
                        "Yesterday: no response.",
                    ],
                    special_values={"outage_duration_days": outage_days},
                )
            )

    # 3) iran-dns-behavior: trigger when DNS behavior category changes.
    iran_today = today_obs.get("iran-dns-behavior")
    iran_yesterday = yesterday_obs.get("iran-dns-behavior")
    if iran_today and iran_yesterday:
        today_class = _iran_behavior_class(iran_today)
        yesterday_class = _iran_behavior_class(iran_yesterday)
        if today_class and yesterday_class and today_class != yesterday_class:
            events.append(
                SignificanceEvent(
                    observer="iran-dns-behavior",
                    title="Iran DNS response category changed",
                    bullets=[
                        f"Previous class: {yesterday_class}.",
                        f"Current class: {today_class}.",
                        "Category change from summary query outcomes.",
                    ],
                    special_values={"dns_behavior_class": today_class},
                )
            )

    # 4) area51-reachability: trigger if state changes after >= 30 days stability.
    area_today = today_obs.get("area51-reachability")
    if area_today:
        today_state = _area51_state(area_today)
        area_state = state.get("area51", {})
        last_state = area_state.get("last_state")
        last_change = area_state.get("last_change_date")
        if today_state and last_state and last_change and today_state != last_state:
            stable_days = (today - _parse_date(last_change)).days
            if stable_days >= 30:
                events.append(
                    SignificanceEvent(
                        observer="area51-reachability",
                    title="Area 51 reachability state shifted after stability",
                    bullets=[
                        f"New reachability state: {today_state}.",
                        f"Stable for {stable_days} days before change.",
                        "Reachability from ping/TCP outcomes only.",
                    ],
                    special_values={"reachability_state": today_state},
                )
            )

    # 5) traceroute-to-nowhere: trigger on stop-zone change or hop collapse >= 50%.
    trace_today = today_obs.get("traceroute-to-nowhere")
    trace_yesterday = yesterday_obs.get("traceroute-to-nowhere")
    if trace_today and trace_yesterday:
        today_targets = _traceroute_targets(trace_today)
        yesterday_targets = _traceroute_targets(trace_yesterday)
        for key, today_target in today_targets.items():
            yesterday_target = yesterday_targets.get(key)
            if not yesterday_target:
                continue
            today_zone = today_target.get("stop_zone")
            yesterday_zone = yesterday_target.get("stop_zone")
            today_hops = today_target.get("hops_reached")
            yesterday_hops = yesterday_target.get("hops_reached")
            if (
                isinstance(today_zone, str)
                and isinstance(yesterday_zone, str)
                and today_zone != yesterday_zone
            ):
                events.append(
                    SignificanceEvent(
                        observer="traceroute-to-nowhere",
                        title="Traceroute termination region changed",
                        bullets=[
                            f"Termination region today: {today_zone}.",
                            f"Termination region yesterday: {yesterday_zone}.",
                            "Stop region from hop count only.",
                        ],
                        special_values={"termination_region": today_zone},
                    )
                )
                break
            if (
                isinstance(today_hops, int)
                and isinstance(yesterday_hops, int)
                and yesterday_hops > 0
                and today_hops <= (yesterday_hops / 2)
            ):
                events.append(
                    SignificanceEvent(
                        observer="traceroute-to-nowhere",
                        title="Traceroute path length changed",
                        bullets=[
                            f"Termination region today: {today_zone or 'unknown'}.",
                            f"Hops today: {today_hops}.",
                            f"Hops yesterday: {yesterday_hops}.",
                        ],
                        special_values={"termination_region": today_zone or "unknown"},
                    )
                )
                break

    # 6) internet-shrinkage-index: trigger if absolute change >= 0.10 in 24 hours.
    shrink_today = today_obs.get("internet-shrinkage-index")
    shrink_yesterday = yesterday_obs.get("internet-shrinkage-index")
    if shrink_today and shrink_yesterday:
        today_index = _shrinkage_index(shrink_today)
        yesterday_index = _shrinkage_index(shrink_yesterday)
        if today_index is not None and yesterday_index is not None:
            delta = today_index - yesterday_index
            if abs(delta) >= 0.10:
                events.append(
                    SignificanceEvent(
                        observer="internet-shrinkage-index",
                        title="Internet shrinkage index shifted sharply",
                        bullets=[
                            f"Index today: {today_index:.2f}.",
                            f"Index yesterday: {yesterday_index:.2f}.",
                            f"Delta: {delta:+.2f}.",
                        ],
                        special_values={"delta_value": round(delta, 2)},
                    )
                )

    # 7) asn-visibility-by-country: trigger if >= 3 ASNs disappear in a day.
    asn_today = today_obs.get("asn-visibility-by-country")
    asn_yesterday = yesterday_obs.get("asn-visibility-by-country")
    if asn_today and asn_yesterday:
        today_countries = _asn_countries(asn_today)
        yesterday_countries = _asn_countries(asn_yesterday)
        for country, today_entry in today_countries.items():
            yesterday_entry = yesterday_countries.get(country)
            if not yesterday_entry:
                continue
            today_visible = today_entry.get("visible_asns")
            yesterday_visible = yesterday_entry.get("visible_asns")
            if (
                isinstance(today_visible, int)
                and isinstance(yesterday_visible, int)
                and yesterday_visible - today_visible >= 3
            ):
                events.append(
                    SignificanceEvent(
                        observer="asn-visibility-by-country",
                        title="ASN visibility changed in one country",
                        bullets=[
                            f"Affected country: {country}.",
                            f"Visible ASNs today: {today_visible}.",
                            f"Visible ASNs yesterday: {yesterday_visible}.",
                        ],
                        special_values={"affected_country": country},
                    )
                )
                break

    # 8) tls-fingerprint-change-watcher: trigger if fingerprint changes after >= 30 days.
    tls_today = today_obs.get("tls-fingerprint-change-watcher")
    if tls_today:
        tls_state = state.get("tls_fingerprints", {}).get("hosts", {})
        targets = tls_today.get("targets")
        if isinstance(targets, list):
            for target in targets:
                if not isinstance(target, dict):
                    continue
                host = target.get("host")
                name = target.get("name")
                fingerprint = target.get("fingerprint_sha256")
                if not isinstance(host, str) or not isinstance(fingerprint, str):
                    continue
                previous = tls_state.get(host)
                if not isinstance(previous, dict):
                    continue
                if previous.get("fingerprint") != fingerprint:
                    first_seen = previous.get("first_seen")
                    if not isinstance(first_seen, str):
                        continue
                    age_days = (today - _parse_date(first_seen)).days
                    if age_days >= 30:
                        events.append(
                            SignificanceEvent(
                                observer="tls-fingerprint-change-watcher",
                                title="TLS fingerprint changed after long stability",
                                bullets=[
                                    f"Target: {name or 'unknown'}.",
                                    f"Previous fingerprint age: {age_days} days.",
                                    "Change detected via stored fingerprint history.",
                                ],
                                special_values={"fingerprint_age_days": age_days},
                            )
                        )
                        break

    # 9) silent-countries-list: trigger when silent country count increases by >= 2.
    silent_today = today_obs.get("silent-countries-list")
    silent_yesterday = yesterday_obs.get("silent-countries-list")
    if silent_today and silent_yesterday:
        today_count = _silent_countries_count(silent_today)
        yesterday_count = _silent_countries_count(silent_yesterday)
        if today_count is not None and yesterday_count is not None:
            delta = today_count - yesterday_count
            if delta >= 2:
                events.append(
                    SignificanceEvent(
                        observer="silent-countries-list",
                        title="Silent country count changed",
                        bullets=[
                            f"Silent countries today: {today_count}.",
                            f"Silent countries yesterday: {yesterday_count}.",
                            f"Delta: +{delta}.",
                        ],
                        special_values={"delta_silent_count": delta},
                    )
                )

    # 10) ipv6-adoption-locked-states: trigger on first presence or stable disappearance.
    ipv6_today = today_obs.get("ipv6-adoption-locked-states")
    if ipv6_today:
        ipv6_state = state.get("ipv6_states", {}).get("countries", {})
        countries = _ipv6_countries(ipv6_today)
        for country, entry in countries.items():
            ipv6_available = entry.get("ipv6_available")
            if not isinstance(ipv6_available, bool):
                continue
            previous = ipv6_state.get(country, {})
            last_state = previous.get("last_state")
            stable_since = previous.get("stable_since")
            stable_days = None
            if isinstance(stable_since, str):
                stable_days = (today - _parse_date(stable_since)).days
            if last_state is None and ipv6_available:
                events.append(
                    SignificanceEvent(
                        observer="ipv6-adoption-locked-states",
                        title="IPv6 presence detected for the first time",
                        bullets=[
                            f"Country: {country}.",
                            "IPv6 state: detected.",
                            "First observed in current data.",
                        ],
                        special_values={"ipv6_state": "appeared"},
                    )
                )
                break
            if last_state is True and ipv6_available is False and stable_days is not None:
                if stable_days >= 7:
                    events.append(
                        SignificanceEvent(
                            observer="ipv6-adoption-locked-states",
                            title="IPv6 presence changed after stability",
                            bullets=[
                                f"Country: {country}.",
                                "IPv6 state: changed.",
                                f"Stable for {stable_days} days before change.",
                            ],
                            special_values={"ipv6_state": "disappeared"},
                        )
                    )
                    break

    # 11) global-reachability-score: trigger on lowest value since project start.
    global_today = today_obs.get("global-reachability-score")
    global_yesterday = yesterday_obs.get("global-reachability-score")
    if global_today and global_yesterday:
        today_score = _global_reachability_score(global_today)
        yesterday_score = _global_reachability_score(global_yesterday)
        reach_state = state.get("global_reachability", {})
        lowest_score = reach_state.get("lowest_score")
        if today_score is not None:
            if (
                yesterday_score is not None
                and lowest_score is not None
                and today_score < float(lowest_score)
            ):
                events.append(
                    SignificanceEvent(
                        observer="global-reachability-score",
                        title="Global reachability score deviated to a new low",
                        bullets=[
                            f"Score today: {today_score:.2f}.",
                            "Lowest value since measurements began.",
                            "Score from reported country scores only.",
                        ],
                        special_values={"score_rank": "lowest_on_record"},
                    )
                )

    # 12) undersea-cable-dependency: trigger on single-cable dependency or loss.
    cable_today = today_obs.get("undersea-cable-dependency")
    cable_yesterday = yesterday_obs.get("undersea-cable-dependency")
    if cable_today and cable_yesterday:
        today_countries = _undersea_countries(cable_today)
        yesterday_countries = _undersea_countries(cable_yesterday)
        for country, today_entry in today_countries.items():
            yesterday_entry = yesterday_countries.get(country)
            if not yesterday_entry:
                continue
            today_count = today_entry.get("cable_count")
            yesterday_count = yesterday_entry.get("cable_count")
            if not isinstance(today_count, int) or not isinstance(yesterday_count, int):
                continue
            if today_count == 1 and yesterday_count > 1:
                events.append(
                    SignificanceEvent(
                        observer="undersea-cable-dependency",
                        title="Undersea cable redundancy changed",
                        bullets=[
                            f"Affected region: {country}.",
                            f"Cable count today: {today_count}.",
                            f"Cable count yesterday: {yesterday_count}.",
                        ],
                        special_values={"affected_region": country},
                    )
                )
                break
            if today_count == 0 and yesterday_count > 0:
                events.append(
                    SignificanceEvent(
                        observer="undersea-cable-dependency",
                        title="Undersea cable redundancy changed",
                        bullets=[
                            f"Affected region: {country}.",
                            f"Cable count today: {today_count}.",
                            f"Cable count yesterday: {yesterday_count}.",
                        ],
                        special_values={"affected_region": country},
                    )
                )
                break

    # 13) dns-time-to-answer-index: trigger when latency doubles in 24 hours.
    dns_today = today_obs.get("dns-time-to-answer-index")
    dns_yesterday = yesterday_obs.get("dns-time-to-answer-index")
    if dns_today and dns_yesterday:
        today_avg = _dns_avg_latency(dns_today)
        yesterday_avg = _dns_avg_latency(dns_yesterday)
        if (
            today_avg is not None
            and yesterday_avg is not None
            and yesterday_avg > 0
            and today_avg >= (yesterday_avg * 2)
        ):
            multiplier = round(today_avg / yesterday_avg, 2)
            events.append(
                SignificanceEvent(
                    observer="dns-time-to-answer-index",
                    title="Global DNS latency changed sharply",
                    bullets=[
                        f"Average query time today: {today_avg:.2f} ms.",
                        f"Average query time yesterday: {yesterday_avg:.2f} ms.",
                        f"Latency multiplier: {multiplier:.2f}.",
                    ],
                    special_values={"latency_multiplier": multiplier},
                )
            )

    # 14) mx-presence-by-country: trigger on zero-to-one MX transitions.
    mx_today = today_obs.get("mx-presence-by-country")
    mx_yesterday = yesterday_obs.get("mx-presence-by-country")
    if mx_today and mx_yesterday:
        transition = _mx_country_transition(mx_today, mx_yesterday)
        if transition:
            country, mx_count = transition
            events.append(
                SignificanceEvent(
                    observer="mx-presence-by-country",
                    title="MX presence detected in a country",
                    bullets=[
                        f"Country: {country}.",
                        f"Valid MX domains today: {mx_count}.",
                        "Previous presence: zero.",
                    ],
                    special_values={"country_code": country},
                )
            )

    # 15) world-observer-meta: use a single meta event when >= 3 observers signal deviations.
    if len(events) >= 3:
        observers_involved = sorted({event.observer for event in events})
        events = [
            SignificanceEvent(
                observer="world-observer-meta",
                title="Multiple observers detected deviations",
                bullets=[
                    f"Observers involved: {', '.join(observers_involved)}.",
                    f"Total observers: {len(observers_involved)}.",
                    f"Date: {today_str}.",
                ],
                special_values={"observers_involved": observers_involved},
            )
        ]

    # Update baseline state after evaluation to preserve change detection.
    if cuba_today:
        _update_cuba_state(state, _cuba_classification(cuba_today), today)
    if area_today:
        _update_area51_state(state, _area51_state(area_today), today_str)
    if tls_today:
        _update_tls_state(state, tls_today, today_str)
    if ipv6_today:
        _update_ipv6_state(state, ipv6_today, today_str)
    if global_today:
        _update_global_reachability_state(state, _global_reachability_score(global_today), today_str)

    return events, state


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a daily significance PNG.")
    parser.add_argument("--date", help="Date to evaluate (YYYY-MM-DD)")
    args = parser.parse_args()

    today_str = _coerce_date(args.date)
    today_date = _parse_date(today_str)
    yesterday_str = (today_date - timedelta(days=1)).isoformat()

    today_dir = DAILY_DIR / today_str
    yesterday_dir = DAILY_DIR / yesterday_str

    today_obs = _collect_observations(today_dir)
    yesterday_obs = _collect_observations(yesterday_dir)

    state = _load_state()
    _ensure_state_comments(state)
    events, state = evaluate_significance(
        today_str,
        yesterday_str,
        today_obs,
        yesterday_obs,
        state,
    )

    selected = _select_event(events)

    existing_png = None
    if OUTPUT_DIR.exists():
        matches = sorted(OUTPUT_DIR.glob(f"{today_str}-*.png"))
        existing_png = matches[0] if matches else None
    already_generated = state.get("last_generated_date") == today_str or existing_png is not None
    if existing_png and state.get("last_generated_date") != today_str:
        observer_name = existing_png.stem[len(today_str) + 1 :]
        state["last_generated_date"] = today_str
        state["last_generated_observer"] = observer_name or state.get("last_generated_observer")
    if selected and not already_generated:
        output_path = _render_png(today_str, selected)
        state["last_generated_date"] = today_str
        state["last_generated_observer"] = selected.observer
        _save_state(state)
        print(str(output_path))
        return

    _save_state(state)
    if not selected:
        print("No significant deviation detected.")
    else:
        print("Deviation already observed for this date.")


if __name__ == "__main__":
    main()
