"""Stateful, aggregated connectivity observer for north-korea-connectivity."""

from __future__ import annotations

import json
import math
import os
import random
import socket
import ssl
import struct
import subprocess
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

OBSERVER = "north-korea-connectivity"
MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
TARGETS_PATH = MODULE_DIR / "targets.json"
CONFIG_PATH = MODULE_DIR / "config.json"
DAILY_ROOT = REPO_ROOT / "data" / "daily"
LATEST_DIR = REPO_ROOT / "data" / "latest"
LATEST_SUMMARY_PATH = LATEST_DIR / "summary.json"
LATEST_CHART_PATH = LATEST_DIR / "chart.png"

TCP_PORTS = (80, 443, 22)
LAYER_NAMES = ("dns", "tcp", "icmp", "tls")
RARE_STATE_TRANSITIONS = {
    "silent->partial",
    "silent->controlled",
    "silent->anomalous",
    "silent->open_ish",
    "dark->anomalous",
    "dark->open_ish",
    "controlled->anomalous",
    "controlled->open_ish",
}


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _date_utc() -> str:
    env_value = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if env_value:
        try:
            return datetime.strptime(env_value, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return _today_utc()
    return _today_utc()


def _load_json(path: Path, default: Any) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return payload


def _load_targets() -> List[str]:
    payload = _load_json(TARGETS_PATH, [])
    if not isinstance(payload, list):
        return []
    hosts: List[str] = []
    for item in payload:
        if isinstance(item, dict):
            host = item.get("host")
            if isinstance(host, str) and host.strip():
                hosts.append(host.strip())
    return hosts


def _load_config() -> Dict[str, Any]:
    payload = _load_json(CONFIG_PATH, {})
    if not isinstance(payload, dict):
        payload = {}
    baseline_days = int(payload.get("baseline_days", 30) or 30)
    sigma_mult = float(payload.get("sigma_mult", 2.0) or 2.0)
    timeout_s = float(payload.get("timeout_s", 2.0) or 2.0)
    tts_trials = int(payload.get("time_to_silence_trials", 5) or 5)
    tts_max_rounds = int(payload.get("time_to_silence_max_rounds", 6) or 6)
    return {
        "baseline_days": max(7, baseline_days),
        "sigma_mult": max(0.5, sigma_mult),
        "timeout_s": max(0.5, timeout_s),
        "time_to_silence_trials": max(1, tts_trials),
        "time_to_silence_max_rounds": max(1, tts_max_rounds),
    }


def _ping(host: str, timeout_s: float) -> bool:
    command = ["ping", "-c", "1", "-W", str(max(1, int(math.ceil(timeout_s)))), host]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except Exception:
        return False
    return result.returncode == 0


def _dns_probe(host: str, timeout_s: float) -> Tuple[bool, Optional[float]]:
    start = time.monotonic()
    try:
        socket.getaddrinfo(host, None)
    except Exception:
        return False, None
    elapsed_ms = (time.monotonic() - start) * 1000
    return True, round(elapsed_ms, 2)


def _tcp_probe(host: str, port: int, timeout_s: float) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        return sock.connect_ex((host, port)) == 0
    except Exception:
        return False
    finally:
        sock.close()


def _tls_probe(host: str, timeout_s: float) -> bool:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, 443), timeout=timeout_s) as raw_sock:
            raw_sock.settimeout(timeout_s)
            with context.wrap_socket(raw_sock, server_hostname=host):
                return True
    except Exception:
        return False


def _empty_layer(include_latency: bool = False) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "successes": 0,
        "probe_count": 0,
        "attempted": 0,
        "expected": 0,
    }
    if include_latency:
        payload["latencies"] = []
    return payload


def _probe_once(hosts: List[str], timeout_s: float) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, int]]:
    layers: Dict[str, Dict[str, Any]] = {
        "dns": _empty_layer(include_latency=True),
        "tcp": _empty_layer(),
        "icmp": _empty_layer(),
        "tls": _empty_layer(),
    }
    diagnostics = {"api_attempts": 0, "retries": 0, "http_status": None}

    for host in hosts:
        layers["dns"]["expected"] += 1
        layers["dns"]["attempted"] += 1
        diagnostics["api_attempts"] += 1
        dns_ok, dns_latency = _dns_probe(host, timeout_s)
        layers["dns"]["probe_count"] += 1
        if dns_ok:
            layers["dns"]["successes"] += 1
            if dns_latency is not None:
                layers["dns"]["latencies"].append(dns_latency)

        layers["icmp"]["expected"] += 1
        layers["icmp"]["attempted"] += 1
        diagnostics["api_attempts"] += 1
        icmp_ok = _ping(host, timeout_s)
        layers["icmp"]["probe_count"] += 1
        if icmp_ok:
            layers["icmp"]["successes"] += 1

        layers["tls"]["expected"] += 1
        layers["tls"]["attempted"] += 1
        diagnostics["api_attempts"] += 1
        tls_ok = _tls_probe(host, timeout_s)
        layers["tls"]["probe_count"] += 1
        if tls_ok:
            layers["tls"]["successes"] += 1

        for port in TCP_PORTS:
            layers["tcp"]["expected"] += 1
            layers["tcp"]["attempted"] += 1
            diagnostics["api_attempts"] += 1
            tcp_ok = _tcp_probe(host, port, timeout_s)
            layers["tcp"]["probe_count"] += 1
            if tcp_ok:
                layers["tcp"]["successes"] += 1

    return layers, diagnostics


def _merge_layer_totals(total: Dict[str, Dict[str, Any]], piece: Dict[str, Dict[str, Any]]) -> None:
    for layer_name in LAYER_NAMES:
        total[layer_name]["successes"] += piece[layer_name]["successes"]
        total[layer_name]["probe_count"] += piece[layer_name]["probe_count"]
        total[layer_name]["attempted"] += piece[layer_name]["attempted"]
        total[layer_name]["expected"] += piece[layer_name]["expected"]
        if layer_name == "dns":
            total[layer_name]["latencies"].extend(piece[layer_name]["latencies"])


def _finalize_layers(total: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    finalized: Dict[str, Dict[str, Any]] = {}
    for layer_name in LAYER_NAMES:
        payload = total[layer_name]
        probe_count = int(payload["probe_count"])
        success_rate = (float(payload["successes"]) / probe_count) if probe_count else 0.0
        completeness = (
            float(payload["attempted"]) / float(payload["expected"])
            if payload["expected"]
            else 0.0
        )
        layer_output: Dict[str, Any] = {
            "success_rate": round(success_rate, 4),
            "probe_count": probe_count,
            "data_completeness": round(completeness, 4),
        }
        if layer_name == "dns":
            latencies: List[float] = payload.get("latencies", [])
            mean_latency = (sum(latencies) / len(latencies)) if latencies else None
            layer_output["mean_latency_ms"] = round(mean_latency, 2) if mean_latency else None
        finalized[layer_name] = layer_output
    return finalized


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(math.ceil(0.95 * len(ordered))) - 1
    idx = min(max(idx, 0), len(ordered) - 1)
    return float(ordered[idx])


def _time_to_silence(hosts: List[str], timeout_s: float, trials: int, max_rounds: int) -> Dict[str, float]:
    if not hosts:
        return {"mean_seconds": 0.0, "p95_seconds": 0.0, "worst_seconds": 0.0}

    measurements: List[float] = []
    for _ in range(trials):
        shuffled = hosts[:]
        random.shuffle(shuffled)
        start = time.monotonic()
        elapsed = 0.0
        for _round in range(max_rounds):
            probe_round, _ = _probe_once(shuffled, timeout_s)
            any_success = any(probe_round[layer]["successes"] > 0 for layer in LAYER_NAMES)
            elapsed = time.monotonic() - start
            if not any_success:
                break
        measurements.append(round(elapsed, 3))

    mean_seconds = sum(measurements) / len(measurements)
    return {
        "mean_seconds": round(mean_seconds, 3),
        "p95_seconds": round(_p95(measurements), 3),
        "worst_seconds": round(max(measurements), 3),
    }


def _list_recent_daily_files(limit: int, up_to_date: str) -> List[Path]:
    if not DAILY_ROOT.exists():
        return []
    dirs = [
        path
        for path in DAILY_ROOT.iterdir()
        if path.is_dir() and path.name <= up_to_date and (path / f"{OBSERVER}.json").exists()
    ]
    dirs.sort(key=lambda p: p.name)
    return [(day / f"{OBSERVER}.json") for day in dirs[-limit:]]


def _metric_snapshot(payload: Dict[str, Any]) -> Dict[str, float]:
    layers = payload.get("layers", {}) if isinstance(payload, dict) else {}
    tts = payload.get("time_to_silence", {}) if isinstance(payload, dict) else {}
    return {
        "dns_success_rate": float(layers.get("dns", {}).get("success_rate", 0.0) or 0.0),
        "tcp_success_rate": float(layers.get("tcp", {}).get("success_rate", 0.0) or 0.0),
        "icmp_success_rate": float(layers.get("icmp", {}).get("success_rate", 0.0) or 0.0),
        "tls_success_rate": float(layers.get("tls", {}).get("success_rate", 0.0) or 0.0),
        "tts_mean_seconds": float(tts.get("mean_seconds", 0.0) or 0.0),
        "tts_p95_seconds": float(tts.get("p95_seconds", 0.0) or 0.0),
        "tts_worst_seconds": float(tts.get("worst_seconds", 0.0) or 0.0),
    }


def _baseline(current_date: str, window: int) -> Tuple[Dict[str, Dict[str, float]], List[Dict[str, Any]]]:
    history: List[Dict[str, Any]] = []
    for file_path in _list_recent_daily_files(limit=window, up_to_date=current_date):
        payload = _load_json(file_path, {})
        if not isinstance(payload, dict):
            continue
        if payload.get("date_utc") == current_date:
            continue
        snapshot = _metric_snapshot(payload)
        snapshot["connectivity_state"] = payload.get("connectivity_state", "unknown")
        snapshot["date_utc"] = payload.get("date_utc", file_path.parent.name)
        history.append(snapshot)

    stats: Dict[str, Dict[str, float]] = {}
    metric_keys = [
        "dns_success_rate",
        "tcp_success_rate",
        "icmp_success_rate",
        "tls_success_rate",
        "tts_mean_seconds",
        "tts_p95_seconds",
        "tts_worst_seconds",
    ]
    for key in metric_keys:
        values = [float(item[key]) for item in history if key in item]
        if not values:
            stats[key] = {"mean": 0.0, "stddev": 0.0, "samples": 0}
            continue
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        stats[key] = {
            "mean": round(mean, 6),
            "stddev": round(math.sqrt(variance), 6),
            "samples": len(values),
        }
    return stats, history


def _derive_state(
    layers: Dict[str, Dict[str, Any]],
    baseline_stats: Dict[str, Dict[str, float]],
    sigma_mult: float,
) -> str:
    dns_rate = float(layers["dns"]["success_rate"])
    tcp_rate = float(layers["tcp"]["success_rate"])
    icmp_rate = float(layers["icmp"]["success_rate"])
    tls_rate = float(layers["tls"]["success_rate"])

    if dns_rate == 0.0 and tcp_rate == 0.0 and icmp_rate == 0.0 and tls_rate == 0.0:
        return "silent"
    if dns_rate > 0 and tcp_rate == 0.0 and tls_rate == 0.0:
        return "dark"
    if tcp_rate > 0 or tls_rate > 0:
        tcp_base = baseline_stats.get("tcp_success_rate", {})
        tls_base = baseline_stats.get("tls_success_rate", {})
        tcp_z = _zscore(tcp_rate, tcp_base.get("mean", 0.0), tcp_base.get("stddev", 0.0))
        tls_z = _zscore(tls_rate, tls_base.get("mean", 0.0), tls_base.get("stddev", 0.0))
        if max(tcp_z, tls_z) >= sigma_mult + 0.5 and (tcp_rate >= 0.35 or tls_rate >= 0.35):
            return "open_ish"
        if max(tcp_z, tls_z) >= sigma_mult:
            return "anomalous"
        if (0 < tcp_rate <= 0.2) and (0 < tls_rate <= 0.2):
            return "controlled"
        return "partial"
    return "partial"


def _zscore(value: float, mean: float, stddev: float) -> float:
    if stddev <= 0:
        return 0.0 if value == mean else 99.0
    return (value - mean) / stddev


def _significance(
    current: Dict[str, float],
    baseline_stats: Dict[str, Dict[str, float]],
    current_state: str,
    history: List[Dict[str, Any]],
    sigma_mult: float,
) -> Dict[str, Any]:
    metric_details: Dict[str, Any] = {}
    metric_triggered = False

    for metric, current_value in current.items():
        base = baseline_stats.get(metric, {"mean": 0.0, "stddev": 0.0, "samples": 0})
        z = _zscore(current_value, float(base.get("mean", 0.0)), float(base.get("stddev", 0.0)))
        triggered = abs(z) >= sigma_mult and int(base.get("samples", 0)) >= 5
        metric_details[metric] = {
            "value": round(current_value, 6),
            "mean_30d": base.get("mean", 0.0),
            "stddev_30d": base.get("stddev", 0.0),
            "zscore": round(z, 4),
            "triggered": bool(triggered),
        }
        metric_triggered = metric_triggered or bool(triggered)

    prior_states = [str(item.get("connectivity_state", "unknown")) for item in history[-30:]]
    previous_state = prior_states[-1] if prior_states else None
    transition = f"{previous_state}->{current_state}" if previous_state else None
    prior_count = prior_states.count(current_state)
    transition_is_uncommon = bool(prior_states) and (prior_count / len(prior_states)) < 0.1
    transition_is_known_rare = bool(transition) and transition in RARE_STATE_TRANSITIONS
    rare_state = bool(prior_states) and previous_state != current_state and (
        transition_is_known_rare or transition_is_uncommon
    )

    any_significant = metric_triggered or rare_state
    triggered_metrics = [
        metric_name
        for metric_name, metric_payload in metric_details.items()
        if metric_payload.get("triggered")
    ]
    details: Dict[str, Any] = {
        "metrics": metric_details,
        "triggered_metrics": triggered_metrics,
        "state_transition": {
            "previous_state": previous_state,
            "current_state": current_state,
            "transition": transition,
            "rare": rare_state,
            "known_rare_transition": transition_is_known_rare,
            "uncommon_state_today": transition_is_uncommon,
        },
    }

    return {
        "sigma_mult": sigma_mult,
        "any_significant": any_significant,
        "details": details,
    }


def _color_for_state(state: str) -> Tuple[int, int, int]:
    mapping = {
        "silent": (120, 120, 120),
        "dark": (70, 90, 150),
        "partial": (210, 160, 60),
        "controlled": (60, 140, 220),
        "anomalous": (190, 80, 50),
        "open_ish": (70, 170, 80),
    }
    return mapping.get(state, (160, 160, 160))


_FONT = {
    " ": ["000", "000", "000", "000", "000"],
    "-": ["000", "000", "111", "000", "000"],
    ":": ["0", "1", "0", "1", "0"],
    ".": ["0", "0", "0", "0", "1"],
    "_": ["000", "000", "000", "000", "111"],
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "001", "001", "001"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
    "A": ["111", "101", "111", "101", "101"],
    "B": ["110", "101", "110", "101", "110"],
    "C": ["111", "100", "100", "100", "111"],
    "D": ["110", "101", "101", "101", "110"],
    "E": ["111", "100", "111", "100", "111"],
    "F": ["111", "100", "111", "100", "100"],
    "G": ["111", "100", "101", "101", "111"],
    "H": ["101", "101", "111", "101", "101"],
    "I": ["111", "010", "010", "010", "111"],
    "K": ["101", "101", "110", "101", "101"],
    "L": ["100", "100", "100", "100", "111"],
    "M": ["101", "111", "111", "101", "101"],
    "N": ["101", "111", "111", "111", "101"],
    "O": ["111", "101", "101", "101", "111"],
    "P": ["111", "101", "111", "100", "100"],
    "R": ["111", "101", "111", "110", "101"],
    "S": ["111", "100", "111", "001", "111"],
    "T": ["111", "010", "010", "010", "010"],
    "U": ["101", "101", "101", "101", "111"],
    "V": ["101", "101", "101", "101", "010"],
    "W": ["101", "101", "111", "111", "101"],
    "Y": ["101", "101", "111", "010", "010"],
    "Z": ["111", "001", "010", "100", "111"],
}


def _new_canvas(width: int, height: int, color: Tuple[int, int, int]) -> bytearray:
    r, g, b = color
    return bytearray([r, g, b] * width * height)


def _set_px(canvas: bytearray, width: int, height: int, x: int, y: int, color: Tuple[int, int, int]) -> None:
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    i = (y * width + x) * 3
    canvas[i : i + 3] = bytes(color)


def _draw_rect(canvas: bytearray, width: int, height: int, x0: int, y0: int, x1: int, y1: int, color: Tuple[int, int, int]) -> None:
    for y in range(max(0, y0), min(height, y1)):
        for x in range(max(0, x0), min(width, x1)):
            _set_px(canvas, width, height, x, y, color)


def _draw_text(canvas: bytearray, width: int, height: int, x: int, y: int, text: str, color: Tuple[int, int, int]) -> None:
    cursor = x
    for char in text.upper():
        glyph = _FONT.get(char, _FONT[" "])
        glyph_width = len(glyph[0]) if glyph else 3
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    _set_px(canvas, width, height, cursor + gx, y + gy, color)
        cursor += glyph_width + 1


def _write_png(path: Path, width: int, height: int, rgb_data: bytearray) -> None:
    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data))
            + chunk_type
            + data
            + struct.pack("!I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        )

    rows = []
    stride = width * 3
    for y in range(height):
        start = y * stride
        rows.append(b"\x00" + bytes(rgb_data[start : start + stride]))
    compressed = zlib.compress(b"".join(rows), level=9)

    png = bytearray()
    png.extend(b"\x89PNG\r\n\x1a\n")
    png.extend(chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)))
    png.extend(chunk(b"IDAT", compressed))
    png.extend(chunk(b"IEND", b""))
    path.write_bytes(bytes(png))


def _generate_chart_if_needed(
    date_utc: str,
    significance: Dict[str, Any],
    history: List[Dict[str, Any]],
    current_state: str,
) -> None:
    if not significance.get("any_significant"):
        return

    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    width, height = 1100, 360
    canvas = _new_canvas(width, height, (248, 248, 248))

    _draw_text(canvas, width, height, 20, 20, f"NORTH-KOREA-CONNECTIVITY {date_utc}", (25, 25, 25))
    _draw_text(canvas, width, height, 20, 34, f"STATE: {current_state}", _color_for_state(current_state))

    timeline = history[-29:] + [{"date_utc": date_utc, "connectivity_state": current_state}]
    if len(timeline) < 30:
        missing = 30 - len(timeline)
        timeline = ([{"date_utc": "", "connectivity_state": "unknown"}] * missing) + timeline

    left, top, right, bottom = 20, 90, width - 20, 240
    _draw_rect(canvas, width, height, left - 1, top - 1, right + 1, top, (180, 180, 180))
    _draw_rect(canvas, width, height, left - 1, bottom, right + 1, bottom + 1, (180, 180, 180))
    _draw_rect(canvas, width, height, left - 1, top, left, bottom, (180, 180, 180))
    _draw_rect(canvas, width, height, right, top, right + 1, bottom, (180, 180, 180))
    slot_width = (right - left) / 30.0

    for idx, item in enumerate(timeline):
        state = str(item.get("connectivity_state", "unknown"))
        x0 = left + idx * slot_width
        x1 = x0 + slot_width - 1
        _draw_rect(canvas, width, height, int(x0), top, int(x1), bottom, _color_for_state(state))

    _draw_text(canvas, width, height, 20, 245, "LAST 30-DAY STATE TIMELINE", (25, 25, 25))

    metric_rows: List[Tuple[str, Dict[str, Any]]] = []
    for metric_name, metric in significance.get("details", {}).get("metrics", {}).items():
        if isinstance(metric, dict) and metric.get("triggered"):
            metric_rows.append((metric_name, metric))
    metric_rows = metric_rows[:2]

    y = 290
    if not metric_rows:
        _draw_text(canvas, width, height, 20, y, "TRIGGER: RARE STATE TRANSITION", (120, 30, 30))
    else:
        _draw_text(canvas, width, height, 20, y, "TRIGGERED METRICS:", (25, 25, 25))
        y += 22
        for name, metric in metric_rows:
            text = (
                f"- {name}: value={metric.get('value')} mean30={metric.get('mean_30d')} "
                f"std30={metric.get('stddev_30d')} z={metric.get('zscore')}"
            )
            _draw_text(canvas, width, height, 30, y, text, (120, 30, 30))
            y += 20

    _write_png(LATEST_CHART_PATH, width, height, canvas)


def _update_latest_summary(date_utc: str, current_payload: Dict[str, Any]) -> None:
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    daily_files = _list_recent_daily_files(limit=7, up_to_date=date_utc)
    last_7_days: List[Dict[str, Any]] = []

    for path in daily_files:
        payload = _load_json(path, {})
        if not isinstance(payload, dict):
            continue
        last_7_days.append(
            {
                "date_utc": payload.get("date_utc", path.parent.name),
                "state": payload.get("connectivity_state", "unknown"),
                "any_significant": bool(payload.get("significance", {}).get("any_significant", False)),
            }
        )

    if not any(day.get("date_utc") == date_utc for day in last_7_days):
        last_7_days.append(
            {
                "date_utc": date_utc,
                "state": current_payload.get("connectivity_state", "unknown"),
                "any_significant": bool(current_payload.get("significance", {}).get("any_significant", False)),
            }
        )
        last_7_days = last_7_days[-7:]

    summary: Dict[str, Any] = {
        "observer": OBSERVER,
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
        "latest_date_utc": date_utc,
        "last_7_days": last_7_days,
    }
    if LATEST_CHART_PATH.exists():
        summary["chart_path"] = "data/latest/chart.png"

    LATEST_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


def run() -> Dict[str, Any]:
    date_utc = _date_utc()
    config = _load_config()
    hosts = _load_targets()

    totals = {
        "dns": _empty_layer(include_latency=True),
        "tcp": _empty_layer(),
        "icmp": _empty_layer(),
        "tls": _empty_layer(),
    }

    diagnostics = {"api_attempts": 0, "retries": 0, "http_status": None}

    if hosts:
        for _ in range(2):
            probe_layers, probe_diag = _probe_once(hosts, config["timeout_s"])
            _merge_layer_totals(totals, probe_layers)
            diagnostics["api_attempts"] += probe_diag["api_attempts"]

    layers = _finalize_layers(totals)
    tts = _time_to_silence(
        hosts,
        config["timeout_s"],
        config["time_to_silence_trials"],
        config["time_to_silence_max_rounds"],
    )

    baseline_stats, history = _baseline(date_utc, int(config["baseline_days"]))
    current_metrics = {
        "dns_success_rate": float(layers["dns"]["success_rate"]),
        "tcp_success_rate": float(layers["tcp"]["success_rate"]),
        "icmp_success_rate": float(layers["icmp"]["success_rate"]),
        "tls_success_rate": float(layers["tls"]["success_rate"]),
        "tts_mean_seconds": float(tts["mean_seconds"]),
        "tts_p95_seconds": float(tts["p95_seconds"]),
        "tts_worst_seconds": float(tts["worst_seconds"]),
    }

    state = _derive_state(layers, baseline_stats, float(config["sigma_mult"]))
    significance = _significance(
        current_metrics,
        baseline_stats,
        state,
        history,
        float(config["sigma_mult"]),
    )

    completeness_values = [float(layers[layer]["data_completeness"]) for layer in LAYER_NAMES]
    min_completeness = min(completeness_values) if completeness_values else 0.0
    if not hosts:
        data_status = "error"
    elif min_completeness >= 0.95:
        data_status = "ok"
    elif min_completeness > 0:
        data_status = "partial"
    else:
        data_status = "unavailable"

    payload: Dict[str, Any] = {
        "observer": OBSERVER,
        "date_utc": date_utc,
        "data_status": data_status,
        "connectivity_state": state,
        "layers": {
            "dns": {
                "success_rate": layers["dns"]["success_rate"],
                "mean_latency_ms": layers["dns"].get("mean_latency_ms"),
                "probe_count": layers["dns"]["probe_count"],
                "data_completeness": layers["dns"]["data_completeness"],
            },
            "tcp": {
                "success_rate": layers["tcp"]["success_rate"],
                "probe_count": layers["tcp"]["probe_count"],
                "data_completeness": layers["tcp"]["data_completeness"],
            },
            "icmp": {
                "success_rate": layers["icmp"]["success_rate"],
                "probe_count": layers["icmp"]["probe_count"],
                "data_completeness": layers["icmp"]["data_completeness"],
            },
            "tls": {
                "success_rate": layers["tls"]["success_rate"],
                "probe_count": layers["tls"]["probe_count"],
                "data_completeness": layers["tls"]["data_completeness"],
            },
        },
        "time_to_silence": {
            "mean_seconds": tts["mean_seconds"],
            "p95_seconds": tts["p95_seconds"],
            "worst_seconds": tts["worst_seconds"],
        },
        "baseline_30d": baseline_stats,
        "significance": significance,
        "diagnostics": diagnostics,
    }

    _generate_chart_if_needed(date_utc, significance, history, state)
    _update_latest_summary(date_utc, payload)

    return payload


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
