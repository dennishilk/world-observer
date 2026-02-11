#!/usr/bin/env python3
"""Cron-safe daily orchestration + git publisher."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Sequence

import fcntl

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = REPO_ROOT / "logs" / "daily.log"
LOCK_FILE = REPO_ROOT / "state" / "daily_run.lock"
DEPLOY_KEY = Path("/home/nebu/.ssh/deploy_key")
RUN_DAILY_SCRIPT = REPO_ROOT / "scripts" / "run_daily.py"
SIGNIFICANCE_SCRIPT = REPO_ROOT / "visualizations" / "generate_significance_png.py"
DATA_DAILY_DIR = REPO_ROOT / "data" / "daily"
DATA_LATEST_DIR = REPO_ROOT / "data" / "latest"
SIGNIFICANT_DIR = REPO_ROOT / "visualizations" / "significant"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily world-observer jobs and publish outputs")
    parser.add_argument("--date", help="Target date (YYYY-MM-DD); default is yesterday UTC")
    return parser.parse_args()


def _logger() -> logging.Logger:
    logger = logging.getLogger("run_daily_cron")
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


def _target_date(input_date: str | None) -> str:
    if input_date:
        datetime.strptime(input_date, "%Y-%m-%d")
        return input_date
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = (
        f"ssh -i {DEPLOY_KEY} -o IdentitiesOnly=yes -o BatchMode=yes "
        "-o StrictHostKeyChecking=accept-new"
    )
    return env


def _run(args: Sequence[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
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
            raise SystemExit("daily runner already active")
        yield


def _run_python_script(script: Path, extra_args: Sequence[str], logger: logging.Logger) -> None:
    cmd = [sys.executable, str(script), *extra_args]
    result = _run(cmd)
    if result.stdout.strip():
        logger.info(result.stdout.strip())
    if result.stderr.strip():
        logger.info(result.stderr.strip())
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(cmd)}")


def _copy_significance_pngs(date_str: str, logger: logging.Logger) -> list[Path]:
    copied: list[Path] = []
    target_dir = DATA_DAILY_DIR / date_str
    target_dir.mkdir(parents=True, exist_ok=True)
    if not SIGNIFICANT_DIR.exists():
        return copied

    for png in sorted(SIGNIFICANT_DIR.glob(f"{date_str}-*.png")):
        destination = target_dir / png.name
        shutil.copy2(png, destination)
        copied.append(destination)

    if copied:
        logger.info("copied significance PNGs: %s", ", ".join(str(path) for path in copied))
    else:
        logger.info("no significance PNGs for %s", date_str)
    return copied


def _update_latest_summary(date_str: str, logger: logging.Logger) -> None:
    DATA_LATEST_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = DATA_LATEST_DIR / "summary.json"
    existing: dict[str, object] = {}
    if summary_path.exists():
        try:
            existing = json.loads(summary_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except json.JSONDecodeError:
            existing = {}

    existing["last_daily_run_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing["run_date_utc"] = date_str
    existing["runner"] = "scripts/run_daily_cron.py"

    summary_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("updated summary: %s", summary_path)


def _git_commit_and_push(date_str: str, logger: logging.Logger) -> None:
    env = _git_env()

    add_targets = [
        "data/daily",
        "data/latest",
        "visualizations/significant",
    ]
    add = _run(["/usr/bin/git", "add", "--", *add_targets], env=env)
    if add.returncode != 0:
        raise RuntimeError(add.stderr.strip() or add.stdout.strip() or "git add failed")

    diff = _run(["/usr/bin/git", "diff", "--cached", "--quiet"], env=env)
    if diff.returncode == 0:
        logger.info("no staged daily changes; skipping commit/push")
        return
    if diff.returncode not in (0, 1):
        raise RuntimeError(diff.stderr.strip() or diff.stdout.strip() or "git diff --cached failed")

    message = f"daily: observer outputs {date_str}"
    commit = _run(["/usr/bin/git", "commit", "-m", message], env=env)
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr.strip() or commit.stdout.strip() or "git commit failed")

    commit_hash = _run(["/usr/bin/git", "rev-parse", "--short", "HEAD"], env=env)
    if commit_hash.returncode == 0:
        logger.info("commit made: %s", commit_hash.stdout.strip())

    push = _run(["/usr/bin/git", "push", "origin", "HEAD"], env=env)
    if push.returncode != 0:
        raise RuntimeError(push.stderr.strip() or push.stdout.strip() or "git push failed")
    logger.info("push status: success")


def main() -> int:
    logger = _logger()
    args = _parse_args()

    try:
        date_str = _target_date(args.date)
        with _lock_execution(LOCK_FILE):
            logger.info("starting daily run for date %s", date_str)
            _run_python_script(RUN_DAILY_SCRIPT, ["--date", date_str], logger)
            _run_python_script(SIGNIFICANCE_SCRIPT, ["--date", date_str], logger)
            _copy_significance_pngs(date_str, logger)
            _update_latest_summary(date_str, logger)
            _git_commit_and_push(date_str, logger)
            logger.info("daily run completed")
    except Exception as exc:  # noqa: BLE001
        logger.exception("daily run failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
