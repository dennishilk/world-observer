"""Shared DWD CDC recent daily KL download and parsing helpers."""
from __future__ import annotations

import csv
import io
import socket
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

DWD_KL_RECENT_BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/recent/"
MISSING_VALUES = {"", "-999", "-999.0"}


@dataclass
class DwdDiagnostics:
    api_attempts: int = 0
    retries: int = 0
    http_status: int | None = None
    adapter_errors: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "api_attempts": self.api_attempts,
            "retries": self.retries,
            "http_status": self.http_status,
            "adapter_errors": self.adapter_errors or [],
        }


def station_zip_url(station_id: str, base_url: str = DWD_KL_RECENT_BASE_URL) -> str:
    return f"{base_url.rstrip('/')}/tageswerte_KL_{station_id}_akt.zip"


def fetch_url(url: str, diagnostics: DwdDiagnostics, *, timeout_seconds: int, max_retries: int, user_agent: str, sleep_seconds: float = 0.4) -> bytes:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        diagnostics.api_attempts += 1
        if attempt:
            diagnostics.retries += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                diagnostics.http_status = getattr(response, "status", response.getcode())
                if diagnostics.http_status != 200:
                    raise RuntimeError(f"HTTP status {diagnostics.http_status}")
                return response.read()
        except urllib.error.HTTPError as exc:
            diagnostics.http_status = exc.code
            last_error = exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError, RuntimeError) as exc:
            last_error = exc
        if attempt < max_retries and sleep_seconds > 0:
            time.sleep(sleep_seconds * (attempt + 1))
    raise RuntimeError(f"DWD CDC request failed after {diagnostics.api_attempts} attempts and {diagnostics.retries} retries: {last_error}")


def parse_dwd_date(raw: str) -> date:
    return datetime.strptime(raw.strip(), "%Y%m%d").date()


def parse_float(raw: str | None) -> float | None:
    if raw is None or raw.strip() in MISSING_VALUES:
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _detect_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:10])
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        return ";"


def inspect_daily_product(zip_bytes: bytes, zip_filename: str | None = None) -> dict[str, Any]:
    """Return raw inspection details for a DWD daily KL ZIP without normalizing fields."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        contained_filenames = zf.namelist()
        names = [n for n in contained_filenames if n.lower().startswith("produkt_klima_tag_") and n.lower().endswith(".txt")]
        if not names:
            raise ValueError("DWD ZIP did not contain a daily climate product file")
        selected_filename = sorted(names)[0]
        with zf.open(selected_filename) as fh:
            text = fh.read().decode("latin1")
    lines = text.splitlines()
    delimiter = _detect_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return {
        "zip_filename": zip_filename,
        "contained_filenames": contained_filenames,
        "selected_filename": selected_filename,
        "first_10_lines": lines[:10],
        "header_row": lines[0] if lines else "",
        "delimiter": delimiter,
        "fieldnames": reader.fieldnames,
    }


def parse_daily_product(zip_bytes: bytes) -> list[dict[str, Any]]:
    inspection = inspect_daily_product(zip_bytes)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        with zf.open(inspection["selected_filename"]) as fh:
            text = fh.read().decode("latin1")
    reader = csv.DictReader(io.StringIO(text), delimiter=inspection["delimiter"])
    if reader.fieldnames:
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
    if not reader.fieldnames or "MESS_DATUM" not in reader.fieldnames or "RSK" not in reader.fieldnames:
        raise ValueError(f"DWD daily climate CSV missing required columns MESS_DATUM/RSK; delimiter={inspection['delimiter']!r}; fieldnames={inspection['fieldnames']!r}; header={inspection['header_row']!r}")
    rows: list[dict[str, Any]] = []
    for raw in reader:
        row = {str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items() if k is not None}
        try:
            obs_date = parse_dwd_date(row["MESS_DATUM"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"malformed DWD daily climate CSV row date: {row.get('MESS_DATUM')!r}") from exc
        rows.append({"date": obs_date, "precip_mm": parse_float(row.get("RSK")), "temperature_c": parse_float(row.get("TMK"))})
    if not rows:
        raise ValueError("DWD daily climate CSV contained no observations")
    return sorted(rows, key=lambda r: r["date"])


def window_values(rows: list[dict[str, Any]], latest: date, days: int, field: str) -> tuple[list[float], int]:
    start = latest - timedelta(days=days - 1)
    by_date = {r["date"]: r for r in rows if start <= r["date"] <= latest}
    values = [by_date[d][field] for d in (start + timedelta(days=i) for i in range(days)) if d in by_date and by_date[d].get(field) is not None]
    return values, days


def rolling_total(rows: list[dict[str, Any]], latest: date, days: int, min_valid: int) -> tuple[float | None, int, int]:
    values, expected = window_values(rows, latest, days, "precip_mm")
    return (round(sum(values), 1) if len(values) >= min_valid else None, len(values), expected)
