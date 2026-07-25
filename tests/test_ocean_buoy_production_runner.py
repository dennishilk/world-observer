from __future__ import annotations
import json, os, subprocess, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; RUNNER=ROOT/"scripts/run_ocean_buoy_observer_production.sh"

def payload():
    return {"observer":{"id":"ocean-buoy-observer","generated_at":"2026-07-25T12:00:00Z","status":"healthy","data_status":"ok"},"coverage":{},"statistics":{"total_stations":1},"stations":[{"id":"x","latitude":1,"longitude":2,"observed_at":"2026-07-25T12:00:00Z","source_id":"test","attribution":"test","measurements":{"wind_speed_m_s":0}}]}

def observer(tmp, value=None, raw=None, sleep=0):
    path=tmp/"observer.py"; doc=value or payload()
    path.write_text("import json,sys,time\n"+f"time.sleep({sleep!r})\n"+"p="+repr(doc)+"\n"+"\nif '--validate' in sys.argv:\n try: q=json.load(open(sys.argv[-1])); assert q.get('stations')\n except Exception: sys.exit(1)\n sys.exit(0)\n"+"print("+repr(raw)+") if "+repr(raw is not None)+" else print(json.dumps(p))\n")
    return path

def env(tmp, obs):
    e=os.environ.copy(); e.update(PYTHON=sys.executable,WORLD_OBSERVER_OCEAN_BUOY_OBSERVER=str(obs),WORLD_OBSERVER_LATEST_DIR=str(tmp/"latest"),WORLD_OBSERVER_DASHBOARD_DIR=str(tmp/"dashboard"),WORLD_OBSERVER_OCEAN_BUOY_SNAPSHOT_DIR=str(tmp/"snapshots"),WORLD_OBSERVER_OCEAN_BUOY_HISTORY_DIR=str(tmp/"history"),WORLD_OBSERVER_STATE_DIR=str(tmp/"state"),WORLD_OBSERVER_TIMESTAMP_UTC="2026-07-25T12-15-00Z")
    return e

def run(e): return subprocess.run([str(RUNNER)],cwd=ROOT,env=e,text=True,capture_output=True)

def test_success_creates_latest_dashboard_snapshot_and_compact_history(tmp_path):
    result=run(env(tmp_path,observer(tmp_path))); assert result.returncode==0, result.stderr+result.stdout
    assert (tmp_path/"latest/ocean-buoy-observer.json").is_file()
    assert (tmp_path/"dashboard/latest/ocean-buoy-observer.json").is_file()
    assert (tmp_path/"snapshots/2026-07-25T12-15-00Z.json").is_file()
    history=json.loads((tmp_path/"history/2026-07-25.json").read_text()); assert "stations" not in history and history["statistics"]["total_stations"]==1

def test_bad_or_zero_station_output_preserves_last_good(tmp_path):
    latest=tmp_path/"latest/ocean-buoy-observer.json"; latest.parent.mkdir(); latest.write_text('{"known":"good"}')
    assert run(env(tmp_path,observer(tmp_path,raw="{bad"))).returncode != 0; assert latest.read_text()=='{"known":"good"}'
    assert run(env(tmp_path,observer(tmp_path,value={**payload(),"stations":[]}))).returncode != 0; assert latest.read_text()=='{"known":"good"}'

def test_retention_is_boundary_scoped_and_overlap_is_prevented(tmp_path):
    snaps=tmp_path/"snapshots"; snaps.mkdir(); old=snaps/"2026-07-01T00-00-00Z.json"; recent=snaps/"2026-07-24T00-00-00Z.json"; other=tmp_path/"other/2026-07-01T00-00-00Z.json"; other.parent.mkdir()
    for p in (old,recent,other): p.write_text("{}")
    ago=time.time()-8*86400; os.utime(old,(ago,ago)); os.utime(other,(ago,ago))
    assert run(env(tmp_path,observer(tmp_path))).returncode==0; assert not old.exists() and recent.exists() and other.exists()
    e=env(tmp_path,observer(tmp_path,sleep=1)); (tmp_path/"state/ocean_buoy_observer.lock").unlink(missing_ok=True)
    first=subprocess.Popen([str(RUNNER)],cwd=ROOT,env=e,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    for _ in range(100):
        if (tmp_path/"state/ocean_buoy_observer.lock").exists(): break
        time.sleep(.01)
    second=run(e); first.communicate(timeout=5); assert second.returncode==0 and "another run is active" in second.stdout

def test_daily_lock_collision_skips(tmp_path):
    import fcntl
    state=tmp_path/"state"; state.mkdir(); lock=open(state/"daily_run.lock","w"); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    result=run(env(tmp_path,observer(tmp_path))); assert result.returncode==0 and "daily workflow is active" in result.stdout and not (tmp_path/"latest/ocean-buoy-observer.json").exists()
