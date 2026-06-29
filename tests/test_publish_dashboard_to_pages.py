from __future__ import annotations

from pathlib import Path

import pytest

from scripts.publish_dashboard_to_pages import publish_dashboard_to_pages


def _make_pages_repo(path: Path) -> None:
    path.mkdir()
    (path / "index.html").write_text("home", encoding="utf-8")
    (path / "world-observer.html").write_text("world observer", encoding="utf-8")


def _make_dashboard(path: Path) -> None:
    path.mkdir()
    (path / "summary.json").write_text('{"ok":true}\n', encoding="utf-8")
    history = path / "history"
    history.mkdir()
    (history / "media-language-germany.json").write_text('{"points":[]}\n', encoding="utf-8")


def test_publish_dashboard_to_pages_successful_copy(tmp_path) -> None:
    dashboard = tmp_path / "dashboard"
    pages_repo = tmp_path / "dennishilk.github.io"
    _make_dashboard(dashboard)
    _make_pages_repo(pages_repo)

    copied = publish_dashboard_to_pages(pages_repo, dashboard)

    assert [path.relative_to(pages_repo).as_posix() for path in copied] == [
        "world-observer/dashboard/history/media-language-germany.json",
        "world-observer/dashboard/summary.json",
    ]
    assert (
        pages_repo / "world-observer" / "dashboard" / "summary.json"
    ).read_text(encoding="utf-8") == '{"ok":true}\n'
    assert (
        pages_repo / "world-observer" / "dashboard" / "history" / "media-language-germany.json"
    ).read_text(encoding="utf-8") == '{"points":[]}\n'


def test_publish_dashboard_to_pages_rejects_invalid_pages_repo(tmp_path) -> None:
    dashboard = tmp_path / "dashboard"
    pages_repo = tmp_path / "not-pages"
    _make_dashboard(dashboard)
    pages_repo.mkdir()
    (pages_repo / "index.html").write_text("home", encoding="utf-8")

    with pytest.raises(ValueError, match="world-observer.html"):
        publish_dashboard_to_pages(pages_repo, dashboard)


def test_publish_dashboard_to_pages_creates_destination_directory(tmp_path) -> None:
    dashboard = tmp_path / "dashboard"
    pages_repo = tmp_path / "dennishilk.github.io"
    _make_dashboard(dashboard)
    _make_pages_repo(pages_repo)

    publish_dashboard_to_pages(pages_repo, dashboard)

    assert (pages_repo / "world-observer" / "dashboard").is_dir()


def test_publish_dashboard_to_pages_does_not_touch_unrelated_files(tmp_path) -> None:
    dashboard = tmp_path / "dashboard"
    pages_repo = tmp_path / "dennishilk.github.io"
    _make_dashboard(dashboard)
    _make_pages_repo(pages_repo)
    unrelated = pages_repo / "world-observer" / "keep.txt"
    unrelated.parent.mkdir()
    unrelated.write_text("do not touch", encoding="utf-8")
    root_unrelated = pages_repo / "CNAME"
    root_unrelated.write_text("example.com", encoding="utf-8")
    stale = pages_repo / "world-observer" / "dashboard" / "stale.json"
    stale.parent.mkdir()
    stale.write_text("old", encoding="utf-8")

    publish_dashboard_to_pages(pages_repo, dashboard)

    assert unrelated.read_text(encoding="utf-8") == "do not touch"
    assert root_unrelated.read_text(encoding="utf-8") == "example.com"
    assert not stale.exists()
