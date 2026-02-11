#!/usr/bin/env python3
"""High-level verification runner for world-observer automation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
DAILY_ROOT = REPO_ROOT / "data" / "daily"
LATEST_CHART = REPO_ROOT / "data" / "latest" / "chart.png"

FORBIDDEN_KEYS = (
    "ip",
    "ip_address",
    "domain",
    "domain_name",
    "hostname",
    "certificate",
    "cert_pem",
    "raw_route",
    "traceroute_raw",
)


def run(cmd: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd))
    return subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=check)


def load_run_daily_observers() -> list[str]:
    namespace: dict[str, object] = {}
    code = (REPO_ROOT / "scripts" / "run_daily.py").read_text(encoding="utf-8")
    exec(compile(code, "run_daily.py", "exec"), namespace)
    observers = namespace.get("OBSERVERS")
    if not isinstance(observers, list):
        raise RuntimeError("Unable to load OBSERVERS from scripts/run_daily.py")
    return [str(x) for x in observers]


def iter_json_paths(root: Path) -> Iterable[Path]:
    for path in sorted(root.glob("*.json")):
        yield path


def assert_daily_outputs(run_date: str, observers: list[str]) -> None:
    day_dir = DAILY_ROOT / run_date
    missing = [name for name in observers if not (day_dir / f"{name}.json").exists()]
    if missing:
        raise AssertionError(f"Missing daily outputs: {', '.join(missing)}")


def assert_json_schema(run_date: str, observers: list[str]) -> None:
    day_dir = DAILY_ROOT / run_date
    for observer in observers:
        payload = json.loads((day_dir / f"{observer}.json").read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise AssertionError(f"{observer}: JSON root is not object")
        if payload.get("observer") != observer:
            raise AssertionError(f"{observer}: observer field mismatch")
        if payload.get("status") == "error":
            continue
        if "date_utc" in payload and payload.get("date_utc") != run_date:
            raise AssertionError(f"{observer}: expected date_utc {run_date}")
        if "date" in payload and payload.get("date") != run_date:
            raise AssertionError(f"{observer}: expected date {run_date}")


def assert_privacy_keys(run_date: str) -> None:
    day_dir = DAILY_ROOT / run_date
    for path in iter_json_paths(day_dir):
        payload = json.loads(path.read_text(encoding="utf-8"))
        text = json.dumps(payload).lower()
        for key in FORBIDDEN_KEYS:
            bad_token = f'"{key}"'
            if bad_token in text:
                raise AssertionError(f"{path.name}: found restricted key token {bad_token}")


def verify_png_policy() -> None:
    observer = REPO_ROOT / "observers" / "tls-fingerprint-change" / "observer.py"
    base_date = date.today() - timedelta(days=2)
    low_date = base_date.isoformat()
    high_date = (base_date + timedelta(days=1)).isoformat()

    if LATEST_CHART.exists():
        LATEST_CHART.unlink()

    env = os.environ.copy()
    env["WORLD_OBSERVER_DATE_UTC"] = low_date
    low_result = run([sys.executable, str(observer)], env=env)
    low_payload = json.loads(low_result.stdout)

    low_sig = bool(low_payload.get("significance", {}).get("any_significant", False))
    if low_sig:
        print("[warn] baseline run was significant; skipping strict no-PNG assertion")
    elif LATEST_CHART.exists():
        raise AssertionError("chart.png exists despite non-significant baseline run")

    env_high = os.environ.copy()
    env_high["WORLD_OBSERVER_DATE_UTC"] = high_date
    env_high["WORLD_OBSERVER_TLS_FORCE_SIGNIFICANT"] = "1"
    high_payload = json.loads(run([sys.executable, str(observer)], env=env_high).stdout)
    high_sig = bool(high_payload.get("significance", {}).get("any_significant", False))
    if not high_sig:
        raise AssertionError("forced significance did not produce a significant payload")
    if not LATEST_CHART.exists():
        raise AssertionError("chart.png missing after forced significance run")


def verify_heartbeat(check_push: bool) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    cmd = [sys.executable, "scripts/heartbeat_push.py"]
    if not check_push:
        cmd.append("--no-push")
    run(cmd, env=env)


def main() -> None:
    parser = argparse.ArgumentParser(description="Repository quality/stability verification")
    parser.add_argument("--check-push", action="store_true", help="Run heartbeat with git push enabled")
    args = parser.parse_args()

    run_date = (date.today() - timedelta(days=1)).isoformat()
    observers = load_run_daily_observers()

    verify_heartbeat(check_push=args.check_push)
    run([sys.executable, "scripts/run_daily.py", "--date", run_date])
    assert_daily_outputs(run_date, observers)
    assert_json_schema(run_date, observers)
    assert_privacy_keys(run_date)
    verify_png_policy()

    print("All repository verification checks passed.")


if __name__ == "__main__":
    main()
