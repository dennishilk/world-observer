"""Long-horizon trend observer based on global-reachability-score history."""

from __future__ import annotations

import json
import math
import os
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

OBSERVER = "global-reachability-long-horizon"
SOURCE_OBSERVER = "global-reachability-score"
MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
CONFIG_PATH = MODULE_DIR / "config.json"
DAILY_ROOT = REPO_ROOT / "data" / "daily"
LATEST_DIR = REPO_ROOT / "data" / "latest"
LATEST_SUMMARY_PATH = LATEST_DIR / "summary.json"
LATEST_CHART_PATH = LATEST_DIR / "chart.png"


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


def _load_config() -> Dict[str, Any]:
    payload = _load_json(CONFIG_PATH, {})
    if not isinstance(payload, dict):
        payload = {}
    return {
        "mass_event_k": max(1, int(payload.get("mass_event_k", 5))),
        "trend_break_threshold": max(0.0, float(payload.get("trend_break_threshold", 0.08))),
        "top_countries_in_chart": max(3, int(payload.get("top_countries_in_chart", 6))),
    }


def _source_daily_paths_up_to(date_str: str) -> List[Path]:
    if not DAILY_ROOT.exists():
        return []
    rows: List[Path] = []
    for day_dir in DAILY_ROOT.iterdir():
        if not day_dir.is_dir() or day_dir.name > date_str:
            continue
        candidate = day_dir / f"{SOURCE_OBSERVER}.json"
        if candidate.exists():
            rows.append(candidate)
    return sorted(rows, key=lambda p: p.parent.name)


def _extract_day_scores(path: Path) -> Dict[str, float]:
    payload = _load_json(path, {})
    if not isinstance(payload, dict):
        return {}
    countries = payload.get("countries", [])
    if not isinstance(countries, list):
        return {}

    day_scores: Dict[str, float] = {}
    for row in countries:
        if not isinstance(row, dict):
            continue
        country = str(row.get("country", "")).strip()
        score = row.get("score_percent")
        if not country or not isinstance(score, (int, float)):
            continue
        day_scores[country] = float(score)
    return day_scores


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _linear_slope(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    n = len(values)
    x_avg = (n - 1) / 2.0
    y_avg = _mean(values)
    numerator = 0.0
    denominator = 0.0
    for i, value in enumerate(values):
        dx = i - x_avg
        numerator += dx * (value - y_avg)
        denominator += dx * dx
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _metric_row(country: str, history: List[float]) -> Dict[str, Any]:
    today = history[-1]
    last_90 = history[-90:]
    last_180 = history[-180:]
    min_180 = min(last_180)
    max_180 = max(last_180)
    drawdown = max_180 - today

    return {
        "country": country,
        "score_today": round(today, 4),
        "mean_90d": round(_mean(last_90), 4),
        "mean_180d": round(_mean(last_180), 4),
        "slope_90d": round(_linear_slope(last_90), 6),
        "slope_180d": round(_linear_slope(last_180), 6),
        "drawdown_180d": round(drawdown, 4),
        "is_new_180d_low": math.isclose(today, min_180, rel_tol=0.0, abs_tol=1e-9),
        "is_new_180d_high": math.isclose(today, max_180, rel_tol=0.0, abs_tol=1e-9),
    }


def _global_series(day_scores: List[Dict[str, float]]) -> List[float]:
    rows: List[float] = []
    for entry in day_scores:
        values = list(entry.values())
        if not values:
            continue
        rows.append(_mean(values))
    return rows


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _encode_png_rgb(width: int, height: int, pixels: List[List[Tuple[int, int, int]]], metadata: Dict[str, str]) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    text_chunks = [
        _png_chunk(b"tEXt", key.encode("latin1", errors="ignore") + b"\x00" + value.encode("latin1", errors="ignore"))
        for key, value in metadata.items()
    ]

    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            r, g, b = pixels[y][x]
            raw.extend((r, g, b))

    idat = _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
    iend = _png_chunk(b"IEND", b"")
    return signature + ihdr + b"".join(text_chunks) + idat + iend


def _draw_line(pixels: List[List[Tuple[int, int, int]]], points: List[Tuple[int, int]], color: Tuple[int, int, int]) -> None:
    if len(points) < 2:
        return
    height = len(pixels)
    width = len(pixels[0]) if pixels else 0

    for idx in range(1, len(points)):
        x0, y0 = points[idx - 1]
        x1, y1 = points[idx]
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        steps = max(dx, dy, 1)
        for step in range(steps + 1):
            t = step / steps
            x = int(round(x0 + (x1 - x0) * t))
            y = int(round(y0 + (y1 - y0) * t))
            if 0 <= x < width and 0 <= y < height:
                pixels[y][x] = color
                if y + 1 < height:
                    pixels[y + 1][x] = color


def _render_chart(
    date_str: str,
    global_180d: List[float],
    lows: List[Dict[str, Any]],
    highs: List[Dict[str, Any]],
    triggers: List[str],
    config: Dict[str, Any],
) -> None:
    width, height = 960, 540
    background = (244, 247, 251)
    pixels = [[background for _ in range(width)] for _ in range(height)]

    # Panel 1: global 180d trend line.
    left, top = 40, 40
    panel_w, panel_h = 880, 240
    for y in range(top, top + panel_h):
        pixels[y][left] = (170, 175, 185)
    for x in range(left, left + panel_w):
        pixels[top + panel_h - 1][x] = (170, 175, 185)

    if global_180d:
        min_v = min(global_180d)
        max_v = max(global_180d)
        spread = max(1e-6, max_v - min_v)
        step = panel_w / max(1, len(global_180d) - 1)
        points: List[Tuple[int, int]] = []
        for idx, value in enumerate(global_180d):
            x = int(left + idx * step)
            y = int(top + panel_h - 1 - ((value - min_v) / spread) * (panel_h - 1))
            points.append((x, y))
        _draw_line(pixels, points, (36, 90, 168))

    # Panel 2: top countries driving new lows/highs.
    bar_left = 60
    bar_top = 320
    bar_h = 20
    bar_gap = 12
    bar_max = 520

    ranked = (sorted(lows, key=lambda row: row["drawdown_180d"], reverse=True) + highs)[: config["top_countries_in_chart"]]
    for idx, row in enumerate(ranked):
        y0 = bar_top + idx * (bar_h + bar_gap)
        y1 = min(height - 1, y0 + bar_h)
        mag = min(1.0, max(0.05, abs(float(row.get("drawdown_180d", 0.0))) / 100.0))
        w = int(bar_max * mag)
        is_low = bool(row.get("is_new_180d_low", False))
        color = (190, 60, 60) if is_low else (50, 155, 85)
        for y in range(y0, y1):
            for x in range(bar_left, min(width - 1, bar_left + w)):
                pixels[y][x] = color

    metadata = {
        "Title": f"Global Reachability Long Horizon {date_str}",
        "Observer": OBSERVER,
        "Triggers": " | ".join(triggers),
        "Global180dPoints": str(len(global_180d)),
        "TopLows": "; ".join(f"{r['country']}:{r['score_today']:.2f}" for r in lows[:10]),
        "TopHighs": "; ".join(f"{r['country']}:{r['score_today']:.2f}" for r in highs[:10]),
    }
    png = _encode_png_rgb(width, height, pixels, metadata)
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_CHART_PATH.write_bytes(png)


def _daily_output_paths(date_str: str) -> Tuple[Path, Path]:
    day_dir = DAILY_ROOT / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"{OBSERVER}.json", LATEST_SUMMARY_PATH


def _write_latest_summary(
    date_str: str,
    any_significant: bool,
    new_low_count: int,
) -> None:
    # Build last_7_days strictly from historical outputs of this observer.
    rows: List[Dict[str, Any]] = []
    if DAILY_ROOT.exists():
        for day_dir in sorted([d for d in DAILY_ROOT.iterdir() if d.is_dir()], key=lambda p: p.name):
            if day_dir.name > date_str:
                continue
            payload = _load_json(day_dir / f"{OBSERVER}.json", {})
            if not isinstance(payload, dict):
                continue
            stats = payload.get("summary_stats", {})
            sig = payload.get("significance", {})
            rows.append(
                {
                    "date_utc": payload.get("date_utc", day_dir.name),
                    "new_180d_low_count": int(stats.get("new_180d_low_count", 0) or 0),
                    "any_significant": bool(sig.get("any_significant", False)),
                }
            )

    if not any(r["date_utc"] == date_str for r in rows):
        rows.append(
            {
                "date_utc": date_str,
                "new_180d_low_count": int(new_low_count),
                "any_significant": bool(any_significant),
            }
        )

    rows = sorted(rows, key=lambda r: r["date_utc"])[-7:]
    summary: Dict[str, Any] = {
        "observer": OBSERVER,
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
        "latest_date_utc": date_str,
        "last_7_days": rows,
    }
    if any_significant and LATEST_CHART_PATH.exists():
        summary["chart_path"] = "data/latest/chart.png"

    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run() -> Dict[str, Any]:
    date_str = _date_utc()
    config = _load_config()

    source_paths = _source_daily_paths_up_to(date_str)
    day_country_scores: List[Dict[str, float]] = [_extract_day_scores(path) for path in source_paths]
    countries_index: Dict[str, List[float]] = {}
    for day_scores in day_country_scores:
        for country, score in day_scores.items():
            countries_index.setdefault(country, []).append(score)

    countries: List[Dict[str, Any]] = []
    for country, history in sorted(countries_index.items()):
        if not history:
            continue
        countries.append(_metric_row(country, history[-180:]))

    global_series = _global_series(day_country_scores)
    global_last_180 = global_series[-180:]
    avg_today = _mean(list(day_country_scores[-1].values())) if day_country_scores and day_country_scores[-1] else 0.0
    avg_mean_180 = _mean(global_last_180)

    is_global_low = bool(global_last_180) and math.isclose(avg_today, min(global_last_180), rel_tol=0.0, abs_tol=1e-9)
    is_global_high = bool(global_last_180) and math.isclose(avg_today, max(global_last_180), rel_tol=0.0, abs_tol=1e-9)

    new_lows = [row for row in countries if row["is_new_180d_low"]]
    new_highs = [row for row in countries if row["is_new_180d_high"]]

    slope_180 = _linear_slope(global_last_180)
    prev_180 = global_series[-181:-1] if len(global_series) >= 181 else global_series[:-1]
    prev_slope_180 = _linear_slope(prev_180)
    slope_delta = slope_180 - prev_slope_180
    trend_break = abs(slope_delta) >= float(config["trend_break_threshold"])

    triggers: List[str] = []
    if is_global_low:
        triggers.append("new_global_180d_low")
    if is_global_high:
        triggers.append("new_global_180d_high")
    if len(new_lows) >= int(config["mass_event_k"]):
        triggers.append(f"mass_new_180d_lows>={int(config['mass_event_k'])}")
    if trend_break:
        triggers.append(f"trend_break_delta={slope_delta:.6f}")

    any_significant = len(triggers) > 0

    if any_significant:
        _render_chart(date_str, global_last_180, new_lows, new_highs, triggers, config)
    elif LATEST_CHART_PATH.exists():
        LATEST_CHART_PATH.unlink()

    if not countries:
        data_status = "unavailable"
    elif any(len(scores) < 180 for scores in countries_index.values()):
        data_status = "partial"
    else:
        data_status = "ok"

    payload: Dict[str, Any] = {
        "observer": OBSERVER,
        "date_utc": date_str,
        "data_status": data_status,
        "countries": countries,
        "global": {
            "avg_score_today": round(avg_today, 4),
            "avg_mean_180d": round(avg_mean_180, 4),
            "is_new_180d_low": is_global_low,
            "is_new_180d_high": is_global_high,
        },
        "summary_stats": {
            "countries_evaluated": len(countries),
            "new_180d_low_count": len(new_lows),
        },
        "significance": {
            "any_significant": any_significant,
            "triggers": triggers,
        },
    }

    daily_output, _ = _daily_output_paths(date_str)
    daily_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_latest_summary(date_str, any_significant, len(new_lows))
    return payload


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
