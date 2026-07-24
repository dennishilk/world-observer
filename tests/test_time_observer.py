from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "observers" / "time-observer" / "observer.py"
LEAP_SECONDS_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "time-observer" / "Leap_Second.dat"
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


def test_parse_live_format_leap_second_history_and_current_offset() -> None:
    entries = observer.parse_leap_seconds(LEAP_SECONDS_FIXTURE.read_text())
    assert len(entries) == 28
    assert entries[0] == {"effective_date": "1972-01-01", "tai_minus_utc_seconds": 10, "mjd": 41317}
    assert entries[-1] == {"effective_date": "2017-01-01", "tai_minus_utc_seconds": 37, "mjd": 57754}
    assert [entry["mjd"] for entry in entries] == sorted(entry["mjd"] for entry in entries)
    assert observer.tai_minus_utc(entries, date(2026, 7, 24)) == 37


def test_future_leap_second_is_not_applied_early() -> None:
    entries = observer.parse_leap_seconds(" 57754.0\t1\t1\t2017\t37\n 62502.0\t1\t1\t2030\t38\n")
    assert observer.tai_minus_utc(entries, date(2029, 12, 31)) == 37
    assert observer.tai_minus_utc(entries, date(2030, 1, 1)) == 38


def test_malformed_leap_second_source_fails_safely() -> None:
    assert observer.parse_leap_seconds(" 57754.0 1 1 2017 37\n 62502.0 1 1 2030 invalid\n") == []
    assert observer.parse_leap_seconds(" 57754.0 1 1 2017 37\n 57754.0 1 1 2017 38\n") == []


def test_malformed_leap_second_response_is_data_unavailable(monkeypatch) -> None:
    finals = "26  7 24 61244.00 I  0.123456 0.000001  0.234567 0.000001  I -0.0456789 0.0000010\n"

    def fetch(url: str):
        text = finals if url == observer.SOURCES["earth_orientation"] else " 57754.0 1 1 2017 invalid\n"
        return text, {"url": url, "ok": True, "http_status": 200, "error": None}

    monkeypatch.setattr(observer, "_fetch_text", fetch)
    built = observer.build_payload()
    assert built["data_status"] == "partial"
    assert built["time_scales"]["tai_minus_utc_seconds"] is None
    assert built["time_scales"]["classification"] == "data_unavailable"
    assert built["diagnostics"]["sources"]["leap_seconds"]["ok"] is False
    assert built["diagnostics"]["sources"]["leap_seconds"]["error"] == "ParseError"


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
