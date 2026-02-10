"""Correlation-only meta observer for silent-countries-list."""

from __future__ import annotations

import json
import os
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Set, Tuple


OBSERVER_NAME = "silent-countries-list"
MODULE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = MODULE_DIR / "config.json"
REPO_ROOT = MODULE_DIR.parents[1]
DAILY_ROOT = REPO_ROOT / "data" / "daily"
LATEST_ROOT = REPO_ROOT / "data" / "latest"
LATEST_SUMMARY_PATH = LATEST_ROOT / "summary.json"
CHART_PATH = LATEST_ROOT / "chart.png"


@dataclass(frozen=True)
class CountrySignals:
    """Normalized country-level signal values used for scoring."""

    hard_silence: float = 0.0
    low_reachability: float = 0.0
    dns_anomaly: float = 0.0
    time_to_silence: float = 0.0
    ipv6_absence: float = 0.0


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _coerce_date() -> str:
    date_value = os.environ.get("WORLD_OBSERVER_DATE_UTC")
    if not date_value:
        return _today_utc()
    try:
        return datetime.strptime(date_value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return _today_utc()


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_config() -> Dict[str, Any]:
    payload = _load_json(CONFIG_PATH)
    if not payload:
        raise ValueError(f"Missing or invalid config at {CONFIG_PATH}")
    return payload


def _normalize_country(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    country = value.strip()
    return country if country else None


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _safe_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _iter_last_n_dates(date_str: str, days: int) -> List[str]:
    base = datetime.strptime(date_str, "%Y-%m-%d").date()
    return [(base - timedelta(days=offset)).isoformat() for offset in range(1, days + 1)]


def _load_observer_payloads(date_str: str, observers: List[str]) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    daily_dir = DAILY_ROOT / date_str
    loaded: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = []

    for observer in observers:
        payload = _load_json(daily_dir / f"{observer}.json")
        if payload is None:
            missing.append(observer)
            continue
        loaded[observer] = payload

    return loaded, missing


def _collect_signals(payloads: Dict[str, Dict[str, Any]]) -> Dict[str, CountrySignals]:
    by_country: Dict[str, Dict[str, float]] = {}

    def touch(country: str) -> Dict[str, float]:
        return by_country.setdefault(
            country,
            {
                "hard_silence": 0.0,
                "low_reachability": 0.0,
                "dns_anomaly": 0.0,
                "time_to_silence": 0.0,
                "ipv6_absence": 0.0,
            },
        )

    nk = payloads.get("north-korea-connectivity", {})
    targets = nk.get("targets")
    if isinstance(targets, list) and targets:
        total = 0
        silent_like = 0
        dns_anomaly_hits = 0
        for target in targets:
            if not isinstance(target, dict):
                continue
            total += 1
            ping_ok = target.get("ping", {}).get("ok")
            tcp_ok = target.get("tcp_443", {}).get("ok")
            dns_a = target.get("dns", {}).get("a", {}).get("status")
            dns_aaaa = target.get("dns", {}).get("aaaa", {}).get("status")
            dns_failed = dns_a in {"error", "timeout", "noanswer", "nxdomain"} and dns_aaaa in {
                "error",
                "timeout",
                "noanswer",
                "nxdomain",
            }
            if ping_ok is False and tcp_ok is False and dns_failed:
                silent_like += 1
            if dns_failed:
                dns_anomaly_hits += 1
        if total > 0:
            record = touch("KP")
            record["hard_silence"] = max(record["hard_silence"], silent_like / total)
            record["dns_anomaly"] = max(record["dns_anomaly"], dns_anomaly_hits / total)

    reachability = payloads.get("global-reachability-score", {})
    countries = reachability.get("countries")
    if isinstance(countries, list):
        for item in countries:
            if not isinstance(item, dict):
                continue
            country = _normalize_country(item.get("country"))
            if not country:
                continue
            score_percent = _safe_float(item.get("score_percent"))
            if score_percent is None:
                continue
            low_reachability = _clip01((100.0 - score_percent) / 100.0)
            record = touch(country)
            record["low_reachability"] = max(record["low_reachability"], low_reachability)
            if score_percent <= 20.0:
                record["hard_silence"] = max(record["hard_silence"], 1.0)

    ipv6 = payloads.get("ipv6-locked-states", {})
    countries = ipv6.get("countries")
    if isinstance(countries, list):
        for item in countries:
            if not isinstance(item, dict):
                continue
            country = _normalize_country(item.get("country"))
            if not country:
                continue
            rate = _safe_float(item.get("ipv6_capable_rate"))
            if rate is not None:
                record = touch(country)
                record["ipv6_absence"] = max(record["ipv6_absence"], _clip01(1.0 - rate))

    iran = payloads.get("iran-dns-behavior", {})
    summary = iran.get("summary")
    if isinstance(summary, dict):
        answered = _safe_float(summary.get("answered"))
        total_queries = _safe_float(summary.get("total_queries"))
        if answered is not None and total_queries and total_queries > 0:
            failure_ratio = _clip01((total_queries - answered) / total_queries)
            record = touch("IR")
            record["dns_anomaly"] = max(record["dns_anomaly"], failure_ratio)

    cuba = payloads.get("cuba-internet-weather", {})
    weather_summary = cuba.get("weather_summary")
    if isinstance(weather_summary, dict):
        classification = weather_summary.get("classification")
        if isinstance(classification, str):
            normalized = classification.strip().lower()
            record = touch("CU")
            if normalized in {"offline", "blackout"}:
                record["hard_silence"] = max(record["hard_silence"], 1.0)
            elif normalized in {"degraded", "intermittent"}:
                record["low_reachability"] = max(record["low_reachability"], 0.65)
                record["dns_anomaly"] = max(record["dns_anomaly"], 0.35)

    return {country: CountrySignals(**values) for country, values in by_country.items()}


def _weighted_score(signals: CountrySignals, weights: Dict[str, float]) -> float:
    total_weight = sum(max(0.0, weights.get(key, 0.0)) for key in CountrySignals.__annotations__)
    if total_weight <= 0:
        return 0.0

    weighted_sum = (
        signals.hard_silence * max(0.0, weights.get("hard_silence", 0.0))
        + signals.low_reachability * max(0.0, weights.get("low_reachability", 0.0))
        + signals.dns_anomaly * max(0.0, weights.get("dns_anomaly", 0.0))
        + signals.time_to_silence * max(0.0, weights.get("time_to_silence", 0.0))
        + signals.ipv6_absence * max(0.0, weights.get("ipv6_absence", 0.0))
    )
    return round(_clip01(weighted_sum / total_weight), 4)


def _load_history_scores(date_str: str, lookback_days: int = 30) -> Tuple[Dict[str, List[float]], Dict[str, str], Dict[str, Set[str]]]:
    history_scores: Dict[str, List[float]] = {}
    prev_scores: Dict[str, str] = {}
    prev_top: Dict[str, Set[str]] = {}

    for idx, day in enumerate(_iter_last_n_dates(date_str, lookback_days)):
        payload = _load_json(DAILY_ROOT / day / f"{OBSERVER_NAME}.json")
        if not payload:
            continue

        top_list = payload.get("top_silent_countries")
        if isinstance(top_list, list):
            prev_top[day] = {
                c.get("country")
                for c in top_list
                if isinstance(c, dict) and isinstance(c.get("country"), str)
            }
            for entry in top_list:
                if not isinstance(entry, dict):
                    continue
                country = _normalize_country(entry.get("country"))
                score = _safe_float(entry.get("silence_score"))
                if country and score is not None:
                    history_scores.setdefault(country, []).append(score)
                    if idx == 0:
                        value = entry.get("classification")
                        prev_scores[country] = value if isinstance(value, str) else "normal"

    return history_scores, prev_scores, prev_top


def _classify_country(
    score: float,
    previous_score: float,
    recent_scores: List[float],
    thresholds: Dict[str, Any],
) -> str:
    silent_threshold = float(thresholds.get("silent", 0.7))
    degrading_threshold = float(thresholds.get("degrading", 0.35))
    persistent_threshold = float(thresholds.get("persistently_silent", silent_threshold))
    persistent_days = int(thresholds.get("persistent_days", 3))
    recovering_delta = float(thresholds.get("recovering_delta", -0.1))
    anomaly_jump = float(thresholds.get("anomaly_jump", 0.35))

    delta = score - previous_score
    if abs(delta) >= anomaly_jump:
        return "anomalous"

    run = [score] + recent_scores[: max(0, persistent_days - 1)]
    if len(run) >= persistent_days and all(item >= persistent_threshold for item in run[:persistent_days]):
        return "persistently_silent"

    if score >= silent_threshold:
        return "silent"

    if delta <= recovering_delta and previous_score >= degrading_threshold:
        return "recovering"

    if score >= degrading_threshold:
        return "degrading"

    return "normal"


def _build_baselines(history_scores: Dict[str, List[float]]) -> Dict[str, Dict[str, float]]:
    baselines: Dict[str, Dict[str, float]] = {}
    for country, values in history_scores.items():
        if not values:
            continue
        baseline_mean = mean(values)
        baseline_std = pstdev(values) if len(values) > 1 else 0.0
        baselines[country] = {
            "mean": round(baseline_mean, 4),
            "std": round(baseline_std, 4),
        }
    return baselines


def _z_score(score: float, baseline: Optional[Dict[str, float]]) -> float:
    if not baseline:
        return 0.0
    std = baseline.get("std", 0.0)
    if std <= 0:
        return 0.0
    return (score - baseline.get("mean", 0.0)) / std


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack("!I", len(data)) + chunk_type + data + struct.pack("!I", crc)


def _write_minimal_png(path: Path, width: int, height: int, rows: List[bytes]) -> None:
    raw = b"".join(b"\x00" + row for row in rows)
    compressed = zlib.compress(raw, level=9)

    ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", ihdr)
    png += _png_chunk(b"IDAT", compressed)
    png += _png_chunk(b"IEND", b"")
    path.write_bytes(png)


def _render_significant_chart(top_countries: List[Dict[str, Any]], changed_entries: Set[str]) -> None:
    width = 1000
    row_height = 36
    rows_count = max(8, min(12, len(top_countries)))
    height = 120 + rows_count * row_height

    bg = (20, 24, 31)
    bar = (76, 153, 255)
    changed = (255, 170, 76)

    rows = [bytearray(bg * width) for _ in range(height)]

    for idx, entry in enumerate(top_countries[:rows_count]):
        score = _clip01(float(entry.get("silence_score", 0.0)))
        country = str(entry.get("country", "?"))
        y0 = 80 + idx * row_height
        y1 = min(height - 1, y0 + 22)
        x0 = 120
        x1 = min(width - 30, x0 + int(760 * score))
        color = changed if country in changed_entries else bar

        for y in range(y0, y1):
            row = rows[y]
            for x in range(x0, x1):
                pos = x * 3
                row[pos] = color[0]
                row[pos + 1] = color[1]
                row[pos + 2] = color[2]

    LATEST_ROOT.mkdir(parents=True, exist_ok=True)
    _write_minimal_png(CHART_PATH, width, height, [bytes(row) for row in rows])


def run() -> Dict[str, Any]:
    """Run the correlation observer and return structured output."""

    date_str = _coerce_date()
    config = _load_config()
    observers = config.get("source_observers", [])
    weights = config.get("weights", {})
    thresholds = config.get("thresholds", {})
    top_n = int(config.get("top_n", 10))
    sigma_mult = float(thresholds.get("sigma_threshold", 2.0))
    mass_k = int(thresholds.get("mass_event_class_changes", 3))

    if not isinstance(observers, list):
        observers = []

    payloads, missing = _load_observer_payloads(date_str, [o for o in observers if isinstance(o, str)])
    signals = _collect_signals(payloads)

    history_scores, previous_classifications, prev_top_by_day = _load_history_scores(date_str, lookback_days=30)
    prev_day = _iter_last_n_dates(date_str, 1)[0]
    prev_day_top = prev_top_by_day.get(prev_day, set())

    baselines = _build_baselines(history_scores)

    current_rows: List[Dict[str, Any]] = []
    changed_entries: Set[str] = set()
    triggers: List[str] = []
    class_changes = 0

    for country, country_signals in signals.items():
        score = _weighted_score(country_signals, weights)
        previous_scores = history_scores.get(country, [])
        previous_score = previous_scores[0] if previous_scores else score
        delta_score = round(score - previous_score, 4)

        classification = _classify_country(score, previous_score, previous_scores, thresholds)
        previous_class = previous_classifications.get(country, "normal")
        if previous_class != classification:
            class_changes += 1
            changed_entries.add(country)

        baseline = baselines.get(country)
        z = _z_score(score, baseline)
        if z > sigma_mult:
            triggers.append(f"{country} z-score {z:.2f} > {sigma_mult:.2f}")

        if classification in {"silent", "persistently_silent"} and previous_class not in {
            "silent",
            "persistently_silent",
        }:
            triggers.append(f"{country} transitioned into {classification}")

        current_rows.append(
            {
                "country": country,
                "silence_score": score,
                "classification": classification,
                "delta_score": delta_score,
            }
        )

    current_rows.sort(key=lambda item: item["silence_score"], reverse=True)
    top_rows = current_rows[: max(1, top_n)]

    top_countries = {item["country"] for item in top_rows}
    new_in_top = sorted(top_countries - prev_day_top)
    if new_in_top:
        changed_entries.update(new_in_top)
        triggers.append("new top-N entries: " + ", ".join(new_in_top))

    if class_changes > mass_k:
        triggers.append(f"mass event: {class_changes} countries changed class (> {mass_k})")

    any_significant = len(triggers) > 0

    data_status = "ok"
    if not payloads:
        data_status = "unavailable"
    elif missing:
        data_status = "partial"

    silent_count = sum(1 for row in current_rows if row["classification"] == "silent")
    persistently_silent_count = sum(
        1 for row in current_rows if row["classification"] == "persistently_silent"
    )

    output = {
        "observer": OBSERVER_NAME,
        "date_utc": date_str,
        "data_status": data_status,
        "top_silent_countries": top_rows,
        "summary_stats": {
            "countries_evaluated": len(current_rows),
            "silent_count": silent_count,
            "persistently_silent_count": persistently_silent_count,
        },
        "baseline_30d": baselines,
        "significance": {
            "sigma_mult": sigma_mult,
            "any_significant": any_significant,
            "triggers": triggers,
        },
    }

    DAILY_ROOT.joinpath(date_str).mkdir(parents=True, exist_ok=True)
    daily_path = DAILY_ROOT / date_str / f"{OBSERVER_NAME}.json"
    daily_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if any_significant:
        _render_significant_chart(top_rows, changed_entries)

    latest_date = date_str
    all_dates = sorted([path.name for path in DAILY_ROOT.iterdir() if path.is_dir() and path.name >= "2000-01-01"])
    if all_dates:
        latest_date = all_dates[-1]

    last_7_days: List[Dict[str, Any]] = []
    latest_date_obj = datetime.strptime(latest_date, "%Y-%m-%d").date()
    for offset in range(6, -1, -1):
        day = (latest_date_obj - timedelta(days=offset)).isoformat()
        payload = _load_json(DAILY_ROOT / day / f"{OBSERVER_NAME}.json")
        if not payload:
            continue
        sig = payload.get("significance", {}) if isinstance(payload.get("significance"), dict) else {}
        stats = payload.get("summary_stats", {}) if isinstance(payload.get("summary_stats"), dict) else {}
        last_7_days.append(
            {
                "date_utc": day,
                "countries_evaluated": int(stats.get("countries_evaluated", 0)),
                "silent_count": int(stats.get("silent_count", 0)),
                "persistently_silent_count": int(stats.get("persistently_silent_count", 0)),
                "any_significant": bool(sig.get("any_significant", False)),
            }
        )

    latest_summary: Dict[str, Any] = {
        "observer": OBSERVER_NAME,
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
        "latest_date_utc": latest_date,
        "last_7_days": last_7_days,
    }
    if CHART_PATH.exists():
        latest_summary["chart_path"] = "data/latest/chart.png"

    LATEST_ROOT.mkdir(parents=True, exist_ok=True)
    LATEST_SUMMARY_PATH.write_text(
        json.dumps(latest_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return output


def main() -> None:
    """Serialize the observation to stdout."""

    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
