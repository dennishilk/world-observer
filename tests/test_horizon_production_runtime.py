from __future__ import annotations
import fcntl, importlib.util, json, subprocess, sys
from pathlib import Path

REPO_ROOT=Path(__file__).resolve().parents[1]

def test_runtime_script_has_no_git_commands_and_updates_only_horizon(tmp_path):
    script=REPO_ROOT/'scripts/run_horizon_observer_production.sh'
    text=script.read_text()
    assert 'git add' not in text and 'git commit' not in text and 'git push' not in text
    website=tmp_path/'site/world-observer/dashboard/latest/horizon-observer.json'
    before={p.relative_to(REPO_ROOT) for p in (REPO_ROOT/'dashboard/latest').glob('*.json')}
    r=subprocess.run([str(script)], cwd=REPO_ROOT, env={**__import__('os').environ,'WORLD_OBSERVER_HORIZON_WEBSITE_OUTPUT':str(website),'WORLD_OBSERVER_NOW_UTC':'2026-01-15T13:00:00Z'}, text=True, capture_output=True, timeout=60)
    assert r.returncode==0, r.stderr+r.stdout
    assert website.exists(); json.loads(website.read_text())
    after={p.relative_to(REPO_ROOT) for p in (REPO_ROOT/'dashboard/latest').glob('*.json')}
    assert after-before <= {Path('dashboard/latest/horizon-observer.json')}

def test_runtime_script_preserves_previous_on_failure(tmp_path):
    script=REPO_ROOT/'scripts/run_horizon_observer_production.sh'; website=tmp_path/'horizon.json'; website.write_text('{"old":true}\n')
    r=subprocess.run([str(script)], cwd=REPO_ROOT, env={**__import__('os').environ,'WORLD_OBSERVER_HORIZON_WEBSITE_OUTPUT':str(website),'PYTHON':'/bin/false'}, text=True, capture_output=True, timeout=30)
    assert r.returncode!=0 and website.read_text()=='{"old":true}\n'

def test_runtime_lock_skips_concurrent(tmp_path):
    lockdir=tmp_path/'locks'; lockdir.mkdir(); lock=(lockdir/'horizon_observer.lock').open('w'); fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    r=subprocess.run([str(REPO_ROOT/'scripts/run_horizon_observer_production.sh')], cwd=REPO_ROOT, env={**__import__('os').environ,'WORLD_OBSERVER_LOCK_DIR':str(lockdir),'WORLD_OBSERVER_HORIZON_WEBSITE_OUTPUT':str(tmp_path/'out.json')}, text=True, capture_output=True, timeout=30)
    assert r.returncode==0 and 'skipping' in r.stdout
