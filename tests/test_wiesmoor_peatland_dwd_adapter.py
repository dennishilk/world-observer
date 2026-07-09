from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path


def load_observer():
    path = Path(__file__).resolve().parents[1] / "observers" / "wiesmoor-peatland" / "observer.py"
    spec = importlib.util.spec_from_file_location("wiesmoor_peatland_observer", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def product_zip(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("produkt_klima_tag_20260101_20260131_00001.txt", "\n".join(lines) + "\n")
    return buf.getvalue()


def test_dwd_missing_value_does_not_become_zero() -> None:
    observer = load_observer()
    rows = observer.parse_daily_product(product_zip([
        "STATIONS_ID;MESS_DATUM;QN_3;FX;FM;QN_4;RSK;RSKF;SDK;SHK_TAG;NM;VPM;PM;TMK;UPM;TXK;TNK;TGK;eor",
        "1;20260101;-999;-999;-999;3;-999;-999;-999;-999;-999;-999;-999;4.2;-999;-999;-999;-999;eor",
        "1;20260102;-999;-999;-999;3;0.0;0;-999;-999;-999;-999;-999;5.1;-999;-999;-999;-999;eor",
    ]))
    assert rows[0]["precip_mm"] is None
    assert rows[1]["precip_mm"] == 0.0


def test_missing_day_does_not_count_as_dry_day_and_coverage_blocks_total() -> None:
    observer = load_observer()
    latest = date(2026, 1, 7)
    rows = [
        {"date": latest - timedelta(days=i), "precip_mm": 1.0, "temperature_c": None}
        for i in range(6)
    ]
    total, valid, expected = observer.rolling_total(rows, latest, 7, 7)
    assert total is None
    assert valid == 6
    assert expected == 7


def test_rolling_total_allows_real_zero_precipitation() -> None:
    observer = load_observer()
    latest = date(2026, 1, 7)
    rows = [
        {"date": latest - timedelta(days=i), "precip_mm": 0.0, "temperature_c": None}
        for i in range(7)
    ]
    total, valid, expected = observer.rolling_total(rows, latest, 7, 7)
    assert total == 0.0
    assert valid == 7
    assert expected == 7


def test_30_day_coverage_rule() -> None:
    observer = load_observer()
    latest = date(2026, 1, 30)
    rows = [{"date": latest - timedelta(days=i), "precip_mm": 1.0, "temperature_c": None} for i in range(27)]
    total, valid, expected = observer.rolling_total(rows, latest, 30, 27)
    assert total == 27.0
    assert valid == 27
    assert expected == 30


def test_station_selection_is_nearest_recent_station() -> None:
    observer = load_observer()
    text = """
Stations_id von_datum bis_datum Stationshoehe geoBreite geoLaenge Stationsname Bundesland Abgabe
----------- --------- --------- ------------- --------- --------- ----------------------------------------- ---------- ------
00001 20200101 20260105 1 53.5000 7.8000 Near_recent Niedersachsen frei
00002 20200101 20260105 1 54.0000 8.5000 Far_recent Niedersachsen frei
00003 20200101 20250101 1 53.4200 7.7400 Nearest_stale Niedersachsen frei
"""
    stations = observer.parse_station_description(text, today=date(2026, 1, 10))
    selected = observer.select_station(stations, today=date(2026, 1, 10))
    assert selected.station_id == "00001"
    assert selected.name == "Near recent"
