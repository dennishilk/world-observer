"""Observer for the internet-shrinkage-index.

Trend-only aggregator that consumes existing daily observer JSON outputs.
No active probing is performed by this observer.
"""

from __future__ import annotations

import json
import math
import os
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

OBSERVER = "internet-shrinkage-index"

WINDOW_DAYS = int(os.getenv("ISI_WINDOW_DAYS", "30"))
PEAK_LOOKBACK_DAYS = int(os.getenv("ISI_PEAK_LOOKBACK_DAYS", "90"))
BASELINE_DAYS = int(os.getenv("ISI_BASELINE_DAYS", "30"))
MASS_EVENT_K = int(os.getenv("ISI_MASS_EVENT_K", "5"))

WEIGHT_TREND = 0.45
WEIGHT_DISTANCE_TO_PEAK = 0.35
WEIGHT_PERSISTENCE = 0.20
WEIGHT_SILENCE_MODIFIER = 0.10

TREND_SLOPE_SCALE = 0.02
REGIME_SLOPE_THRESHOLD = 0.015
REGIME_MULTIPLIER = 2.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _run_date() -> str:
    date_str = os.getenv("WORLD_OBSERVER_DATE_UTC", "").strip()
    if not date_str:
        return _today_utc()
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return _today_utc()


def _date_range_inclusive(end_date: str, days: int) -> List[str]:
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    start = end - timedelta(days=max(days - 1, 0))
    result: List[str] = []
    cur = start
    while cur <= end:
        result.append(cur.isoformat())
        cur += timedelta(days=1)
    return result


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_daily_observer(date_str: str, observer_name: str) -> Optional[Dict[str, Any]]:
    path = _repo_root() / "data" / "daily" / date_str / f"{observer_name}.json"
    return _load_json(path)


def _country_name(raw: Any) -> Optional[str]:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _coerce_ratio(value: Any) -> Optional[float]:
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if numeric < 0:
        return None
    if numeric > 1.0:
        if numeric <= 100.0:
            numeric = numeric / 100.0
        else:
            return None
    return max(0.0, min(1.0, numeric))


def _extract_signal_maps(date_str: str) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, float], Dict[str, float]]:
    """Return (reachability_bad, asn_bad, ipv6_bad, silence_modifier)."""

    reachability_bad: Dict[str, float] = {}
    asn_bad: Dict[str, float] = {}
    ipv6_bad: Dict[str, float] = {}
    silence_modifier: Dict[str, float] = {}

    grs = _load_daily_observer(date_str, "global-reachability-score")
    if grs:
        for item in grs.get("countries", []):
            if not isinstance(item, dict):
                continue
            country = _country_name(item.get("country"))
            if not country:
                continue
            score_percent = item.get("score_percent")
            ratio = _coerce_ratio(score_percent)
            if ratio is None and isinstance(item.get("score"), (int, float)) and isinstance(
                item.get("max_score"), (int, float)
            ):
                max_score = float(item["max_score"])
                if max_score > 0:
                    ratio = max(0.0, min(1.0, float(item["score"]) / max_score))
            if ratio is not None:
                reachability_bad[country] = 1.0 - ratio

    asn = _load_daily_observer(date_str, "asn-visibility-by-country")
    if asn:
        for item in asn.get("countries", []):
            if not isinstance(item, dict):
                continue
            country = _country_name(item.get("country"))
            if not country:
                continue
            ratio = _coerce_ratio(item.get("visibility_ratio"))
            if ratio is None and isinstance(item.get("visible_asns"), (int, float)) and isinstance(
                item.get("total_asns"), (int, float)
            ):
                total_asns = float(item["total_asns"])
                if total_asns > 0:
                    ratio = max(0.0, min(1.0, float(item["visible_asns"]) / total_asns))
            if ratio is not None:
                asn_bad[country] = 1.0 - ratio

    ipv6 = _load_daily_observer(date_str, "ipv6-locked-states") or _load_daily_observer(
        date_str, "ipv6-adoption-locked-states"
    )
    if ipv6:
        for item in ipv6.get("countries", []):
            if not isinstance(item, dict):
                continue
            country = _country_name(item.get("country"))
            if not country:
                continue
            ratio = _coerce_ratio(item.get("ipv6_capable_rate"))
            if ratio is None:
                ratio = _coerce_ratio(item.get("ipv6_ratio"))
            if ratio is None:
                ratio = _coerce_ratio(item.get("rate"))
            if ratio is not None:
                ipv6_bad[country] = 1.0 - ratio

    silent = _load_daily_observer(date_str, "silent-countries-list")
    if silent:
        for item in silent.get("countries", []):
            if not isinstance(item, dict):
                continue
            country = _country_name(item.get("country"))
            if not country:
                continue
            classification = str(item.get("classification", "")).strip().lower()
            persistently_silent = bool(item.get("persistently_silent")) or classification == "persistently_silent"
            is_silent = bool(item.get("silent"))
            if persistently_silent:
                silence_modifier[country] = 1.0
            elif is_silent:
                silence_modifier[country] = 0.6

    return reachability_bad, asn_bad, ipv6_bad, silence_modifier


def _mean(values: Iterable[float]) -> Optional[float]:
    vals = list(values)
    if not vals:
        return None
    return sum(vals) / len(vals)


def _stddev(values: List[float], mean: float) -> float:
    if not values:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(max(0.0, variance))


def _linear_slope(series: List[float]) -> Optional[float]:
    n = len(series)
    if n < 2:
        return None
    x_mean = (n - 1) / 2.0
    y_mean = sum(series) / n
    num = 0.0
    den = 0.0
    for idx, value in enumerate(series):
        dx = idx - x_mean
        num += dx * (value - y_mean)
        den += dx * dx
    if den <= 0.0:
        return None
    return num / den


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _load_historical_outputs(end_date: str, lookback_days: int) -> Dict[str, Dict[str, Any]]:
    outputs: Dict[str, Dict[str, Any]] = {}
    for date_str in _date_range_inclusive(end_date, lookback_days):
        payload = _load_daily_observer(date_str, OBSERVER)
        if payload:
            outputs[date_str] = payload
    return outputs


def _build_country_daily_bad_series(end_date: str) -> Dict[str, Dict[str, float]]:
    """country -> date -> aggregated badness mean across available input signals."""

    lookback = max(WINDOW_DAYS, PEAK_LOOKBACK_DAYS)
    series: Dict[str, Dict[str, float]] = {}
    for date_str in _date_range_inclusive(end_date, lookback):
        reachability_bad, asn_bad, ipv6_bad, _silence_mod = _extract_signal_maps(date_str)
        countries = set(reachability_bad) | set(asn_bad) | set(ipv6_bad)
        for country in countries:
            values: List[float] = []
            if country in reachability_bad:
                values.append(reachability_bad[country])
            if country in asn_bad:
                values.append(asn_bad[country])
            if country in ipv6_bad:
                values.append(ipv6_bad[country])
            if not values:
                continue
            country_series = series.setdefault(country, {})
            country_series[date_str] = sum(values) / len(values)
    return series


def _extract_historical_country_scores(
    historical_outputs: Dict[str, Dict[str, Any]], country: str
) -> List[Tuple[str, float]]:
    rows: List[Tuple[str, float]] = []
    for date_str in sorted(historical_outputs):
        payload = historical_outputs[date_str]
        countries = payload.get("countries")
        if not isinstance(countries, list):
            continue
        for item in countries:
            if not isinstance(item, dict):
                continue
            if item.get("country") != country:
                continue
            score = item.get("shrinkage_score")
            if isinstance(score, (int, float)):
                rows.append((date_str, float(score)))
    return rows


def _extract_historical_global_scores(historical_outputs: Dict[str, Dict[str, Any]]) -> List[Tuple[str, float]]:
    rows: List[Tuple[str, float]] = []
    for date_str in sorted(historical_outputs):
        payload = historical_outputs[date_str]
        global_obj = payload.get("global")
        if not isinstance(global_obj, dict):
            continue
        score = global_obj.get("global_shrinkage_index")
        if isinstance(score, (int, float)):
            rows.append((date_str, float(score)))
    return rows


def _compute_country_components(
    country: str,
    end_date: str,
    bad_series_by_country: Dict[str, Dict[str, float]],
    silence_map_today: Dict[str, float],
) -> Tuple[float, Dict[str, Optional[float]]]:
    date_window = _date_range_inclusive(end_date, WINDOW_DAYS)
    peak_window = _date_range_inclusive(end_date, PEAK_LOOKBACK_DAYS)
    history = bad_series_by_country.get(country, {})

    trend_series = [history[d] for d in date_window if d in history]
    trend: Optional[float] = None
    if len(trend_series) >= 2:
        slope = _linear_slope(trend_series)
        if slope is not None and slope > 0:
            trend = _clamp01(slope / TREND_SLOPE_SCALE)
        elif slope is not None:
            trend = 0.0

    distance_to_peak: Optional[float] = None
    peak_series = [history[d] for d in peak_window if d in history]
    if peak_series and end_date in history:
        current = history[end_date]
        min_recent = min(peak_series)
        distance_to_peak = _clamp01(current - min_recent)

    persistence: Optional[float] = None
    if len(trend_series) >= 2:
        deltas = [trend_series[i] - trend_series[i - 1] for i in range(1, len(trend_series))]
        if deltas:
            persistence = sum(1 for delta in deltas if delta > 0) / len(deltas)

    silence_modifier = silence_map_today.get(country)

    weighted_components: List[Tuple[float, float]] = []
    if trend is not None:
        weighted_components.append((WEIGHT_TREND, trend))
    if distance_to_peak is not None:
        weighted_components.append((WEIGHT_DISTANCE_TO_PEAK, distance_to_peak))
    if persistence is not None:
        weighted_components.append((WEIGHT_PERSISTENCE, persistence))

    if weighted_components:
        base_weight = sum(weight for weight, _value in weighted_components)
        base_score = sum(weight * value for weight, value in weighted_components) / base_weight
    else:
        base_score = 0.0

    if silence_modifier is not None:
        score = _clamp01(base_score + (WEIGHT_SILENCE_MODIFIER * silence_modifier))
    else:
        score = _clamp01(base_score)

    components = {
        "trend": trend,
        "distance_to_peak": distance_to_peak,
        "persistence": persistence,
        "silence_modifier": silence_modifier,
    }
    return score, components


def _set_px(canvas: List[List[Tuple[int, int, int]]], x: int, y: int, color: Tuple[int, int, int]) -> None:
    if 0 <= y < len(canvas) and 0 <= x < len(canvas[0]):
        canvas[y][x] = color


def _draw_line(
    canvas: List[List[Tuple[int, int, int]]],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: Tuple[int, int, int],
) -> None:
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    err = dx + dy

    while True:
        _set_px(canvas, x0, y0, color)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _fill_rect(
    canvas: List[List[Tuple[int, int, int]]],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: Tuple[int, int, int],
) -> None:
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            _set_px(canvas, x, y, color)


def _save_png(
    path: Path,
    canvas: List[List[Tuple[int, int, int]]],
    text_chunks: Optional[List[Tuple[str, str]]] = None,
) -> None:
    height = len(canvas)
    width = len(canvas[0]) if height else 0

    raw = bytearray()
    for row in canvas:
        raw.append(0)
        for r, g, b in row:
            raw.extend((r, g, b))

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    payload = bytearray(b"\x89PNG\r\n\x1a\n")
    payload.extend(_chunk(b"IHDR", ihdr))

    for key, value in (text_chunks or []):
        payload.extend(_chunk(b"tEXt", f"{key}\x00{value}".encode("latin-1", errors="replace")))

    payload.extend(_chunk(b"IDAT", zlib.compress(bytes(raw), level=9)))
    payload.extend(_chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(payload))


def _chart_image(
    global_series: List[Tuple[str, float]],
    new_max_countries: List[Tuple[str, float]],
    triggers: List[str],
    output_path: Path,
) -> None:
    width, height = 1100, 700
    margin_left, margin_right = 70, 40
    margin_top, margin_bottom = 80, 140
    chart_width = width - margin_left - margin_right
    chart_height = 300

    canvas: List[List[Tuple[int, int, int]]] = [
        [(255, 255, 255) for _ in range(width)] for _ in range(height)
    ]

    values = [value for _date_str, value in global_series]
    dates = [date_str for date_str, _value in global_series]

    if len(values) >= 2 and max(values) != min(values):
        min_v = min(values)
        max_v = max(values)
        points: List[Tuple[int, int]] = []
        for idx, val in enumerate(values):
            x = int(margin_left + (idx / (len(values) - 1)) * chart_width)
            y = int(margin_top + chart_height - ((val - min_v) / (max_v - min_v)) * chart_height)
            points.append((x, y))
        for idx in range(1, len(points)):
            x0, y0 = points[idx - 1]
            x1, y1 = points[idx]
            _draw_line(canvas, x0, y0, x1, y1, (25, 92, 205))
            _draw_line(canvas, x0, y0 + 1, x1, y1 + 1, (25, 92, 205))
            _draw_line(canvas, x0, y0 - 1, x1, y1 - 1, (25, 92, 205))
    _fill_rect(canvas, margin_left, margin_top, margin_left + chart_width, margin_top, (150, 150, 150))
    _fill_rect(
        canvas,
        margin_left,
        margin_top + chart_height,
        margin_left + chart_width,
        margin_top + chart_height,
        (150, 150, 150),
    )
    _fill_rect(canvas, margin_left, margin_top, margin_left, margin_top + chart_height, (150, 150, 150))
    _fill_rect(
        canvas,
        margin_left + chart_width,
        margin_top,
        margin_left + chart_width,
        margin_top + chart_height,
        (150, 150, 150),
    )

    section_top = margin_top + chart_height + 45
    top = sorted(new_max_countries, key=lambda item: item[1], reverse=True)[:8]
    bar_left = margin_left
    bar_top = section_top + 20
    for idx, (country, score) in enumerate(top):
        y = bar_top + idx * 22
        bar_len = int(score * 260)
        _fill_rect(canvas, bar_left + 90, y + 2, bar_left + 90 + bar_len, y + 12, (220, 90, 70))

    trigger_text = ", ".join(triggers) if triggers else "none"
    key_countries = ", ".join(country for country, _score in top[:5])
    text_chunks = [
        ("Title", "Internet Shrinkage Index Significant Change"),
        ("Trigger", trigger_text),
        ("Countries", key_countries[:180]),
        ("DateRange", f"{dates[0] if dates else ''}..{dates[-1] if dates else ''}"),
    ]
    _save_png(output_path, canvas, text_chunks=text_chunks)


def _write_latest_summary(
    run_date: str,
    historical_outputs: Dict[str, Dict[str, Any]],
    current_new_max_count: int,
    current_mass_event: bool,
    chart_exists: bool,
) -> None:
    repo = _repo_root()
    latest_dir = repo / "data" / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)

    recent_dates = _date_range_inclusive(run_date, 7)
    last_7_days: List[Dict[str, Any]] = []
    for date_str in recent_dates:
        if date_str == run_date:
            payload = {
                "summary_stats": {
                    "new_max_count": current_new_max_count,
                    "mass_event": current_mass_event,
                }
            }
        else:
            payload = historical_outputs.get(date_str, {})
        summary_stats = payload.get("summary_stats") if isinstance(payload, dict) else None
        new_max_count = 0
        mass_event = False
        if isinstance(summary_stats, dict):
            raw_new_max = summary_stats.get("new_max_count")
            raw_mass = summary_stats.get("mass_event")
            if isinstance(raw_new_max, int):
                new_max_count = raw_new_max
            if isinstance(raw_mass, bool):
                mass_event = raw_mass
        last_7_days.append(
            {
                "date_utc": date_str,
                "new_max_count": new_max_count,
                "mass_event": mass_event,
            }
        )

    summary_payload: Dict[str, Any] = {
        "observer": OBSERVER,
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
        "latest_date_utc": run_date,
        "last_7_days": last_7_days,
    }
    if chart_exists:
        summary_payload["chart_path"] = "data/latest/chart.png"

    (latest_dir / "summary.json").write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run() -> Dict[str, Any]:
    run_date = _run_date()
    repo = _repo_root()

    history_lookback = max(BASELINE_DAYS + 7, PEAK_LOOKBACK_DAYS + 2)
    historical_outputs = _load_historical_outputs(run_date, history_lookback)

    bad_series_by_country = _build_country_daily_bad_series(run_date)
    reachability_bad, asn_bad, ipv6_bad, silence_today = _extract_signal_maps(run_date)

    countries_today = sorted(set(reachability_bad) | set(asn_bad) | set(ipv6_bad) | set(silence_today))

    countries_payload: List[Dict[str, Any]] = []
    new_max_countries: List[Tuple[str, float]] = []

    for country in countries_today:
        score, components = _compute_country_components(country, run_date, bad_series_by_country, silence_today)
        history_rows = _extract_historical_country_scores(historical_outputs, country)
        previous_scores = [value for date_str, value in history_rows if date_str < run_date]

        baseline_values = previous_scores[-BASELINE_DAYS:]
        baseline_mean = _mean(baseline_values) or 0.0
        baseline_std = _stddev(baseline_values, baseline_mean) if baseline_values else 0.0

        delta = score - baseline_mean
        previous_max = max(previous_scores) if previous_scores else None
        is_new_max = previous_max is None or score > previous_max
        if is_new_max:
            new_max_countries.append((country, score))

        countries_payload.append(
            {
                "country": country,
                "shrinkage_score": round(score, 6),
                "components": {
                    "trend": None if components["trend"] is None else round(components["trend"], 6),
                    "distance_to_peak": None
                    if components["distance_to_peak"] is None
                    else round(components["distance_to_peak"], 6),
                    "persistence": None
                    if components["persistence"] is None
                    else round(components["persistence"], 6),
                    "silence_modifier": None
                    if components["silence_modifier"] is None
                    else round(components["silence_modifier"], 6),
                },
                "baseline_30d": {
                    "mean": round(baseline_mean, 6),
                    "std": round(baseline_std, 6),
                },
                "delta": round(delta, 6),
                "is_new_max": is_new_max,
            }
        )

    global_score = _mean(item["shrinkage_score"] for item in countries_payload) or 0.0
    global_history_rows = _extract_historical_global_scores(historical_outputs)
    previous_global = [value for date_str, value in global_history_rows if date_str < run_date]

    global_baseline_values = previous_global[-BASELINE_DAYS:]
    global_baseline_mean = _mean(global_baseline_values) or 0.0
    global_baseline_std = _stddev(global_baseline_values, global_baseline_mean) if global_baseline_values else 0.0
    if countries_payload:
        global_is_new_max = (max(previous_global) if previous_global else None) is None or (
            previous_global and global_score > max(previous_global)
        )
        if not previous_global:
            global_is_new_max = True
    else:
        global_is_new_max = False

    new_max_count = sum(1 for item in countries_payload if item["is_new_max"])
    mass_event = new_max_count >= MASS_EVENT_K

    global_recent = [value for _date_str, value in global_history_rows[-7:]] + [global_score]
    global_prior = [value for _date_str, value in global_history_rows[-BASELINE_DAYS:]]
    recent_slope = _linear_slope(global_recent) if len(global_recent) >= 2 else None
    prior_slope = _linear_slope(global_prior) if len(global_prior) >= 2 else None
    trend_regime_change = False
    if recent_slope is not None:
        if prior_slope is None:
            trend_regime_change = abs(recent_slope) >= REGIME_SLOPE_THRESHOLD
        else:
            trend_regime_change = abs(recent_slope) >= REGIME_SLOPE_THRESHOLD and abs(recent_slope) >= (
                abs(prior_slope) * REGIME_MULTIPLIER
            )

    triggers: List[str] = []
    if any(item["is_new_max"] for item in countries_payload):
        triggers.append("country_new_max")
    if global_is_new_max:
        triggers.append("global_new_max")
    if mass_event:
        triggers.append("mass_event")
    if trend_regime_change:
        triggers.append("trend_regime_change")

    any_significant = bool(triggers) and bool(countries_payload)

    chart_path = repo / "data" / "latest" / "chart.png"
    if any_significant:
        global_for_chart = (global_history_rows + [(run_date, global_score)])[-30:]
        _chart_image(global_for_chart, new_max_countries, triggers, chart_path)
    elif chart_path.exists():
        chart_path.unlink()

    _write_latest_summary(run_date, historical_outputs, new_max_count, mass_event, chart_path.exists())

    data_status = "ok"
    if not countries_payload:
        data_status = "unavailable"
    elif not (reachability_bad and asn_bad and ipv6_bad):
        data_status = "partial"

    return {
        "observer": OBSERVER,
        "date_utc": run_date,
        "data_status": data_status,
        "countries": countries_payload,
        "global": {
            "global_shrinkage_index": round(global_score, 6),
            "baseline_30d": {
                "mean": round(global_baseline_mean, 6),
                "std": round(global_baseline_std, 6),
            },
            "is_new_max": global_is_new_max,
        },
        "summary_stats": {
            "countries_evaluated": len(countries_payload),
            "new_max_count": new_max_count,
            "mass_event": mass_event,
        },
        "significance": {
            "any_significant": any_significant,
            "triggers": triggers,
        },
    }


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
