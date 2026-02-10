#!/usr/bin/env python3
"""Create and push hourly heartbeat files."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _heartbeat_timestamp() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def _heartbeat_payload(timestamp: datetime) -> dict:
    return {
        "timestamp_utc": timestamp.strftime("%Y-%m-%dT%H:00:00Z"),
        "status": "alive",
        "note": "Periodic heartbeat. No observation results included.",
    }


def _write_if_changed(path: Path, payload: dict) -> bool:
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def _apply_retention(heartbeat_dir: Path, keep: int = 12) -> List[Path]:
    heartbeat_files = sorted(path for path in heartbeat_dir.glob("*.json"))
    if len(heartbeat_files) <= keep:
        return []
    to_delete = heartbeat_files[: len(heartbeat_files) - keep]
    for path in to_delete:
        path.unlink(missing_ok=True)
    return to_delete


def _git(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=_repo_root(), check=True, capture_output=True, text=True)


def main() -> None:
    repo_root = _repo_root()
    heartbeat_dir = repo_root / "state" / "heartbeat"
    heartbeat_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _heartbeat_timestamp()
    filename = timestamp.strftime("%Y-%m-%dT%HZ.json")
    heartbeat_path = heartbeat_dir / filename
    _write_if_changed(heartbeat_path, _heartbeat_payload(timestamp))
    _apply_retention(heartbeat_dir, keep=12)

    subprocess.run(
        ["git", "add", "-A", "state/heartbeat"],
        cwd=repo_root,
    )

    diff_check = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", "state/heartbeat"],
        cwd=repo_root,
        check=False,
    )
    if diff_check.returncode == 0:
        return

    commit_message = f"heartbeat: system alive (UTC {timestamp:%H}:00)"
    _git(["git", "commit", "-m", commit_message, "--", "state/heartbeat"])
    _git(["git", "push"])


if __name__ == "__main__":
    main()
