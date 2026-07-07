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
        for name, source_url in observer.SOURCES.items():
            if url == source_url:
                return payloads[name], {"url": url, "ok": True, "http_status": 200, "error": None}
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(observer, "_fetch_json", fake_fetch)

    built = observer.build_payload()

    assert built["status"] == "ok"
    assert built["data_status"] == "partial"
    assert built["condition"] == "minor storm"
    assert built["storm_scale"] == "G1"
    assert built["diagnostics"]["row_counts"] == {"kp": 1, "mag": 0, "plasma": 0}
