#!/usr/bin/env python3
"""Cron-safe heartbeat writer + git publisher."""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Sequence

import fcntl

REPO_ROOT = Path(__file__).resolve().parents[1]
HEARTBEAT_DIR = REPO_ROOT / "state" / "heartbeat"
LOG_FILE = REPO_ROOT / "logs" / "heartbeat.log"
LOCK_FILE = REPO_ROOT / "state" / "heartbeat_push.lock"
DEPLOY_KEY = Path("/home/nebu/.ssh/deploy_key")
KEEP_FILES = 12


def _logger() -> logging.Logger:
    logger = logging.getLogger("heartbeat_push")
    if logger.handlers:
        return logger

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
        utc=True,
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = (
        f"ssh -i {DEPLOY_KEY} -o IdentitiesOnly=yes -o BatchMode=yes "
        "-o StrictHostKeyChecking=accept-new"
    )
    return env


def _run_command(args: Sequence[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@contextmanager
def _lock_execution(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("heartbeat runner already active")
        yield


def _current_hour() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def _heartbeat_payload(stamp: datetime) -> dict[str, object]:
    return {
        "timestamp_utc": stamp.strftime("%Y-%m-%dT%H:00:00Z"),
        "epoch": int(stamp.timestamp()),
        "hostname": socket.gethostname(),
        "status": "alive",
    }


def _write_heartbeat(stamp: datetime, logger: logging.Logger) -> Path:
    HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
    path = HEARTBEAT_DIR / f"{stamp:%Y-%m-%dT%HZ}.json"
    payload = _heartbeat_payload(stamp)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("new heartbeat file created: %s", path)
    return path


def _apply_retention(logger: logging.Logger) -> list[Path]:
    files = sorted(HEARTBEAT_DIR.glob("*.json"))
    if len(files) <= KEEP_FILES:
        return []
    deleted = files[: len(files) - KEEP_FILES]
    for path in deleted:
        path.unlink(missing_ok=True)
    logger.info("deleted %s old heartbeat files: %s", len(deleted), ", ".join(p.name for p in deleted))
    return deleted


def _git_commit_and_push(stamp: datetime, logger: logging.Logger) -> None:
    env = _git_env()

    add = _run_command(["/usr/bin/git", "add", "--", "state/heartbeat"], env=env)
    if add.returncode != 0:
        raise RuntimeError(add.stderr.strip() or add.stdout.strip() or "git add failed")

    diff = _run_command(["/usr/bin/git", "diff", "--cached", "--quiet", "--", "state/heartbeat"], env=env)
    if diff.returncode == 0:
        logger.info("no staged heartbeat changes; skipping commit/push")
        return
    if diff.returncode not in (0, 1):
        raise RuntimeError(diff.stderr.strip() or diff.stdout.strip() or "git diff --cached failed")

    message = f"heartbeat: alive {stamp:%Y-%m-%d %H}:00 UTC"
    commit = _run_command(["/usr/bin/git", "commit", "-m", message, "--", "state/heartbeat"], env=env)
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr.strip() or commit.stdout.strip() or "git commit failed")

    commit_hash = _run_command(["/usr/bin/git", "rev-parse", "--short", "HEAD"], env=env)
    if commit_hash.returncode == 0:
        logger.info("commit made: %s", commit_hash.stdout.strip())

    push = _run_command(["/usr/bin/git", "push", "origin", "HEAD"], env=env)
    if push.returncode != 0:
        raise RuntimeError(push.stderr.strip() or push.stdout.strip() or "git push failed")
    logger.info("push status: success")


def main() -> int:
    logger = _logger()
    try:
        with _lock_execution(LOCK_FILE):
            stamp = _current_hour()
            _write_heartbeat(stamp, logger)
            _apply_retention(logger)
            _git_commit_and_push(stamp, logger)
            logger.info("heartbeat run completed")
    except Exception as exc:  # noqa: BLE001
        logger.exception("heartbeat run failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
