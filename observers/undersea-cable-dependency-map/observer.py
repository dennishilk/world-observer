"""undersea-cable-dependency-map observer.

Dataset-driven observer that computes per-country dependency/redundancy
metrics from a static undersea cable dataset.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import struct
import urllib.request
import zlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

OBSERVER = "undersea-cable-dependency-map"
MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
CONFIG_PATH = MODULE_DIR / "config.json"
CACHE_DIR = MODULE_DIR / ".cache"
DAILY_ROOT = REPO_ROOT / "data" / "daily"
LATEST_DIR = REPO_ROOT / "data" / "latest"
LATEST_SUMMARY_PATH = LATEST_DIR / "summary.json"
LATEST_CHART_PATH = LATEST_DIR / "chart.png"


def _date_utc() -> str:
    value = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if value:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
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
        "dataset_name": str(payload.get("dataset_name", "Greg's Cable Map derivative")).strip(),
        "dataset_url": str(payload.get("dataset_url", "")).strip(),
        "dataset_path": str(payload.get("dataset_path", "")).strip(),
        "last_updated_hint": str(payload.get("last_updated_hint", "")).strip(),
        "top_n": max(3, int(payload.get("top_n", 10))),
        "metric_delta_threshold": float(payload.get("metric_delta_threshold", 0.03)),
        "top_country_set_threshold": max(1, int(payload.get("top_country_set_threshold", 2))),
    }


def _cache_dataset(config: Dict[str, Any]) -> Path | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    url = config["dataset_url"]
    if not url:
        return None

    filename = url.rsplit("/", 1)[-1].strip() or "dataset.bin"
    cached_path = CACHE_DIR / filename
    if cached_path.exists():
        return cached_path

    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # nosec B310
            cached_path.write_bytes(response.read())
        return cached_path
    except Exception:
        return None


def _resolve_dataset_path(config: Dict[str, Any]) -> Path | None:
    user_path = config["dataset_path"]
    if user_path:
        p = Path(user_path)
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        if p.exists():
            return p

    cached = _cache_dataset(config)
    if cached and cached.exists():
        return cached

    # Fallback to legacy sample dataset to keep observer cron-safe.
    fallback = REPO_ROOT / "observers" / "undersea-cable-dependency" / "cables.json"
    if fallback.exists():
        return fallback
    return None


def _dataset_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _extract_country(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip().upper()
    if len(text) == 2 and text.isalpha():
        return text
    return value.strip()


def _normalize_landing(raw: Dict[str, Any]) -> Dict[str, str]:
    country = ""
    for key in ("country", "country_code", "iso2", "iso", "nation"):
        country = _extract_country(raw.get(key))
        if country:
            break
    name = str(raw.get("name", "")).strip()
    return {"country": country, "name": name}


def _countries_from_value(value: Any) -> List[str]:
    out: List[str] = []
    if isinstance(value, list):
        for item in value:
            c = _extract_country(item)
            if c:
                out.append(c)
    elif isinstance(value, str):
        pieces = [p.strip() for p in value.replace("|", ",").split(",")]
        out.extend([_extract_country(p) for p in pieces if p.strip()])
    return sorted(set([c for c in out if c]))


def _parse_json_dataset(path: Path) -> List[Set[str]]:
    payload = _load_json(path, {})
    cables: List[Set[str]] = []

    if isinstance(payload, list):
        # legacy simplified country->cables format
        for item in payload:
            if not isinstance(item, dict):
                continue
            country = _extract_country(item.get("country"))
            entries = item.get("cables", [])
            if not country or not isinstance(entries, list):
                continue
            for _cable in entries:
                cables.append({country})
        return cables

    if isinstance(payload, dict) and isinstance(payload.get("features"), list):
        # GeoJSON-like format
        for feature in payload.get("features", []):
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties", {})
            if not isinstance(props, dict):
                props = {}
            countries = set(_countries_from_value(props.get("countries", [])))
            if not countries:
                landings = props.get("landing_points", [])
                if isinstance(landings, list):
                    for landing in landings:
                        if isinstance(landing, dict):
                            parsed = _normalize_landing(landing)
                            if parsed["country"]:
                                countries.add(parsed["country"])
            if countries:
                cables.append(countries)

    if isinstance(payload, dict) and isinstance(payload.get("cables"), list):
        for cable in payload.get("cables", []):
            if not isinstance(cable, dict):
                continue
            countries = set(_countries_from_value(cable.get("countries", [])))
            if not countries:
                for landing in cable.get("landings", []):
                    if isinstance(landing, dict):
                        parsed = _normalize_landing(landing)
                        if parsed["country"]:
                            countries.add(parsed["country"])
            if countries:
                cables.append(countries)

    return cables


def _parse_csv_dataset(path: Path) -> List[Set[str]]:
    cables: Dict[str, Set[str]] = defaultdict(set)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not isinstance(row, dict):
                continue
            cable_id = str(row.get("cable_id") or row.get("cable") or row.get("name") or "").strip()
            country = ""
            for key in ("country", "country_code", "iso2", "iso"):
                country = _extract_country(row.get(key))
                if country:
                    break
            if cable_id and country:
                cables[cable_id].add(country)
    return [countries for countries in cables.values() if countries]


def _load_cable_country_sets(dataset_path: Path) -> List[Set[str]]:
    suffix = dataset_path.suffix.lower()
    if suffix in {".json", ".geojson"}:
        return _parse_json_dataset(dataset_path)
    if suffix == ".csv":
        return _parse_csv_dataset(dataset_path)
    return []


def _compute_metrics(cables: List[Set[str]]) -> List[Dict[str, Any]]:
    cable_total_by_country: Dict[str, int] = defaultdict(int)
    landing_total_by_country: Dict[str, int] = defaultdict(int)
    partners_by_country: Dict[str, Set[str]] = defaultdict(set)

    for countries in cables:
        clean = sorted(set([c for c in countries if c]))
        if not clean:
            continue
        for country in clean:
            cable_total_by_country[country] += 1
            landing_total_by_country[country] += 1
        if len(clean) > 1:
            for country in clean:
                partners_by_country[country].update([c for c in clean if c != country])

    if not cable_total_by_country:
        return []

    max_landings = max(landing_total_by_country.values())
    max_cables = max(cable_total_by_country.values())
    max_partners = max((len(v) for v in partners_by_country.values()), default=0)

    output: List[Dict[str, Any]] = []
    for country in sorted(cable_total_by_country.keys()):
        landings = landing_total_by_country[country]
        cables_count = cable_total_by_country[country]
        partner_count = len(partners_by_country.get(country, set()))

        norm_landings = landings / max_landings if max_landings else 0.0
        norm_cables = cables_count / max_cables if max_cables else 0.0
        norm_partners = partner_count / max_partners if max_partners else 0.0

        concentration = 1.0 - ((norm_landings + norm_cables + norm_partners) / 3.0)
        dependency = min(1.0, max(0.0, concentration))
        redundancy = 1.0 - dependency

        output.append(
            {
                "country": country,
                "landing_count": int(landings),
                "cable_count": int(cables_count),
                "unique_partner_countries": int(partner_count),
                "redundancy_score": round(float(redundancy), 6),
                "dependency_score": round(float(dependency), 6),
                "concentration_index": round(float(concentration), 6),
            }
        )

    return output


def _yesterday(date_str: str) -> str:
    return (datetime.strptime(date_str, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()


def _load_previous_payload(date_str: str) -> Dict[str, Any]:
    path = DAILY_ROOT / _yesterday(date_str) / f"{OBSERVER}.json"
    if path.exists():
        payload = _load_json(path, {})
        if isinstance(payload, dict):
            return payload
    latest_path = LATEST_DIR / f"{OBSERVER}.json"
    payload = _load_json(latest_path, {})
    return payload if isinstance(payload, dict) else {}


def _country_metric_map(payload: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    rows = payload.get("countries", [])
    out: Dict[str, Dict[str, float]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        c = str(row.get("country", "")).strip()
        if not c:
            continue
        out[c] = {
            "dependency_score": float(row.get("dependency_score", 0.0)),
            "redundancy_score": float(row.get("redundancy_score", 0.0)),
            "landing_count": float(row.get("landing_count", 0)),
            "cable_count": float(row.get("cable_count", 0)),
            "unique_partner_countries": float(row.get("unique_partner_countries", 0)),
        }
    return out


def _detect_significance(
    countries: List[Dict[str, Any]],
    dataset_hash: str,
    previous: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    triggers: List[str] = []

    prev_hash = str(previous.get("dataset", {}).get("dataset_hash", "")) if isinstance(previous.get("dataset"), dict) else ""
    if prev_hash and prev_hash != dataset_hash:
        triggers.append("dataset updated")

    prev_metrics = _country_metric_map(previous)
    curr_metrics = {str(row["country"]): row for row in countries}
    threshold = float(config["metric_delta_threshold"])
    top_n = int(config["top_n"])

    top_dep = [row["country"] for row in sorted(countries, key=lambda x: x["dependency_score"], reverse=True)[:top_n]]
    prev_dep = sorted(prev_metrics.keys(), key=lambda c: prev_metrics[c].get("dependency_score", 0.0), reverse=True)[:top_n]
    dep_sym_diff = len(set(top_dep).symmetric_difference(set(prev_dep)))
    if prev_dep and dep_sym_diff >= int(config["top_country_set_threshold"]):
        triggers.append("top dependency cohort shifted")

    top_red = [row["country"] for row in sorted(countries, key=lambda x: x["redundancy_score"], reverse=True)[:top_n]]
    prev_red = sorted(prev_metrics.keys(), key=lambda c: prev_metrics[c].get("redundancy_score", 0.0), reverse=True)[:top_n]
    red_sym_diff = len(set(top_red).symmetric_difference(set(prev_red)))
    if prev_red and red_sym_diff >= int(config["top_country_set_threshold"]):
        triggers.append("top redundancy cohort shifted")

    for country in top_dep:
        prev_row = prev_metrics.get(country)
        if not prev_row:
            continue
        curr_row = curr_metrics.get(country, {})
        if abs(float(curr_row.get("dependency_score", 0.0)) - prev_row.get("dependency_score", 0.0)) >= threshold:
            triggers.append(f"dependency_score changed for {country}")
            break

    for country in top_red:
        prev_row = prev_metrics.get(country)
        if not prev_row:
            continue
        curr_row = curr_metrics.get(country, {})
        if abs(float(curr_row.get("redundancy_score", 0.0)) - prev_row.get("redundancy_score", 0.0)) >= threshold:
            triggers.append(f"redundancy_score changed for {country}")
            break

    any_significant = len(triggers) > 0
    return any_significant, sorted(set(triggers))


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _encode_png_rgb(width: int, height: int, pixels: List[List[Tuple[int, int, int]]], metadata: Dict[str, str]) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    text_chunks = [
        _png_chunk(b"tEXt", k.encode("latin1", errors="ignore") + b"\x00" + v.encode("latin1", errors="ignore"))
        for k, v in metadata.items()
    ]
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixels[y][x])
    idat = _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
    iend = _png_chunk(b"IEND", b"")
    return signature + ihdr + b"".join(text_chunks) + idat + iend


def _draw_rect(pixels: List[List[Tuple[int, int, int]]], x0: int, y0: int, x1: int, y1: int, color: Tuple[int, int, int]) -> None:
    height = len(pixels)
    width = len(pixels[0]) if height else 0
    x0 = max(0, min(width - 1, x0))
    x1 = max(0, min(width, x1))
    y0 = max(0, min(height - 1, y0))
    y1 = max(0, min(height, y1))
    for y in range(y0, y1):
        row = pixels[y]
        for x in range(x0, x1):
            row[x] = color


def _generate_chart(countries: List[Dict[str, Any]], triggers: List[str]) -> None:
    width, height = 900, 520
    pixels = [[(245, 247, 250) for _ in range(width)] for _ in range(height)]

    _draw_rect(pixels, 0, 0, width, 56, (32, 44, 74))
    _draw_rect(pixels, 0, height - 36, width, height, (59, 66, 82))

    dep_top = sorted(countries, key=lambda x: x["dependency_score"], reverse=True)[:10]
    red_top = sorted(countries, key=lambda x: x["redundancy_score"], reverse=True)[:10]

    bar_area_top = 80
    bar_area_bottom = height - 60
    bar_area_height = bar_area_bottom - bar_area_top

    left_x0, left_x1 = 40, (width // 2) - 20
    right_x0, right_x1 = (width // 2) + 20, width - 40

    def draw_bars(rows: List[Dict[str, Any]], score_key: str, x0: int, x1: int, color: Tuple[int, int, int]) -> None:
        if not rows:
            return
        slot_h = max(8, bar_area_height // 10)
        for i, row in enumerate(rows):
            y = bar_area_top + i * slot_h
            y1 = min(bar_area_bottom, y + slot_h - 4)
            score = float(row.get(score_key, 0.0))
            bar_w = int((x1 - x0) * max(0.0, min(1.0, score)))
            _draw_rect(pixels, x0, y, x0 + bar_w, y1, color)

    draw_bars(dep_top, "dependency_score", left_x0, left_x1, (196, 73, 73))
    draw_bars(red_top, "redundancy_score", right_x0, right_x1, (46, 125, 50))

    trigger_band_color = (208, 71, 71) if "dataset updated" in triggers else (240, 140, 48)
    _draw_rect(pixels, 0, 56, width, 70, trigger_band_color)

    metadata = {
        "observer": OBSERVER,
        "dependency_top10": ", ".join([str(r["country"]) for r in dep_top]),
        "redundancy_top10": ", ".join([str(r["country"]) for r in red_top]),
        "triggers": "; ".join(triggers),
        "note": "Top dependency/redundancy bars; annotation in metadata",
    }
    LATEST_CHART_PATH.write_bytes(_encode_png_rgb(width, height, pixels, metadata))


def _last_7_days(date_str: str) -> List[Dict[str, Any]]:
    end = datetime.strptime(date_str, "%Y-%m-%d").date()
    items: List[Dict[str, Any]] = []
    for delta in range(6, -1, -1):
        day = (end - timedelta(days=delta)).isoformat()
        path = DAILY_ROOT / day / f"{OBSERVER}.json"
        significant = False
        if path.exists():
            payload = _load_json(path, {})
            if isinstance(payload, dict):
                significant = bool(payload.get("significance", {}).get("any_significant", False))
        items.append({"date_utc": day, "any_significant": significant})
    return items


def _write_latest_summary(date_str: str, any_significant: bool) -> None:
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
        "latest_date_utc": date_str,
        "last_7_days": _last_7_days(date_str),
    }
    if any_significant and LATEST_CHART_PATH.exists():
        payload["chart_path"] = "data/latest/chart.png"
    LATEST_SUMMARY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run() -> Dict[str, Any]:
    date_str = _date_utc()
    config = _load_config()
    dataset_path = _resolve_dataset_path(config)

    if dataset_path is None:
        payload = {
            "observer": OBSERVER,
            "date_utc": date_str,
            "data_status": "unavailable",
            "dataset": {
                "name": config["dataset_name"],
                "dataset_hash": "",
                "last_updated_hint": config["last_updated_hint"],
            },
            "countries": [],
            "summary_stats": {"countries_evaluated": 0, "any_significant": False},
            "significance": {"any_significant": False, "triggers": ["dataset unavailable"]},
        }
        _write_latest_summary(date_str, False)
        return payload

    dataset_hash = _dataset_hash(dataset_path)
    cables = _load_cable_country_sets(dataset_path)
    countries = _compute_metrics(cables)
    previous = _load_previous_payload(date_str)
    any_significant, triggers = _detect_significance(countries, dataset_hash, previous, config)

    if any_significant:
        _generate_chart(countries, triggers)

    payload = {
        "observer": OBSERVER,
        "date_utc": date_str,
        "data_status": "ok" if countries else "partial",
        "dataset": {
            "name": config["dataset_name"],
            "dataset_hash": dataset_hash,
            "last_updated_hint": config["last_updated_hint"],
        },
        "countries": [
            {
                "country": row["country"],
                "landing_count": row["landing_count"],
                "cable_count": row["cable_count"],
                "unique_partner_countries": row["unique_partner_countries"],
                "redundancy_score": row["redundancy_score"],
                "dependency_score": row["dependency_score"],
            }
            for row in countries
        ],
        "summary_stats": {
            "countries_evaluated": len(countries),
            "any_significant": any_significant,
        },
        "significance": {
            "any_significant": any_significant,
            "triggers": triggers,
        },
    }

    _write_latest_summary(date_str, any_significant)
    return payload


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
