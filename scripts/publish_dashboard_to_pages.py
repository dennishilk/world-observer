#!/usr/bin/env python3
"""Copy exported dashboard files into a local GitHub Pages checkout."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Iterable

PAGES_REQUIRED_FILES = ("index.html", "world-observer.html")
DESTINATION_RELATIVE = Path("world-observer") / "dashboard"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _validate_pages_repo(pages_repo: Path) -> Path:
    pages_repo = pages_repo.expanduser().resolve()
    missing = [name for name in PAGES_REQUIRED_FILES if not (pages_repo / name).is_file()]
    if missing:
        raise ValueError(
            f"{pages_repo} does not look like the website repo; missing: {', '.join(missing)}"
        )
    return pages_repo


def _clear_directory(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _iter_files(path: Path) -> Iterable[Path]:
    return sorted(item for item in path.rglob("*") if item.is_file())


def publish_dashboard_to_pages(pages_repo: Path, dashboard_dir: Path | None = None) -> list[Path]:
    """Replace the website checkout's world-observer/dashboard with exported files."""
    source_dir = dashboard_dir or (_repo_root() / "dashboard")
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Dashboard directory not found: {source_dir}")

    pages_repo = _validate_pages_repo(pages_repo)
    destination = pages_repo / DESTINATION_RELATIVE
    destination.mkdir(parents=True, exist_ok=True)

    _clear_directory(destination)

    copied: list[Path] = []
    for source_file in _iter_files(source_dir):
        relative = source_file.relative_to(source_dir)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target)
        copied.append(target)
    return copied


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy exported dashboard files into a local dennishilk.github.io checkout."
    )
    parser.add_argument("--pages-repo", type=Path, required=True, help="Path to the local GitHub Pages repo checkout.")
    parser.add_argument("--dashboard-dir", type=Path, default=None, help="Dashboard export directory to copy from.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        copied = publish_dashboard_to_pages(args.pages_repo, args.dashboard_dir)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    for path in copied:
        print(path)


if __name__ == "__main__":
    main()
