"""Traceroute-to-nowhere observer with aggregated privacy-preserving metrics."""

from __future__ import annotations

import json
import math
import os
import shutil
import socket
import struct
import subprocess
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Tuple

OBSERVER = "traceroute-to-nowhere"
MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
CONFIG_PATH = MODULE_DIR / "config.json"
TARGETS_PATH = MODULE_DIR / "targets.json"
DAILY_ROOT = REPO_ROOT / "data" / "daily"
LATEST_DIR = REPO_ROOT / "data" / "latest"
LATEST_SUMMARY_PATH = LATEST_DIR / "summary.json"
LATEST_CHART_PATH = LATEST_DIR / "chart.png"


class Config(Dict[str, Any]):
    pass


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
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _load_config() -> Config:
    payload = _load_json(CONFIG_PATH, {})
    if not isinstance(payload, dict):
        payload = {}

    baseline_days = max(7, int(payload.get("baseline_days", 30)))
    max_ttl = max(5, int(payload.get("max_ttl", 16)))
    timeout_s = max(0.5, float(payload.get("timeout_s", 1.5)))
    probe_delay_s = max(0.0, float(payload.get("probe_delay_s", 0.35)))
    sigma_mult = max(0.5, float(payload.get("sigma_mult", 2.0)))
    median_drop_threshold = max(1.0, float(payload.get("median_drop_threshold", 2.0)))
    unreachable_markers = payload.get("unreachable_markers", ["!N", "!H", "!P", "!X", "!S"])
    if not isinstance(unreachable_markers, list):
        unreachable_markers = ["!N", "!H", "!P", "!X", "!S"]

    return Config(
        baseline_days=baseline_days,
        max_ttl=max_ttl,
        timeout_s=timeout_s,
        probe_delay_s=probe_delay_s,
        sigma_mult=sigma_mult,
        median_drop_threshold=median_drop_threshold,
        unreachable_markers=[str(marker) for marker in unreachable_markers],
    )


def _load_targets() -> List[Dict[str, str]]:
    payload = _load_json(TARGETS_PATH, [])
    if not isinstance(payload, list):
        return []

    targets: List[Dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        host = str(item.get("host", "")).strip()
        name = str(item.get("name", host)).strip() or host
        if not host:
            continue
        targets.append({"name": name, "host": host})
    return targets


def _stddev(values: List[float]) -> float:
    if not values:
        return 0.0
    avg = sum(values) / len(values)
    variance = sum((v - avg) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _resolve_ip(host: str) -> str | None:
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return None


def _run_trace_summary(host: str, config: Config) -> Dict[str, Any]:
    traceroute_cmd = shutil.which("traceroute")
    if not traceroute_cmd:
        return {
            "reached_destination": False,
            "last_replied_hop": 0,
            "total_hops_attempted": int(config["max_ttl"]),
            "unanswered_hop_proportion": 1.0,
            "status": "traceroute_unavailable",
        }

    destination_ip = _resolve_ip(host)
    if destination_ip is None:
        return {
            "reached_destination": False,
            "last_replied_hop": 0,
            "total_hops_attempted": int(config["max_ttl"]),
            "unanswered_hop_proportion": 1.0,
            "status": "dns_resolution_failed",
        }

    command = [
        traceroute_cmd,
        "-n",
        "-m",
        str(config["max_ttl"]),
        "-q",
        "1",
        "-w",
        str(config["timeout_s"]),
        host,
    ]

    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        return {
            "reached_destination": False,
            "last_replied_hop": 0,
            "total_hops_attempted": int(config["max_ttl"]),
            "unanswered_hop_proportion": 1.0,
            "status": "traceroute_failed",
        }

    last_replied_hop = 0
    unanswered_hops = 0
    hops_seen = 0
    reached_destination = False

    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped or not stripped[0].isdigit():
            continue

        parts = stripped.split()
        try:
            hop_number = int(parts[0])
        except ValueError:
            continue

        hops_seen = max(hops_seen, hop_number)
        first_token = parts[1] if len(parts) > 1 else ""
        is_unanswered = first_token == "*"

        if is_unanswered:
            unanswered_hops += 1
        else:
            last_replied_hop = max(last_replied_hop, hop_number)

        if destination_ip in stripped:
            reached_destination = True
            break

        if any(marker in stripped for marker in config["unreachable_markers"]):
            break

    total_hops_attempted = hops_seen if hops_seen > 0 else int(config["max_ttl"])
    unanswered_hop_proportion = unanswered_hops / total_hops_attempted if total_hops_attempted else 1.0

    return {
        "reached_destination": reached_destination,
        "last_replied_hop": int(last_replied_hop),
        "total_hops_attempted": int(total_hops_attempted),
        "unanswered_hop_proportion": round(float(unanswered_hop_proportion), 6),
        "status": "ok",
    }


def _daily_files_up_to(date_str: str) -> List[Path]:
    if not DAILY_ROOT.exists():
        return []
    files: List[Path] = []
    for day_dir in DAILY_ROOT.iterdir():
        if not day_dir.is_dir() or day_dir.name > date_str:
            continue
        path = day_dir / f"{OBSERVER}.json"
        if path.exists():
            files.append(path)
    return sorted(files, key=lambda p: p.parent.name)


def _baseline_values(date_str: str, baseline_days: int) -> Tuple[List[float], List[float]]:
    fail_rates: List[float] = []
    median_hops: List[float] = []
    for path in _daily_files_up_to(date_str):
        payload = _load_json(path, {})
        if not isinstance(payload, dict):
            continue
        if payload.get("date_utc") == date_str:
            continue
        metrics = payload.get("metrics", {})
        if not isinstance(metrics, dict):
            continue
        fail_rate = metrics.get("fail_rate")
        median_hop = metrics.get("median_last_replied_hop")
        if isinstance(fail_rate, (int, float)):
            fail_rates.append(float(fail_rate))
        if isinstance(median_hop, (int, float)):
            median_hops.append(float(median_hop))

    return fail_rates[-baseline_days:], median_hops[-baseline_days:]


def _baseline_stats(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0}
    avg = sum(values) / len(values)
    return {"mean": round(avg, 6), "std": round(_stddev(values), 6)}


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _encode_png_rgb(width: int, height: int, pixels: List[List[tuple[int, int, int]]], metadata: Dict[str, str]) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    text_chunks = [
        _png_chunk(
            b"tEXt",
            key.encode("latin1", errors="ignore") + b"\x00" + value.encode("latin1", errors="ignore"),
        )
        for key, value in metadata.items()
    ]

    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixels[y][x])

    idat = _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
    iend = _png_chunk(b"IEND", b"")
    return signature + ihdr + b"".join(text_chunks) + idat + iend


def _draw_line(pixels: List[List[tuple[int, int, int]]], x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy

    h = len(pixels)
    w = len(pixels[0]) if h else 0

    while True:
        if 0 <= x0 < w and 0 <= y0 < h:
            pixels[y0][x0] = color
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _render_significant_chart(date_str: str, triggers: List[str], history_rows: List[Dict[str, Any]]) -> None:
    width, height = 920, 480
    bg = (246, 249, 253)
    pixels = [[bg for _ in range(width)] for _ in range(height)]

    margin_left = 70
    margin_right = 30
    margin_top = 40
    margin_bottom = 70
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    rows = history_rows[-30:]
    if not rows:
        return

    for y in range(margin_top, margin_top + plot_h + 1, max(1, plot_h // 5)):
        for x in range(margin_left, margin_left + plot_w):
            pixels[y][x] = (223, 230, 240)

    for y in range(margin_top, margin_top + plot_h):
        pixels[y][margin_left] = (110, 120, 140)
    for x in range(margin_left, margin_left + plot_w):
        pixels[margin_top + plot_h][x] = (110, 120, 140)

    fail_values = [float(item.get("fail_rate", 0.0)) for item in rows]
    hop_values = [float(item.get("median_last_replied_hop", 0.0)) for item in rows]

    max_hop = max(max(hop_values), 1.0)
    count = len(rows)
    step = plot_w / max(1, count - 1)

    fail_points: List[tuple[int, int]] = []
    hop_points: List[tuple[int, int]] = []

    for idx, (fail_rate, hop_med) in enumerate(zip(fail_values, hop_values)):
        x = int(margin_left + idx * step)
        y_fail = int(margin_top + plot_h - (min(max(fail_rate, 0.0), 1.0) * plot_h))
        y_hop = int(margin_top + plot_h - (max(0.0, min(1.0, hop_med / max_hop)) * plot_h))
        fail_points.append((x, y_fail))
        hop_points.append((x, y_hop))

    for idx in range(1, len(fail_points)):
        _draw_line(pixels, *fail_points[idx - 1], *fail_points[idx], (205, 60, 66))
        _draw_line(pixels, *hop_points[idx - 1], *hop_points[idx], (32, 102, 182))

    metadata = {
        "Title": f"Traceroute significance {date_str}",
        "Observer": OBSERVER,
        "FailRateSeries": "; ".join(f"{row['date_utc']}={row['fail_rate']:.4f}" for row in rows),
        "MedianHopSeries": "; ".join(f"{row['date_utc']}={row['median_last_replied_hop']:.2f}" for row in rows),
        "Trigger": " | ".join(triggers) if triggers else "none",
    }

    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_CHART_PATH.write_bytes(_encode_png_rgb(width, height, pixels, metadata))


def _last_7_summary(date_str: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in _daily_files_up_to(date_str)[-7:]:
        payload = _load_json(path, {})
        if not isinstance(payload, dict):
            continue
        metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {}
        significance = payload.get("significance", {}) if isinstance(payload.get("significance"), dict) else {}
        rows.append(
            {
                "date_utc": str(payload.get("date_utc", path.parent.name)),
                "fail_rate": round(float(metrics.get("fail_rate", 0.0) or 0.0), 6),
                "any_significant": bool(significance.get("any_significant", False)),
            }
        )
    return rows


def _write_latest_summary(date_str: str, any_significant: bool) -> None:
    payload: Dict[str, Any] = {
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
        "latest_date_utc": date_str,
        "last_7_days": _last_7_summary(date_str),
    }
    if LATEST_CHART_PATH.exists() and any_significant:
        payload["chart_path"] = "data/latest/chart.png"

    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_SUMMARY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run() -> Dict[str, Any]:
    date_str = _date_utc()
    config = _load_config()
    anchors = _load_targets()

    traces: List[Dict[str, Any]] = []
    for idx, anchor in enumerate(anchors):
        traces.append(_run_trace_summary(anchor["host"], config))
        if idx < len(anchors) - 1:
            time.sleep(float(config["probe_delay_s"]))

    trace_count = len(traces)
    failed = sum(1 for t in traces if not t["reached_destination"])
    last_hops = [int(t["last_replied_hop"]) for t in traces]
    unanswered = [float(t["unanswered_hop_proportion"]) for t in traces]
    early_blackholes = sum(1 for t in traces if int(t["last_replied_hop"]) <= 3)

    fail_rate = (failed / trace_count) if trace_count else 1.0
    median_last_replied_hop = float(median(last_hops)) if last_hops else 0.0
    early_blackhole_rate = (early_blackholes / trace_count) if trace_count else 0.0
    timeout_hop_density = (sum(unanswered) / trace_count) if trace_count else 1.0

    fail_hist, hop_hist = _baseline_values(date_str, int(config["baseline_days"]))
    baseline_fail = _baseline_stats(fail_hist)
    baseline_hop = _baseline_stats(hop_hist)

    fail_std = baseline_fail["std"]
    fail_z = 0.0 if fail_std == 0.0 else (fail_rate - baseline_fail["mean"]) / fail_std
    hop_drop = baseline_hop["mean"] - median_last_replied_hop

    mass_event_threshold = max(1, (trace_count + 1) // 2)
    mass_event = failed >= mass_event_threshold and trace_count > 0

    triggers: List[str] = []
    if fail_z > float(config["sigma_mult"]):
        triggers.append(f"z_fail_rate>{float(config['sigma_mult']):.2f}")
    if hop_drop > float(config["median_drop_threshold"]):
        triggers.append(f"median_last_replied_hop_drop>{float(config['median_drop_threshold']):.2f}")
    if mass_event:
        triggers.append(f"mass_event_failed_anchors>={mass_event_threshold}")

    any_significant = bool(triggers)

    data_status = "ok"
    unavailable_count = sum(1 for t in traces if t["status"] in {"traceroute_unavailable", "traceroute_failed"})
    if trace_count == 0:
        data_status = "unavailable"
    elif unavailable_count == trace_count:
        data_status = "unavailable"
    elif unavailable_count > 0:
        data_status = "partial"

    output = {
        "observer": OBSERVER,
        "date_utc": date_str,
        "data_status": data_status,
        "anchors": {"count": trace_count},
        "metrics": {
            "trace_count": trace_count,
            "fail_rate": round(fail_rate, 6),
            "median_last_replied_hop": round(median_last_replied_hop, 6),
            "early_blackhole_rate": round(early_blackhole_rate, 6),
            "timeout_hop_density": round(timeout_hop_density, 6),
        },
        "baseline_30d": {
            "fail_rate": baseline_fail,
            "median_last_replied_hop": baseline_hop,
        },
        "significance": {
            "sigma_mult": round(float(config["sigma_mult"]), 6),
            "any_significant": any_significant,
            "triggers": triggers,
        },
    }

    history_rows: List[Dict[str, Any]] = []
    for path in _daily_files_up_to(date_str):
        payload = _load_json(path, {})
        if not isinstance(payload, dict):
            continue
        metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {}
        history_rows.append(
            {
                "date_utc": str(payload.get("date_utc", path.parent.name)),
                "fail_rate": float(metrics.get("fail_rate", 0.0) or 0.0),
                "median_last_replied_hop": float(metrics.get("median_last_replied_hop", 0.0) or 0.0),
            }
        )

    history_rows.append(
        {
            "date_utc": date_str,
            "fail_rate": float(output["metrics"]["fail_rate"]),
            "median_last_replied_hop": float(output["metrics"]["median_last_replied_hop"]),
        }
    )

    if any_significant:
        _render_significant_chart(date_str, triggers, history_rows)
    elif LATEST_CHART_PATH.exists():
        LATEST_CHART_PATH.unlink()

    _write_latest_summary(date_str, any_significant)

    return output


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
