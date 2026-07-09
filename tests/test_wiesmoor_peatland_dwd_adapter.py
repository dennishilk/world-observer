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


def test_dwd_soil_moisture_selects_wiesmoor_grid_cell_deterministically(monkeypatch) -> None:
    observer = load_observer()
    year_url = observer._soil_moisture_year_url(2026)
    file_name = "grids_germany_daily_soil_moisture_grass_2026_0-60_v1.nc"

    def fake_fetch(url, diagnostics):
        if url == year_url:
            return f'<a href="{file_name}">{file_name}</a>'.encode()
        assert url == year_url + file_name
        return b"netcdf"

    def fake_extract(data, source_url):
        assert data == b"netcdf"
        assert source_url == year_url + file_name
        return observer.DwdSoilMoistureObservation(date(2026, 6, 30), 456.0, observer.DWD_SOIL_MOISTURE_UNIT, 3475000.0, 5921000.0, 53.416, 7.735, source_url)

    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", "2026-07-09")
    monkeypatch.setattr(observer, "_fetch_url", fake_fetch)
    monkeypatch.setattr(observer, "_extract_soil_moisture_observation", fake_extract)
    payload, diagnostics = observer.regional_soil_water()
    assert diagnostics.error is None
    assert payload["status"] == "ok"
    assert payload["latest_date"] == "2026-06-30"
    assert payload["latest_value"] == 456.0
    assert payload["unit"] == "‰ nFK"
    assert payload["grid_cell"]["latitude"] == 53.416
    assert payload["source"]["selected_file_url"].endswith(file_name)


def test_dwd_soil_moisture_missing_fill_values_remain_unavailable() -> None:
    observer = load_observer()
    assert observer._parse_soil_moisture_value("-9999") is None
    assert observer._parse_soil_moisture_value(-9999.0) is None
    assert observer._parse_soil_moisture_value("") is None


def test_dwd_soil_moisture_real_numeric_zero_is_valid() -> None:
    observer = load_observer()
    assert observer._parse_soil_moisture_value("0") == 0.0
    assert observer._parse_soil_moisture_value(0.0) == 0.0


def test_dwd_soil_moisture_date_parsing_and_unit_preservation(monkeypatch) -> None:
    observer = load_observer()
    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", "2026-07-09")
    assert observer._date_utc() == "2026-07-09"
    obs = observer.DwdSoilMoistureObservation(date(2026, 1, 2), 12.5, observer.DWD_SOIL_MOISTURE_UNIT, None, None, None, None, "u")
    assert obs.observation_date.isoformat() == "2026-01-02"
    assert obs.unit == "‰ nFK"


def test_dwd_soil_moisture_graceful_upstream_failure(monkeypatch) -> None:
    observer = load_observer()

    def fake_fetch(url, diagnostics):
        raise RuntimeError("simulated DWD soil outage")

    monkeypatch.setattr(observer, "_fetch_url", fake_fetch)
    payload, diagnostics = observer.regional_soil_water()
    assert payload["status"] == "unavailable"
    assert payload["latest_value"] is None
    assert payload["source"]["status"] == "temporarily_unavailable"
    assert "simulated DWD soil outage" in diagnostics.error


def test_dwd_soil_moisture_directory_file_selection() -> None:
    observer = load_observer()
    html = """
<a href="grids_germany_daily_soil_moisture_grass_2026_0-50_v1.nc">wrong layer</a>
<a href="grids_germany_daily_soil_moisture_grass_2026_0-60_v1.nc">v1</a>
<a href="grids_germany_daily_soil_moisture_grass_2025_0-60_v1.nc">wrong year</a>
"""
    hrefs = observer.parse_directory_hrefs(html)
    assert observer.select_soil_moisture_file(hrefs, 2026) == "grids_germany_daily_soil_moisture_grass_2026_0-60_v1.nc"


def daily_rows(latest: date, precip: list[float | None], temps: list[float | None] | None = None) -> list[dict]:
    temps = temps if temps is not None else [10.0] * len(precip)
    return [
        {"date": latest - timedelta(days=len(precip) - 1 - i), "precip_mm": p, "temperature_c": temps[i]}
        for i, p in enumerate(precip)
    ]


def test_rolling_temperature_means_require_documented_coverage() -> None:
    observer = load_observer()
    latest = date(2026, 1, 30)
    rows = daily_rows(latest, [1.0] * 30, [float(i + 1) for i in range(30)])
    mean_7d, valid_7d, expected_7d = observer.rolling_mean(rows, latest, 7, observer.MIN_COVERAGE_7D, "temperature_c")
    mean_30d, valid_30d, expected_30d = observer.rolling_mean(rows, latest, 30, observer.MIN_COVERAGE_30D, "temperature_c")
    assert mean_7d == 27.0
    assert valid_7d == expected_7d == 7
    assert mean_30d == 15.5
    assert valid_30d == expected_30d == 30


def test_temperature_mean_missing_and_absent_dates_block_insufficient_coverage() -> None:
    observer = load_observer()
    latest = date(2026, 1, 7)
    rows = daily_rows(latest, [1.0] * 6, [10.0] * 6)
    mean, valid, expected = observer.rolling_mean(rows, latest, 7, observer.MIN_COVERAGE_7D, "temperature_c")
    assert mean is None
    assert valid == 6
    assert expected == 7


def test_dry_day_threshold_boundary_behavior() -> None:
    observer = load_observer()
    latest = date(2026, 1, 7)
    rows = daily_rows(latest, [0.0, 0.2, 0.999, 1.0, 1.1, None, 0.5])
    count, valid, expected = observer.dry_day_count(rows, latest, 7, 7)
    assert count is None
    assert valid == 6
    assert expected == 7
    complete_rows = daily_rows(latest, [0.0, 0.2, 0.999, 1.0, 1.1, 2.0, 0.5])
    count, valid, expected = observer.dry_day_count(complete_rows, latest, 7, 7)
    assert count == 4
    assert valid == expected == 7


def test_7_day_and_30_day_dry_day_counts_follow_precipitation_coverage() -> None:
    observer = load_observer()
    latest = date(2026, 1, 30)
    precip = [0.0] * 20 + [1.0] * 7 + [None] * 3
    rows = daily_rows(latest, precip)
    dry_30d, valid_30d, expected_30d = observer.dry_day_count(rows, latest, 30, observer.MIN_COVERAGE_30D)
    assert dry_30d == 20
    assert valid_30d == 27
    assert expected_30d == 30
    dry_7d, valid_7d, expected_7d = observer.dry_day_count(rows, latest, 7, observer.MIN_COVERAGE_7D)
    assert dry_7d is None
    assert valid_7d == 4
    assert expected_7d == 7


def test_consecutive_dry_days_ending_at_latest_observation_stops_at_wet_or_missing() -> None:
    observer = load_observer()
    latest = date(2026, 1, 10)
    rows = daily_rows(latest, [0.0, 0.5, 1.0, 0.2, 0.3])
    assert observer.consecutive_dry_days(rows, latest) == 2
    rows_with_missing_gap = daily_rows(latest, [0.0, None, 0.2, 0.3, 0.4])
    assert observer.consecutive_dry_days(rows_with_missing_gap, latest) == 3
    rows_with_absent_gap = [r for r in rows_with_missing_gap if r["date"] != latest - timedelta(days=3)]
    assert observer.consecutive_dry_days(rows_with_absent_gap, latest) == 3
    rows_latest_wet = daily_rows(latest, [0.0, 0.5, 0.2, 0.3, 1.0])
    assert observer.consecutive_dry_days(rows_latest_wet, latest) == 0


def test_weather_pressure_emits_extended_metrics_from_dwd_daily_climate(monkeypatch) -> None:
    observer = load_observer()
    station_text = """
Stations_id von_datum bis_datum Stationshoehe geoBreite geoLaenge Stationsname Bundesland Abgabe
00001 20200101 20260731 1 53.4200 7.7400 Wiesmoor_Test Niedersachsen frei
"""
    lines = ["STATIONS_ID;MESS_DATUM;QN_3;FX;FM;QN_4;RSK;RSKF;SDK;SHK_TAG;NM;VPM;PM;TMK;UPM;TXK;TNK;TGK;eor"]
    start = date(2026, 1, 1)
    for i in range(30):
        day = start + timedelta(days=i)
        precip = 0.0 if i >= 27 else 1.0
        temp = 10 + i
        lines.append(f"1;{day:%Y%m%d};-999;-999;-999;3;{precip};0;-999;-999;-999;-999;-999;{temp};-999;-999;-999;-999;eor")

    def fake_fetch(url, diagnostics):
        if url.endswith(observer.DWD_STATION_DESCRIPTION):
            return station_text.encode("latin1")
        if url.endswith("tageswerte_KL_00001_akt.zip"):
            return product_zip(lines)
        raise AssertionError(url)

    monkeypatch.setattr(observer, "_fetch_url", fake_fetch)
    payload, diagnostics = observer.weather_pressure()
    assert diagnostics.error is None
    assert payload["latest_precipitation_mm"] == 0.0
    assert payload["rainfall_7d_mm"] == 4.0
    assert payload["rainfall_30d_mm"] == 27.0
    assert payload["temperature_c"] == 39.0
    assert payload["temperature_mean_7d_c"] == 36.0
    assert payload["temperature_mean_30d_c"] == 24.5
    assert payload["dry_days_7d"] == 3
    assert payload["dry_days_30d"] == 3
    assert payload["consecutive_dry_days"] == 3
    assert payload["coverage"]["dry_day_threshold_mm"] == 1.0


def test_copernicus_swi_grid_cell_selection_is_deterministic() -> None:
    observer = load_observer()
    cell = observer.select_copernicus_swi_grid_cell()
    assert cell["crs"] == "EPSG:4326"
    assert cell["pixel_size_degrees"] == 1 / 112
    assert cell["row"] == 2081
    assert cell["column"] == 2098
    assert cell["latitude"] == 53.4196429
    assert cell["longitude"] == 7.7321429


def test_copernicus_swi_missing_fill_values_remain_unavailable() -> None:
    observer = load_observer()
    for value in [241, 242, 251, 252, 253, 254, 255, 201, -1, float("nan"), None]:
        assert observer._parse_copernicus_swi_value(value) is None


def test_copernicus_swi_real_numeric_zero_is_valid() -> None:
    observer = load_observer()
    assert observer._parse_copernicus_swi_value(0) == 0.0
    assert observer._parse_copernicus_swi_value("0") == 0.0


def test_copernicus_swi_scale_factor_applied_after_valid_range_check() -> None:
    observer = load_observer()
    assert observer._parse_copernicus_swi_value(1) == 0.5
    assert observer._parse_copernicus_swi_value(200) == 100.0


def test_copernicus_swi_date_parsing() -> None:
    observer = load_observer()
    assert observer._parse_copernicus_swi_date("c_gls_SWI1km_202607071200_CEURO_SCATSAR_V2.0.1.nc") == date(2026, 7, 7)
    assert observer._parse_copernicus_swi_date("2026-07-08T12:00:00Z") == date(2026, 7, 8)


def test_copernicus_swi_graceful_unavailable_does_not_call_metadata_url(monkeypatch) -> None:
    observer = load_observer()

    def fail_fetch(url, diagnostics):
        raise AssertionError("metadata-only adapter must not fetch live URLs")

    monkeypatch.setattr(observer, "_fetch_url", fail_fetch)
    payload, diagnostics = observer.copernicus_soil_water()
    assert payload["data_status"] == "unavailable"
    assert payload["latest_date"] is None
    assert payload["latest_value"] is None
    assert payload["file_url"] is None
    assert payload["source"]["status"] == "metadata_only"
    assert "anonymous CDSE product discovery was not verified" in diagnostics.error


def test_copernicus_swi_v201_metadata_and_filename_payload() -> None:
    observer = load_observer()
    payload, diagnostics = observer.copernicus_soil_water()
    assert diagnostics.http_status is None
    assert payload["product_version"] == "V2.0.1"
    assert payload["file_naming_convention"] == "c_gls_SWI1km_YYYYMMDD1200_CEURO_SCATSAR_VX.Y.X.nc"
    assert payload["variable"] == "SWI_002"
    assert payload["variable_meaning"] == "SWI_002 means T=2"
    assert payload["spatial_resolution"] == "1/112° (~1 km), EPSG:4326"
    assert payload["raw_valid_range"] == [0, 200]
    assert payload["scale_factor"] == 0.5
    assert payload["fill_value"] == 255
    assert payload["flag_values"] == [241, 242, 251, 252, 253, 254]


def test_build_payload_adds_independent_copernicus_soil_water_without_regressing_pressure(monkeypatch) -> None:
    observer = load_observer()
    monkeypatch.setattr(observer, "groundwater_proxy", lambda: ({"data_status": "unavailable", "source": {"name": "g"}}, observer.AdapterDiagnostics()))
    monkeypatch.setattr(observer, "regional_soil_water", lambda: ({"trend": "unavailable", "source": {"name": "dwd"}}, observer.AdapterDiagnostics()))
    monkeypatch.setattr(observer, "weather_pressure", lambda: ({"data_status": "unavailable", "rainfall_7d_mm": None, "rainfall_30d_mm": None, "source": {"name": "w"}}, observer.AdapterDiagnostics()))
    monkeypatch.setattr(observer, "copernicus_soil_water", lambda: ({"data_status": "unavailable", "latest_value": None, "source": {"name": "c"}}, observer.AdapterDiagnostics(api_attempts=1, error="metadata only")))
    payload = observer.build_payload()
    assert "copernicus_soil_water" in payload
    assert payload["regional_soil_water"] == {"trend": "unavailable", "source": {"name": "dwd"}}
    assert payload["peatland_hydrological_pressure"]["value"] == "unavailable"
    assert observer.COPERNICUS_SWI_ADAPTER_ID not in payload["diagnostics"]["live_adapters_enabled"]
    assert observer.COPERNICUS_SWI_ADAPTER_ID in payload["diagnostics"]["metadata_adapters"]


def test_peat_context_schema_presence_and_static_status() -> None:
    observer = load_observer()
    context = observer.peat_context()
    for key in [
        "context_status",
        "area_name",
        "source_name",
        "source_url",
        "moor_type_context",
        "peat_thickness_context",
        "land_use_history",
        "drainage_context",
        "extraction_history",
        "restoration_or_management_context",
        "why_this_area_matters",
        "limitations",
        "data_status",
        "reproducibility_note",
        "wiesmoor_nord",
    ]:
        assert key in context
    assert context["context_status"] == "static_source_backed_context_not_live"
    assert context["data_status"] == "static_context_only"
    assert context["location"]["latitude"] == observer.LATITUDE
    assert context["location"]["longitude"] == observer.LONGITUDE


def test_peat_context_does_not_fabricate_numeric_peat_thickness() -> None:
    observer = load_observer()
    context = observer.peat_context()
    thickness = context["peat_thickness_context"]
    assert thickness["status"] == "numeric_value_unavailable"
    assert thickness["value"] is None
    assert thickness["unit"] is None
    assert "peat_thickness" in context["wiesmoor_nord"]["unavailable_numeric_fields"]
    assert "mapped_area" in context["wiesmoor_nord"]["unavailable_numeric_fields"]


def test_mooris_source_metadata_presence() -> None:
    observer = load_observer()
    context = observer.peat_context()
    source = context["source"]
    assert source["status"] == "static_context"
    assert source["url"] == observer.MOORIS_WIESMOOR_NORD_URL
    assert source["source_checked_over_http"] is False
    assert source["http_status"] is None
    assert observer.NLWKN_MOORIS_INFO_URL in source["supporting_urls"]
    assert context["wiesmoor_nord"]["page_or_dataset_identifier"] == "MoorIS page pgId=585; Moorschutzprogramm area 377 Wiesmoor-Nord"


def test_static_peat_context_does_not_affect_live_adapter_status(monkeypatch) -> None:
    observer = load_observer()
    monkeypatch.setattr(observer, "groundwater_proxy", lambda: ({"data_status": "unavailable", "source": {"name": "g"}}, observer.AdapterDiagnostics(api_attempts=2, http_status=200)))
    monkeypatch.setattr(observer, "regional_soil_water", lambda: ({"trend": "unavailable", "source": {"name": "dwd"}}, observer.AdapterDiagnostics(api_attempts=3, http_status=200)))
    monkeypatch.setattr(observer, "weather_pressure", lambda: ({"data_status": "unavailable", "rainfall_7d_mm": None, "rainfall_30d_mm": None, "source": {"name": "w"}}, observer.AdapterDiagnostics(api_attempts=4, http_status=200)))
    monkeypatch.setattr(observer, "copernicus_soil_water", lambda: ({"data_status": "unavailable", "latest_value": None, "source": {"name": "c"}}, observer.AdapterDiagnostics(error="metadata only")))
    payload = observer.build_payload()
    assert payload["diagnostics"]["api_attempts"] == 9
    assert payload["diagnostics"]["live_adapters_enabled"] == [observer.DWD_ADAPTER_ID, observer.NLWKN_GROUNDWATER_ADAPTER_ID, observer.DWD_SOIL_MOISTURE_ADAPTER_ID]
    assert payload["diagnostics"]["metadata_adapters"] == [observer.COPERNICUS_SWI_ADAPTER_ID]
    assert payload["sources"][0]["status"] == "static_context"
    assert payload["sources"][0]["source_checked_over_http"] is False
    assert payload["peatland_hydrological_pressure"]["value"] == "unavailable"
