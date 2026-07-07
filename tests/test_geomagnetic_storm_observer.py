from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "observers" / "geomagnetic-storm-observer" / "observer.py"
spec = importlib.util.spec_from_file_location("geomagnetic_storm_observer", MODULE_PATH)
observer = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(observer)


def test_storm_scale_boundaries() -> None:
    assert observer.storm_scale(4.99) == "G0"
    assert observer.storm_scale(5) == "G1"
    assert observer.storm_scale(6) == "G2"
    assert observer.storm_scale(7) == "G3"
    assert observer.storm_scale(8) == "G4"
    assert observer.storm_scale(9) == "G5"
    assert observer.storm_scale(None) is None


def test_condition_boundaries() -> None:
    assert observer.condition(1.5) == "quiet"
    assert observer.condition(2.5) == "unsettled"
    assert observer.condition(4) == "active"
    assert observer.condition(5) == "minor storm"
    assert observer.condition(6) == "moderate storm"
    assert observer.condition(7) == "strong storm"
    assert observer.condition(8) == "severe storm"
    assert observer.condition(9) == "extreme storm"


def test_parse_noaa_rows() -> None:
    kp_payload = [["time_tag", "Kp", "a_running", "station_count"], ["2026-07-07 03:00:00.000", "5.33", "20", "8"], ["2026-07-07 00:00:00.000", "2.67", "12", "8"]]
    mag_payload = [["time_tag", "bx_gsm", "by_gsm", "bz_gsm", "lon_gsm", "lat_gsm", "bt"], ["2026-07-07 00:00:00.000", "1", "2", "", "0", "0", "4"], ["2026-07-07 00:01:00.000", "1", "2", "-4.8", "0", "0", "4"]]
    plasma_payload = [["time_tag", "density", "speed", "temperature"], ["2026-07-07 00:00:00.000", "4", "410.6", "90000"]]

    kp, max_kp, kp_rows = observer.latest_kp(kp_payload)
    assert kp == {"observed_at_utc": "2026-07-07 03:00:00.000", "value": 5.33, "max_available": 5.33}
    assert max_kp == 5.33
    assert kp_rows == 2
    assert observer.latest_bz_gsm(mag_payload) == (-4.8, "2026-07-07 00:01:00.000", 2)
    assert observer.latest_solar_wind_speed(plasma_payload) == (410.6, "2026-07-07 00:00:00.000", 1)


def test_uses_ordered_solar_wind_source_fallbacks() -> None:
    assert observer.SOURCES["kp"] == "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
    assert observer.SOURCE_CANDIDATES["mag"][0] == "https://services.swpc.noaa.gov/products/solar-wind/mag-2-hour.json"
    assert observer.SOURCE_CANDIDATES["plasma"][0] == "https://services.swpc.noaa.gov/products/solar-wind/plasma-2-hour.json"
    assert "https://services.swpc.noaa.gov/json/dscovr/dscovr_mag_1m.json" in observer.SOURCE_CANDIDATES["mag"]
    assert "https://services.swpc.noaa.gov/json/dscovr/dscovr_plasma_1m.json" in observer.SOURCE_CANDIDATES["plasma"]


def test_parse_two_hour_solar_wind_rows_uses_latest_valid_time_tag() -> None:
    mag_payload = [
        ["time_tag", "bx_gsm", "by_gsm", "bz_gsm", "lon_gsm", "lat_gsm", "bt"],
        ["2026-07-05 00:00:00.000", "1.1", "2.2", "-1.5", "10.0", "1.0", "3.0"],
        ["2026-07-07 00:00:00.000", "1.2", "2.3", "", "11.0", "1.1", "3.1"],
        ["2026-07-06 23:59:00.000", "1.3", "2.4", "-4.8", "12.0", "1.2", "3.2"],
        ["2026-07-07 00:01:00.000", "1.4", "2.5", "-6.25", "13.0", "1.3", "3.3"],
    ]
    plasma_payload = [
        ["time_tag", "density", "speed", "temperature"],
        ["2026-07-05 00:00:00.000", "5.1", "390.4", "90000"],
        ["2026-07-07 00:00:00.000", "5.2", "null", "91000"],
        ["2026-07-06 23:59:00.000", "5.3", "420.6", "92000"],
        ["2026-07-07 00:01:00.000", "5.4", "455.25", "93000"],
    ]

    assert observer.latest_bz_gsm(mag_payload) == (-6.25, "2026-07-07 00:01:00.000", 4)
    assert observer.latest_solar_wind_speed(plasma_payload) == (455.25, "2026-07-07 00:01:00.000", 4)


def test_parse_noaa_object_kp_rows_uses_newest_valid_time_tag() -> None:
    kp_payload = [
        {"time_tag": "2026-07-07T09:00:00", "Kp": 0.67, "a_running": 3, "station_count": 7},
        {"time_tag": "2026-07-07T03:00:00", "Kp": 4.67, "a_running": 20, "station_count": 7},
        {"time_tag": "not-a-date", "Kp": 8.0, "a_running": 80, "station_count": 7},
    ]

    kp, max_kp, kp_rows = observer.latest_kp(kp_payload)

    assert kp == {"observed_at_utc": "2026-07-07T09:00:00", "value": 0.67, "max_available": 8.0}
    assert max_kp == 8.0
    assert kp_rows == 3


def test_kp_available_with_header_only_mag_plasma_is_partial(monkeypatch) -> None:
    payloads = {
        "kp": [{"time_tag": "2026-07-07T09:00:00", "Kp": 5.67, "a_running": 30, "station_count": 7}],
        "mag": [["time_tag", "bx_gsm", "by_gsm", "bz_gsm", "lon_gsm", "lat_gsm", "bt"]],
        "plasma": [["time_tag", "density", "speed", "temperature"]],
    }

    def fake_fetch(url: str, timeout_s: int = observer.TIMEOUT_S):
        if url == observer.SOURCES["kp"]:
            return payloads["kp"], {"url": url, "ok": True, "http_status": 200, "error": None}
        for name in ("mag", "plasma"):
            if url == observer.SOURCE_CANDIDATES[name][0]:
                return payloads[name], {"url": url, "ok": True, "http_status": 200, "error": None}
        return [["time_tag"]], {"url": url, "ok": True, "http_status": 200, "error": None}

    monkeypatch.setattr(observer, "_fetch_json", fake_fetch)

    built = observer.build_payload()

    assert built["status"] == "ok"
    assert built["data_status"] == "partial"
    assert built["condition"] == "minor storm"
    assert built["storm_scale"] == "G1"
    assert built["diagnostics"]["row_counts"] == {"kp": 1, "mag": 0, "plasma": 0}


def test_solar_wind_fallback_uses_second_valid_source(monkeypatch) -> None:
    mag_urls = ["https://example.invalid/mag-404.json", "https://example.invalid/mag-valid.json"]
    monkeypatch.setitem(observer.SOURCE_CANDIDATES, "mag", mag_urls)
    valid_payload = [["time_tag", "bz_gsm"], ["2026-07-07 00:01:00.000", "-7.2"]]

    def fake_fetch(url: str, timeout_s: int = observer.TIMEOUT_S):
        if url == mag_urls[0]:
            return None, {"url": url, "ok": False, "http_status": 404, "error": "HTTP 404"}
        if url == mag_urls[1]:
            return valid_payload, {"url": url, "ok": True, "http_status": 200, "error": None}
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(observer, "_fetch_json", fake_fetch)

    payload, diagnostics, attempts = observer._fetch_first_valid_source("mag", observer.latest_bz_gsm)

    assert payload == valid_payload
    assert attempts == 2
    assert diagnostics["selected_url"] == mag_urls[1]
    assert [attempt["http_status"] for attempt in diagnostics["attempts"]] == [404, 200]
    assert diagnostics["attempts"][1]["valid"] is True


def test_solar_wind_fallback_all_sources_unavailable(monkeypatch) -> None:
    plasma_urls = ["https://example.invalid/plasma-404.json", "https://example.invalid/plasma-empty.json"]
    monkeypatch.setitem(observer.SOURCE_CANDIDATES, "plasma", plasma_urls)

    def fake_fetch(url: str, timeout_s: int = observer.TIMEOUT_S):
        if url == plasma_urls[0]:
            return None, {"url": url, "ok": False, "http_status": 404, "error": "HTTP 404"}
        if url == plasma_urls[1]:
            return [["time_tag", "speed"]], {"url": url, "ok": True, "http_status": 200, "error": None}
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(observer, "_fetch_json", fake_fetch)

    payload, diagnostics, attempts = observer._fetch_first_valid_source("plasma", observer.latest_solar_wind_speed)

    assert payload is None
    assert attempts == 2
    assert diagnostics["selected_url"] is None
    assert [attempt["valid"] for attempt in diagnostics["attempts"]] == [False, False]


def test_build_payload_records_selected_fallback_urls(monkeypatch) -> None:
    kp_url = observer.SOURCES["kp"]
    mag_urls = ["https://example.invalid/mag-404.json", "https://example.invalid/mag-valid.json"]
    plasma_urls = ["https://example.invalid/plasma-404.json", "https://example.invalid/plasma-valid.json"]
    monkeypatch.setitem(observer.SOURCE_CANDIDATES, "mag", mag_urls)
    monkeypatch.setitem(observer.SOURCE_CANDIDATES, "plasma", plasma_urls)

    payloads = {
        kp_url: [{"time_tag": "2026-07-07T09:00:00", "Kp": 4.67}],
        mag_urls[1]: [["time_tag", "bz_gsm"], ["2026-07-07 00:01:00.000", "-6.25"]],
        plasma_urls[1]: [["time_tag", "speed"], ["2026-07-07 00:01:00.000", "455.25"]],
    }

    def fake_fetch(url: str, timeout_s: int = observer.TIMEOUT_S):
        if url in payloads:
            return payloads[url], {"url": url, "ok": True, "http_status": 200, "error": None}
        return None, {"url": url, "ok": False, "http_status": 404, "error": "HTTP 404"}

    monkeypatch.setattr(observer, "_fetch_json", fake_fetch)

    built = observer.build_payload()

    assert built["solar_wind"] == {
        "bz_gsm": -6.25,
        "bz_gsm_observed_at_utc": "2026-07-07 00:01:00.000",
        "speed_km_s": 455.25,
        "speed_observed_at_utc": "2026-07-07 00:01:00.000",
    }
    assert built["source"]["urls"] == {"kp": kp_url, "mag": mag_urls[1], "plasma": plasma_urls[1]}
    assert built["diagnostics"]["sources"]["mag"]["selected_url"] == mag_urls[1]
    assert built["diagnostics"]["sources"]["plasma"]["selected_url"] == plasma_urls[1]
