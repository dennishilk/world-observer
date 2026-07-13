from __future__ import annotations
import importlib.util, json, socket
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PATH = REPO_ROOT / "observers" / "horizon-observer" / "observer.py"

def load():
    spec=importlib.util.spec_from_file_location("horizon_observer", PATH)
    mod=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(mod); return mod

def test_azimuth_and_compass_boundaries():
    o=load(); assert o.normalize_azimuth(-1)==359; assert o.normalize_azimuth(360)==0
    assert o.compass_direction(0)=="N"; assert o.compass_direction(11.24)=="N"; assert o.compass_direction(11.25)=="NNE"
    assert o.compass_direction(33.74)=="NNE"; assert o.compass_direction(33.75)=="NE"; assert o.compass_direction(348.74)=="NNW"; assert o.compass_direction(348.75)=="N"

def test_twilight_boundaries_and_visibility():
    o=load()
    assert o.sky_light_state(0)["state"]=="day"; assert o.sky_light_state(-0.01)["state"]=="civil_twilight"
    assert o.sky_light_state(-6)["state"]=="civil_twilight"; assert o.sky_light_state(-6.01)["state"]=="nautical_twilight"
    assert o.sky_light_state(-12)["state"]=="nautical_twilight"; assert o.sky_light_state(-12.01)["state"]=="astronomical_twilight"
    assert o.sky_light_state(-18)["state"]=="astronomical_twilight"; assert o.sky_light_state(-18.01)["state"]=="night"
    assert o.geometric_visibility(-1,"planet")=="below_horizon"; assert o.geometric_visibility(3,"planet")=="low"; assert o.geometric_visibility(10,"planet")=="fair"; assert o.geometric_visibility(20,"planet")=="good"
    assert o.display_visibility("good","day","planet")=="daylight_limited"

def test_payload_schema_moon_samples_negative_and_iss(monkeypatch, tmp_path):
    o=load(); monkeypatch.chdir(REPO_ROOT)
    payload=o.build_payload(datetime(2026,1,15,21,0,tzinfo=timezone.utc))
    for key in ("observer","generated_at","location","data_status","summary","sky_state","orientation","objects","horizon_scene","constellations","milky_way","iss","diagnostics","sources"):
        assert key in payload
    moon=next(x for x in payload["objects"] if x["id"]=="moon")
    assert 0 <= moon["display_metadata"]["illumination_fraction"] <= 1
    assert 0 <= moon["display_metadata"]["illumination_percent"] <= 100
    for obj in payload["objects"]:
        s=obj["altitude_series_24h"]; assert len(s)==49; assert s[0]["timestamp_utc"] < s[-1]["timestamp_utc"]
    assert any(sample["altitude_deg"] < 0 for obj in payload["objects"] for sample in obj["altitude_series_24h"])
    assert payload["iss"]["status"]=="unavailable" and payload["iss"]["reason"]=="local_tle_missing"

def test_rise_set_unavailable_edge_case(monkeypatch):
    o=load()
    class FakeAlwaysUp(Exception): pass
    class FakeEphem:
        AlwaysUpError = FakeAlwaysUp
        NeverUpError = RuntimeError
        class Sun: pass
    class BadObserver:
        def next_rising(self, body): raise FakeAlwaysUp()
        def next_setting(self, body): raise FakeAlwaysUp()
    monkeypatch.setattr(o, "EPHEM_AVAILABLE", True)
    monkeypatch.setattr(o, "ephem", FakeEphem)
    monkeypatch.setattr(o, "observer_at", lambda dt: BadObserver())
    rs=o.rise_set(FakeEphem.Sun, datetime(2026,1,1,tzinfo=timezone.utc))
    assert rs["rise_time_utc"] is None and rs["set_time_utc"] is None and rs["event_status"]=="circumpolar"

def test_constellations_limited_milky_way_wrap_and_deterministic(monkeypatch):
    o=load(); t=datetime(2026,7,1,22,0,tzinfo=timezone.utc)
    labels=o.build_constellations(t); assert len(labels)<=10; assert all(x["altitude_deg"]>=10 for x in labels)
    mw=o.milky_way(t); assert mw["sample_count"]==36; assert "segment_id" in mw["points"][0]
    p1=o.build_payload(t); p2=o.build_payload(t)
    j1=next(x for x in p1["objects"] if x["id"]=="jupiter"); j2=next(x for x in p2["objects"] if x["id"]=="jupiter")
    assert abs(j1["altitude_deg"]-j2["altitude_deg"]) < 0.01

def test_no_network_request(monkeypatch):
    def fail(*a, **k): raise AssertionError("network attempted")
    monkeypatch.setattr(socket, "create_connection", fail)
    o=load(); p=o.build_payload(datetime(2026,3,1,0,0,tzinfo=timezone.utc))
    assert p["diagnostics"]["external_api_requests"] == 0
