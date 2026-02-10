"""Observer for IPv6 adoption in configured locked states using APNIC Labs aggregates."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Optional, Tuple

OBSERVER_NAME = "ipv6-locked-states"
MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
CONFIG_PATH = MODULE_DIR / "config.json"
DAILY_DIR = REPO_ROOT / "data" / "daily"
LATEST_DIR = REPO_ROOT / "data" / "latest"
LATEST_SUMMARY_PATH = LATEST_DIR / "summary.json"
CHART_PATH = LATEST_DIR / "chart.png"
CACHE_DIR = MODULE_DIR / ".cache"


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _resolve_date_utc() -> str:
    override = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if not override:
        return _today_utc()
    try:
        return datetime.strptime(override, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return _today_utc()


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_config() -> Dict[str, Any]:
    payload = _load_json(CONFIG_PATH)
    if payload is None:
        raise RuntimeError(f"Invalid config at {CONFIG_PATH}")
    return payload


def _normalize_rate(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value > 1.0:
        value = value / 100.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _to_int(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _extract_point(candidate: Dict[str, Any]) -> Tuple[Optional[float], Optional[int], Optional[str]]:
    date_value = candidate.get("date") or candidate.get("day") or candidate.get("x")
    if isinstance(date_value, str):
        date_value = date_value[:10]

    for key in (
        "v6capable",
        "v6_capable",
        "ipv6",
        "value",
        "y",
        "percent",
        "pct",
        "v6",
    ):
        if key in candidate:
            rate = _normalize_rate(candidate.get(key))
            if rate is not None:
                sample = _to_int(candidate.get("samples") or candidate.get("sample_size") or candidate.get("n"))
                return rate, sample, date_value if isinstance(date_value, str) else None
    return None, None, date_value if isinstance(date_value, str) else None


def _extract_latest_measurement(payload: Dict[str, Any], target_date: str) -> Tuple[Optional[float], Optional[int], str]:
    sequences: List[Iterable[Any]] = []
    for key in ("series", "data", "results", "measurements", "timeline"):
        value = payload.get(key)
        if isinstance(value, list):
            sequences.append(value)

    points: List[Tuple[Optional[str], float, Optional[int]]] = []
    for sequence in sequences:
        for item in sequence:
            if isinstance(item, dict):
                rate, sample, day = _extract_point(item)
                if rate is not None:
                    points.append((day, rate, sample))

    if not points:
        rate = _normalize_rate(payload.get("v6capable") or payload.get("ipv6") or payload.get("value"))
        sample = _to_int(payload.get("samples") or payload.get("sample_size") or payload.get("n"))
        if rate is None:
            return None, None, "unavailable"
        return rate, sample, "ok"

    dated_points = [point for point in points if point[0] == target_date]
    if dated_points:
        _, rate, sample = dated_points[-1]
        return rate, sample, "ok"

    with_dates = [point for point in points if point[0] is not None]
    with_dates.sort(key=lambda item: item[0])
    if with_dates:
        _, rate, sample = with_dates[-1]
        return rate, sample, "partial"

    _, rate, sample = points[-1]
    return rate, sample, "partial"


def _fetch_apnic_country(country: str, source: Dict[str, Any], target_date: str) -> Tuple[Optional[float], Optional[int], str, Optional[str]]:
    endpoints = source.get("endpoints", [])
    timeout_seconds = float(source.get("timeout_seconds", 20))
    if not isinstance(endpoints, list):
        endpoints = []

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for endpoint_template in endpoints:
        if not isinstance(endpoint_template, str) or "{country}" not in endpoint_template:
            continue
        url = endpoint_template.format(country=urllib.parse.quote(country))
        try:
            with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            continue

        cache_file = CACHE_DIR / f"{target_date}-{country}.json"
        cache_file.write_text(raw, encoding="utf-8")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        rate, sample_size, status = _extract_latest_measurement(payload, target_date)
        if rate is not None:
            return rate, sample_size, status, url

    return None, None, "unavailable", None


def _collect_history(country: str, date_utc: str, baseline_window_days: int) -> List[float]:
    today = datetime.strptime(date_utc, "%Y-%m-%d").date()
    values: List[float] = []
    for day_offset in range(1, baseline_window_days + 1):
        day = (today - timedelta(days=day_offset)).isoformat()
        daily_file = DAILY_DIR / day / f"{OBSERVER_NAME}.json"
        payload = _load_json(daily_file)
        if not payload:
            continue
        countries = payload.get("countries")
        if not isinstance(countries, list):
            continue
        for item in countries:
            if not isinstance(item, dict):
                continue
            if item.get("country") != country:
                continue
            value = _normalize_rate(item.get("ipv6_capable_rate"))
            if value is not None:
                values.append(value)
            break
    return values


def _baseline(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0}
    if len(values) == 1:
        return {"mean": values[0], "std": 0.0}
    return {"mean": mean(values), "std": pstdev(values)}


def _country_name_lookup(locked_states: List[Dict[str, str]]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for item in locked_states:
        code = str(item.get("country", "")).upper()
        if not code:
            continue
        names[code] = str(item.get("display_name") or code)
    return names


def _z_score(observed: float, baseline_mean: float, baseline_std: float) -> float:
    if baseline_std <= 0:
        return 0.0
    return (observed - baseline_mean) / baseline_std


def _significance_entry(country: str, observed: Optional[float], sample_size: Optional[int], status: str, baseline_cfg: Dict[str, Any], date_utc: str) -> Dict[str, Any]:
    if observed is None:
        return {
            "country": country,
            "ipv6_capable_rate": 0.0,
            "sample_size": sample_size,
            "baseline_30d": {"mean": 0.0, "std": 0.0},
            "delta_pp": 0.0,
            "z": 0.0,
            "is_significant": False,
            "data_status": "unavailable",
        }

    history = _collect_history(country, date_utc, int(baseline_cfg["baseline_window_days"]))
    baseline = _baseline(history)
    delta_pp = (observed - baseline["mean"]) * 100.0
    z_value = _z_score(observed, baseline["mean"], baseline["std"])

    significant = bool(
        abs(z_value) > float(baseline_cfg["sigma_mult"])
        or abs(delta_pp) >= float(baseline_cfg["step_threshold_pp"])
    )

    return {
        "country": country,
        "ipv6_capable_rate": round(observed, 6),
        "sample_size": sample_size,
        "baseline_30d": {
            "mean": round(baseline["mean"], 6),
            "std": round(baseline["std"], 6),
        },
        "delta_pp": round(delta_pp, 3),
        "z": round(z_value, 3),
        "is_significant": significant,
        "data_status": status,
    }


def _daily_data_status(countries: List[Dict[str, Any]]) -> str:
    statuses = {item.get("data_status") for item in countries}
    if statuses == {"ok"}:
        return "ok"
    if statuses == {"unavailable"}:
        return "unavailable"
    return "partial"


def _build_triggers(countries: List[Dict[str, Any]], mass_event: bool) -> List[str]:
    triggers: List[str] = []
    for item in countries:
        if not item.get("is_significant"):
            continue
        reasons: List[str] = []
        if abs(float(item.get("z", 0.0))) > 0:
            reasons.append(f"z={item['z']}")
        if abs(float(item.get("delta_pp", 0.0))) > 0:
            reasons.append(f"delta_pp={item['delta_pp']}")
        reason_text = ", ".join(reasons) if reasons else "threshold"
        triggers.append(f"{item['country']}: {reason_text}")
    if mass_event:
        triggers.append("mass_event")
    return triggers


def _write_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return len(data).to_bytes(4, "big") + chunk_type + data + crc.to_bytes(4, "big")


def _render_simple_png(countries: List[Dict[str, Any]], reasons: List[str], date_utc: str) -> None:
    width, height = 960, 420
    background = (16, 18, 24)
    bar_color = (80, 180, 255)
    baseline_color = (255, 200, 80)

    pixels = bytearray()
    canvas = [[background for _ in range(width)] for _ in range(height)]

    top = sorted(
        [item for item in countries if item.get("is_significant")],
        key=lambda item: max(abs(float(item.get("z", 0.0))), abs(float(item.get("delta_pp", 0.0)) / 5.0)),
        reverse=True,
    )[:5]

    bar_start_y = 80
    row_h = 60
    left = 250
    max_w = 620

    for idx, item in enumerate(top):
        y = bar_start_y + idx * row_h
        obs = float(item.get("ipv6_capable_rate", 0.0))
        base = float(item.get("baseline_30d", {}).get("mean", 0.0))
        obs_w = int(max_w * max(0.0, min(1.0, obs)))
        base_w = int(max_w * max(0.0, min(1.0, base)))

        for yy in range(y, min(y + 26, height)):
            for xx in range(left, min(left + obs_w, width)):
                canvas[yy][xx] = bar_color
        for yy in range(y + 30, min(y + 38, height)):
            for xx in range(left, min(left + base_w, width)):
                canvas[yy][xx] = baseline_color

    for y in range(height):
        pixels.append(0)
        for x in range(width):
            r, g, b = canvas[y][x]
            pixels.extend((r, g, b))

    text = f"{OBSERVER_NAME} {date_utc} | triggers: {'; '.join(reasons[:4])}"
    text_chunk = _write_chunk(b"tEXt", b"Description\x00" + text.encode("latin-1", errors="replace"))

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    png.extend(_write_chunk(b"IHDR", ihdr))
    png.extend(text_chunk)
    png.extend(_write_chunk(b"IDAT", zlib.compress(bytes(pixels), level=6)))
    png.extend(_write_chunk(b"IEND", b""))

    CHART_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHART_PATH.write_bytes(bytes(png))


def _last_7_days_summary(date_utc: str) -> Dict[str, Any]:
    today = datetime.strptime(date_utc, "%Y-%m-%d").date()
    rows: List[Dict[str, Any]] = []
    for day_offset in range(0, 7):
        day = (today - timedelta(days=day_offset)).isoformat()
        payload = _load_json(DAILY_DIR / day / f"{OBSERVER_NAME}.json")
        if not payload:
            continue
        stats = payload.get("summary_stats", {})
        rows.append(
            {
                "date_utc": day,
                "significant_count": int(stats.get("significant_count", 0)),
                "mass_event": bool(stats.get("mass_event", False)),
            }
        )
    return {"days": rows}


def _write_latest_summary(date_utc: str, any_significant: bool) -> None:
    payload: Dict[str, Any] = {
        "observer": OBSERVER_NAME,
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
        "latest_date_utc": date_utc,
        "last_7_days": _last_7_days_summary(date_utc),
    }
    if any_significant and CHART_PATH.exists():
        payload["chart_path"] = "data/latest/chart.png"

    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_SUMMARY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run() -> Dict[str, Any]:
    cfg = _load_config()
    date_utc = _resolve_date_utc()
    locked_states = cfg.get("locked_states", [])
    source = cfg.get("source", {})

    if not isinstance(locked_states, list):
        locked_states = []
    names = _country_name_lookup(locked_states)

    seed_countries = [str(item.get("country", "")).upper() for item in locked_states if isinstance(item, dict)]
    seed_countries = [country for country in seed_countries if country]

    baseline_cfg = {
        "baseline_window_days": int(cfg.get("baseline_window_days", 30)),
        "sigma_mult": float(cfg.get("sigma_mult", 2.0)),
        "step_threshold_pp": float(cfg.get("step_threshold_pp", 5.0)),
        "mass_event_k": int(cfg.get("mass_event_k", 3)),
    }

    countries: List[Dict[str, Any]] = []
    fetch_sources: List[str] = []
    for country in seed_countries:
        override_key = f"WORLD_OBSERVER_IPV6_LOCKED_STATES_MOCK_RATE_{country}"
        override = os.environ.get(override_key)
        if override is not None:
            observed = _normalize_rate(override)
            sample_size = None
            status = "ok" if observed is not None else "unavailable"
            used_source = f"env:{override_key}"
        else:
            observed, sample_size, status, used_source = _fetch_apnic_country(country, source, date_utc)

        if used_source:
            fetch_sources.append(f"{country}:{used_source}")

        entry = _significance_entry(country, observed, sample_size, status, baseline_cfg, date_utc)
        entry["display_name"] = names.get(country, country)
        countries.append(entry)

    significant_count = sum(1 for item in countries if item.get("is_significant"))
    mass_event = significant_count >= baseline_cfg["mass_event_k"]
    any_significant = significant_count > 0
    triggers = _build_triggers(countries, mass_event)

    payload = {
        "observer": OBSERVER_NAME,
        "date_utc": date_utc,
        "data_status": _daily_data_status(countries),
        "countries": [
            {
                "country": item["country"],
                "ipv6_capable_rate": item["ipv6_capable_rate"],
                "sample_size": item["sample_size"],
                "baseline_30d": item["baseline_30d"],
                "delta_pp": item["delta_pp"],
                "z": item["z"],
                "is_significant": item["is_significant"],
                "data_status": item["data_status"],
            }
            for item in countries
        ],
        "summary_stats": {
            "countries_evaluated": len(countries),
            "significant_count": significant_count,
            "mass_event": mass_event,
        },
        "significance": {
            "sigma_mult": baseline_cfg["sigma_mult"],
            "step_threshold_pp": baseline_cfg["step_threshold_pp"],
            "any_significant": any_significant,
            "triggers": triggers,
        },
        "source": {
            "provider": source.get("provider", "APNIC Labs"),
            "references": fetch_sources,
        },
    }

    if any_significant or mass_event:
        _render_simple_png(countries, triggers, date_utc)
    elif CHART_PATH.exists():
        CHART_PATH.unlink()

    _write_latest_summary(date_utc, any_significant or mass_event)
    return payload


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
