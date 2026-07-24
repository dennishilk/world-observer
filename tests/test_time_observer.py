from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "observers" / "time-observer" / "observer.py"
spec = importlib.util.spec_from_file_location("time_observer", MODULE_PATH)
observer = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(observer)


def test_parse_finals_keeps_observed_and_predicted_classification() -> None:
    source = """26  7 24 61244.00 I  0.123456 0.000001  0.234567 0.000001  I -0.0456789 0.0000010\n26  7 25 61245.00 P  0.123456 0.000001  0.234567 0.000001  P -0.0460000 0.0000010\n"""
    assert observer.parse_finals2000a(source) == [
        {"mjd": 61244, "ut1_minus_utc_seconds": -0.0456789, "status": "observed"},
        {"mjd": 61245, "ut1_minus_utc_seconds": -0.046, "status": "predicted"},
    ]


def test_parse_leap_second_history_and_current_offset() -> None:
    source = """ 41317.0  1  1 1972       10s\n 57754.0  1  1 2017       37s\n"""
    entries = observer.parse_leap_seconds(source)
    assert entries == [
        {"effective_date": "1972-01-01", "tai_minus_utc_seconds": 10, "mjd": 41317},
        {"effective_date": "2017-01-01", "tai_minus_utc_seconds": 37, "mjd": 57754},
    ]
    assert observer.tai_minus_utc(entries, date(2026, 7, 24)) == 37


def test_missing_sources_leave_values_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(observer, "_fetch_text", lambda url: (None, {"url": url, "ok": False, "http_status": None, "error": "URLError"}))
    built = observer.build_payload()
    assert built["data_status"] == "unavailable"
    assert built["time_scales"]["tai_minus_utc_seconds"] is None
    assert built["earth_orientation"]["ut1_minus_utc_seconds"] is None
    assert built["earth_orientation"]["status"] == "data_unavailable"


def test_exact_eop_date_wins_over_newer_prediction() -> None:
    records = [{"mjd": observer.mjd_for_date(date(2026, 7, 24)), "ut1_minus_utc_seconds": -0.04, "status": "observed"}, {"mjd": observer.mjd_for_date(date(2026, 7, 25)), "ut1_minus_utc_seconds": -0.05, "status": "predicted"}]
    assert observer.select_eop_record(records, date(2026, 7, 24)) == records[0]
