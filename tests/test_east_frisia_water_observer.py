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

# DWD daily precipitation adapter tests
import io
import zipfile
from urllib.error import HTTPError

dwd = observer.dwd


def dwd_zip(rows, member="produkt_klima_tag_20260601_20260630_05640.txt"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, "\n".join(rows) + "\n")
    return buf.getvalue()


def dwd_lines(values):
    lines = ["STATIONS_ID;MESS_DATUM;QN_3;FX;FM;QN_4;RSK;RSKF;SDK;SHK_TAG;NM;VPM;PM;TMK;UPM;TXK;TNK;TGK;eor"]
    for idx, value in enumerate(values, start=1):
        day = f"202606{idx:02d}"
        lines.append(f"5640;{day};-999;-999;-999;3;{value};0;-999;-999;-999;-999;-999;12.0;-999;-999;-999;-999;eor")
    return lines


def patch_dwd_fetch(monkeypatch, zip_bytes=None, exc=None):
    def fake(url, diagnostics, **kwargs):
        diagnostics.api_attempts += 1
        if exc:
            raise exc
        return zip_bytes
    monkeypatch.setattr(dwd.dwd_daily_kl, "fetch_url", fake)


def test_dwd_valid_zero_rainfall(monkeypatch):
    patch_dwd_fetch(monkeypatch, dwd_zip(dwd_lines(["0.0"] * 30)))
    result = dwd.fetch()
    assert result.status == "live"
    assert result.observations["latest_rainfall_mm"] == 0.0
    assert result.observations["rainfall_7d_total_mm"] == 0.0


def test_dwd_parses_official_spaced_header_names(monkeypatch):
    lines = dwd_lines(["0.5"] * 30)
    lines[0] = "STATIONS_ID;MESS_DATUM; QN_3; FX; FM; QN_4; RSK; RSKF; SDK; SHK_TAG; NM; VPM; PM; TMK; UPM; TXK; TNK; TGK; eor"
    patch_dwd_fetch(monkeypatch, dwd_zip(lines))
    result = dwd.fetch()
    assert result.status == "live"
    assert result.observations["latest_rainfall_mm"] == 0.5
    assert result.observations["rainfall_7d_total_mm"] == 3.5


def test_dwd_detects_source_delimiter(monkeypatch):
    lines = dwd_lines(["0.5"] * 30)
    lines = [line.replace(";", ",") for line in lines]
    patch_dwd_fetch(monkeypatch, dwd_zip(lines))
    result = dwd.fetch()
    assert result.status == "live"
    assert result.observations["latest_rainfall_mm"] == 0.5
    assert result.observations["rainfall_7d_total_mm"] == 3.5


def test_dwd_missing_columns_reports_raw_parser_context(monkeypatch):
    patch_dwd_fetch(monkeypatch, dwd_zip(["not,the,right,columns", "x,y,z,w", "a,b,c,d"]))
    result = dwd.fetch()
    assert result.status == "unavailable"
    error = result.diagnostics["adapter_errors"][0]
    assert "missing required columns" in error
    assert "delimiter=','" in error
    assert "fieldnames=['not', 'the', 'right', 'columns']" in error
    assert "header='not,the,right,columns'" in error


def test_dwd_valid_latest_rainfall(monkeypatch):
    patch_dwd_fetch(monkeypatch, dwd_zip(dwd_lines(["1.0"] * 29 + ["4.2"])))
    result = dwd.fetch()
    assert result.observations["latest_date"] == "2026-06-30"
    assert result.observations["latest_rainfall_mm"] == 4.2
    assert result.observations["proxy_label"] == "inland/central East Frisia rainfall proxy"


def test_dwd_7_of_7_coverage(monkeypatch):
    patch_dwd_fetch(monkeypatch, dwd_zip(dwd_lines(["1.0"] * 30)))
    obs = dwd.fetch().observations
    assert obs["rainfall_7d_total_mm"] == 7.0
    assert obs["coverage"]["valid_days_7d"] == 7


def test_dwd_incomplete_7_day_coverage(monkeypatch):
    patch_dwd_fetch(monkeypatch, dwd_zip(dwd_lines(["1.0"] * 29 + ["-999"])))
    obs = dwd.fetch().observations
    assert obs["rainfall_7d_total_mm"] is None
    assert obs["coverage"]["valid_days_7d"] == 6


def test_dwd_27_of_30_accepted(monkeypatch):
    patch_dwd_fetch(monkeypatch, dwd_zip(dwd_lines(["-999"] * 3 + ["1.0"] * 27)))
    obs = dwd.fetch().observations
    assert obs["rainfall_30d_total_mm"] == 27.0
    assert obs["coverage"]["valid_days_30d"] == 27


def test_dwd_below_27_of_30_rejected(monkeypatch):
    patch_dwd_fetch(monkeypatch, dwd_zip(dwd_lines(["-999"] * 4 + ["1.0"] * 26)))
    obs = dwd.fetch().observations
    assert obs["rainfall_30d_total_mm"] is None
    assert obs["coverage"]["valid_days_30d"] == 26


def test_dwd_missing_marker_unavailable_not_zero(monkeypatch):
    patch_dwd_fetch(monkeypatch, dwd_zip(dwd_lines(["1.0"] * 29 + ["-999"])))
    obs = dwd.fetch().observations
    assert obs["latest_date"] == "2026-06-30"
    assert obs["latest_rainfall_mm"] is None


def test_dwd_malformed_csv(monkeypatch):
    patch_dwd_fetch(monkeypatch, dwd_zip(["not;the;right;columns", "x;y;z"]))
    result = dwd.fetch()
    assert result.status == "unavailable"
    assert "missing required columns" in result.diagnostics["adapter_errors"][0]


def test_dwd_missing_zip_member(monkeypatch):
    patch_dwd_fetch(monkeypatch, dwd_zip(["x"], member="readme.txt"))
    result = dwd.fetch()
    assert result.status == "unavailable"
    assert "did not contain" in result.diagnostics["adapter_errors"][0]


def test_dwd_http_failure(monkeypatch):
    patch_dwd_fetch(monkeypatch, exc=HTTPError("u", 503, "Service Unavailable", {}, None))
    result = dwd.fetch()
    assert result.status == "unavailable"
    assert "dwd_fetch_failed" in result.diagnostics["adapter_errors"][0]


def test_dwd_timeout_and_retry_diagnostics(monkeypatch):
    diag_seen = {}
    def fake(url, diagnostics, **kwargs):
        diagnostics.api_attempts += 2
        diagnostics.retries += 1
        diag_seen.update(kwargs)
        raise TimeoutError("timed out")
    monkeypatch.setattr(dwd.dwd_daily_kl, "fetch_url", fake)
    result = dwd.fetch()
    assert result.status == "unavailable"
    assert result.diagnostics["api_attempts"] == 2
    assert result.diagnostics["retries"] == 1
    assert diag_seen["timeout_seconds"] == dwd.DWD_CONFIG["timeout_seconds"]


def test_dwd_failure_does_not_break_wsv(monkeypatch):
    monkeypatch.setattr(observer.dwd, "fetch", lambda: (_ for _ in ()).throw(RuntimeError("dwd boom")))
    monkeypatch.setattr(observer.wsv, "_get_json", lambda url, diagnostics: (diagnostics.__setitem__("api_attempts", diagnostics["api_attempts"] + 1) or (station() if "measurements" not in url else measurements([("2026-07-11T18:00:00+02:00", 1), ("2026-07-11T18:10:00+02:00", 2), ("2026-07-11T18:20:00+02:00", 3), ("2026-07-11T18:25:00+02:00", 5)]))))
    payload = observer.build_payload()
    assert payload["adapters"][0]["status"] == "adapter_error"
    assert payload["adapters"][2]["status"] == "live"


def test_wsv_failure_does_not_break_dwd(monkeypatch):
    monkeypatch.setattr(observer.wsv, "fetch", lambda: (_ for _ in ()).throw(RuntimeError("wsv boom")))
    patch_dwd_fetch(monkeypatch, dwd_zip(dwd_lines(["1.0"] * 30)))
    payload = observer.build_payload()
    assert payload["adapters"][0]["status"] == "live"
    assert payload["adapters"][2]["status"] == "adapter_error"


def test_both_live_adapters_succeed_together(monkeypatch):
    patch_dwd_fetch(monkeypatch, dwd_zip(dwd_lines(["1.0"] * 30)))
    monkeypatch.setattr(observer.wsv, "_get_json", lambda url, diagnostics: (diagnostics.__setitem__("api_attempts", diagnostics["api_attempts"] + 1) or (station() if "measurements" not in url else measurements([("2026-07-11T18:00:00+02:00", 1), ("2026-07-11T18:10:00+02:00", 2), ("2026-07-11T18:20:00+02:00", 3), ("2026-07-11T18:25:00+02:00", 5)]))))
    payload = observer.build_payload()
    statuses = {item["adapter"]: item["status"] for item in payload["adapters"]}
    assert statuses["dwd"] == "live"
    assert statuses["wsv"] == "live"
    assert statuses["nlwkn"] in {"live", "unavailable"}
    assert statuses["bsh"] == "adapter_pending"
    assert payload["data_status"] == "partial"
    assert payload["recommendation"]["next_recommended_adapter"] == "bsh"

# NLWKN Pegelonline adapter tests
nlwkn = observer.nlwkn
NLWKN_ID = "184"


def nlwkn_ts(value: str) -> str:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return f"/Date({int(stamp.timestamp() * 1000)}+0200)/"


def nlwkn_station(unit="cm", current_timestamp=None, current_value="401,3"):
    if current_timestamp is None:
        current_timestamp = nlwkn_ts("2026-07-11T16:20:00Z")
    return {
        "getStammdatenResult": [
            {
                "STA_ID": NLWKN_ID,
                "Name": "Bensersiel",
                "GewaesserName": "Nordsee",
                "Betreiber": "NLWKN Betriebsstelle Aurich",
                "Code": "9303",
                "Parameter": [
                    {
                        "PAT_ID": "1",
                        "Name": "Wasserstand",
                        "Einheit": unit,
                        "Datenspuren": [
                            {"DAS_ID": "144222103", "Gebernummer": "1", "WebDisplayName": "Wasserstand", "IstWasserstand": True, "IstTide": False, "HatPegelstaende": True, "IntervallSek": 300, "AktuellerMesswert": current_value, "AktuellerMesswert_Zeitpunkt": current_timestamp}
                        ],
                    }
                ],
            }
        ]
    }


def nlwkn_measurements(vals):
    return {"getZeitreiheResult": [{"Zeitpunkt": ts, "Messwert": value} for ts, value in vals]}


def patch_nlwkn_json(monkeypatch, station_payload=None, measurement_payload=None, exc=None):
    def fake(url, diagnostics):
        diagnostics["api_attempts"] += 1
        if exc:
            raise exc
        return station_payload if "stammdaten" in url else measurement_payload
    monkeypatch.setattr(nlwkn, "_get_json", fake)


def fetch_nlwkn(monkeypatch, vals, station_payload=None):
    patch_nlwkn_json(monkeypatch, station_payload or nlwkn_station(), nlwkn_measurements(vals))
    return nlwkn.fetch(now=NOW)


def test_nlwkn_valid_current_measurement(monkeypatch):
    result = fetch_nlwkn(monkeypatch, [(nlwkn_ts("2026-07-11T16:00:00Z"), 399), (nlwkn_ts("2026-07-11T16:10:00Z"), 400), (nlwkn_ts("2026-07-11T16:15:00Z"), 401), (nlwkn_ts("2026-07-11T16:20:00Z"), 401.3)])
    assert result.status == "live"
    assert result.observations["station_id"] == NLWKN_ID
    assert result.observations["unit"] == "cm"
    assert result.observations["source_organization"].startswith("Niedersächsischer Landesbetrieb")
    assert result.diagnostics["raw_measurement_timestamp"] == nlwkn_ts("2026-07-11T16:20:00Z")



def test_nlwkn_regression_uses_confirmed_official_fields(monkeypatch):
    payload = nlwkn_station()
    station_obj = payload["getStammdatenResult"][0]
    station_obj["legacy_ID_should_not_be_used"] = "not-a-station-id"
    station_obj["Parameter"][0]["legacy_ID_should_not_be_used"] = "not-a-parameter-id"
    result = fetch_nlwkn(monkeypatch, [(nlwkn_ts("2026-07-11T16:00:00Z"), 399), (nlwkn_ts("2026-07-11T16:10:00Z"), 400), (nlwkn_ts("2026-07-11T16:15:00Z"), 401), (nlwkn_ts("2026-07-11T16:20:00Z"), 401.3)], payload)
    assert result.status == "live"
    assert result.observations["station_id"] == "184"
    assert result.diagnostics["confirmed_station"]["station_id"] == "184"
    assert result.diagnostics["confirmed_station"]["station_name"] == "Bensersiel"
    assert result.diagnostics["confirmed_parameters"][0]["parameter_id"] == "1"
    assert result.observations["station_name"] == "Bensersiel"
    assert result.observations["water_body"] == "Nordsee"
    assert result.observations["operator"] == "NLWKN Betriebsstelle Aurich"
    assert result.observations["unit"] == "cm"
    assert "confirmed_station_key_names" not in result.diagnostics
    assert "confirmed_parameter_key_names" not in result.diagnostics


def test_nlwkn_multiple_datenspuren_present_exposes_concise_diagnostics(monkeypatch):
    payload = nlwkn_station()
    payload["getStammdatenResult"][0]["Parameter"][0]["Datenspuren"].append(
        {"DAS_ID": "144316942", "Gebernummer": "2", "WebDisplayName": "mittlere Tidekurve", "IstWasserstand": False, "IstTide": True, "HatPegelstaende": False, "IntervallSek": 300, "AktuellerMesswert": "524,1", "AktuellerMesswert_Zeitpunkt": nlwkn_ts("2026-07-11T16:20:00Z")}
    )
    result = fetch_nlwkn(monkeypatch, [(nlwkn_ts("2026-07-11T16:00:00Z"), 399), (nlwkn_ts("2026-07-11T16:10:00Z"), 400), (nlwkn_ts("2026-07-11T16:15:00Z"), 401), (nlwkn_ts("2026-07-11T16:20:00Z"), 401.3)], payload)
    assert result.status == "live"
    assert result.observations["pinned_datenspur_id"] == "144222103"
    assert [item["DAS_ID"] for item in result.diagnostics["datenspur_candidates"]] == ["144222103", "144316942"]
    assert set(result.diagnostics["datenspur_candidates"][0]) == {"DAS_ID", "Gebernummer", "WebDisplayName", "IstWasserstand", "IstTide", "HatPegelstaende", "IntervallSek", "latest_value", "latest_timestamp", "latest_timestamp_utc"}


def test_nlwkn_only_pinned_datenspur_is_used(monkeypatch):
    payload = nlwkn_station(current_value="572,9")
    payload["getStammdatenResult"][0]["Parameter"][0]["Datenspuren"].append(
        {"DAS_ID": "144316942", "AktuellerMesswert": "524,1", "AktuellerMesswert_Zeitpunkt": nlwkn_ts("2026-07-11T16:20:00Z")}
    )
    measurements_payload = {"getZeitreiheResult": [
        {"DAS_ID": "144222103", "Messwerte": [{"Zeitpunkt": nlwkn_ts("2026-07-11T16:00:00Z"), "Messwert": 568}, {"Zeitpunkt": nlwkn_ts("2026-07-11T16:10:00Z"), "Messwert": 570}, {"Zeitpunkt": nlwkn_ts("2026-07-11T16:15:00Z"), "Messwert": 571}, {"Zeitpunkt": nlwkn_ts("2026-07-11T16:20:00Z"), "Messwert": 572.9}]},
        {"DAS_ID": "144316942", "Messwerte": [{"Zeitpunkt": nlwkn_ts("2026-07-11T16:20:00Z"), "Messwert": 524.1}]},
    ]}
    patch_nlwkn_json(monkeypatch, payload, measurements_payload)
    result = nlwkn.fetch(now=NOW)
    assert result.status == "live"
    assert result.observations["latest_measurement_value"] == 572.9
    assert result.observations["valid_values_used"] == 4


def test_nlwkn_other_datenspur_same_timestamp_does_not_conflict(monkeypatch):
    payload = nlwkn_station(current_timestamp=nlwkn_ts("2026-07-11T16:00:00Z"), current_value="572,9")
    payload["getStammdatenResult"][0]["Parameter"][0]["Datenspuren"].append({"DAS_ID": "144316942", "AktuellerMesswert": "524,1", "AktuellerMesswert_Zeitpunkt": nlwkn_ts("2026-07-11T16:00:00Z")})
    measurement_payload = {"getZeitreiheResult": [
        {"DAS_ID": "144222103", "Zeitpunkt": nlwkn_ts("2026-07-11T16:00:00Z"), "Messwert": 572.9},
        {"DAS_ID": "144316942", "Zeitpunkt": nlwkn_ts("2026-07-11T16:00:00Z"), "Messwert": 524.1},
    ]}
    patch_nlwkn_json(monkeypatch, payload, measurement_payload)
    result = nlwkn.fetch(now=NOW)
    assert result.status == "live"
    assert result.diagnostics["conflicting_duplicate_timestamp_count"] == 0
    assert result.observations["latest_measurement_value"] == 572.9



def test_nlwkn_real_nested_response_selects_only_pinned_datenspur_before_parsing(monkeypatch):
    payload = nlwkn_station(current_timestamp=nlwkn_ts("2026-07-12T09:50:00Z"), current_value="577,4")
    payload["getStammdatenResult"][0]["Parameter"][0]["Datenspuren"].append(
        {"DAS_ID": "144316942", "Gebernummer": "2", "WebDisplayName": "mittlere Tidekurve", "IstWasserstand": False, "IstTide": True, "HatPegelstaende": True, "IntervallSek": 300, "AktuellerMesswert": "623,2", "AktuellerMesswert_Zeitpunkt": nlwkn_ts("2026-07-12T09:50:00Z")}
    )
    measurement_payload = {
        "getZeitreiheResult": {
            "STA_ID": "184",
            "Parameter": [
                {
                    "PAT_ID": "1",
                    "Datenspuren": [
                        {
                            "DAS_ID": "144222103",
                            "Pegelstaende": [
                                {"Zeitpunkt": nlwkn_ts("2026-07-12T09:35:00Z"), "Messwert": 574.0},
                                {"Zeitpunkt": nlwkn_ts("2026-07-12T09:40:00Z"), "Messwert": 575.0},
                                {"Zeitpunkt": nlwkn_ts("2026-07-12T09:45:00Z"), "Messwert": 576.0},
                                {"Zeitpunkt": nlwkn_ts("2026-07-12T09:50:00Z"), "Messwert": 577.4},
                            ],
                        },
                        {
                            "DAS_ID": "144316942",
                            "Pegelstaende": [
                                {"Zeitpunkt": nlwkn_ts("2026-07-12T09:50:00Z"), "Messwert": 623.2},
                            ],
                        },
                    ],
                }
            ],
        }
    }
    patch_nlwkn_json(monkeypatch, payload, measurement_payload)
    result = nlwkn.fetch(now=datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc))
    assert result.status == "live"
    assert result.diagnostics["available_datenspur_ids"] == ["144222103", "144316942"]
    assert result.diagnostics["selected_datenspur_id"] == "144222103"
    assert result.diagnostics["selected_datenspur_measurement_count"] == 4
    assert result.diagnostics["rejected_datenspur_ids"] == ["144316942"]
    assert result.diagnostics["conflicting_duplicate_timestamp_count"] == 0
    assert result.observations["latest_measurement_value"] == 577.4
    assert result.observations["valid_values_used"] == 4

def test_nlwkn_missing_pinned_datenspur_fails_closed(monkeypatch):
    payload = nlwkn_station()
    payload["getStammdatenResult"][0]["Parameter"][0]["Datenspuren"][0]["DAS_ID"] = "144316942"
    patch_nlwkn_json(monkeypatch, payload, nlwkn_measurements([(nlwkn_ts("2026-07-11T16:00:00Z"), 1)]))
    result = nlwkn.fetch(now=NOW)
    assert result.status == "unavailable"
    assert "pinned NLWKN Datenspur DAS_ID '144222103' missing" in result.diagnostics["adapter_errors"][0]

def test_nlwkn_valid_zero_measurement(monkeypatch):
    result = fetch_nlwkn(monkeypatch, [(nlwkn_ts("2026-07-11T16:00:00Z"), 0), (nlwkn_ts("2026-07-11T16:10:00Z"), 0), (nlwkn_ts("2026-07-11T16:15:00Z"), 0), (nlwkn_ts("2026-07-11T16:20:00Z"), 0)])
    assert result.observations["latest_measurement_value"] == 0.0


def test_nlwkn_stale_measurement(monkeypatch):
    result = fetch_nlwkn(monkeypatch, [(nlwkn_ts("2026-07-11T10:00:00Z"), 1), (nlwkn_ts("2026-07-11T10:10:00Z"), 1), (nlwkn_ts("2026-07-11T10:15:00Z"), 1), (nlwkn_ts("2026-07-11T10:20:00Z"), 1)], nlwkn_station(current_timestamp=nlwkn_ts("2026-07-11T10:20:00Z"), current_value="1"))
    assert result.observations["freshness_status"] == "stale_measurement"


def test_nlwkn_summer_cest_local_timestamp(monkeypatch):
    result = fetch_nlwkn(
        monkeypatch,
        [("11.07.2026 19:00", 399), ("11.07.2026 19:10", 400), ("11.07.2026 19:15", 401), ("11.07.2026 19:20", 401.3)],
        nlwkn_station(current_timestamp="11.07.2026 19:20"),
    )
    assert result.status == "live"
    assert result.observations["latest_measurement_timestamp_utc"] == "2026-07-11T17:20:00Z"
    assert result.diagnostics["raw_measurement_timestamp"] == "11.07.2026 19:20"


def test_nlwkn_winter_cet_local_timestamp(monkeypatch):
    result = fetch_nlwkn(
        monkeypatch,
        [("11.01.2026 19:00", 399), ("11.01.2026 19:10", 400), ("11.01.2026 19:15", 401), ("11.01.2026 19:20", 401.3)],
        nlwkn_station(current_timestamp="11.01.2026 19:20"),
    )
    assert result.status == "live"
    assert result.observations["latest_measurement_timestamp_utc"] == "2026-01-11T18:20:00Z"
    assert result.diagnostics["raw_measurement_timestamp"] == "11.01.2026 19:20"


def test_nlwkn_json_date_timestamp_still_supported(monkeypatch):
    result = fetch_nlwkn(monkeypatch, [(nlwkn_ts("2026-07-11T16:20:00Z"), 401.3)])
    assert result.status == "live"
    assert result.observations["latest_measurement_timestamp_utc"] == "2026-07-11T16:20:00Z"


def test_nlwkn_malformed_timestamp(monkeypatch):
    result = fetch_nlwkn(monkeypatch, [("not-a-date", 1)])
    assert result.status == "unavailable"
    assert "malformed_timestamp" in result.diagnostics["adapter_errors"][0]
    assert result.diagnostics["raw_measurement_timestamp"] == "not-a-date"


def test_nlwkn_json_timestamp_without_offset_fails_closed(monkeypatch):
    result = fetch_nlwkn(monkeypatch, [("/Date(1783785600000)/", 1)])
    assert result.status == "unavailable"
    assert "malformed_timestamp" in result.diagnostics["adapter_errors"][0]


def test_nlwkn_unexpected_unit(monkeypatch):
    result = fetch_nlwkn(monkeypatch, [(nlwkn_ts("2026-07-11T16:00:00Z"), 1)], nlwkn_station(unit="m"))
    assert result.status == "unavailable"


def test_nlwkn_malformed_payload(monkeypatch):
    patch_nlwkn_json(monkeypatch, [], [])
    assert nlwkn.fetch(now=NOW).status == "unavailable"


def test_nlwkn_missing_pinned_station_prints_live_metadata_diagnostics(monkeypatch):
    payload = {
        "getStammdatenResult": [
            {"STA_ID": "101", "Name": "Emden Hafen", "Parameter": []},
            {"STA_ID": "102", "Name": "Norden Binnen", "Parameter": []},
            {"STA_ID": "103", "Name": "Wittmund Kanal", "Parameter": []},
        ]
    }
    patch_nlwkn_json(monkeypatch, payload, nlwkn_measurements([]))
    result = nlwkn.fetch(now=NOW)
    assert result.status == "unavailable"
    assert result.diagnostics["station_count"] == 3
    assert "first_20_station_ids" not in result.diagnostics
    assert "Bensersiel" not in result.diagnostics["station_name_matches"]
    assert result.diagnostics["station_name_matches"]["Norden"] == [{"station_id": "102", "station_name": "Norden Binnen"}]
    assert "pinned NLWKN station ID '184' missing" in result.diagnostics["adapter_errors"][0]


def test_nlwkn_does_not_select_another_matching_station(monkeypatch):
    payload = nlwkn_station()
    payload["getStammdatenResult"][0]["STA_ID"] = "9303"
    patch_nlwkn_json(monkeypatch, payload, nlwkn_measurements([(nlwkn_ts("2026-07-11T16:00:00Z"), 1)]))
    result = nlwkn.fetch(now=NOW)
    assert result.status == "unavailable"
    assert result.diagnostics["station_name_matches"]["Bensersiel"] == [{"station_id": "9303", "station_name": "Bensersiel"}]
    assert "pinned NLWKN station ID '184' missing" in result.diagnostics["adapter_errors"][0]


def test_nlwkn_pinned_station_identity_change_fails_closed(monkeypatch):
    payload = nlwkn_station()
    payload["getStammdatenResult"][0]["Name"] = "Bensersiel Ersatz"
    patch_nlwkn_json(monkeypatch, payload, nlwkn_measurements([(nlwkn_ts("2026-07-11T16:00:00Z"), 1)]))
    result = nlwkn.fetch(now=NOW)
    assert result.status == "unavailable"
    assert "pinned NLWKN station name changed" in result.diagnostics["adapter_errors"][0]


def test_nlwkn_http_failure_or_timeout(monkeypatch):
    patch_nlwkn_json(monkeypatch, exc=URLError("timeout"))
    assert nlwkn.fetch(now=NOW).status == "unavailable"


def test_nlwkn_identical_duplicate_timestamp_value_accepted(monkeypatch):
    result = fetch_nlwkn(
        monkeypatch,
        [
            (nlwkn_ts("2026-07-11T16:00:00Z"), 399),
            (nlwkn_ts("2026-07-11T16:10:00Z"), 400),
            (nlwkn_ts("2026-07-11T16:10:00Z"), "400,0"),
            (nlwkn_ts("2026-07-11T16:15:00Z"), 401),
            (nlwkn_ts("2026-07-11T16:20:00Z"), 401.3),
        ],
    )
    assert result.status == "live"
    assert result.diagnostics["duplicate_timestamp_count"] == 1
    assert result.diagnostics["conflicting_duplicate_timestamp_count"] == 0
    assert result.observations["valid_values_used"] == 4


def test_nlwkn_conflicting_duplicate_timestamp_values_rejected(monkeypatch):
    result = fetch_nlwkn(monkeypatch, [(nlwkn_ts("2026-07-11T16:00:00Z"), 1), (nlwkn_ts("2026-07-11T16:00:00Z"), 2)])
    assert result.status == "unavailable"
    assert result.diagnostics["duplicate_timestamp_count"] == 0
    assert result.diagnostics["conflicting_duplicate_timestamp_count"] == 1
    assert "conflicting_duplicate_timestamp" in result.diagnostics["adapter_errors"][0]


def test_nlwkn_trend_calculation_after_deduplication(monkeypatch):
    result = fetch_nlwkn(
        monkeypatch,
        [
            (nlwkn_ts("2026-07-11T16:20:00Z"), 405),
            (nlwkn_ts("2026-07-11T16:00:00Z"), 400),
            (nlwkn_ts("2026-07-11T16:10:00Z"), 402),
            (nlwkn_ts("2026-07-11T16:10:00Z"), 402),
            (nlwkn_ts("2026-07-11T16:15:00Z"), 403),
        ],
        nlwkn_station(current_timestamp=nlwkn_ts("2026-07-11T16:20:00Z"), current_value="405"),
    )
    assert result.status == "live"
    assert result.diagnostics["duplicate_timestamp_count"] == 1
    assert result.observations["trend_direction"] == "rising"
    assert result.observations["trend"]["window_start_utc"] == "2026-07-11T16:00:00Z"
    assert result.observations["trend"]["window_end_utc"] == "2026-07-11T16:20:00Z"
    assert result.observations["trend"]["signed_change"] == 5.0
    assert result.observations["valid_values_used"] == 4


def test_nlwkn_insufficient_values_produces_unavailable_trend(monkeypatch):
    result = fetch_nlwkn(monkeypatch, [(nlwkn_ts("2026-07-11T16:00:00Z"), 1)])
    assert result.observations["trend_direction"] == "unavailable"


def test_nlwkn_failure_isolated_from_wsv_and_dwd(monkeypatch):
    monkeypatch.setattr(observer.nlwkn, "fetch", lambda: (_ for _ in ()).throw(RuntimeError("nlwkn boom")))
    patch_dwd_fetch(monkeypatch, dwd_zip(dwd_lines(["1.0"] * 30)))
    monkeypatch.setattr(observer.wsv, "_get_json", lambda url, diagnostics: (diagnostics.__setitem__("api_attempts", diagnostics["api_attempts"] + 1) or (station() if "measurements" not in url else measurements([("2026-07-11T18:00:00+02:00", 1), ("2026-07-11T18:10:00+02:00", 2), ("2026-07-11T18:20:00+02:00", 3), ("2026-07-11T18:25:00+02:00", 5)]))))
    payload = observer.build_payload()
    statuses = {item["adapter"]: item["status"] for item in payload["adapters"]}
    assert statuses["nlwkn"] == "adapter_error"
    assert statuses["dwd"] == "live"
    assert statuses["wsv"] == "live"
    assert statuses["bsh"] == "adapter_pending"
