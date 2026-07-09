#!/usr/bin/env python3
"""Wiesmoor Peatland Observer.

Local environmental proxy observer for the Wiesmoor peatland landscape. The
observer is intentionally conservative: it does not report an in-situ peat
water-table measurement. The DWD daily climate adapter provides a regional
weather proxy only; groundwater and satellite soil-water adapters remain
pending.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from html.parser import HTMLParser
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

OBSERVER = "wiesmoor-peatland"
LATITUDE = 53.4167
LONGITUDE = 7.7333
DWD_KL_RECENT_BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/recent/"
DWD_STATION_DESCRIPTION = "KL_Tageswerte_Beschreibung_Stationen.txt"
DWD_ADAPTER_ID = "dwd_cdc_daily_climate_kl_recent"
DWD_SOIL_MOISTURE_ADAPTER_ID = "dwd_cdc_daily_soil_moisture_grass"
DWD_SOIL_MOISTURE_BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/soil_moisture/grass/"
DWD_SOIL_MOISTURE_DATASET_ID = "urn:wmo:md:de-dwd-cdc:25285481-9c88-4304-a90a-26fff84a9a84"
DWD_SOIL_MOISTURE_PRODUCT = "Daily grids of mean soil moisture under grass for Germany, Version v1.0"
DWD_SOIL_MOISTURE_CULTURE = "grass"
DWD_SOIL_MOISTURE_LAYER = "0-60"
DWD_SOIL_MOISTURE_UNIT = "‰ nFK"
DWD_SOIL_MOISTURE_FILL_VALUES = {-9999, -9999.0}
NLWKN_GROUNDWATER_ADAPTER_ID = "nlwkn_groundwaterstandonline_public"
NLWKN_STATIONS_URL = "https://bis.azure-api.net/GrundwasserstandonlinePublic/REST/stammdaten/stationen/allegrundwasserstationen?key=9dc05f4e3b4a43a9988d747825b39f43"
NLWKN_PORTAL_URL = "https://www.grundwasserstandonline.nlwkn.niedersachsen.de/"
USER_AGENT = "WorldObserver/0.14 WiesmoorPeatlandObserver (+https://github.com/)"
REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 2
RECENT_OBSERVATION_MAX_AGE_DAYS = 14
MIN_COVERAGE_7D = 7
MIN_COVERAGE_30D = 27
MISSING_VALUES = {"", "-999", "-999.0"}
SOIL_MOISTURE_MISSING_VALUES = {"", "-9999", "-9999.0", "nan", "NaN"}
GERMANY_LATITUDE_RANGE = (47.0, 56.0)
GERMANY_LONGITUDE_RANGE = (5.0, 16.0)


@dataclass(frozen=True)
class DwdSoilMoistureObservation:
    observation_date: date
    value: float | None
    unit: str
    grid_cell_x: float | None
    grid_cell_y: float | None
    grid_cell_latitude: float | None
    grid_cell_longitude: float | None
    source_url: str

class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            for key, value in attrs:
                if key.lower() == "href" and value:
                    self.hrefs.append(value)

@dataclass(frozen=True)
class DwdStation:
    station_id: str
    from_date: date
    to_date: date
    latitude: float
    longitude: float
    name: str
    state: str
    distance_km: float

@dataclass(frozen=True)
class NlwknGroundwaterStation:
    station_name: str
    station_id: str | None
    latitude: float | None
    longitude: float | None
    distance_km: float | None
    latest_date: str | None
    latest_value: float | None
    latest_value_unit: str | None
    status_category: str | None
    data_status: str
    source_url: str | None

@dataclass
class AdapterDiagnostics:
    api_attempts: int = 0
    retries: int = 0
    http_status: int | None = None
    error: str | None = None

_RUN_CACHE: dict[str, bytes | str] = {}

def _date_utc() -> str:
    raw = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if raw:
        try: return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
        except ValueError: pass
    return datetime.now(timezone.utc).date().isoformat()

def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _unavailable_source(name: str, url: str, note: str) -> dict[str, Any]:
    return {"name": name, "url": url, "status": "adapter_pending", "note": note}

def _parse_dwd_date(raw: str) -> date:
    return datetime.strptime(raw.strip(), "%Y%m%d").date()

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km using the documented haversine formula."""
    radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def _fetch_url(url: str, diagnostics: AdapterDiagnostics) -> bytes:
    if url in _RUN_CACHE and isinstance(_RUN_CACHE[url], bytes):
        return _RUN_CACHE[url]  # type: ignore[return-value]
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        diagnostics.api_attempts += 1
        if attempt: diagnostics.retries += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                diagnostics.http_status = getattr(response, "status", None)
                data = response.read()
                _RUN_CACHE[url] = data
                return data
        except urllib.error.HTTPError as exc:
            diagnostics.http_status = exc.code; last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt < MAX_RETRIES:
            time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"HTTP request failed for {url}: {last_error}")

def parse_station_description(text: str, today: date | None = None) -> list[DwdStation]:
    today = today or datetime.now(timezone.utc).date()
    stations: list[DwdStation] = []
    for line in text.splitlines():
        if not re.match(r"^\s*\d{5}\s+\d{8}\s+\d{8}\s+", line):
            continue
        parts = line.split()
        try:
            station_id = parts[0].zfill(5)
            from_date, to_date = _parse_dwd_date(parts[1]), _parse_dwd_date(parts[2])
            lat, lon = float(parts[4]), float(parts[5])
        except (ValueError, IndexError):
            continue
        name = parts[6].replace("_", " ")
        state = " ".join(parts[7:-1]) if len(parts) > 8 else ""
        stations.append(DwdStation(station_id, from_date, to_date, lat, lon, name, state, round(haversine_km(LATITUDE, LONGITUDE, lat, lon), 2)))
    return sorted(stations, key=lambda s: (s.distance_km, s.station_id))

def _station_zip_url(station_id: str) -> str:
    return f"{DWD_KL_RECENT_BASE_URL}tageswerte_KL_{station_id}_akt.zip"

def select_station(stations: list[DwdStation], today: date | None = None) -> DwdStation | None:
    today = today or datetime.now(timezone.utc).date()
    recent_cutoff = today - timedelta(days=RECENT_OBSERVATION_MAX_AGE_DAYS)
    suitable = [s for s in stations if s.to_date >= recent_cutoff]
    return suitable[0] if suitable else None

def _parse_float(raw: str | None) -> float | None:
    if raw is None or raw.strip() in MISSING_VALUES: return None
    try: return float(raw.strip())
    except ValueError: return None

def _normalize_key(key: Any) -> str:
    return str(key).lower().replace("_", "").replace("-", "")

def _deep_get(record: Any, names: set[str]) -> Any:
    """Return the first value whose normalized key is in names from nested source JSON."""
    return _deep_get_preferred(record, list(names))

def _deep_get_preferred(record: Any, names: list[str]) -> Any:
    """Return a nested value while honoring the caller's field preference order."""
    normalized_names = [_normalize_key(name) for name in names]
    if isinstance(record, dict):
        normalized_items = [(_normalize_key(key), value) for key, value in record.items()]
        for name in normalized_names:
            for key, value in normalized_items:
                if key == name and value is not None:
                    return value
        for value in record.values():
            found = _deep_get_preferred(value, names)
            if found is not None:
                return found
    elif isinstance(record, list):
        for value in record:
            found = _deep_get_preferred(value, names)
            if found is not None:
                return found
    return None

def _parse_coordinate(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    return _parse_float(value.replace(",", "."))

def _parse_latest_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    return _parse_float(value.replace(",", "."))

def _in_range(value: float | None, bounds: tuple[float, float]) -> bool:
    return value is not None and bounds[0] <= value <= bounds[1]

def _parse_nlwkn_coordinates(record: dict[str, Any]) -> tuple[float | None, float | None]:
    """Parse NLWKN WGS84 coordinates, including reversed Latitude/Longitude labels."""
    rechtswert = _parse_coordinate(_deep_get_preferred(record, ["WGS84Rechtswert"]))
    hochwert = _parse_coordinate(_deep_get_preferred(record, ["WGS84Hochwert"]))
    if _in_range(rechtswert, GERMANY_LATITUDE_RANGE) and _in_range(hochwert, GERMANY_LONGITUDE_RANGE):
        return rechtswert, hochwert

    labeled_lat = _parse_coordinate(_deep_get_preferred(record, ["Latitude", "lat", "geobreite", "breitengrad"]))
    labeled_lon = _parse_coordinate(_deep_get_preferred(record, ["Longitude", "lon", "lng", "geolaenge", "geolange", "laengengrad", "längengrad"]))
    if _in_range(labeled_lat, GERMANY_LATITUDE_RANGE) and _in_range(labeled_lon, GERMANY_LONGITUDE_RANGE):
        return labeled_lat, labeled_lon
    if _in_range(labeled_lon, GERMANY_LATITUDE_RANGE) and _in_range(labeled_lat, GERMANY_LONGITUDE_RANGE):
        return labeled_lon, labeled_lat
    return None, None

def normalize_nlwkn_status_label(label: Any) -> str | None:
    """Normalize common labels while preserving source-native labels safely."""
    if label is None:
        return None
    normalized = str(label).strip()
    if not normalized:
        return None
    compact = normalized.lower().replace("_", " ").replace("-", " ")
    compact = re.sub(r"\s+", " ", compact)
    mapping = {
        "sehr niedrig": "very_low",
        "sehr nied­rig": "very_low",
        "very low": "very_low",
        "niedrig": "low",
        "low": "low",
        "normal": "normal",
        "mittel": "normal",
        "hoch": "high",
        "high": "high",
        "sehr hoch": "very_high",
        "very high": "very_high",
    }
    return mapping.get(compact, normalized)

def parse_nlwkn_station(record: dict[str, Any]) -> NlwknGroundwaterStation:
    station_id = _deep_get_preferred(record, ["STA_Nummer", "STA_ID", "station_id", "stationid", "stationsid", "messstellenid", "id"])
    station_name = _deep_get_preferred(record, ["Name", "STA_Name", "station_name", "stationname", "messstellenname", "bezeichnung"])
    place = _deep_get_preferred(record, ["Ort", "Landkreis"])
    lat, lon = _parse_nlwkn_coordinates(record)
    latest_value = _parse_latest_value(_deep_get_preferred(record, ["GWAktuellerMesswertNNM", "Wert", "GWAktuellerMesswert", "latestvalue", "aktuellerwert", "messwert", "tageswert"]))
    latest_date = _deep_get_preferred(record, ["AktuellerMesswert_Zeitpunkt", "latestdate", "datum", "messdatum", "zeitpunkt", "tageswertdatum"])
    unit = _deep_get_preferred(record, ["unit", "einheit", "masseinheit", "maßeinheit"])
    status = normalize_nlwkn_status_label(_deep_get_preferred(record, ["AktuellGrundwasserstandsklasse", "Grundwasserstandsklasse", "statuscategory", "status", "klasse", "klassifikation", "einordnung"]))
    source_url = _deep_get_preferred(record, ["sourceurl", "url", "link"]) or NLWKN_PORTAL_URL
    distance = round(haversine_km(LATITUDE, LONGITUDE, lat, lon), 2) if lat is not None and lon is not None else None
    return NlwknGroundwaterStation(
        station_name=str(station_name or place or "NLWKN groundwater station"),
        station_id=str(station_id) if station_id is not None else None,
        latitude=lat,
        longitude=lon,
        distance_km=distance,
        latest_date=str(latest_date) if latest_date else None,
        latest_value=latest_value,
        latest_value_unit=str(unit) if unit else ("m NHN" if latest_value is not None else None),
        status_category=status,
        data_status="ok" if latest_value is not None and latest_date else ("partial" if latest_value is not None or latest_date or status else "metadata_only"),
        source_url=str(source_url) if source_url else None,
    )

def select_nlwkn_stations(stations: list[NlwknGroundwaterStation], limit: int = 3) -> list[NlwknGroundwaterStation]:
    suitable = [s for s in stations if s.distance_km is not None]
    return sorted(suitable, key=lambda s: (s.data_status not in {"ok", "partial"}, s.distance_km if s.distance_km is not None else 10**9, s.station_id or s.station_name))[:limit]

def _station_to_dict(station: NlwknGroundwaterStation) -> dict[str, Any]:
    return {
        "station_name": station.station_name,
        "station_id": station.station_id,
        "latitude": station.latitude,
        "longitude": station.longitude,
        "distance_km": station.distance_km,
        "latest_date": station.latest_date,
        "latest_value": station.latest_value,
        "latest_value_unit": station.latest_value_unit,
        "status_category": station.status_category,
        "data_status": station.data_status,
        "source_url": station.source_url,
    }

def parse_daily_product(zip_bytes: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.lower().startswith("produkt_klima_tag_") and n.lower().endswith(".txt")]
        if not names: raise ValueError("DWD ZIP did not contain a daily climate product file")
        with zf.open(sorted(names)[0]) as fh:
            text = fh.read().decode("latin1")
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for raw in reader:
        row = {str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items() if k is not None}
        try: obs_date = _parse_dwd_date(row["MESS_DATUM"])
        except (KeyError, ValueError): continue
        rows.append({"date": obs_date, "precip_mm": _parse_float(row.get("RSK")), "temperature_c": _parse_float(row.get("TMK"))})
    return sorted(rows, key=lambda r: r["date"])

def rolling_total(rows: list[dict[str, Any]], latest: date, days: int, min_valid: int) -> tuple[float | None, int, int]:
    # Coverage rule: only sum observations inside the calendar window. Missing DWD values (-999/null)
    # and absent days reduce valid_days; they are never treated as dry 0.0 mm days.
    start = latest - timedelta(days=days - 1)
    by_date = {r["date"]: r for r in rows if start <= r["date"] <= latest}
    values = [by_date[d]["precip_mm"] for d in (start + timedelta(days=i) for i in range(days)) if d in by_date and by_date[d]["precip_mm"] is not None]
    return (round(sum(values), 1) if len(values) >= min_valid else None, len(values), days)

def _station_metadata(station: DwdStation | None) -> dict[str, Any] | None:
    if station is None: return None
    return {"station_id": station.station_id, "station_name": station.name, "latitude": station.latitude, "longitude": station.longitude, "distance_km": station.distance_km, "selection_method": f"Nearest DWD CDC recent daily climate station to Wiesmoor ({LATITUDE}, {LONGITUDE}) with station metadata end date within {RECENT_OBSERVATION_MAX_AGE_DAYS} days; distance uses haversine great-circle calculation."}

# keep existing context funcs
def peat_context() -> dict[str, Any]:
    return {
        "area_name": "Wiesmoor-Nord / Wiesmoor peatland landscape",
        "location": {
            "municipality": "Wiesmoor",
            "district": "Aurich",
            "state": "Lower Saxony",
            "country": "Germany",
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
        },
        "context_note": (
            "Wiesmoor is a settlement and landscape shaped by raised-bog peat extraction, drainage, "
            "peat-fired industry and subsequent agricultural/horticultural use. MoorIS Niedersachsen "
            "maps the Wiesmoor-Nord peatland context, including peat-thickness information; this "
            "observer carries that context as static source metadata rather than as a live sensor."
        ),
        "peat_thickness_context": {
            "status": "context_available_from_source_not_live_ingested",
            "description": "MoorIS Niedersachsen / Wiesmoor-Nord provides local peat-thickness context for the mapped peatland area.",
            "value": None,
            "unit": None,
            "precision_note": "No numeric peat-thickness value is emitted until a reproducible MoorIS data extraction is added.",
        },
        "source": {
            "name": "MoorIS Niedersachsen / Wiesmoor-Nord",
            "url": "https://mooris-niedersachsen.de/",
            "status": "static_context",
        },
    }


def groundwater_proxy() -> dict[str, Any]:
    diagnostics = AdapterDiagnostics()
    source = {
        "name": "NLWKN Grundwasserstandonline / groundwater monitoring data",
        "url": NLWKN_PORTAL_URL,
        "status": "live_adapter",
        "dataset": "Grundwasserstandonline public station metadata with current daily value where exposed",
        "station_metadata_url": NLWKN_STATIONS_URL,
    }
    base: dict[str, Any] = {
        "label": "groundwater proxy",
        "interpretation_note": (
            "Nearby groundwater stations can indicate regional groundwater behaviour but are not an "
            "in-situ peat water-table sensor for Wiesmoor-Nord."
        ),
        "selection_method": (
            f"Fetch official NLWKN Grundwasserstandonline public station metadata, parse station "
            f"coordinates and current values when present, then select the nearest suitable stations "
            f"to Wiesmoor ({LATITUDE}, {LONGITUDE}) by haversine distance; prefer stations with live "
            f"value/date/status metadata but never fabricate missing values."
        ),
        "stations": [],
        "nearest_station": None,
        "regional_status_summary": "unavailable",
        "source": source,
        "data_status": "unavailable",
    }
    try:
        raw = _fetch_url(NLWKN_STATIONS_URL, diagnostics)
        payload = json.loads(raw.decode("utf-8-sig"))
        records = payload if isinstance(payload, list) else payload.get("getStammdatenResult") or payload.get("data") or payload.get("stations") or payload.get("features") or []
        parsed: list[NlwknGroundwaterStation] = []
        for item in records:
            if isinstance(item, dict):
                if item.get("type") == "Feature" and isinstance(item.get("properties"), dict):
                    merged = dict(item["properties"])
                    coords = (item.get("geometry") or {}).get("coordinates") if isinstance(item.get("geometry"), dict) else None
                    if isinstance(coords, list) and len(coords) >= 2:
                        merged.setdefault("longitude", coords[0])
                        merged.setdefault("latitude", coords[1])
                    item = merged
                parsed.append(parse_nlwkn_station(item))
        selected = select_nlwkn_stations(parsed, 3)
        base["stations"] = [_station_to_dict(s) for s in selected]
        base["nearest_station"] = base["stations"][0] if selected else None
        statuses = [s.status_category for s in selected if s.status_category]
        if statuses:
            base["regional_status_summary"] = statuses[0] if len(set(statuses)) == 1 else "mixed_source_native_status"
        if selected:
            base["data_status"] = "ok" if all(s.data_status == "ok" for s in selected) else "partial"
        else:
            raise RuntimeError("NLWKN response contained no stations with usable coordinates")
    except Exception as exc:
        diagnostics.error = str(exc)
        source["status"] = "temporarily_unavailable"
        source["note"] = "NLWKN adapter failed gracefully; no groundwater values were fabricated."
        base["stations"] = []
        base["nearest_station"] = None
        base["data_status"] = "unavailable"
    return base, diagnostics


def _parse_soil_moisture_value(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        if raw in DWD_SOIL_MOISTURE_FILL_VALUES or (isinstance(raw, float) and math.isnan(raw)):
            return None
        return float(raw)
    text = str(raw).strip().replace(",", ".")
    if text in SOIL_MOISTURE_MISSING_VALUES:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return None if value in DWD_SOIL_MOISTURE_FILL_VALUES else value

def _soil_moisture_year_url(year: int) -> str:
    return f"{DWD_SOIL_MOISTURE_BASE_URL}{year}/"

def parse_directory_hrefs(html: str) -> list[str]:
    parser = _HrefParser()
    parser.feed(html)
    return parser.hrefs

def select_soil_moisture_file(hrefs: list[str], year: int, layer: str = DWD_SOIL_MOISTURE_LAYER) -> str | None:
    pattern = re.compile(rf"^grids_germany_daily_soil_moisture_{DWD_SOIL_MOISTURE_CULTURE}_{year}_{re.escape(layer)}_v\d+\.nc$")
    candidates = sorted(href for href in hrefs if pattern.match(href.split("/")[-1]))
    return candidates[-1] if candidates else None

def _extract_soil_moisture_observation(netcdf_bytes: bytes, source_url: str) -> DwdSoilMoistureObservation:
    try:
        import netCDF4  # type: ignore[import-not-found]
        from pyproj import Transformer  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("netCDF4 and pyproj are required to extract DWD soil-moisture NetCDF grid cells in this environment") from exc
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".nc") as tmp:
        tmp.write(netcdf_bytes)
        tmp.flush()
        with netCDF4.Dataset(tmp.name) as ds:  # type: ignore[attr-defined]
            x_var = ds.variables.get("x") or ds.variables.get("X")
            y_var = ds.variables.get("y") or ds.variables.get("Y")
            time_var = ds.variables.get("time") or ds.variables.get("TIME")
            if x_var is None or y_var is None or time_var is None:
                raise RuntimeError("DWD soil-moisture NetCDF lacks expected x/y/time coordinate variables")
            data_var = None
            for var in ds.variables.values():
                dims = tuple(getattr(var, "dimensions", ()))
                units = str(getattr(var, "units", ""))
                name = str(getattr(var, "name", ""))
                long_name = str(getattr(var, "long_name", ""))
                if "time" in dims and ("‰" in units or "nFK" in units or "soil" in (name + long_name).lower()):
                    if len(dims) >= 3:
                        data_var = var
                        break
            if data_var is None:
                raise RuntimeError("DWD soil-moisture NetCDF lacks an identifiable time/y/x soil-moisture variable")

            xs = list(x_var[:])
            ys = list(y_var[:])
            transformer = Transformer.from_crs("EPSG:4326", "EPSG:31467", always_xy=True)
            target_x, target_y = transformer.transform(LONGITUDE, LATITUDE)
            x_index = min(range(len(xs)), key=lambda i: abs(float(xs[i]) - target_x))
            y_index = min(range(len(ys)), key=lambda i: abs(float(ys[i]) - target_y))
            times = list(time_var[:])
            if not times:
                raise RuntimeError("DWD soil-moisture NetCDF time coordinate is empty")
            time_index = len(times) - 1
            dt = netCDF4.num2date(times[time_index], getattr(time_var, "units"), getattr(time_var, "calendar", "standard"))
            obs_date = date(int(dt.year), int(dt.month), int(dt.day))
            dims = tuple(getattr(data_var, "dimensions", ()))
            index_by_dim = {"time": time_index, "x": x_index, "X": x_index, "y": y_index, "Y": y_index}
            key = tuple(index_by_dim.get(dim, 0) for dim in dims)
            raw_value = data_var[key]
            if hasattr(raw_value, "filled"):
                raw_value = raw_value.filled(-9999)
            try:
                raw_scalar = raw_value.item()
            except AttributeError:
                raw_scalar = raw_value
            value = _parse_soil_moisture_value(raw_scalar)
            unit = str(getattr(data_var, "units", DWD_SOIL_MOISTURE_UNIT)) or DWD_SOIL_MOISTURE_UNIT
            return DwdSoilMoistureObservation(obs_date, value, unit, float(xs[x_index]), float(ys[y_index]), None, None, source_url)

def _soil_moisture_source(status: str = "live_adapter") -> dict[str, Any]:
    return {
        "name": "Deutscher Wetterdienst (DWD) Climate Data Center",
        "url": DWD_SOIL_MOISTURE_BASE_URL,
        "status": status,
        "dataset": DWD_SOIL_MOISTURE_PRODUCT,
        "dataset_id": DWD_SOIL_MOISTURE_DATASET_ID,
        "description_url": DWD_SOIL_MOISTURE_BASE_URL + "DESCRIPTION_grids_germany_daily_soil_moisture_grass_en.pdf",
    }

def regional_soil_water() -> tuple[dict[str, Any], AdapterDiagnostics]:
    diagnostics = AdapterDiagnostics()
    source = _soil_moisture_source()
    base: dict[str, Any] = {
        "label": "regional DWD gridded soil-moisture condition",
        "dataset": DWD_SOIL_MOISTURE_PRODUCT,
        "dataset_id": DWD_SOIL_MOISTURE_DATASET_ID,
        "variable": "mean soil moisture under grass, 0-60 cm layer",
        "unit": DWD_SOIL_MOISTURE_UNIT,
        "spatial_resolution_km": 1,
        "temporal_resolution": "daily",
        "latest_value": None,
        "latest_date": None,
        "status": "unavailable",
        "trend": "unavailable",
        "grid_cell": None,
        "selection_method": f"Deterministically select the source grid cell containing or nearest to Wiesmoor ({LATITUDE}, {LONGITUDE}) from the DWD NetCDF grid metadata; no regional averaging and no conversion to peat water-table depth.",
        "limitations": [
            "Regional gridded model product, not an in-situ peat water-table sensor.",
            "DWD AMBAV soil moisture under grass preserves source-native ‰ nFK semantics and is not converted to water-table depth.",
        ],
        "source": source,
    }
    try:
        year = int(_date_utc()[:4])
        listing_url = _soil_moisture_year_url(year)
        html = _fetch_url(listing_url, diagnostics).decode("utf-8", "replace")
        filename = select_soil_moisture_file(parse_directory_hrefs(html), year)
        if not filename:
            raise RuntimeError(f"No DWD soil-moisture NetCDF file for layer {DWD_SOIL_MOISTURE_LAYER} found in {listing_url}")
        file_url = listing_url + filename
        source["selected_file_url"] = file_url
        obs = _extract_soil_moisture_observation(_fetch_url(file_url, diagnostics), file_url)
        base["latest_date"] = obs.observation_date.isoformat()
        base["latest_value"] = obs.value
        base["grid_cell"] = {"x": obs.grid_cell_x, "y": obs.grid_cell_y, "latitude": obs.grid_cell_latitude, "longitude": obs.grid_cell_longitude}
        source["observation_date"] = obs.observation_date.isoformat()
        source["source_url"] = obs.source_url
        base["status"] = "ok" if obs.value is not None else "unavailable"
    except Exception as exc:
        diagnostics.error = str(exc)
        source["status"] = "temporarily_unavailable"
        source["note"] = "DWD soil-moisture adapter failed gracefully; no soil-moisture values were fabricated."
    return base, diagnostics


def weather_pressure() -> tuple[dict[str, Any], AdapterDiagnostics]:
    diagnostics = AdapterDiagnostics()
    source_url = DWD_KL_RECENT_BASE_URL
    source = {
        "name": "Deutscher Wetterdienst (DWD) Climate Data Center",
        "url": source_url,
        "status": "live_adapter",
        "dataset": "Recent daily climate observations Germany (KL), daily precipitation RSK and daily mean temperature TMK",
        "station_description_url": DWD_KL_RECENT_BASE_URL + DWD_STATION_DESCRIPTION,
    }
    base: dict[str, Any] = {
        "label": "weather pressure",
        "rainfall_7d_mm": None,
        "rainfall_30d_mm": None,
        "temperature_c": None,
        "temperature_label": "latest valid daily mean temperature (TMK), not an instantaneous/current temperature",
        "latest_date": None,
        "data_status": "unavailable",
        "station": None,
        "coverage": {
            "valid_days_7d": 0,
            "expected_days_7d": 7,
            "valid_days_30d": 0,
            "expected_days_30d": 30,
            "minimum_coverage_rule": f"7-day total requires {MIN_COVERAGE_7D}/7 valid precipitation days; 30-day total requires at least {MIN_COVERAGE_30D}/30 valid precipitation days. DWD -999/missing and absent dates are unavailable, not zero.",
        },
        "source": source,
    }
    station: DwdStation | None = None
    try:
        station_text = _fetch_url(DWD_KL_RECENT_BASE_URL + DWD_STATION_DESCRIPTION, diagnostics).decode("latin1")
        station = select_station(parse_station_description(station_text))
        base["station"] = _station_metadata(station)
        if station is None:
            raise RuntimeError("No suitable recent DWD KL station found in station description")
        source["selected_station_zip_url"] = _station_zip_url(station.station_id)
        zip_bytes = _fetch_url(_station_zip_url(station.station_id), diagnostics)
        rows = parse_daily_product(zip_bytes)
        valid_precip_rows = [r for r in rows if r["precip_mm"] is not None]
        if not valid_precip_rows:
            raise RuntimeError("Selected DWD station has no valid precipitation observations")
        latest = max(r["date"] for r in valid_precip_rows)
        rainfall_7d, valid_7d, expected_7d = rolling_total(rows, latest, 7, MIN_COVERAGE_7D)
        rainfall_30d, valid_30d, expected_30d = rolling_total(rows, latest, 30, MIN_COVERAGE_30D)
        latest_temp = next((r["temperature_c"] for r in reversed(rows) if r["date"] <= latest and r["temperature_c"] is not None), None)
        base.update({
            "rainfall_7d_mm": rainfall_7d,
            "rainfall_30d_mm": rainfall_30d,
            "temperature_c": latest_temp,
            "latest_date": latest.isoformat(),
            "data_status": "ok" if rainfall_7d is not None and rainfall_30d is not None else "partial",
            "coverage": {
                **base["coverage"],
                "valid_days_7d": valid_7d,
                "expected_days_7d": expected_7d,
                "valid_days_30d": valid_30d,
                "expected_days_30d": expected_30d,
            },
        })
        source["observation_date"] = latest.isoformat()
    except Exception as exc:
        diagnostics.error = str(exc)
        if station is not None:
            base["station"] = _station_metadata(station)
            source["selected_station_zip_url"] = _station_zip_url(station.station_id)
        source["status"] = "temporarily_unavailable"
        source["note"] = "DWD adapter failed gracefully; no live weather values were fabricated."
    return base, diagnostics


def derive_pressure(soil: dict[str, Any], groundwater: dict[str, Any], weather: dict[str, Any]) -> dict[str, Any]:
    rainfall_7d = weather.get("rainfall_7d_mm")
    rainfall_30d = weather.get("rainfall_30d_mm")
    soil_trend = soil.get("trend") or "unavailable"
    groundwater_status = groundwater.get("data_status") or "unavailable"
    available = [value for value in (rainfall_7d, rainfall_30d) if isinstance(value, (int, float))]
    if not available and soil_trend == "unavailable" and groundwater_status == "unavailable":
        state = "unavailable"
        confidence = "low"
    else:
        state = "unavailable"
        confidence = "low"
    return {
        "value": state,
        "rainfall_7d": rainfall_7d,
        "rainfall_30d": rainfall_30d,
        "soil_water_trend": soil_trend,
        "groundwater_proxy_status": groundwater_status,
        "confidence": confidence,
        "limitations": [
            "Regional proxy observation — not an in-situ peat water-table sensor.",
            "DWD daily rainfall is one regional proxy component only and is not an in-situ peat water-table measurement.",
            "NLWKN groundwater stations are a regional proxy; station distance and local hydrogeological representativeness are uncertain.",
            "Groundwater level observations are not the same as a peat water-table measurement in Wiesmoor-Nord peat soils.",
            "Groundwater stations, satellite soil-water data and weather totals may describe different depths, footprints and response times.",
        ],
    }


def build_payload() -> dict[str, Any]:
    target_date = _date_utc()
    context = peat_context()
    groundwater, groundwater_diagnostics = groundwater_proxy()
    soil, soil_diagnostics = regional_soil_water()
    weather, weather_diagnostics = weather_pressure()
    pressure = derive_pressure(soil, groundwater, weather)
    data_status = "partial" if weather.get("data_status") in {"ok", "partial"} else "unavailable"
    return {
        "observer": OBSERVER,
        "display_name": "Wiesmoor Peatland Observer",
        "category": "environment",
        "date": target_date,
        "date_utc": target_date,
        "collected_at_utc": _now_utc(),
        "status": "ok",
        "data_status": data_status,
        "location": context["location"],
        "observation_type": "regional_proxy_not_in_situ_sensor",
        "peat_context": context,
        "groundwater_proxy": groundwater,
        "regional_soil_water": soil,
        "weather_pressure": weather,
        "peatland_hydrological_pressure": pressure,
        "primary_metric_value": pressure["value"],
        "summary": "Wiesmoor peatland hydrological pressure remains unavailable as an in-situ conclusion; DWD daily rainfall is emitted when available as a regional weather proxy component only.",
        "sources": [context["source"], groundwater["source"], soil["source"], weather["source"]],
        "diagnostics": {
            "api_attempts": weather_diagnostics.api_attempts + groundwater_diagnostics.api_attempts + soil_diagnostics.api_attempts,
            "retries": weather_diagnostics.retries + groundwater_diagnostics.retries + soil_diagnostics.retries,
            "http_status": {"dwd": weather_diagnostics.http_status, "nlwkn_groundwater": groundwater_diagnostics.http_status, "dwd_soil_moisture": soil_diagnostics.http_status},
            "live_adapters_enabled": [DWD_ADAPTER_ID, NLWKN_GROUNDWATER_ADAPTER_ID, DWD_SOIL_MOISTURE_ADAPTER_ID],
            "adapter_errors": ([weather_diagnostics.error] if weather_diagnostics.error else []) + ([groundwater_diagnostics.error] if groundwater_diagnostics.error else []) + ([soil_diagnostics.error] if soil_diagnostics.error else []),
        },
    }


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
