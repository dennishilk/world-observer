#!/usr/bin/env python3
"""Germany household electricity price observer.

The observer intentionally does not scrape tariff-comparison websites by
fallback. Until a stable, redistributable public source is configured, it emits
an unavailable skeleton and can ingest explicitly permitted local imports.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

OBSERVER = "germany-electricity-prices"
IMPORTS_DIR = Path("imports/germany-electricity-prices")
REPRESENTATIVE_HOUSEHOLD = {
    "country": "Germany",
    "location": "Wiesmoor",
    "postal_code": "26628",
    "annual_consumption_kwh": 3500,
    "households_represented": 1,
    "observation_frequency": "daily",
    "observation_type": "descriptive",
}
UNIT = "EUR per kWh"


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
        price = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if price <= 0 or price > 2:
        return None
    return round(price, 4)


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    return (payload, None) if isinstance(payload, dict) else (None, "JSON root is not an object")


def _daily_price_points(root: Path) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    base = root / "state" / OBSERVER
    if not base.exists():
        return points
    for path in sorted(base.glob("*.json")):
        payload, _ = _read_json(path)
        if not payload:
            continue
        date = str(payload.get("date") or payload.get("date_utc") or path.stem)[:10]
        price = _as_price(payload.get("current_price_eur_per_kwh"))
        if price is not None:
            points.append({"date": date, "price": price, "source": "daily"})
    return points


def _validate_import_row(row: dict[str, Any], file_name: str) -> tuple[dict[str, Any] | None, str | None]:
    date = str(row.get("date", ""))[:10]
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None, "invalid date"
    price = _as_price(row.get("price_eur_per_kwh"))
    if price is None:
        return None, "invalid price_eur_per_kwh"
    source = str(row.get("source", "")).strip()
    if not source:
        return None, "missing source"
    return {
        "date": date,
        "price": price,
        "source": source,
        "source_url": row.get("source_url") or None,
        "notes": row.get("notes") or None,
        "import_file": file_name,
    }, None


def import_price_points(imports_dir: Path, daily_dates: set[str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    daily_dates = daily_dates or set()
    points: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    if not imports_dir.exists():
        return points, diagnostics
    for path in sorted(p for p in imports_dir.iterdir() if p.is_file() and p.suffix.lower() in {".json", ".csv"}):
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
            if point["date"] in daily_dates:
                diagnostics.append({"file": path.name, "status": "ignored", "reason": "duplicate date; daily generated data takes precedence", "date": point["date"]})
                continue
            points.append(point)
            accepted += 1
        diagnostics.append({"file": path.name, "status": "loaded", "accepted_rows": accepted})
    return points, diagnostics


def _average(points: list[dict[str, Any]], days: int, date: str) -> float | None:
    cutoff = datetime.strptime(date, "%Y-%m-%d").date() - timedelta(days=days - 1)
    values = [p["price"] for p in points if datetime.strptime(p["date"], "%Y-%m-%d").date() >= cutoff]
    return round(sum(values) / len(values), 4) if values else None


def build_payload(date: str, root: Path | None = None) -> dict[str, Any]:
    root = root or _repo_root()
    daily_points = _daily_price_points(root)
    import_points, import_diagnostics = import_price_points(root / IMPORTS_DIR, {p["date"] for p in daily_points})
    history = sorted(import_points + daily_points, key=lambda p: p["date"])
    latest = next((p for p in reversed(history) if p["date"] <= date), None)
    current = latest["price"] if latest else None
    data_status = "ok" if current is not None else "unavailable"
    diagnostics = {
        "api_attempts": 0,
        "retries": 0,
        "http_status": None,
        "source_status": "placeholder",
        "validation_note": "No stable redistributable public tariff source is configured; only validated local imports are accepted.",
        "daily_state_history_count": len(daily_points),
    }
    payload: dict[str, Any] = {
        "observer": OBSERVER,
        "category": "society",
        "date": date,
        "date_utc": date,
        "status": data_status,
        "data_status": data_status,
        "current_price_eur_per_kwh": current,
        "unit": UNIT,
        "representative_household": REPRESENTATIVE_HOUSEHOLD,
        "source": latest["source"] if latest else None,
        "source_url": latest.get("source_url") if latest else None,
        "history": [{"date": p["date"], "value": p["price"], "source": p["source"]} for p in history],
        "average_30d": _average(history, 30, date),
        "average_365d": _average(history, 365, date),
        "import_diagnostics": import_diagnostics,
        "diagnostics": diagnostics,
    }
    if latest:
        payload["last_seen_date"] = latest["date"]
    else:
        payload["degraded_reason"] = "No stable public source or permitted local import is available for the representative household."
    return payload


def _write_outputs(payload: dict[str, Any], root: Path) -> None:
    date = str(payload.get("date") or payload.get("date_utc"))[:10]
    for path in (root / "state" / OBSERVER / f"{date}.json", root / "data" / "latest" / f"{OBSERVER}.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    payload = build_payload(_date_utc())
    _write_outputs(payload, _repo_root())
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
