#!/usr/bin/env python3
"""East Frisian Tea price observer."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

OBSERVER = "east-frisian-tea-prices"
DISPLAY_NAME = "East Frisian Tea Observer"
DESCRIPTION = "Tracks the retail price development of a representative 500 g loose East Frisian black tea product over time. The observer is descriptive only and does not rate brands or product quality."
URL = "https://www.combi.de/buenting_tee_gruenpack_1101010007.html"
USER_AGENT = "world-observer/1.0 east-frisian-tea-prices (+https://github.com/dennishilk/world-observer)"
EXPECTED_EAN = "4008837201054"
EXPECTED_CURRENCY = "EUR"
MANUAL_SEED = {
    "date": "2026-06-30",
    "price": 9.98,
    "source": "manual_seed",
    "seed_note": "Initial manually seeded observation for trend chart bootstrap before automated collection started.",
}


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


class ProductMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        data = {k.lower(): v for k, v in attrs if v is not None}
        prop = data.get("property")
        content = data.get("content")
        if prop and content is not None:
            self.meta[prop] = content.strip()


def parse_german_decimal(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace(".", "").replace(",", ".")
    try:
        price = float(normalized)
    except ValueError:
        return None
    if price <= 0:
        return None
    return round(price, 2)


def parse_product_meta(html: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    parser = ProductMetaParser()
    parser.feed(html)
    meta = parser.meta
    diagnostics: dict[str, Any] = {
        "parse_status": "parsed_meta_tags",
        "meta_fields_present": sorted(k for k in meta if k.startswith("product:")),
        "availability": meta.get("product:availability"),
        "category": meta.get("product:category"),
        "brand": meta.get("product:brand"),
        "ean": meta.get("product:ean"),
        "currency": meta.get("product:price:currency"),
    }
    price = parse_german_decimal(meta.get("product:price:amount"))
    currency = meta.get("product:price:currency")
    ean = meta.get("product:ean")
    errors: list[str] = []
    if price is None:
        errors.append("missing or invalid product:price:amount")
    if currency != EXPECTED_CURRENCY:
        errors.append(f"currency validation failed: expected {EXPECTED_CURRENCY}")
    if ean != EXPECTED_EAN:
        errors.append(f"EAN validation failed: expected {EXPECTED_EAN}")
    if errors:
        diagnostics["parse_status"] = "validation_failed"
        diagnostics["validation_errors"] = errors
        return None, diagnostics
    return {"price": price, "currency": currency, "ean": ean, "availability": meta.get("product:availability")}, diagnostics


def fetch_product_html(url: str = URL) -> tuple[str | None, dict[str, Any], str | None]:
    diagnostics: dict[str, Any] = {"source": "combi_product_meta", "fetch_url": url, "fetched_at_utc": datetime.now(timezone.utc).isoformat(), "http_status": None, "api_attempts": 1, "retries": 0}
    fixture_html = os.environ.get("WORLD_OBSERVER_TEA_HTML")
    if fixture_html:
        diagnostics["source"] = "combi_product_meta_fixture"
        diagnostics["fixture_used"] = True
        diagnostics["fixture_note"] = "HTML supplied through WORLD_OBSERVER_TEA_HTML; production runs fetch the Combi product page once."
        return fixture_html, diagnostics, None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            diagnostics["http_status"] = getattr(response, "status", None)
            return response.read(1_000_000).decode("utf-8", errors="replace"), diagnostics, None
    except urllib.error.HTTPError as exc:
        diagnostics["http_status"] = exc.code
        return None, diagnostics, f"Combi product page HTTP error {exc.code}"
    except (OSError, urllib.error.URLError) as exc:
        return None, diagnostics, f"Combi product page fetch failed: {type(exc).__name__}: {exc}"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def history_points(root: Path, current_date: str | None = None, current_price: float | None = None, current_source: str | None = None) -> list[dict[str, Any]]:
    points = [{**MANUAL_SEED}]
    base = root / "state" / OBSERVER
    if base.exists():
        for path in sorted(base.glob("*.json")):
            payload = _read_json(path)
            if not payload:
                continue
            date = str(payload.get("date") or payload.get("date_utc") or path.stem)[:10]
            price = payload.get("current_price")
            if isinstance(price, (int, float)) and not isinstance(price, bool):
                points.append({"date": date, "price": round(float(price), 2), "source": payload.get("source") or "state"})
    if current_date and current_price is not None:
        points.append({"date": current_date, "price": current_price, "source": current_source or "current"})
    dedup: dict[str, dict[str, Any]] = {}
    for point in sorted(points, key=lambda p: (p["date"], 0 if p.get("source") == "manual_seed" else 1)):
        dedup[point["date"]] = point
    return sorted(dedup.values(), key=lambda p: p["date"])


def _avg(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 2) if vals else None


def _window(points: list[dict[str, Any]], end_date: str, days: int) -> list[float]:
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    start = end - timedelta(days=days - 1)
    vals = []
    for p in points:
        try:
            d = datetime.strptime(p["date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if start <= d <= end:
            vals.append(float(p["price"]))
    return vals


def build_payload(date: str, observation: dict[str, Any] | None, diagnostics: dict[str, Any], degraded_reason: str | None = None, root: Path | None = None) -> dict[str, Any]:
    root = root or _repo_root()
    current = observation["price"] if observation else None
    points = history_points(root, date if current is not None else None, current, "combi_product_meta")
    values = [float(p["price"]) for p in points]
    prev = next((p for p in reversed(points) if p["date"] < date), None)
    history = [{"date": p["date"], "value": round(float(p["price"]), 2), "source": p.get("source"), **({"seed_note": p["seed_note"]} if p.get("seed_note") else {})} for p in points]
    payload: dict[str, Any] = {
        "observer": OBSERVER,
        "display_name": DISPLAY_NAME,
        "description": DESCRIPTION,
        "category": "society",
        "date": date,
        "date_utc": date,
        "status": "ok" if current is not None else "unavailable",
        "data_status": "ok" if current is not None else "unavailable",
        "source": "combi_product_meta" if current is not None else diagnostics.get("source"),
        "source_url": URL,
        "current_price": current,
        "currency": EXPECTED_CURRENCY,
        "unit": "EUR per 500 g loose tea",
        "ean": observation.get("ean") if observation else EXPECTED_EAN,
        "availability": observation.get("availability") if observation else diagnostics.get("availability"),
        "history": history,
        "average_30d": _avg(_window(points, date, 30)),
        "average_365d": _avg(_window(points, date, 365)),
        "record_low": min(values) if values else None,
        "record_high": max(values) if values else None,
        "historical_min": min(values) if values else None,
        "historical_max": max(values) if values else None,
        "observed_changes": [],
        "diagnostics": diagnostics,
    }
    if current is not None and prev:
        delta = round(current - float(prev["price"]), 2)
        payload["trend_delta"] = delta
        payload["trend_delta_percent"] = round(delta / float(prev["price"]) * 100, 2) if prev["price"] else None
        payload["observed_changes"].append("Price increased compared with the previous observation." if delta > 0 else "Price decreased compared with the previous observation." if delta < 0 else "Price is unchanged compared with the previous observation.")
    else:
        payload["trend_delta"] = None
        payload["trend_delta_percent"] = None
    if degraded_reason:
        payload["degraded_reason"] = degraded_reason
    return payload


def _write_outputs(payload: dict[str, Any], root: Path) -> None:
    date = str(payload.get("date") or payload.get("date_utc"))[:10]
    for path in (root / "state" / OBSERVER / f"{date}.json", root / "data" / "latest" / f"{OBSERVER}.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    date = _date_utc()
    html, fetch_diag, reason = fetch_product_html()
    observation = None
    parse_diag: dict[str, Any] = {}
    if html is not None:
        observation, parse_diag = parse_product_meta(html)
        if observation is None:
            reason = "Combi product meta tag validation failed"
    diagnostics = {**fetch_diag, **parse_diag}
    payload = build_payload(date, observation, diagnostics, reason)
    _write_outputs(payload, _repo_root())
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
