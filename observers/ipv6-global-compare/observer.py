"""Compare country IPv6 adoption against global IPv6 trend using daily JSON inputs only."""

from __future__ import annotations

import json
import os
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Tuple

OBSERVER = "ipv6-global-compare"
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
        "input_observer": str(payload.get("input_observer", "ipv6-locked-states")),
        "baseline_window_days": max(1, int(payload.get("baseline_window_days", 30))),
        "trend_window_days": max(2, int(payload.get("trend_window_days", 7))),
        "sigma_mult": float(payload.get("sigma_mult", 2.0)),
        "mass_event_k": max(1, int(payload.get("mass_event_k", 3))),
        "divergence_min_global_slope": float(payload.get("divergence_min_global_slope", 0.001)),
        "divergence_max_country_slope": float(payload.get("divergence_max_country_slope", 0.0)),
        "top_countries_in_chart": max(3, int(payload.get("top_countries_in_chart", 6))),
    }


def _day_input_paths(day: str, input_observer: str) -> List[Path]:
    names = [input_observer]
    if input_observer == "ipv6-locked-states":
        names.append("ipv6-adoption-locked-states")
    return [DAILY_ROOT / day / f"{name}.json" for name in names]


def _load_input_payload(day: str, input_observer: str) -> Dict[str, Any]:
    for path in _day_input_paths(day, input_observer):
        payload = _load_json(path, {})
        if isinstance(payload, dict) and payload:
            return payload
    return {}


def _extract_countries(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = payload.get("countries")
    if not isinstance(rows, list):
        return []
    result: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        country = str(row.get("country", "")).strip()
        if not country:
            continue
        raw_rate = row.get("ipv6_capable_rate")
        try:
            rate = float(raw_rate)
        except (TypeError, ValueError):
            continue
        if rate < 0:
            rate = 0.0
        if rate > 1:
            rate = 1.0
        result.append({"country": country, "ipv6_rate": rate})
    return result


def _global_rate(countries: List[Dict[str, Any]]) -> Optional[float]:
    if not countries:
        return None
    return mean(float(item["ipv6_rate"]) for item in countries)


def _history_days(date_utc: str, count: int) -> List[str]:
    start = datetime.strptime(date_utc, "%Y-%m-%d").date()
    return [(start - timedelta(days=offset)).isoformat() for offset in range(count)]


def _country_delta_history(country: str, date_utc: str, cfg: Dict[str, Any]) -> List[float]:
    values: List[float] = []
    current = datetime.strptime(date_utc, "%Y-%m-%d").date()
    for offset in range(1, cfg["baseline_window_days"] + 1):
        day = (current - timedelta(days=offset)).isoformat()
        payload = _load_json(DAILY_ROOT / day / f"{OBSERVER}.json", {})
        if not isinstance(payload, dict):
            continue
        countries = payload.get("countries")
        if not isinstance(countries, list):
            continue
        for row in countries:
            if not isinstance(row, dict) or str(row.get("country", "")) != country:
                continue
            try:
                values.append(float(row.get("delta_vs_global")))
            except (TypeError, ValueError):
                pass
            break
    return values


def _baseline(values: List[float]) -> Tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], 0.0
    return mean(values), pstdev(values)


def _z(value: float, avg: float, std: float) -> float:
    if std <= 0:
        return 0.0
    return (value - avg) / std


def _daily_country_rates(day: str, input_observer: str) -> Dict[str, float]:
    payload = _load_input_payload(day, input_observer)
    if not isinstance(payload, dict):
        return {}
    countries = _extract_countries(payload)
    return {item["country"]: float(item["ipv6_rate"]) for item in countries}


def _daily_global_rate(day: str, input_observer: str) -> Optional[float]:
    payload = _load_input_payload(day, input_observer)
    if not isinstance(payload, dict):
        return None
    countries = _extract_countries(payload)
    return _global_rate(countries)


def _slope(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    n = len(values)
    xs = list(range(n))
    x_avg = mean(xs)
    y_avg = mean(values)
    denom = sum((x - x_avg) ** 2 for x in xs)
    if denom <= 0:
        return 0.0
    return sum((x - x_avg) * (y - y_avg) for x, y in zip(xs, values)) / denom


def _trend_slopes(date_utc: str, country: str, cfg: Dict[str, Any]) -> Tuple[float, float]:
    days = list(reversed(_history_days(date_utc, cfg["trend_window_days"])))
    country_series: List[float] = []
    global_series: List[float] = []
    for day in days:
        rates = _daily_country_rates(day, cfg["input_observer"])
        global_rate = _daily_global_rate(day, cfg["input_observer"])
        if global_rate is None:
            continue
        if country not in rates:
            continue
        country_series.append(rates[country])
        global_series.append(global_rate)
    return _slope(country_series), _slope(global_series)


def _percentile_position(value: float, population: List[float]) -> float:
    if not population:
        return 0.0
    leq = sum(1 for item in population if item <= value)
    return leq / len(population)


def _write_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return len(data).to_bytes(4, "big") + chunk_type + data + crc.to_bytes(4, "big")


def _draw_line(canvas: List[List[Tuple[int, int, int]]], x0: int, y0: int, x1: int, y1: int, color: Tuple[int, int, int]) -> None:
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        if 0 <= y < len(canvas) and 0 <= x < len(canvas[0]):
            canvas[y][x] = color
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


def _render_chart(countries: List[Dict[str, Any]], date_utc: str, triggers: List[str], cfg: Dict[str, Any]) -> None:
    width, height = 960, 420
    background = (16, 18, 24)
    divergence_color = (255, 120, 100)
    global_color = (100, 200, 255)

    canvas = [[background for _ in range(width)] for _ in range(height)]

    strongest = sorted(
        countries,
        key=lambda row: abs(float(row.get("z", 0.0))),
        reverse=True,
    )[: cfg["top_countries_in_chart"]]

    left, top, plot_h, bar_w = 80, 70, 220, 80
    max_abs_delta = max([0.01] + [abs(float(row.get("delta_vs_global", 0.0))) for row in strongest])
    for i, row in enumerate(strongest):
        center_x = left + i * (bar_w + 20)
        delta = float(row.get("delta_vs_global", 0.0))
        scaled = int((abs(delta) / max_abs_delta) * (plot_h // 2))
        base_y = top + plot_h // 2
        if delta >= 0:
            y0, y1 = base_y - scaled, base_y
        else:
            y0, y1 = base_y, base_y + scaled
        for y in range(max(0, y0), min(height, y1 + 1)):
            for x in range(max(0, center_x), min(width, center_x + bar_w)):
                canvas[y][x] = divergence_color

    trend_days = list(reversed(_history_days(date_utc, 14)))
    globals_series: List[float] = []
    for day in trend_days:
        g = _daily_global_rate(day, cfg["input_observer"])
        if g is not None:
            globals_series.append(g)
    if len(globals_series) >= 2:
        min_v, max_v = min(globals_series), max(globals_series)
        span = max(0.001, max_v - min_v)
        x_start, x_end = 560, 920
        y_start, y_end = 80, 300
        points: List[Tuple[int, int]] = []
        for i, value in enumerate(globals_series):
            xp = x_start + int((i / (len(globals_series) - 1)) * (x_end - x_start))
            yp = y_end - int(((value - min_v) / span) * (y_end - y_start))
            points.append((xp, yp))
        for p0, p1 in zip(points, points[1:]):
            _draw_line(canvas, p0[0], p0[1], p1[0], p1[1], global_color)

    pixels = bytearray()
    for row in canvas:
        pixels.append(0)
        for r, g, b in row:
            pixels.extend((r, g, b))

    description = f"{OBSERVER} {date_utc} | triggers: {'; '.join(triggers[:4])}"
    text_chunk = _write_chunk(b"tEXt", b"Description\x00" + description.encode("latin-1", errors="replace"))

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    png.extend(_write_chunk(b"IHDR", ihdr))
    png.extend(text_chunk)
    png.extend(_write_chunk(b"IDAT", zlib.compress(bytes(pixels), level=6)))
    png.extend(_write_chunk(b"IEND", b""))

    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_CHART_PATH.write_bytes(bytes(png))


def _last_7_days(date_utc: str) -> List[Dict[str, Any]]:
    today = datetime.strptime(date_utc, "%Y-%m-%d").date()
    rows: List[Dict[str, Any]] = []
    for offset in range(7):
        day = (today - timedelta(days=offset)).isoformat()
        payload = _load_json(DAILY_ROOT / day / f"{OBSERVER}.json", {})
        if not isinstance(payload, dict):
            continue
        stats = payload.get("summary_stats", {})
        if not isinstance(stats, dict):
            stats = {}
        rows.append(
            {
                "date_utc": day,
                "significant_count": int(stats.get("significant_count", 0)),
                "mass_event": bool(stats.get("mass_event", False)),
            }
        )
    return rows


def _write_latest_summary(date_utc: str) -> None:
    payload: Dict[str, Any] = {
        "observer": OBSERVER,
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
        "latest_date_utc": date_utc,
        "last_7_days": _last_7_days(date_utc),
    }
    if LATEST_CHART_PATH.exists():
        payload["chart_path"] = "data/latest/chart.png"
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_SUMMARY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run() -> Dict[str, Any]:
    cfg = _load_config()
    date_utc = _date_utc()
    input_payload = _load_input_payload(date_utc, cfg["input_observer"])
    data_status = "unavailable"
    if isinstance(input_payload, dict):
        data_status = str(input_payload.get("data_status", "partial"))

    source_countries = _extract_countries(input_payload if isinstance(input_payload, dict) else {})
    global_today = _global_rate(source_countries)

    if global_today is None:
        if LATEST_CHART_PATH.exists():
            LATEST_CHART_PATH.unlink()
        _write_latest_summary(date_utc)
        return {
            "observer": OBSERVER,
            "date_utc": date_utc,
            "data_status": "unavailable",
            "countries": [],
            "summary_stats": {
                "countries_evaluated": 0,
                "significant_count": 0,
                "mass_event": False,
            },
            "significance": {
                "sigma_mult": cfg["sigma_mult"],
                "any_significant": False,
                "triggers": ["input_unavailable"],
            },
        }

    all_deltas = [float(item["ipv6_rate"]) - global_today for item in source_countries]
    countries: List[Dict[str, Any]] = []
    triggers: List[str] = []

    for item in source_countries:
        country = str(item["country"])
        ipv6_rate = float(item["ipv6_rate"])
        delta = ipv6_rate - global_today
        hist = _country_delta_history(country, date_utc, cfg)
        base_mean, base_std = _baseline(hist)
        z_value = _z(delta, base_mean, base_std)
        country_slope, global_slope = _trend_slopes(date_utc, country, cfg)
        trend_delta = country_slope - global_slope

        trend_divergence = (
            country_slope <= cfg["divergence_max_country_slope"]
            and global_slope >= cfg["divergence_min_global_slope"]
        )
        is_significant = abs(z_value) > cfg["sigma_mult"] or trend_divergence

        percentile = _percentile_position(delta, all_deltas)

        if is_significant:
            reason = f"{country}: z={round(z_value, 3)}"
            if trend_divergence:
                reason += f", trend_div(country={round(country_slope, 6)}, global={round(global_slope, 6)})"
            triggers.append(reason)

        countries.append(
            {
                "country": country,
                "ipv6_rate": round(ipv6_rate, 6),
                "global_ipv6_rate": round(global_today, 6),
                "delta_vs_global": round(delta, 6),
                "trend_delta": round(trend_delta, 6),
                "percentile_position": round(percentile, 6),
                "baseline_30d": {
                    "mean": round(base_mean, 6),
                    "std": round(base_std, 6),
                },
                "z": round(z_value, 3),
                "is_significant": is_significant,
            }
        )

    significant_count = sum(1 for row in countries if row["is_significant"])
    mass_event = significant_count >= cfg["mass_event_k"]
    if mass_event:
        triggers.append("mass_event")
    any_significant = significant_count > 0

    if any_significant:
        _render_chart(countries, date_utc, triggers, cfg)
    elif LATEST_CHART_PATH.exists():
        LATEST_CHART_PATH.unlink()

    _write_latest_summary(date_utc)

    return {
        "observer": OBSERVER,
        "date_utc": date_utc,
        "data_status": data_status,
        "countries": sorted(countries, key=lambda row: row["country"]),
        "summary_stats": {
            "countries_evaluated": len(countries),
            "significant_count": significant_count,
            "mass_event": mass_event,
        },
        "significance": {
            "sigma_mult": cfg["sigma_mult"],
            "any_significant": any_significant,
            "triggers": triggers,
        },
    }


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
