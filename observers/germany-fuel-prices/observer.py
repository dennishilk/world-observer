#!/usr/bin/env python3
"""Germany Fuel Price Observer.

Builds Germany fuel price dashboard data from permitted local imports by default.

The Tankerkoenig/MTS-K API integration is retained only for optional,
manual/local tests and is never used automatically by production daily runs.
The observer emits unavailable data when no permitted import or manually
requested API result is available; it does not invent prices.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import re
import urllib.request
from html.parser import HTMLParser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

OBSERVER = "germany-fuel-prices"
SUPPORTED_FUELS = {
    "benzin": "Super E5",
    "diesel": "Diesel",
}
API_URL = "https://creativecommons.tankerkoenig.de/json/list.php"
NDR_PUBLIC_AVERAGE_URL = "https://www.ndr.de/nachrichten/info/spritpreise-aktuell-so-entwickeln-sich-benzin-und-dieselpreise%2Cspritpreise-128.html"
USER_AGENT = "world-observer/1.0 (+https://github.com/dennishilk/world-observer)"
IMPORTS_DIR = Path("imports/fuel-prices-germany")
MANUAL_API_ENV = "WORLD_OBSERVER_FUEL_ENABLE_TANKERKOENIG_API"
API_KEY_ENV = "WORLD_OBSERVER_FUEL_API_KEY"
PUBLIC_URL_ENV = "WORLD_OBSERVER_FUEL_PUBLIC_URL"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _date_utc() -> str:
    raw = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def _as_price(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price <= 0 or price > 5:
        return None
    return round(price, 3)


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    return (payload, None) if isinstance(payload, dict) else (None, "JSON root is not an object")


def _daily_price_points(root: Path) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for base in (root / "state" / OBSERVER,):
        if not base.exists():
            continue
        for path in sorted(base.glob("*.json")):
            payload, _ = _read_json(path)
            if not payload:
                continue
            date = str(payload.get("date") or payload.get("date_utc") or path.stem)[:10]
            fuels = payload.get("fuels")
            if not isinstance(fuels, dict):
                continue
            for fuel, item in fuels.items():
                if fuel not in SUPPORTED_FUELS or not isinstance(item, dict):
                    continue
                price = _as_price(item.get("current_price"))
                if price is not None:
                    points.append({"date": date, "fuel_type": fuel, "price": price, "source": "daily"})
    return points


def _validate_import_row(row: dict[str, Any], file_name: str) -> tuple[dict[str, Any] | None, str | None]:
    date = str(row.get("date", ""))[:10]
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None, "invalid date"
    fuel = str(row.get("fuel_type", "")).strip()
    if fuel not in SUPPORTED_FUELS:
        return None, "unsupported fuel_type"
    price = _as_price(row.get("price_eur_per_liter"))
    if price is None:
        return None, "invalid price_eur_per_liter"
    granularity = str(row.get("granularity", "")).strip()
    if granularity not in {"daily", "monthly", "yearly"}:
        return None, "invalid granularity"
    source = str(row.get("source", "")).strip()
    if not source:
        return None, "missing source"
    return {
        "date": date,
        "fuel_type": fuel,
        "price": price,
        "source": source,
        "source_url": row.get("source_url") or None,
        "granularity": granularity,
        "notes": row.get("notes") or None,
        "import_file": file_name,
    }, None


def import_price_points(imports_dir: Path, daily_dates: set[tuple[str, str]] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    daily_dates = daily_dates or set()
    points: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    if not imports_dir.exists():
        return points, diagnostics
    for path in sorted(p for p in imports_dir.iterdir() if p.is_file() and p.suffix.lower() in {".json", ".csv"}):
        rows: list[dict[str, Any]] = []
        try:
            if path.suffix.lower() == ".json":
                raw = json.loads(path.read_text(encoding="utf-8"))
                rows = raw if isinstance(raw, list) else raw.get("records", []) if isinstance(raw, dict) else []
                if not isinstance(rows, list):
                    raise ValueError("JSON import must be a list or object with records list")
            else:
                with path.open(newline="", encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            diagnostics.append({"file": path.name, "status": "ignored", "reason": str(exc)})
            continue
        accepted = 0
        for row in rows:
            if not isinstance(row, dict):
                diagnostics.append({"file": path.name, "status": "ignored", "reason": "row is not an object"})
                continue
            point, reason = _validate_import_row(row, path.name)
            if point is None:
                diagnostics.append({"file": path.name, "status": "ignored", "reason": reason or "invalid row"})
                continue
            key = (point["date"], point["fuel_type"])
            if key in daily_dates:
                diagnostics.append({"file": path.name, "status": "ignored", "reason": "duplicate date; daily generated data takes precedence", "date": point["date"], "fuel_type": point["fuel_type"]})
                continue
            points.append(point)
            accepted += 1
        diagnostics.append({"file": path.name, "status": "loaded", "accepted_rows": accepted})
    return points, diagnostics


def _fetch_current_prices(api_key: str) -> tuple[dict[str, float], dict[str, Any], str | None]:
    lat = os.environ.get("WORLD_OBSERVER_FUEL_LAT", "51.1657")
    lng = os.environ.get("WORLD_OBSERVER_FUEL_LNG", "10.4515")
    rad = os.environ.get("WORLD_OBSERVER_FUEL_RADIUS_KM", "25")
    params = {"lat": lat, "lng": lng, "rad": rad, "sort": "dist", "type": "all", "apikey": api_key}
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    diagnostics: dict[str, Any] = {"api_attempts": 1, "retries": 0, "http_status": None, "source": "tankerkoenig", "sample_center": {"lat": lat, "lng": lng, "radius_km": rad}}
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            diagnostics["http_status"] = getattr(response, "status", None)
            payload = json.loads(response.read(2_000_000).decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        diagnostics["http_status"] = exc.code
        return {}, diagnostics, f"fuel API HTTP error {exc.code}"
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {}, diagnostics, f"fuel API fetch failed: {type(exc).__name__}: {exc}"
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return {}, diagnostics, str(payload.get("message") if isinstance(payload, dict) else "fuel API returned invalid payload")
    stations = payload.get("stations") if isinstance(payload.get("stations"), list) else []
    sums: dict[str, list[float]] = {fuel: [] for fuel in SUPPORTED_FUELS}
    for station in stations:
        if not isinstance(station, dict):
            continue
        mapping = {"benzin": station.get("e5"), "diesel": station.get("diesel")}
        for fuel, value in mapping.items():
            price = _as_price(value)
            if price is not None:
                sums[fuel].append(price)
    prices = {fuel: round(sum(vals) / len(vals), 3) for fuel, vals in sums.items() if vals}
    diagnostics["station_count"] = len(stations)
    diagnostics["priced_station_counts"] = {fuel: len(vals) for fuel, vals in sums.items()}
    if not prices:
        return {}, diagnostics, "fuel API returned no supported current prices"
    return prices, diagnostics, None


class _TextCollector(HTMLParser):
    """Collect visible-ish text from public fuel-price pages."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._parts.append(text)

    def text(self) -> str:
        return " ".join(self._parts)


def _page_text(content: str) -> str:
    parser = _TextCollector()
    parser.feed(content)
    text = parser.text()
    return text or content


def _price_from_match(match: re.Match[str]) -> float | None:
    groups = [group for group in match.groups() if group is not None]
    if not groups:
        return None
    return _as_price(groups[-1].replace(",", "."))


def _parse_public_average_price_details(content: str) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    """Parse nationwide German daily average prices and explain each accepted match."""
    text = re.sub(r"\s+", " ", _page_text(content))
    patterns: dict[str, tuple[tuple[str, str], ...]] = {
        "benzin": (
            ("current average sentence", r"(\d+[,.]\d{2,3})\s*Euro\s+kostete[^.]{0,120}?Liter\s+Super(?!\s*E10)"),
            ("labeled current average", r"(?:Liter\s+)?Super(?:-?Benzin)?\s*(?:\(\s*Sorte\s*E5\s*\)|E5)?[^.]{0,180}?(\d+[,.]\d{2,3})\s*Euro"),
            ("compact euro label", r"Super\s*(?:E5)?\s*(\d+[,.]\d{2,3})\s*€"),
        ),
        "diesel": (
            ("current average sentence", r"(?:Preis\s+für\s+einen\s+Liter\s+)?Diesel[^.]{0,180}?(?:lag|liegt|sind|kostete)[^.]{0,80}?(\d+[,.]\d{2,3})\s*Euro"),
            ("labeled current average", r"(?:beim|für|Liter\s+)?Diesel[^.]{0,180}?(\d+[,.]\d{2,3})\s*Euro"),
            ("compact euro label", r"Diesel\s*(\d+[,.]\d{2,3})\s*€"),
        ),
    }
    prices: dict[str, float] = {}
    details: dict[str, dict[str, Any]] = {}
    for fuel, fuel_patterns in patterns.items():
        for label, pattern in fuel_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            price = _price_from_match(match)
            if price is not None:
                prices[fuel] = price
                details[fuel] = {"pattern": label, "matched_text": match.group(0)[:220]}
                break
    return prices, details


def _parse_public_average_prices(content: str) -> dict[str, float]:
    """Parse nationwide German daily average prices from public page text.

    The parser only accepts explicit fuel labels near euro/liter prices. It does not
    infer missing fuels from unlabeled numbers, avoiding fabricated values.
    """
    prices, _details = _parse_public_average_price_details(content)
    return prices


def _fetch_public_average_url(url: str, source_label: str) -> tuple[dict[str, float], dict[str, Any], str | None]:
    diagnostics: dict[str, Any] = {
        "source": source_label,
        "fetch_url": url,
        "fetched_at_utc": None,
        "parse_status": "not_started",
        "api_attempts": 1,
        "retries": 0,
        "http_status": None,
    }
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            diagnostics["http_status"] = getattr(response, "status", None)
            html = response.read(2_000_000).decode("utf-8", errors="replace")
            diagnostics["fetched_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    except urllib.error.HTTPError as exc:
        diagnostics["http_status"] = exc.code
        diagnostics["parse_status"] = "fetch_failed"
        return {}, diagnostics, f"{url}: HTTP {exc.code}"
    except (OSError, urllib.error.URLError) as exc:
        diagnostics["parse_status"] = "fetch_failed"
        return {}, diagnostics, f"{url}: {type(exc).__name__}: {exc}"

    prices, parse_matches = _parse_public_average_price_details(html)
    diagnostics["parse_matches"] = parse_matches
    diagnostics["priced_fuel_count"] = len(prices)
    diagnostics["parse_status"] = "ok" if prices else "no_supported_prices"
    if not prices:
        return {}, diagnostics, f"{url}: page did not contain supported nationwide average fuel prices"
    host = urllib.parse.urlparse(url).netloc
    diagnostics["source"] = host or source_label
    return prices, diagnostics, None


def _fetch_public_average_prices() -> tuple[dict[str, float], dict[str, Any], str | None]:
    configured = os.environ.get(PUBLIC_URL_ENV, "").strip()
    primary_url = configured or NDR_PUBLIC_AVERAGE_URL
    diagnostics: dict[str, Any] = {
        "source": "public fuel average page",
        "primary_source": urllib.parse.urlparse(primary_url).netloc or primary_url,
        "fetch_url": primary_url,
        "fetched_at_utc": None,
        "parse_status": "not_started",
        "fallback_used": False,
        "api_attempts": 0,
        "retries": 0,
        "http_status": None,
        "missing_fuels_after_primary": [],
        "priced_fuel_count": 0,
    }

    prices, primary_diag, primary_error = _fetch_public_average_url(primary_url, "NDR public fuel average page")
    diagnostics["api_attempts"] += primary_diag.get("api_attempts", 0)
    diagnostics["source"] = primary_diag.get("source") or diagnostics["source"]
    diagnostics["fetch_url"] = primary_diag.get("fetch_url")
    diagnostics["fetched_at_utc"] = primary_diag.get("fetched_at_utc")
    diagnostics["parse_status"] = primary_diag.get("parse_status")
    diagnostics["http_status"] = primary_diag.get("http_status")
    diagnostics["missing_fuels_after_primary"] = [fuel for fuel in SUPPORTED_FUELS if fuel not in prices]
    diagnostics["priced_fuel_count"] = len(prices)
    if prices:
        return prices, diagnostics, None
    return {}, diagnostics, primary_error or "public fuel average page did not contain supported prices"

def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _window_values(points: list[dict[str, Any]], end_date: str, days: int) -> list[float]:
    try:
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return [p["price"] for p in points[-days:]]
    start = end - timedelta(days=days - 1)
    values: list[float] = []
    for point in points:
        try:
            point_date = datetime.strptime(point["date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if start <= point_date <= end:
            values.append(point["price"])
    return values


def _fuel_stats(fuel: str, current: float | None, date: str, history: list[dict[str, Any]], data_status: str, degraded_reason: str | None) -> dict[str, Any]:
    fuel_points = sorted([p for p in history if p["fuel_type"] == fuel], key=lambda p: p["date"])
    latest_prev = next((p for p in reversed(fuel_points) if p["date"] < date), None)
    stats_points = [p for p in fuel_points if current is None or p["date"] != date]
    values = [p["price"] for p in stats_points]
    current_values = values + ([] if current is None else [current])
    item: dict[str, Any] = {
        "label": SUPPORTED_FUELS[fuel],
        "current_price": current,
        "average_30d": _avg(_window_values(stats_points, date, 30) + ([] if current is None else [current])),
        "average_365d": _avg(_window_values(stats_points, date, 365) + ([] if current is None else [current])),
        "record_low": min(current_values) if current_values else None,
        "record_high": max(current_values) if current_values else None,
        "historical_min": min(current_values) if current_values else None,
        "historical_max": max(current_values) if current_values else None,
        "last_seen_date": date if current is not None else (fuel_points[-1]["date"] if fuel_points else None),
        "status": "ok" if current is not None else "unavailable",
        "data_status": data_status if current is not None else "unavailable",
        "observed_changes": [],
    }
    if degraded_reason and current is None:
        item["degraded_reason"] = degraded_reason
    if current is not None and latest_prev:
        delta = round(current - latest_prev["price"], 3)
        item["trend_delta"] = delta
        item["trend_delta_percent"] = round(delta / latest_prev["price"] * 100, 2) if latest_prev["price"] else None
        if delta > 0:
            item["observed_changes"].append("Price increased compared with the previous observation.")
        elif delta < 0:
            item["observed_changes"].append("Price decreased compared with the previous observation.")
        else:
            item["observed_changes"].append("Price is unchanged compared with the previous observation.")
    else:
        item["trend_delta"] = None
        item["trend_delta_percent"] = None
    if current is not None and item["average_30d"] is not None:
        if current > item["average_30d"]:
            item["observed_changes"].append("Price is above the 30-day average.")
        elif current < item["average_30d"]:
            item["observed_changes"].append("Price is below the 30-day average.")
    if current is not None and item["record_high"] is not None and current < item["record_high"]:
        item["observed_changes"].append("Price is below the observed record high.")
    if current is not None and item["average_365d"]:
        item["compared_with_365d_percent"] = round((current - item["average_365d"]) / item["average_365d"] * 100, 2)
    else:
        item["compared_with_365d_percent"] = None
    return item


def _latest_import_prices(points: list[dict[str, Any]], date: str) -> dict[str, float]:
    latest: dict[str, dict[str, Any]] = {}
    for point in sorted(points, key=lambda p: (p["date"], p["fuel_type"])):
        if point["date"] <= date:
            latest[point["fuel_type"]] = point
    return {fuel: point["price"] for fuel, point in latest.items()}


def build_payload(date: str, current_prices: dict[str, float], diagnostics: dict[str, Any], degraded_reason: str | None = None, root: Path | None = None, source: str | None = None) -> dict[str, Any]:
    root = root or _repo_root()
    current_prices = {fuel: price for fuel, price in current_prices.items() if fuel in SUPPORTED_FUELS}
    daily_points = _daily_price_points(root)
    daily_keys = {(p["date"], p["fuel_type"]) for p in daily_points}
    public_auto = source == "public fuel average page"
    duplicate_current_keys = set() if public_auto else {(date, f) for f in current_prices}
    import_points, import_diagnostics = import_price_points(root / IMPORTS_DIR, daily_keys | duplicate_current_keys)
    history = sorted(import_points + daily_points, key=lambda p: (p["date"], p["fuel_type"]))
    if daily_points:
        diagnostics["daily_state_history_count"] = len(daily_points)
        diagnostics["daily_state_history_dates"] = sorted({p["date"] for p in daily_points})
        diagnostics["state_history_note"] = "Trend calculations use repository state snapshots as recorded; prices absent from state/import history are not reconstructed."
    same_date_imports = {p["fuel_type"]: p["price"] for p in import_points if p["date"] == date}
    if public_auto and same_date_imports:
        effective_prices = {**current_prices, **same_date_imports}
        effective_source = "imports/fuel-prices-germany"
        diagnostics["fallback_used"] = True
        diagnostics["local_import_override"] = sorted(same_date_imports)
    else:
        effective_prices = current_prices or _latest_import_prices(import_points, date)
        effective_source = source if current_prices else ("imports/fuel-prices-germany" if effective_prices else None)
        if not current_prices and effective_prices:
            diagnostics["fallback_used"] = True
    diagnostics["priced_fuel_count"] = len(effective_prices)
    data_status = "ok" if effective_prices else "unavailable"
    status = "ok" if effective_prices else "unavailable"
    if not effective_prices and degraded_reason is None:
        degraded_reason = "No permitted fuel price import is available"
    fuels = {fuel: _fuel_stats(fuel, effective_prices.get(fuel), date, history, data_status, degraded_reason) for fuel in SUPPORTED_FUELS}
    payload: dict[str, Any] = {
        "observer": OBSERVER,
        "category": "society",
        "date": date,
        "date_utc": date,
        "status": status,
        "data_status": data_status,
        "source": effective_source or diagnostics.get("source"),
        "fuels": fuels,
        "supported_fuel_types": SUPPORTED_FUELS,
        "import_diagnostics": import_diagnostics,
        "diagnostics": diagnostics,
    }
    if degraded_reason:
        payload["degraded_reason"] = degraded_reason
    return payload


def _write_outputs(payload: dict[str, Any], root: Path) -> None:
    date = str(payload.get("date") or payload.get("date_utc"))[:10]
    for path in (root / "state" / OBSERVER / f"{date}.json", root / "data" / "latest" / f"{OBSERVER}.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _manual_api_enabled() -> bool:
    return os.environ.get(MANUAL_API_ENV, "").strip().lower() in {"1", "true", "yes"}


def main() -> None:
    date = _date_utc()
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if api_key and _manual_api_enabled():
        prices, diagnostics, reason = _fetch_current_prices(api_key)
        payload = build_payload(date, prices, diagnostics, reason, source="Tankerkoenig/MTS-K API")
    else:
        prices, diagnostics, reason = _fetch_public_average_prices()
        if reason:
            diagnostics["fallback_used"] = True
        if api_key:
            diagnostics["tankerkoenig_automatic"] = False
            diagnostics["tankerkoenig_note"] = f"Tankerkönig API key present but {MANUAL_API_ENV} is not enabled; not used automatically"
        payload = build_payload(date, prices, diagnostics, reason, source="public fuel average page")
    _write_outputs(payload, _repo_root())
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
