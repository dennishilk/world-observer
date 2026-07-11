from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

MODULE_PATH = Path("observers/east-frisia-water-observer/observer.py")
SPEC = importlib.util.spec_from_file_location("east_frisia_water_observer", MODULE_PATH)
observer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = observer
assert SPEC.loader is not None
SPEC.loader.exec_module(observer)
wsv = observer.wsv

NOW = datetime(2026, 7, 11, 16, 30, tzinfo=timezone.utc)
UUID = "abb23dad-0880-41ab-8d2d-dd33e11f148f"


def station(unit="cm", timeseries=True):
    return {
        "uuid": UUID,
        "number": "3910010",
        "shortname": "LEERORT",
        "longname": "LEERORT",
        "agency": "STANDORT EMDEN",
        "longitude": 7.426191,
        "latitude": 53.215335,
        "water": {"shortname": "EMS", "longname": "EMS"},
        "timeseries": ([{"shortname": "W", "longname": "WASSERSTAND ROHDATEN", "unit": unit, "equidistance": 1}] if timeseries else []),
    }


def measurements(values):
    return [{"timestamp": ts, "value": value} for ts, value in values]


def patch_json(monkeypatch, station_payload=None, measurement_payload=None, exc=None):
    calls = []
    def fake(url, diagnostics):
        calls.append(url)
        diagnostics["api_attempts"] += 1
        if exc:
            raise exc
        return station_payload if "measurements" not in url else measurement_payload
    monkeypatch.setattr(wsv, "_get_json", fake)
    return calls


def fetch(monkeypatch, vals, station_payload=None):
    patch_json(monkeypatch, station_payload or station(), measurements(vals))
    return wsv.fetch(now=NOW)


def test_valid_current_measurement(monkeypatch):
    result = fetch(monkeypatch, [("2026-07-11T18:00:00+02:00", 430), ("2026-07-11T18:10:00+02:00", 431), ("2026-07-11T18:20:00+02:00", 432), ("2026-07-11T18:25:00+02:00", 433)])
    assert result.status == "live"
    assert result.observations["station_uuid"] == UUID
    assert result.observations["unit"] == "cm"
    assert result.observations["freshness_status"] == "fresh_measurement"


def test_valid_zero_measurement(monkeypatch):
    result = fetch(monkeypatch, [("2026-07-11T18:00:00+02:00", 0), ("2026-07-11T18:10:00+02:00", 0), ("2026-07-11T18:20:00+02:00", 0), ("2026-07-11T18:25:00+02:00", 0)])
    assert result.observations["latest_measurement_value"] == 0.0


def test_rising_trend(monkeypatch):
    assert fetch(monkeypatch, [("2026-07-11T18:00:00+02:00", 1), ("2026-07-11T18:10:00+02:00", 2), ("2026-07-11T18:20:00+02:00", 3), ("2026-07-11T18:25:00+02:00", 5)]).observations["trend_direction"] == "rising"


def test_falling_trend(monkeypatch):
    assert fetch(monkeypatch, [("2026-07-11T18:00:00+02:00", 5), ("2026-07-11T18:10:00+02:00", 4), ("2026-07-11T18:20:00+02:00", 3), ("2026-07-11T18:25:00+02:00", 1)]).observations["trend_direction"] == "falling"


def test_stable_trend_within_noise(monkeypatch):
    assert fetch(monkeypatch, [("2026-07-11T18:00:00+02:00", 10), ("2026-07-11T18:10:00+02:00", 11), ("2026-07-11T18:20:00+02:00", 11), ("2026-07-11T18:25:00+02:00", 12)]).observations["trend_direction"] == "stable"


def test_insufficient_values_produces_unavailable_trend(monkeypatch):
    result = fetch(monkeypatch, [("2026-07-11T18:00:00+02:00", 10)])
    assert result.observations["trend_direction"] == "unavailable"


def test_stale_latest_measurement(monkeypatch):
    result = fetch(monkeypatch, [("2026-07-11T12:00:00+02:00", 10), ("2026-07-11T12:10:00+02:00", 10), ("2026-07-11T12:20:00+02:00", 10), ("2026-07-11T12:25:00+02:00", 10)])
    assert result.observations["freshness_status"] == "stale_measurement"


def test_malformed_timestamp(monkeypatch):
    result = fetch(monkeypatch, [("not-a-date", 10)])
    assert result.status == "unavailable"
    assert "malformed_timestamp" in result.diagnostics["adapter_errors"][0]


def test_missing_timeseries(monkeypatch):
    result = fetch(monkeypatch, [("2026-07-11T18:00:00+02:00", 10)], station(timeseries=False))
    assert result.status == "unavailable"


def test_unexpected_unit(monkeypatch):
    result = fetch(monkeypatch, [("2026-07-11T18:00:00+02:00", 10)], station(unit="m"))
    assert result.status == "unavailable"


def test_malformed_json_structure(monkeypatch):
    patch_json(monkeypatch, [], [])
    assert wsv.fetch(now=NOW).status == "unavailable"


def test_http_failure_or_timeout(monkeypatch):
    patch_json(monkeypatch, exc=URLError("timeout"))
    assert wsv.fetch(now=NOW).status == "unavailable"


def test_duplicate_timestamps(monkeypatch):
    result = fetch(monkeypatch, [("2026-07-11T18:00:00+02:00", 1), ("2026-07-11T18:00:00+02:00", 2)])
    assert result.status == "unavailable"


def test_non_finite_numeric_values(monkeypatch):
    result = fetch(monkeypatch, [("2026-07-11T18:00:00+02:00", float("nan"))])
    assert result.status == "unavailable"


def test_wsv_failure_does_not_break_complete_observer(monkeypatch):
    monkeypatch.setattr(observer.wsv, "fetch", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    payload = observer.build_payload()
    assert [item["adapter"] for item in payload["adapters"]] == ["dwd", "nlwkn", "wsv", "bsh"]
    assert payload["data_status"] == "partial"


def test_overall_payload_partial_when_wsv_succeeds_and_others_pending(monkeypatch):
    monkeypatch.setattr(observer.wsv, "_get_json", lambda url, diagnostics: (diagnostics.__setitem__("api_attempts", diagnostics["api_attempts"] + 1) or (station() if "measurements" not in url else measurements([("2026-07-11T18:00:00+02:00", 1), ("2026-07-11T18:10:00+02:00", 2), ("2026-07-11T18:20:00+02:00", 3), ("2026-07-11T18:25:00+02:00", 5)]))))
    payload = observer.build_payload()
    assert payload["data_status"] == "partial"
    assert payload["live_adapters_enabled"] is True


def test_payload_serializes(monkeypatch):
    payload = observer.build_payload()
    json.dumps(payload)
