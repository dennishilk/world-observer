"""Aggregated TLS fingerprint-change observer with privacy-preserving outputs."""

from __future__ import annotations

import json
import math
import os
import socket
import ssl
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

OBSERVER = "tls-fingerprint-change"
MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
CONFIG_PATH = MODULE_DIR / "config.json"
DAILY_ROOT = REPO_ROOT / "data" / "daily"
LATEST_DIR = REPO_ROOT / "data" / "latest"
LATEST_SUMMARY_PATH = LATEST_DIR / "summary.json"
LATEST_CHART_PATH = LATEST_DIR / "chart.png"
RAW_LOCAL_DIR = REPO_ROOT / "state" / "tls-fingerprint-change"


@dataclass
class Config:
    countries: List[str]
    neutral_targets: List[str]
    probes_per_country: int
    connect_timeout_s: float
    baseline_days: int
    sigma_mult: float
    mass_event_k: int
    major_version_shift_threshold: float
    top_countries_in_chart: int
    min_history_days_for_z: int
    weights: Dict[str, float]


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

    return Config(
        countries=[str(c).upper() for c in payload.get("countries", ["US", "DE", "IN", "BR", "JP"])],
        neutral_targets=[str(t) for t in payload.get("neutral_targets", ["example.com", "iana.org"])],
        probes_per_country=max(1, int(payload.get("probes_per_country", 4))),
        connect_timeout_s=max(0.5, float(payload.get("connect_timeout_s", 4.0))),
        baseline_days=max(7, int(payload.get("baseline_days", 30))),
        sigma_mult=max(0.5, float(payload.get("sigma_mult", 2.0))),
        mass_event_k=max(1, int(payload.get("mass_event_k", 5))),
        major_version_shift_threshold=min(
            1.0, max(0.05, float(payload.get("major_version_shift_threshold", 0.35)))
        ),
        top_countries_in_chart=max(3, int(payload.get("top_countries_in_chart", 6))),
        min_history_days_for_z=max(3, int(payload.get("min_history_days_for_z", 7))),
        weights={
            "version_delta": max(0.0, float(weights.get("version_delta", 0.4))),
            "cipher_delta": max(0.0, float(weights.get("cipher_delta", 0.25))),
            "abort_delta": max(0.0, float(weights.get("abort_delta", 0.2))),
            "alpn_delta": max(0.0, float(weights.get("alpn_delta", 0.15))),
        },
    )


def _tls_version_label(version_name: str) -> str:
    name = version_name.upper().replace(" ", "")
    if "1.3" in name:
        return "TLS1.3"
    if "1.2" in name:
        return "TLS1.2"
    if "1.1" in name:
        return "TLS1.1"
    if "1.0" in name:
        return "TLS1.0"
    return "OTHER"


def _cipher_class(cipher_name: str) -> str:
    name = cipher_name.upper()
    if "CHACHA20" in name:
        return "CHACHA20"
    if "AES_128" in name:
        return "AES_128"
    if "AES_256" in name:
        return "AES_256"
    if "AES" in name:
        return "AES_OTHER"
    return "OTHER"


def _empty_version_dist() -> Dict[str, float]:
    return {"TLS1.0": 0.0, "TLS1.1": 0.0, "TLS1.2": 0.0, "TLS1.3": 0.0, "OTHER": 0.0}


def _normalize_counts(counts: Dict[str, int], keys: List[str], denominator: int) -> Dict[str, float]:
    if denominator <= 0:
        return {k: 0.0 for k in keys}
    return {k: round(max(0.0, counts.get(k, 0) / denominator), 6) for k in keys}


def _probe_target(host: str, timeout_s: float) -> Dict[str, Any]:
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    try:
        with socket.create_connection((host, 443), timeout=timeout_s) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls_sock:
                version_label = _tls_version_label(tls_sock.version() or "")
                cipher_info = tls_sock.cipher() or ("", "", 0)
                cipher_label = _cipher_class(str(cipher_info[0]))
                alpn_present = tls_sock.selected_alpn_protocol() is not None
                return {
                    "success": True,
                    "abort": False,
                    "tls_version": version_label,
                    "cipher_class": cipher_label,
                    "alpn_present": alpn_present,
                    "error_type": None,
                }
    except (socket.timeout, TimeoutError):
        return {
            "success": False,
            "abort": True,
            "tls_version": None,
            "cipher_class": None,
            "alpn_present": False,
            "error_type": "timeout",
        }
    except (ssl.SSLError, OSError, ValueError):
        return {
            "success": False,
            "abort": True,
            "tls_version": None,
            "cipher_class": None,
            "alpn_present": False,
            "error_type": "tls_or_network",
        }


def _l1_delta(current: Dict[str, float], baseline: Dict[str, float], keys: List[str]) -> float:
    return 0.5 * sum(abs(float(current.get(k, 0.0)) - float(baseline.get(k, 0.0))) for k in keys)


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


def _country_history(date_str: str, country: str, config: Config) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in _daily_files_up_to(date_str):
        payload = _load_json(path, {})
        if not isinstance(payload, dict) or payload.get("date_utc") == date_str:
            continue
        for item in payload.get("countries", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("country", "")).upper() != country:
                continue
            rows.append(item)
    if len(rows) > config.baseline_days:
        rows = rows[-config.baseline_days :]
    return rows


def _mean(values: List[float]) -> float:
    return (sum(values) / len(values)) if values else 0.0


def _stddev(values: List[float]) -> float:
    if not values:
        return 0.0
    avg = _mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def _baseline_from_history(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    version_keys = list(_empty_version_dist().keys())
    cipher_keys = ["CHACHA20", "AES_128", "AES_256", "AES_OTHER", "OTHER"]

    if not history:
        return {
            "score_mean": 0.0,
            "score_std": 0.0,
            "version_dist": {k: 0.0 for k in version_keys},
            "cipher_dist": {k: 0.0 for k in cipher_keys},
            "abort_rate": 0.0,
            "alpn_rate": 0.0,
        }

    score_values = [float(row.get("tls_change_score", 0.0)) for row in history if isinstance(row.get("tls_change_score"), (int, float))]
    score_mean = _mean(score_values)
    score_std = _stddev(score_values)

    version_dist = {
        key: round(_mean([float(row.get("tls_version_distribution", {}).get(key, 0.0)) for row in history]), 6)
        for key in version_keys
    }
    cipher_dist = {
        key: round(_mean([float(row.get("cipher_class_distribution", {}).get(key, 0.0)) for row in history]), 6)
        for key in cipher_keys
    }

    abort_rate = round(_mean([float(row.get("handshake_abort_rate", 0.0)) for row in history]), 6)
    alpn_rate = round(_mean([float(row.get("alpn_presence_rate", 0.0)) for row in history]), 6)

    return {
        "score_mean": round(score_mean, 6),
        "score_std": round(score_std, 6),
        "version_dist": version_dist,
        "cipher_dist": cipher_dist,
        "abort_rate": abort_rate,
        "alpn_rate": alpn_rate,
    }


def _compute_change_score(row: Dict[str, Any], baseline: Dict[str, Any], config: Config) -> Tuple[float, Dict[str, float]]:
    weights = config.weights
    weight_total = sum(weights.values())
    if weight_total <= 0:
        return 0.0, {"version_delta": 0.0, "cipher_delta": 0.0, "abort_delta": 0.0, "alpn_delta": 0.0}

    version_keys = list(_empty_version_dist().keys())
    cipher_keys = ["CHACHA20", "AES_128", "AES_256", "AES_OTHER", "OTHER"]

    version_delta = min(
        1.0,
        _l1_delta(row.get("tls_version_distribution", {}), baseline.get("version_dist", {}), version_keys),
    )
    cipher_delta = min(
        1.0,
        _l1_delta(row.get("cipher_class_distribution", {}), baseline.get("cipher_dist", {}), cipher_keys),
    )
    abort_delta = min(
        1.0,
        max(0.0, float(row.get("handshake_abort_rate", 0.0)) - float(baseline.get("abort_rate", 0.0))),
    )
    alpn_delta = min(
        1.0,
        abs(float(row.get("alpn_presence_rate", 0.0)) - float(baseline.get("alpn_rate", 0.0))),
    )

    score = (
        weights["version_delta"] * version_delta
        + weights["cipher_delta"] * cipher_delta
        + weights["abort_delta"] * abort_delta
        + weights["alpn_delta"] * alpn_delta
    ) / weight_total

    return round(max(0.0, min(1.0, score)), 6), {
        "version_delta": round(version_delta, 6),
        "cipher_delta": round(cipher_delta, 6),
        "abort_delta": round(abort_delta, 6),
        "alpn_delta": round(alpn_delta, 6),
    }


def _probe_country(country: str, config: Config) -> Dict[str, Any]:
    total = 0
    success = 0
    abort = 0
    alpn_positive = 0
    version_counts = {k: 0 for k in _empty_version_dist().keys()}
    cipher_counts = {k: 0 for k in ["CHACHA20", "AES_128", "AES_256", "AES_OTHER", "OTHER"]}
    raw_events: List[Dict[str, str]] = []

    targets = config.neutral_targets[:]
    for probe_idx in range(config.probes_per_country):
        host = targets[probe_idx % len(targets)]
        event = _probe_target(host, config.connect_timeout_s)
        total += 1
        if event["success"]:
            success += 1
            version_counts[str(event["tls_version"])] += 1
            cipher_counts[str(event["cipher_class"])] += 1
            if event["alpn_present"]:
                alpn_positive += 1
        if event["abort"]:
            abort += 1

        raw_events.append(
            {
                "success": "1" if event["success"] else "0",
                "abort": "1" if event["abort"] else "0",
                "tls_version": str(event.get("tls_version") or "NONE"),
                "cipher_class": str(event.get("cipher_class") or "NONE"),
                "alpn": "1" if event.get("alpn_present", False) else "0",
                "error_type": str(event.get("error_type") or "none"),
            }
        )

    expected = config.probes_per_country
    data_completeness = min(1.0, total / expected) if expected else 0.0
    success_rate = (success / total) if total else 0.0
    abort_rate = (abort / total) if total else 0.0
    success_denominator = success if success > 0 else 1

    row = {
        "country": country,
        "tls_success_rate": round(success_rate, 6),
        "handshake_abort_rate": round(abort_rate, 6),
        "tls_version_distribution": _normalize_counts(version_counts, list(version_counts.keys()), success_denominator),
        "cipher_class_distribution": _normalize_counts(cipher_counts, list(cipher_counts.keys()), success_denominator),
        "alpn_presence_rate": round((alpn_positive / success_denominator), 6),
        "sample_size": total,
        "data_completeness": round(data_completeness, 6),
        "_raw_local": raw_events,
    }
    return row


def _save_raw_local(date_str: str, countries: List[Dict[str, Any]]) -> None:
    RAW_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "observer": OBSERVER,
        "date_utc": date_str,
        "countries": [
            {"country": row["country"], "events": row.get("_raw_local", [])}
            for row in countries
        ],
    }
    (RAW_LOCAL_DIR / f"{date_str}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _encode_png_rgb(width: int, height: int, pixels: List[List[tuple[int, int, int]]], metadata: Dict[str, str]) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))

    text_chunks = []
    for key, value in metadata.items():
        text_chunks.append(
            _png_chunk(
                b"tEXt",
                key.encode("latin1", errors="ignore") + b"\x00" + value.encode("latin1", errors="ignore"),
            )
        )

    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixels[y][x])

    idat = _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
    iend = _png_chunk(b"IEND", b"")
    return signature + ihdr + b"".join(text_chunks) + idat + iend


def _render_chart(date_str: str, countries: List[Dict[str, Any]], triggers: List[str], config: Config) -> None:
    width, height = 900, 440
    bg = (243, 247, 252)
    pixels = [[bg for _ in range(width)] for _ in range(height)]

    top_rows = sorted(countries, key=lambda row: float(row.get("tls_change_score", 0.0)), reverse=True)[: config.top_countries_in_chart]

    bar_left = 50
    bar_top = 45
    bar_height = 26
    bar_gap = 15
    max_width = 600

    for idx, row in enumerate(top_rows):
        score = float(row.get("tls_change_score", 0.0))
        before = float(row.get("baseline_30d", {}).get("mean", 0.0))
        y0 = bar_top + idx * (bar_height + bar_gap)
        y1 = min(height, y0 + bar_height)

        w_before = max(2, int(max_width * max(0.0, min(1.0, before))))
        w_after = max(2, int(max_width * max(0.0, min(1.0, score))))

        for y in range(y0, y1):
            for x in range(bar_left, min(width, bar_left + w_before)):
                pixels[y][x] = (100, 150, 210)
            for x in range(bar_left, min(width, bar_left + w_after)):
                pixels[y][x] = (220, 98, 82)

        version_shift = abs(
            float(row.get("tls_version_distribution", {}).get("TLS1.3", 0.0))
            - float(row.get("baseline_version_distribution", {}).get("TLS1.3", 0.0))
        )
        marker_x = bar_left + int(max_width * min(1.0, version_shift))
        for y in range(max(0, y0 - 2), min(height, y1 + 2)):
            if 0 <= marker_x < width:
                pixels[y][marker_x] = (40, 40, 40)

    metadata = {
        "Title": f"TLS Fingerprint Change Alert {date_str}",
        "Observer": OBSERVER,
        "TopCountries": "; ".join(
            f"{row['country']}:score={row['tls_change_score']:.3f},z={row['z']:.2f}" for row in top_rows
        ),
        "BeforeAfter": "; ".join(
            f"{row['country']}:before={row['baseline_30d']['mean']:.3f},after={row['tls_change_score']:.3f}" for row in top_rows
        ),
        "Triggers": " | ".join(triggers) if triggers else "n/a",
    }

    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_CHART_PATH.write_bytes(_encode_png_rgb(width, height, pixels, metadata))


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


def _write_latest_summary(date_str: str, any_significant: bool, last_7_days: List[Dict[str, Any]]) -> None:
    payload: Dict[str, Any] = {
        "observer": OBSERVER,
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
        "latest_date_utc": date_str,
        "last_7_days": last_7_days,
    }
    if any_significant and LATEST_CHART_PATH.exists():
        payload["chart_path"] = "data/latest/chart.png"

    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_SUMMARY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run() -> Dict[str, Any]:
    config = _load_config()
    date_str = _date_utc()

    countries: List[Dict[str, Any]] = [_probe_country(country, config) for country in config.countries]
    _save_raw_local(date_str, countries)

    significant_count = 0
    major_shift_count = 0
    triggers: List[str] = []

    for row in countries:
        history = _country_history(date_str, row["country"], config)
        baseline = _baseline_from_history(history)

        score, score_components = _compute_change_score(row, baseline, config)
        row["tls_change_score"] = score
        row["score_components"] = score_components
        row["baseline_version_distribution"] = baseline["version_dist"]
        row["baseline_cipher_distribution"] = baseline["cipher_dist"]

        score_std = float(baseline.get("score_std", 0.0))
        score_mean = float(baseline.get("score_mean", 0.0))
        z = (score - score_mean) / score_std if score_std > 0 else 0.0
        row["z"] = round(z, 6)
        row["baseline_30d"] = {"mean": round(score_mean, 6), "std": round(score_std, 6)}

        version_shift = abs(
            float(row["tls_version_distribution"].get("TLS1.3", 0.0))
            - float(baseline["version_dist"].get("TLS1.3", 0.0))
        )
        enough_history = len(history) >= config.min_history_days_for_z
        sig_z = enough_history and z > config.sigma_mult
        sig_version = enough_history and version_shift > config.major_version_shift_threshold
        sig_abort = enough_history and score_components["abort_delta"] > 0.25
        is_significant = bool(sig_z or sig_version or sig_abort)
        row["is_significant"] = is_significant

        if sig_z:
            triggers.append(f"z>{config.sigma_mult} ({row['country']}={row['z']:.2f})")
        if sig_version:
            triggers.append(
                f"major_version_shift>{config.major_version_shift_threshold:.2f} ({row['country']}={version_shift:.2f})"
            )
            major_shift_count += 1
        if sig_abort:
            triggers.append(f"abort_rate_increase ({row['country']}={score_components['abort_delta']:.2f})")

        if is_significant:
            significant_count += 1

        row.pop("_raw_local", None)

    mass_event = significant_count >= config.mass_event_k
    if mass_event:
        triggers.append(f"mass_event>={config.mass_event_k}")

    any_significant = significant_count > 0 or mass_event
    if os.environ.get("WORLD_OBSERVER_TLS_FORCE_SIGNIFICANT", "").strip() == "1":
        any_significant = True
        if not triggers:
            triggers.append("forced_for_testing")

    if any_significant:
        _render_chart(date_str, countries, sorted(set(triggers)), config)
    elif LATEST_CHART_PATH.exists():
        LATEST_CHART_PATH.unlink()

    completeness_values = [float(row.get("data_completeness", 0.0)) for row in countries]
    if not completeness_values or max(completeness_values) == 0.0:
        data_status = "unavailable"
    elif min(completeness_values) < 1.0:
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
                "tls_success_rate": row["tls_success_rate"],
                "handshake_abort_rate": row["handshake_abort_rate"],
                "tls_version_distribution": row["tls_version_distribution"],
                "cipher_class_distribution": row["cipher_class_distribution"],
                "alpn_presence_rate": row["alpn_presence_rate"],
                "sample_size": row["sample_size"],
                "data_completeness": row["data_completeness"],
                "tls_change_score": row["tls_change_score"],
                "baseline_30d": row["baseline_30d"],
                "z": row["z"],
                "is_significant": row["is_significant"],
            }
            for row in countries
        ],
        "summary_stats": {
            "countries_evaluated": len(countries),
            "significant_count": significant_count,
            "mass_event": mass_event,
        },
        "significance": {
            "sigma_mult": config.sigma_mult,
            "any_significant": any_significant,
            "triggers": sorted(set(triggers)),
            "method": (
                "tls_change_score = weighted(0.5*L1(version_dist_delta), 0.5*L1(cipher_dist_delta), "
                "positive_abort_rate_delta, abs(alpn_rate_delta)); each component clipped to [0,1]."
            ),
        },
    }

    day_dir = DAILY_ROOT / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / f"{OBSERVER}.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    last_7 = _last_7_summary(date_str)
    if not any(item["date_utc"] == date_str for item in last_7):
        last_7.append(
            {"date_utc": date_str, "significant_count": significant_count, "mass_event": mass_event}
        )
    last_7 = sorted(last_7, key=lambda item: item["date_utc"])[-7:]
    _write_latest_summary(date_str, any_significant, last_7)

    return output


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
