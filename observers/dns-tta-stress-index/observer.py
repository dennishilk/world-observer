"""Aggregated DNS time-to-answer stress observer."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any, Dict, List, Optional

import socket
import struct
import zlib

OBSERVER = "dns-tta-stress-index"
MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
CONFIG_PATH = MODULE_DIR / "config.json"
DAILY_ROOT = REPO_ROOT / "data" / "daily"
LATEST_DIR = REPO_ROOT / "data" / "latest"
LATEST_SUMMARY_PATH = LATEST_DIR / "summary.json"
LATEST_CHART_PATH = LATEST_DIR / "chart.png"
RAW_LOCAL_DIR = REPO_ROOT / "state" / "dns-tta-stress-index"


@dataclass
class Config:
    countries: List[str]
    domains: List[str]
    query_types: List[str]
    timeout_s: float
    trials_per_domain: int
    baseline_days: int
    sigma_mult: float
    mass_event_k: int
    hard_timeout_rate: float
    weights: Dict[str, float]
    tta_normalizer_ms: float
    jitter_normalizer_ms: float
    trend_days: int
    top_countries_in_chart: int


def _date_utc() -> str:
    env_value = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if env_value:
        try:
            return datetime.strptime(env_value, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def _load_json(path: Path, default: Any) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return payload


def _load_config() -> Config:
    payload = _load_json(CONFIG_PATH, {})
    if not isinstance(payload, dict):
        payload = {}

    weights = payload.get("weights", {}) if isinstance(payload.get("weights"), dict) else {}
    normalizers = payload.get("normalizers", {}) if isinstance(payload.get("normalizers"), dict) else {}

    return Config(
        countries=[str(c).upper() for c in payload.get("countries", ["US", "DE", "IN", "BR", "JP"])],
        domains=[str(d) for d in payload.get("domains", ["example.com", "iana.org"])],
        query_types=[str(q).upper() for q in payload.get("query_types", ["A", "AAAA"])],
        timeout_s=max(0.5, float(payload.get("timeout_s", 2.0))),
        trials_per_domain=max(1, int(payload.get("trials_per_domain", 2))),
        baseline_days=max(7, int(payload.get("baseline_days", 30))),
        sigma_mult=max(0.5, float(payload.get("sigma_mult", 2.0))),
        mass_event_k=max(1, int(payload.get("mass_event_k", 5))),
        hard_timeout_rate=min(1.0, max(0.0, float(payload.get("hard_timeout_rate", 0.35)))),
        weights={
            "tta_p95": max(0.0, float(weights.get("tta_p95", 0.35))),
            "timeout_rate": max(0.0, float(weights.get("timeout_rate", 0.3))),
            "success_rate": max(0.0, float(weights.get("success_rate", 0.2))),
            "jitter": max(0.0, float(weights.get("jitter", 0.15))),
        },
        tta_normalizer_ms=max(1.0, float(normalizers.get("tta_p95_ms", 600.0))),
        jitter_normalizer_ms=max(1.0, float(normalizers.get("jitter_ms", 150.0))),
        trend_days=max(3, int(payload.get("trend_days", 7))),
        top_countries_in_chart=max(3, int(payload.get("top_countries_in_chart", 6))),
    )


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = (len(ordered) - 1) * pct
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return ordered[lower]
    weight = idx - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _stddev(values: List[float]) -> float:
    if not values:
        return 0.0
    avg = sum(values) / len(values)
    variance = sum((v - avg) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _query_once(domain: str, record_type: str, timeout_s: float) -> Dict[str, Any]:
    started = perf_counter()
    family = socket.AF_INET6 if record_type == "AAAA" else socket.AF_INET
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_s)
    try:
        answers = socket.getaddrinfo(domain, None, family=family, type=socket.SOCK_STREAM)
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        if not answers:
            return {"status": "no_answer", "ms": elapsed_ms}
        return {"status": "success", "ms": elapsed_ms}
    except socket.timeout:
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        return {"status": "timeout", "ms": elapsed_ms}
    except socket.gaierror:
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        return {"status": "error", "ms": elapsed_ms}
    finally:
        socket.setdefaulttimeout(old_timeout)


def _probe_country(country: str, config: Config) -> Dict[str, Any]:
    total = 0
    timeouts = 0
    successes = 0
    successful_ms: List[float] = []
    local_raw: List[Dict[str, Any]] = []

    for domain in config.domains:
        for query_type in config.query_types:
            for _ in range(config.trials_per_domain):
                result = _query_once(domain, query_type, config.timeout_s)
                total += 1
                status = result["status"]
                if status == "timeout":
                    timeouts += 1
                if status == "success":
                    successes += 1
                    successful_ms.append(float(result["ms"]))
                local_raw.append({"domain": domain, "type": query_type, "status": status, "ms": result["ms"]})

    expected = len(config.domains) * len(config.query_types) * config.trials_per_domain
    data_completeness = min(1.0, total / expected) if expected else 0.0
    timeout_rate = (timeouts / total) if total else 0.0
    success_rate = (successes / total) if total else 0.0
    tta_mean_ms = mean(successful_ms) if successful_ms else 0.0
    tta_p95_ms = _percentile(successful_ms, 0.95) if successful_ms else 0.0
    jitter_ms = _stddev(successful_ms) if successful_ms else 0.0

    return {
        "country": country,
        "tta_mean_ms": round(tta_mean_ms, 2),
        "tta_p95_ms": round(tta_p95_ms, 2),
        "timeout_rate": round(timeout_rate, 6),
        "success_rate": round(success_rate, 6),
        "jitter_ms": round(jitter_ms, 2),
        "probe_count": total,
        "data_completeness": round(data_completeness, 6),
        "_local_raw": local_raw,
    }


def _stress_score(metrics: Dict[str, Any], baseline_mean: Optional[float], config: Config) -> float:
    weights = config.weights
    weight_total = sum(weights.values())
    if weight_total <= 0:
        return 0.0

    tta_component = min(1.0, float(metrics["tta_p95_ms"]) / config.tta_normalizer_ms)
    timeout_component = min(1.0, float(metrics["timeout_rate"]))
    success_component = min(1.0, max(0.0, 1.0 - float(metrics["success_rate"])))
    jitter_component = min(1.0, float(metrics["jitter_ms"]) / config.jitter_normalizer_ms)

    raw_score = (
        weights["tta_p95"] * tta_component
        + weights["timeout_rate"] * timeout_component
        + weights["success_rate"] * success_component
        + weights["jitter"] * jitter_component
    ) / weight_total

    completeness = float(metrics.get("data_completeness", 0.0))
    score = raw_score * (0.25 + 0.75 * completeness)

    if baseline_mean is not None and completeness < 0.5:
        score = min(score, baseline_mean + 0.1)

    return round(max(0.0, min(1.0, score)), 6)


def _daily_files_up_to(date_str: str) -> List[Path]:
    if not DAILY_ROOT.exists():
        return []
    files: List[Path] = []
    for day_dir in DAILY_ROOT.iterdir():
        if not day_dir.is_dir() or day_dir.name > date_str:
            continue
        candidate = day_dir / f"{OBSERVER}.json"
        if candidate.exists():
            files.append(candidate)
    return sorted(files, key=lambda p: p.parent.name)


def _country_score_history(date_str: str, country: str, config: Config) -> List[float]:
    history: List[float] = []
    for path in _daily_files_up_to(date_str):
        payload = _load_json(path, {})
        if not isinstance(payload, dict) or payload.get("date_utc") == date_str:
            continue
        for row in payload.get("countries", []):
            if not isinstance(row, dict):
                continue
            if str(row.get("country", "")).upper() != country:
                continue
            score = row.get("dns_stress_score")
            if isinstance(score, (int, float)):
                history.append(float(score))
    if len(history) > config.baseline_days:
        history = history[-config.baseline_days :]
    return history


def _baseline_stats(scores: List[float]) -> Dict[str, float]:
    if not scores:
        return {"mean": 0.0, "std": 0.0}
    avg = sum(scores) / len(scores)
    return {"mean": round(avg, 6), "std": round(_stddev(scores), 6)}


def _last_7_summary(date_str: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in _daily_files_up_to(date_str)[-7:]:
        payload = _load_json(path, {})
        if not isinstance(payload, dict):
            continue
        summary_stats = payload.get("summary_stats", {})
        rows.append(
            {
                "date_utc": payload.get("date_utc", path.parent.name),
                "significant_count": int(summary_stats.get("significant_count", 0) or 0),
                "mass_event": bool(summary_stats.get("mass_event", False)),
            }
        )
    return rows


def _save_local_raw(date_str: str, country_rows: List[Dict[str, Any]]) -> None:
    RAW_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "observer": OBSERVER,
        "date_utc": date_str,
        "raw": [
            {"country": row["country"], "samples": row.get("_local_raw", [])}
            for row in country_rows
        ],
    }
    (RAW_LOCAL_DIR / f"{date_str}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _encode_png_rgb(width: int, height: int, pixels: List[List[tuple[int, int, int]]], metadata: Dict[str, str]) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))

    text_chunks = []
    for key, value in metadata.items():
        text_chunks.append(_png_chunk(b"tEXt", key.encode("latin1", errors="ignore") + b"\x00" + value.encode("latin1", errors="ignore")))

    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            r, g, b = pixels[y][x]
            raw.extend((r, g, b))
    idat = _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
    iend = _png_chunk(b"IEND", b"")
    return signature + ihdr + b"".join(text_chunks) + idat + iend


def _render_chart(
    date_str: str,
    triggers: List[str],
    countries: List[Dict[str, Any]],
    recent_rows: List[Dict[str, Any]],
    config: Config,
) -> None:
    width, height = 900, 420
    bg = (245, 248, 252)
    pixels = [[bg for _ in range(width)] for _ in range(height)]

    top = sorted(countries, key=lambda item: float(item.get("dns_stress_score", 0.0)), reverse=True)[: config.top_countries_in_chart]
    bar_left = 40
    bar_top = 50
    bar_height = 32
    bar_gap = 14
    max_bar_w = 500

    for idx, row in enumerate(top):
        score = float(row.get("dns_stress_score", 0.0))
        timeout_rate = float(row.get("timeout_rate", 0.0))
        y0 = bar_top + idx * (bar_height + bar_gap)
        y1 = min(height - 1, y0 + bar_height)
        bar_w = int(max_bar_w * max(0.02, min(1.0, score)))
        color = (
            min(255, int(120 + 120 * score + 10 * timeout_rate)),
            max(20, int(180 - 120 * score)),
            max(20, int(210 - 150 * score)),
        )
        for y in range(y0, y1):
            for x in range(bar_left, min(width - 1, bar_left + bar_w)):
                pixels[y][x] = color

    trend_base_y = 340
    trend_left = 40
    trend_w = 700
    rows = recent_rows[-config.trend_days :]
    max_sig = max([int(r.get("significant_count", 0)) for r in rows] + [1])
    if rows:
        step = max(1, trend_w // max(1, len(rows) - 1))
        points: List[tuple[int, int]] = []
        for idx, row in enumerate(rows):
            sig = int(row.get("significant_count", 0))
            x = trend_left + idx * step
            y = trend_base_y - int((sig / max_sig) * 90)
            points.append((x, y))
        for x, y in points:
            for yy in range(max(0, y - 2), min(height, y + 3)):
                for xx in range(max(0, x - 2), min(width, x + 3)):
                    pixels[yy][xx] = (30, 60, 140)

    metadata = {
        "Title": f"DNS TTA Stress Alert {date_str}",
        "Observer": OBSERVER,
        "Triggers": " | ".join(triggers) if triggers else "n/a",
        "TopCountries": "; ".join(
            f"{row['country']}:score={row['dns_stress_score']:.3f},z={row['z']:.2f}" for row in top
        ),
        "RecentTrend": "; ".join(
            f"{row['date_utc']}:sig={row['significant_count']},mass={row['mass_event']}" for row in rows
        ),
    }

    png = _encode_png_rgb(width, height, pixels, metadata)
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_CHART_PATH.write_bytes(png)


def _write_latest_summary(date_str: str, any_significant: bool, last_7_days: List[Dict[str, Any]]) -> None:
    summary: Dict[str, Any] = {
        "observer": OBSERVER,
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
        "latest_date_utc": date_str,
        "last_7_days": last_7_days,
    }
    if any_significant and LATEST_CHART_PATH.exists():
        summary["chart_path"] = "data/latest/chart.png"

    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


def run() -> Dict[str, Any]:
    config = _load_config()
    date_str = _date_utc()

    countries: List[Dict[str, Any]] = []
    for country in config.countries:
        countries.append(_probe_country(country, config))

    _save_local_raw(date_str, countries)

    triggers: List[str] = []
    significant_count = 0

    for row in countries:
        history = _country_score_history(date_str, row["country"], config)
        baseline_pre = _baseline_stats(history)
        baseline_mean = baseline_pre["mean"] if history else None
        score = _stress_score(row, baseline_mean, config)
        row["dns_stress_score"] = score

        history_with_today = history + [score]
        baseline = _baseline_stats(history)
        std = baseline["std"]
        z = (score - baseline["mean"]) / std if std > 0 else 0.0
        row["baseline_30d"] = {"mean": baseline["mean"], "std": baseline["std"]}
        row["z"] = round(z, 6)

        sig_z = z > config.sigma_mult and len(history) >= 5
        sig_timeout = float(row["timeout_rate"]) > config.hard_timeout_rate
        is_significant = bool(sig_z or sig_timeout)
        row["is_significant"] = is_significant

        if sig_z:
            triggers.append(f"z>{config.sigma_mult} ({row['country']}={row['z']:.2f})")
        if sig_timeout:
            triggers.append(
                f"timeout_rate>{config.hard_timeout_rate:.2f} ({row['country']}={row['timeout_rate']:.2f})"
            )
        if is_significant:
            significant_count += 1

        row.pop("_local_raw", None)

    mass_event = significant_count >= config.mass_event_k
    if mass_event:
        triggers.append(f"mass_event>= {config.mass_event_k}")

    any_significant = significant_count > 0 or mass_event
    force_flag = os.environ.get("WORLD_OBSERVER_DNS_STRESS_FORCE_SIGNIFICANT", "").strip()
    if force_flag == "1":
        any_significant = True
        if not triggers:
            triggers.append("forced_for_testing")

    if any_significant:
        _render_chart(date_str, triggers, countries, _last_7_summary(date_str), config)
    elif LATEST_CHART_PATH.exists():
        LATEST_CHART_PATH.unlink()

    countries_evaluated = len(countries)
    statuses = [float(row.get("data_completeness", 0.0)) for row in countries]
    if not statuses or max(statuses) == 0.0:
        data_status = "unavailable"
    elif min(statuses) < 1.0:
        data_status = "partial"
    else:
        data_status = "ok"

    output = {
        "observer": OBSERVER,
        "date_utc": date_str,
        "data_status": data_status,
        "countries": [
            {
                "country": row["country"],
                "tta_mean_ms": row["tta_mean_ms"],
                "tta_p95_ms": row["tta_p95_ms"],
                "timeout_rate": row["timeout_rate"],
                "success_rate": row["success_rate"],
                "jitter_ms": row["jitter_ms"],
                "probe_count": row["probe_count"],
                "dns_stress_score": row["dns_stress_score"],
                "baseline_30d": row["baseline_30d"],
                "z": row["z"],
                "is_significant": row["is_significant"],
            }
            for row in countries
        ],
        "summary_stats": {
            "countries_evaluated": countries_evaluated,
            "significant_count": significant_count,
            "mass_event": mass_event,
        },
        "significance": {
            "sigma_mult": config.sigma_mult,
            "any_significant": any_significant,
            "triggers": sorted(set(triggers)),
        },
    }

    day_dir = DAILY_ROOT / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / f"{OBSERVER}.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")

    last_7 = _last_7_summary(date_str)
    if not any(item["date_utc"] == date_str for item in last_7):
        last_7.append(
            {
                "date_utc": date_str,
                "significant_count": significant_count,
                "mass_event": mass_event,
            }
        )
    last_7 = sorted(last_7, key=lambda item: item["date_utc"])[-7:]
    _write_latest_summary(date_str, any_significant, last_7)

    return output


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
