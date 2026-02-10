#!/usr/bin/env python3
"""Run daily observers and collect outputs.

Conservative runner that executes observers once per day, captures JSON
stdout, and stores results in data/daily/<YYYY-MM-DD>/.
"""

from __future__ import annotations

import argparse
import os
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

OBSERVERS: List[str] = [
    "area51-reachability",
    "north-korea-connectivity",
    "cuba-internet-weather",
    "iran-dns-behavior",
    "traceroute-to-nowhere",
    "internet-shrinkage-index",
    "asn-visibility-by-country",
    "tls-fingerprint-change-watcher",
    "silent-countries-list",
    "ipv6-locked-states",
    "global-reachability-score",
    "undersea-cable-dependency",
    "dns-time-to-answer-index",
    "mx-presence-by-country",
]

META_OBSERVER = "world-observer-meta"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _yesterday_utc() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily observers.")
    parser.add_argument(
        "--date",
        help="Override date (YYYY-MM-DD). Defaults to yesterday (UTC).",
    )
    return parser.parse_args()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _error_payload(observer: str, date_str: str, message: str, stderr: str = "") -> Dict[str, Any]:
    payload = {
        "observer": observer,
        "date": date_str,
        "status": "error",
        "error": message,
    }
    if stderr:
        payload["stderr"] = stderr.strip()
    return payload


def _run_observer(observer: str, date_str: str, daily_dir: Path) -> Tuple[bool, str]:
    observer_path = _repo_root() / "observers" / observer / "observer.py"
    output_path = daily_dir / f"{observer}.json"

    if not observer_path.exists():
        _write_json(
            output_path,
            _error_payload(observer, date_str, "observer.py not found"),
        )
        return False, "observer.py not found"

    env = os.environ.copy()
    env["WORLD_OBSERVER_DATE_UTC"] = date_str
    result = subprocess.run(
        [sys.executable, str(observer_path)],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    if result.returncode != 0:
        _write_json(
            output_path,
            _error_payload(
                observer,
                date_str,
                f"observer exited with status {result.returncode}",
                result.stderr,
            ),
        )
        return False, f"exit {result.returncode}"

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        _write_json(
            output_path,
            _error_payload(observer, date_str, f"invalid JSON output: {exc}", result.stderr),
        )
        return False, "invalid JSON"

    if not isinstance(payload, dict):
        _write_json(
            output_path,
            _error_payload(observer, date_str, "JSON root is not an object", result.stderr),
        )
        return False, "non-object JSON"

    _write_json(output_path, payload)
    return True, "ok"


def _run_meta_observer(date_str: str, daily_dir: Path) -> Tuple[bool, str]:
    observer_path = _repo_root() / "observers" / META_OBSERVER / "observer.py"
    summary_json = daily_dir / "summary.json"
    summary_md = daily_dir / "summary.md"

    if not observer_path.exists():
        _write_json(
            summary_json,
            _error_payload(META_OBSERVER, date_str, "observer.py not found"),
        )
        summary_md.write_text(
            f"# {META_OBSERVER} daily summary ({date_str})\n\n"
            "Status: observer.py not found.\n",
            encoding="utf-8",
        )
        return False, "observer.py not found"

    env = os.environ.copy()
    env["WORLD_OBSERVER_DATE_UTC"] = date_str
    result = subprocess.run(
        [sys.executable, str(observer_path)],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    if result.returncode != 0:
        _write_json(
            summary_json,
            _error_payload(
                META_OBSERVER,
                date_str,
                f"observer exited with status {result.returncode}",
                result.stderr,
            ),
        )
        summary_md.write_text(
            f"# {META_OBSERVER} daily summary ({date_str})\n\n"
            "Status: meta observer failed.\n",
            encoding="utf-8",
        )
        return False, f"exit {result.returncode}"

    if not summary_json.exists() or not summary_md.exists():
        _write_json(
            summary_json,
            _error_payload(META_OBSERVER, date_str, "summary output missing"),
        )
        summary_md.write_text(
            f"# {META_OBSERVER} daily summary ({date_str})\n\n"
            "Status: summary output missing.\n",
            encoding="utf-8",
        )
        return False, "summary output missing"

    return True, "ok"


def _update_latest(daily_dir: Path) -> None:
    latest_dir = _repo_root() / "data" / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    for path in daily_dir.glob("*.json"):
        if path.name == "summary.json":
            continue
        shutil.copy2(path, latest_dir / path.name)


def main() -> None:
    args = _parse_args()
    if args.date:
        date_str = args.date
        daily_dir = _repo_root() / "data" / "daily" / date_str
        daily_dir.mkdir(parents=True, exist_ok=True)
    else:
        date_str = _yesterday_utc()
        daily_dir = _repo_root() / "data" / "daily" / date_str
        if daily_dir.exists() and any(daily_dir.iterdir()):
            return
        daily_dir.mkdir(parents=True, exist_ok=True)

    failures: List[str] = []

    for observer in OBSERVERS:
        ok, detail = _run_observer(observer, date_str, daily_dir)
        if ok:
            print(f"[ok] {observer}")
        else:
            print(f"[fail] {observer}: {detail}")
            failures.append(observer)

    meta_ok, meta_detail = _run_meta_observer(date_str, daily_dir)
    if meta_ok:
        print(f"[ok] {META_OBSERVER}")
    else:
        print(f"[fail] {META_OBSERVER}: {meta_detail}")
        failures.append(META_OBSERVER)

    _update_latest(daily_dir)

    if failures:
        print(f"Completed with failures: {', '.join(failures)}")
    else:
        print("Completed with no failures.")


if __name__ == "__main__":
    main()
