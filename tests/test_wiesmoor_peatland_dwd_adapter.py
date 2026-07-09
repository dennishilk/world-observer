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


def test_haversine_distance_is_deterministic_for_wiesmoor_to_station() -> None:
    observer = load_observer()
    assert round(observer.haversine_km(53.4167, 7.7333, 53.5000, 7.8000), 2) == 10.26


def test_nlwkn_station_selection_prefers_nearest_suitable_station() -> None:
    observer = load_observer()
    stations = [
        observer.NlwknGroundwaterStation("far", "2", 54.0, 8.5, 82.0, "2026-01-01", 1.2, "m NHN", "normal", "ok", "u"),
        observer.NlwknGroundwaterStation("near", "1", 53.42, 7.74, 0.57, "2026-01-01", 1.0, "m NHN", "low", "ok", "u"),
        observer.NlwknGroundwaterStation("missing coords", "3", None, None, None, "2026-01-01", 2.0, "m NHN", "high", "ok", "u"),
    ]
    selected = observer.select_nlwkn_stations(stations, limit=2)
    assert [s.station_id for s in selected] == ["1", "2"]


def test_nlwkn_missing_latest_value_does_not_become_zero() -> None:
    observer = load_observer()
    station = observer.parse_nlwkn_station({
        "id": "abc",
        "name": "Test station",
        "latitude": "53,42",
        "longitude": "7,74",
        "aktuellerWert": "",
        "datum": "2026-01-01",
    })
    assert station.latest_value is None
    assert station.data_status == "partial"


def test_nlwkn_status_labels_normalize_safely() -> None:
    observer = load_observer()
    assert observer.normalize_nlwkn_status_label("sehr niedrig") == "very_low"
    assert observer.normalize_nlwkn_status_label("hoch") == "high"
    assert observer.normalize_nlwkn_status_label("source-native special") == "source-native special"


def test_observer_emits_valid_json_if_nlwkn_unavailable(monkeypatch) -> None:
    observer = load_observer()
    real_fetch = observer._fetch_url

    def fake_fetch(url, diagnostics):
        if url == observer.NLWKN_STATIONS_URL:
            raise RuntimeError("simulated NLWKN outage")
        return real_fetch(url, diagnostics)

    monkeypatch.setattr(observer, "_fetch_url", fake_fetch)
    payload = observer.build_payload()
    assert payload["groundwater_proxy"]["data_status"] == "unavailable"
    assert payload["groundwater_proxy"]["nearest_station"] is None
    assert any("simulated NLWKN outage" in error for error in payload["diagnostics"]["adapter_errors"])


def real_nlwkn_fixture() -> dict:
    return {
        "getStammdatenResult": [
            {
                "Name": "Wiesmoor nah",
                "Ort": "Wiesmoor",
                "Landkreis": "Aurich",
                "STA_ID": 1001,
                "STA_Nummer": "GW-1001",
                "AktuellGrundwasserstandsklasse": "normal",
                "GWAktuellerMesswert": None,
                "GWAktuellerMesswertNNM": "4,25",
                "WGS84Hochwert": "7,7400",
                "WGS84Rechtswert": "53,4200",
                "Latitude": "9,86",
                "Longitude": "51,51",
                "Parameter": [
                    {
                        "Datenspuren": [
                            {
                                "AktuellerMesswert_Zeitpunkt": "2026-01-02T03:04:05",
                                "AktuellerPegelstand": {
                                    "Wert": "3,21",
                                    "Grundwasserstandsklasse": "Quelleigene Sonderklasse",
                                },
                            }
                        ]
                    }
                ],
            },
            {
                "Name": "Wiesmoor swapped labels",
                "Ort": "Wiesmoor",
                "Landkreis": "Aurich",
                "STA_ID": "1002",
                "AktuellGrundwasserstandsklasse": "Quelleigene Sonderklasse",
                "GWAktuellerMesswertNNM": "",
                "WGS84Hochwert": None,
                "WGS84Rechtswert": None,
                "Latitude": "7,7333",
                "Longitude": "53,4167",
                "Parameter": [
                    {
                        "Datenspuren": [
                            {
                                "AktuellerMesswert_Zeitpunkt": "2026-01-03T00:00:00",
                                "AktuellerPegelstand": {
                                    "Wert": "",
                                    "Grundwasserstandsklasse": "Quelleigene Sonderklasse",
                                },
                            }
                        ]
                    }
                ],
            },
            {
                "Name": "weiter weg",
                "STA_ID": "1003",
                "WGS84Hochwert": "8,5000",
                "WGS84Rechtswert": "54,0000",
                "AktuellGrundwasserstandsklasse": "hoch",
            },
        ]
    }


def test_nlwkn_real_structure_coordinates_prefer_wgs84_fields() -> None:
    observer = load_observer()
    station = observer.parse_nlwkn_station(real_nlwkn_fixture()["getStammdatenResult"][0])
    assert station.station_id == "GW-1001"
    assert station.station_name == "Wiesmoor nah"
    assert station.latitude == 53.42
    assert station.longitude == 7.74
    assert station.latest_value == 4.25
    assert station.latest_value_unit == "m NHN"
    assert station.latest_date == "2026-01-02T03:04:05"
    assert station.status_category == "normal"


def test_nlwkn_swapped_latitude_longitude_labels_are_corrected() -> None:
    observer = load_observer()
    station = observer.parse_nlwkn_station(real_nlwkn_fixture()["getStammdatenResult"][1])
    assert station.latitude == 53.4167
    assert station.longitude == 7.7333
    assert station.latest_value is None
    assert station.latest_value_unit is None
    assert station.status_category == "Quelleigene Sonderklasse"


def test_groundwater_proxy_real_structure_selects_wiesmoor_nearest_stations(monkeypatch) -> None:
    observer = load_observer()

    def fake_fetch(url, diagnostics):
        assert url == observer.NLWKN_STATIONS_URL
        return observer.json.dumps(real_nlwkn_fixture()).encode()

    monkeypatch.setattr(observer, "_fetch_url", fake_fetch)
    payload, diagnostics = observer.groundwater_proxy()
    assert diagnostics.error is None
    assert payload["data_status"] == "partial"
    assert [s["station_id"] for s in payload["stations"][:2]] == ["1002", "GW-1001"]
    assert all(s["distance_km"] is not None for s in payload["stations"])
    assert payload["nearest_station"]["station_name"] == "Wiesmoor swapped labels"


def test_nlwkn_nested_values_preserve_missing_as_null_not_zero() -> None:
    observer = load_observer()
    station = observer.parse_nlwkn_station(real_nlwkn_fixture()["getStammdatenResult"][1])
    assert station.latest_value is None
    assert station.data_status == "partial"
