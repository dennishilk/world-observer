"""Observer for area51-reachability using aggregated airspace activity units (AU)."""

from __future__ import annotations

import json
import math
import os
import sys
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import urlopen

OBSERVER_NAME = "area51-reachability"
MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
RAW_STATE_DIR = REPO_ROOT / "state" / "area51-reachability"


@dataclass
class Config:
    bucket_minutes: int
    sigma_mult: float
    baseline_window: int
    bbox: Dict[str, float]
    source_url: str
    request_timeout_s: int


def _load_config() -> Config:
    payload = json.loads((MODULE_DIR / "config.json").read_text(encoding="utf-8"))
    return Config(
        bucket_minutes=int(payload.get("bucket_minutes", 15)),
        sigma_mult=float(payload.get("sigma_mult", 2.0)),
        baseline_window=int(payload.get("baseline_window", 30)),
        bbox=dict(payload.get("bbox", {})),
        source_url=str(payload.get("source", {}).get("url", "https://opensky-network.org/api/states/all")),
        request_timeout_s=int(payload.get("source", {}).get("timeout_s", 15)),
    )


def _target_date_utc() -> date:
    env_date = os.getenv("WORLD_OBSERVER_DATE_UTC")
    if env_date:
        return datetime.strptime(env_date, "%Y-%m-%d").date()
    return datetime.now(timezone.utc).date()


def _bucket_count(bucket_minutes: int) -> int:
    return (24 * 60) // bucket_minutes


def _load_raw_day(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"buckets": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"buckets": {}}
    if not isinstance(payload, dict):
        return {"buckets": {}}
    buckets = payload.get("buckets")
    if not isinstance(buckets, dict):
        payload["buckets"] = {}
    return payload


def _save_raw_day(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fetch_aircraft(url: str, timeout_s: int) -> Optional[List[Dict[str, Any]]]:
    max_attempts = 3
    backoff_delays_s = (1, 2)

    for attempt in range(max_attempts):
        try:
            with urlopen(url, timeout=timeout_s) as response:  # nosec - public data API
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            if attempt < max_attempts - 1:
                delay = backoff_delays_s[attempt]
                print(
                    f"[{OBSERVER_NAME}] fetch attempt {attempt + 1}/{max_attempts} failed ({exc}); retrying in {delay}s",
                    file=sys.stderr,
                )
                time_module.sleep(delay)
                continue
            return None

        if isinstance(payload, dict):
            aircraft = payload.get("ac")
            if isinstance(aircraft, list):
                filtered: List[Dict[str, Any]] = []
                for item in aircraft:
                    if isinstance(item, dict):
                        filtered.append(item)
                return filtered

            states = payload.get("states")
            if isinstance(states, list):
                normalized: List[Dict[str, Any]] = []
                for state in states:
                    if not isinstance(state, list) or len(state) < 14:
                        continue
                    normalized.append(
                        {
                            "lon": state[5],
                            "lat": state[6],
                            "alt_baro": state[7],
                            "gs": state[9],
                            "track": state[10],
                            "alt_geom": state[13],
                        }
                    )
                return normalized

        if attempt < max_attempts - 1:
            delay = backoff_delays_s[attempt]
            print(
                f"[{OBSERVER_NAME}] fetch attempt {attempt + 1}/{max_attempts} returned null/invalid aircraft data; retrying in {delay}s",
                file=sys.stderr,
            )
            time_module.sleep(delay)

    return None


def _in_bbox(item: Dict[str, Any], bbox: Dict[str, float]) -> bool:
    lat = item.get("lat")
    lon = item.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    return (
        bbox["min_lat"] <= float(lat) <= bbox["max_lat"]
        and bbox["min_lon"] <= float(lon) <= bbox["max_lon"]
    )


def _is_moving(item: Dict[str, Any]) -> bool:
    gs = item.get("gs")
    return isinstance(gs, (int, float)) and float(gs) >= 30.0


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _segment_kinematic_score(item: Dict[str, Any], bucket_start: datetime) -> float:
    """Score anonymous movement segments by repetitive/stable kinematic patterns only."""
    score = 0.0

    speed = _to_float(item.get("gs"))
    altitude = _to_float(item.get("alt_baro"))
    if altitude is None:
        altitude = _to_float(item.get("alt_geom"))
    heading = _to_float(item.get("track"))

    if speed is not None and 120.0 <= speed <= 320.0:
        score += 1.0
    if altitude is not None and 4000.0 <= altitude <= 18000.0:
        score += 1.0
    if heading is not None and 30.0 <= heading <= 330.0:
        score += 0.5

    hour = bucket_start.hour
    if 13 <= hour <= 23:
        score += 0.5

    return score


def _is_janet_like(item: Dict[str, Any], bucket_start: datetime) -> bool:
    return _segment_kinematic_score(item, bucket_start) >= 2.0


def _current_bucket_start(target_day: date, bucket_minutes: int) -> datetime:
    now = datetime.now(timezone.utc)
    if now.date() != target_day:
        return datetime.combine(target_day, time.min, tzinfo=timezone.utc) + timedelta(
            minutes=((24 * 60) // bucket_minutes - 1) * bucket_minutes
        )
    minutes = (now.hour * 60 + now.minute) // bucket_minutes * bucket_minutes
    return datetime.combine(target_day, time.min, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _summarize_bucket(ac: List[Dict[str, Any]], config: Config, bucket_start: datetime) -> Dict[str, int]:
    total = 0
    janet_like = 0
    for item in ac:
        if not _in_bbox(item, config.bbox):
            continue
        if not _is_moving(item):
            continue
        total += 1
        if _is_janet_like(item, bucket_start):
            janet_like += 1
    return {"total": total, "janet_like": janet_like, "other": max(total - janet_like, 0)}


def _collect_day_activity(config: Config, target_day: date) -> Tuple[Dict[str, Any], str]:
    raw_path = RAW_STATE_DIR / f"{target_day.isoformat()}.json"
    raw_state = _load_raw_day(raw_path)
    buckets = raw_state.setdefault("buckets", {})

    bucket_start = _current_bucket_start(target_day, config.bucket_minutes)
    key = bucket_start.strftime("%H:%M")
    query = urlencode(
        {
            "lamin": config.bbox["min_lat"],
            "lamax": config.bbox["max_lat"],
            "lomin": config.bbox["min_lon"],
            "lomax": config.bbox["max_lon"],
        }
    )
    separator = "&" if "?" in config.source_url else "?"
    source_url = f"{config.source_url}{separator}{query}"
    fetched = _fetch_aircraft(source_url, config.request_timeout_s)

    status = "ok"
    if fetched is None:
        status = "partial" if buckets else "unavailable"
    else:
        summary = _summarize_bucket(fetched, config, bucket_start)
        buckets[key] = summary
        _save_raw_day(raw_path, raw_state)

    expected = _bucket_count(config.bucket_minutes)
    present = len([v for v in buckets.values() if isinstance(v, dict)])
    if present == 0:
        status = "unavailable"
    elif present < expected:
        status = "partial"

    totals = {"total": 0, "janet_like": 0, "other": 0}
    for value in buckets.values():
        if not isinstance(value, dict):
            continue
        for k in totals:
            v = value.get(k)
            if isinstance(v, int):
                totals[k] += v

    return {
        "bucket_count": present,
        "expected_bucket_count": expected,
        "au": totals,
    }, status


def _safe_float(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _load_daily_series(class_name: str, window: int, target_day: date) -> List[float]:
    values: List[float] = []
    daily_root = REPO_ROOT / "data" / "daily"
    for i in range(1, window + 1):
        day = target_day - timedelta(days=i)
        path = daily_root / day.isoformat() / f"{OBSERVER_NAME}.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        au = payload.get("au") if isinstance(payload, dict) else None
        if not isinstance(au, dict):
            continue
        value = _safe_float(au.get(class_name))
        if value is not None:
            values.append(value)
    return values


def _mean_std(values: List[float]) -> Tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return mean, math.sqrt(variance)


def _zscore(observed: int, mean: float, std: float) -> float:
    if std <= 0:
        return 0.0
    return (observed - mean) / std


def _build_chart_if_significant(target_day: date, latest: Dict[str, Any], window: int) -> Optional[str]:
    try:
        import matplotlib.pyplot as plt  # type: ignore
    except ImportError:
        return None

    dates: List[str] = []
    janet_vals: List[float] = []
    other_vals: List[float] = []
    total_vals: List[float] = []
    for i in range(window - 1, 0, -1):
        day = target_day - timedelta(days=i)
        path = REPO_ROOT / "data" / "daily" / day.isoformat() / f"{OBSERVER_NAME}.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        au = payload.get("au")
        if not isinstance(au, dict):
            continue
        j = _safe_float(au.get("janet_like"))
        o = _safe_float(au.get("other"))
        t = _safe_float(au.get("total"))
        if j is None or o is None or t is None:
            continue
        dates.append(day.isoformat())
        janet_vals.append(j)
        other_vals.append(o)
        total_vals.append(t)

    dates.append(target_day.isoformat())
    janet_vals.append(float(latest["au"]["janet_like"]))
    other_vals.append(float(latest["au"]["other"]))
    total_vals.append(float(latest["au"]["total"]))

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(dates, janet_vals, label="janet_like")
    ax.plot(dates, other_vals, label="other")
    ax.plot(dates, total_vals, label="total")

    for class_name, color in [("janet_like", "C0"), ("other", "C1"), ("total", "C2")]:
        mean = latest["baseline_30d"][class_name]["mean"]
        upper = mean + (latest["significance"]["sigma_mult"] * latest["baseline_30d"][class_name]["std"])
        ax.axhline(mean, linestyle="--", linewidth=0.8, color=color, alpha=0.35)
        ax.axhline(upper, linestyle=":", linewidth=0.8, color=color, alpha=0.35)

    ax.scatter([dates[-1]], [total_vals[-1]], color="red", zorder=4)
    ax.set_title("area51-reachability AU daily sums (30-day context)")
    ax.set_ylabel("Activity Units (AU)")
    ax.tick_params(axis="x", labelrotation=45)
    ax.legend()
    fig.tight_layout()

    chart_path = REPO_ROOT / "data" / "latest" / "chart.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(chart_path, dpi=150)
    plt.close(fig)
    return "data/latest/chart.png"


def _write_latest_summary(target_day: date, daily_payload: Dict[str, Any], chart_path: Optional[str]) -> None:
    latest_dir = REPO_ROOT / "data" / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)

    last7: List[Dict[str, Any]] = []
    for i in range(6, -1, -1):
        day = target_day - timedelta(days=i)
        path = REPO_ROOT / "data" / "daily" / day.isoformat() / f"{OBSERVER_NAME}.json"
        if day == target_day:
            payload = daily_payload
        elif path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
        else:
            continue
        au = payload.get("au") if isinstance(payload, dict) else None
        sig = payload.get("significance") if isinstance(payload, dict) else None
        if not isinstance(au, dict) or not isinstance(sig, dict):
            continue
        last7.append(
            {
                "date_utc": day.isoformat(),
                "au": {
                    "janet_like": int(au.get("janet_like", 0)),
                    "other": int(au.get("other", 0)),
                    "total": int(au.get("total", 0)),
                },
                "any_significant": bool(sig.get("any_significant", False)),
            }
        )

    summary = {
        "observer": OBSERVER_NAME,
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
        "latest_date_utc": target_day.isoformat(),
        "last_7_days": last7,
        "chart_path": chart_path,
    }

    (latest_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run() -> Dict[str, Any]:
    config = _load_config()
    target_day = _target_date_utc()
    collection, status = _collect_day_activity(config, target_day)

    observed = collection["au"]
    baseline: Dict[str, Dict[str, float]] = {}
    significance: Dict[str, Any] = {"sigma_mult": config.sigma_mult}

    any_sig = False
    for class_name in ["janet_like", "other", "total"]:
        series = _load_daily_series(class_name, config.baseline_window, target_day)
        mean, std = _mean_std(series)
        z = _zscore(int(observed[class_name]), mean, std)
        sig = bool(std > 0 and observed[class_name] > (mean + config.sigma_mult * std))
        baseline[class_name] = {"mean": round(mean, 4), "std": round(std, 4)}
        significance[class_name] = {"is_significant": sig, "z": round(z, 4)}
        any_sig = any_sig or sig

    significance["any_significant"] = any_sig

    payload = {
        "observer": OBSERVER_NAME,
        "date_utc": target_day.isoformat(),
        "data_status": status,
        "bucket_minutes": config.bucket_minutes,
        "bbox": config.bbox,
        "bucket_count": collection["bucket_count"],
        "au": {
            "janet_like": int(observed["janet_like"]),
            "other": int(observed["other"]),
            "total": int(observed["total"]),
        },
        "baseline_30d": baseline,
        "significance": significance,
    }

    chart_path = _build_chart_if_significant(target_day, payload, config.baseline_window) if any_sig else None
    _write_latest_summary(target_day, payload, chart_path)

    return payload


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
