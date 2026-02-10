#!/usr/bin/env python3
"""Create and push hourly heartbeat files.

Designed for unattended cron usage:
- idempotent staging/commit behavior
- optional dry-run and no-push modes for verification
- non-interactive SSH push behavior
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Sequence


DEFAULT_DEPLOY_KEY = Path.home() / ".ssh" / "id_ed25519_world_observer"


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


def _build_git_env(repo_root: Path) -> dict:
    env = os.environ.copy()
    config_cmd = subprocess.run(
        ["git", "config", "--local", "--get", "core.sshCommand"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if config_cmd.returncode == 0 and config_cmd.stdout.strip():
        env["GIT_SSH_COMMAND"] = config_cmd.stdout.strip()
        return env

    if DEFAULT_DEPLOY_KEY.exists():
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {DEFAULT_DEPLOY_KEY} -o BatchMode=yes "
            "-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        )
    return env


def _git(args: Sequence[str], repo_root: Path, env: dict, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), cwd=repo_root, env=env, capture_output=True, text=True, check=check)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create/push hourly heartbeat file")
    parser.add_argument("--no-push", action="store_true", help="Create/commit heartbeat without pushing")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing git state")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    repo_root = _repo_root()
    env = _build_git_env(repo_root)

    heartbeat_dir = repo_root / "state" / "heartbeat"
    heartbeat_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _heartbeat_timestamp()
    filename = timestamp.strftime("%Y-%m-%dT%HZ.json")
    heartbeat_path = heartbeat_dir / filename

    changed = _write_if_changed(heartbeat_path, _heartbeat_payload(timestamp))
    removed = _apply_retention(heartbeat_dir, keep=12)

    if args.dry_run:
        print(f"[dry-run] heartbeat_file={heartbeat_path} changed={changed} removed={len(removed)}")
        return

    _git(["git", "add", "--", "state/heartbeat"], repo_root, env)

    diff_check = _git(
        ["git", "diff", "--cached", "--quiet", "--", "state/heartbeat"],
        repo_root,
        env,
        check=False,
    )
    if diff_check.returncode == 0:
        print("[heartbeat] no staged changes")
        return

    commit_message = f"heartbeat: system alive (UTC {timestamp:%H}:00)"
    commit = _git(["git", "commit", "-m", commit_message, "--", "state/heartbeat"], repo_root, env, check=False)
    if commit.returncode != 0:
        # Handle rare races where another process committed first.
        print(commit.stderr.strip() or commit.stdout.strip())
        return

    print(commit.stdout.strip())

    if args.no_push:
        print("[heartbeat] push skipped (--no-push)")
        return

    push = _git(["git", "push"], repo_root, env, check=False)
    if push.returncode != 0:
        print(push.stderr.strip() or push.stdout.strip())
        raise SystemExit(push.returncode)
    print(push.stdout.strip())


if __name__ == "__main__":
    main()
