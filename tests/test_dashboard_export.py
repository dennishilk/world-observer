from __future__ import annotations

import json
from pathlib import Path

from scripts import export_dashboard
from scripts.run_daily import OBSERVERS


def _write_latest(latest_dir: Path, observer: str, payload: dict) -> None:
    (latest_dir / f"{observer}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_export_dashboard_succeeds_and_writes_valid_json(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()

    for observer in OBSERVERS:
        _write_latest(
            latest_dir,
            observer,
            {"observer": observer, "data_status": "ok", "summary": {"value": 1}},
        )
    _write_latest(
        latest_dir,
        export_dashboard.MEDIA_OBSERVER,
        {
            "observer": export_dashboard.MEDIA_OBSERVER,
            "data_status": "ok",
            "fear_index_overall": 12.5,
            "headline_count": 8,
            "source_groups": {
                "public_broadcast": {"headline_count": 3, "fear_index": 10.0},
                "private_media": {"headline_count": 5, "fear_index": 14.0},
            },
            "top_terms": [{"term": "krise", "count": 2}],
            "category_counts": {"political_pressure": 2},
            "diagnostics": {"internal": "not exported"},
        },
    )

    written = export_dashboard.export_dashboard(latest_dir, dashboard_dir)

    assert sorted(written) == sorted((*export_dashboard.OUTPUT_FILES, *export_dashboard.HISTORY_FILES))
    for name in export_dashboard.OUTPUT_FILES:
        payload = json.loads((dashboard_dir / name).read_text(encoding="utf-8"))
        assert isinstance(payload, dict)

    summary = json.loads((dashboard_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["observer_count"] == len(OBSERVERS)
    assert summary["observers_ok"] == len(OBSERVERS)
    assert summary["missing_count"] == 0
    assert summary["dashboard_version"] == export_dashboard.DASHBOARD_VERSION

    media = json.loads((dashboard_dir / "media.json").read_text(encoding="utf-8"))
    assert media == {
        "category_counts": {"political_pressure": 2},
        "fear_index_overall": 12.5,
        "headline_count": 8,
        "private_media": {"fear_index": 14.0, "headline_count": 5},
        "public_broadcast": {"fear_index": 10.0, "headline_count": 3},
        "top_terms": [{"term": "krise", "count": 2}],
    }


def test_export_dashboard_handles_missing_observer(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    missing = OBSERVERS[0]

    for observer in OBSERVERS[1:]:
        _write_latest(latest_dir, observer, {"observer": observer, "data_status": "ok"})

    export_dashboard.export_dashboard(latest_dir, dashboard_dir)

    summary = json.loads((dashboard_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["missing_count"] == 1
    assert summary["observers_ok"] == len(OBSERVERS) - 1
    assert missing in summary["missing_observers"]
    assert (dashboard_dir / "internet.json").exists()
    assert (dashboard_dir / "media.json").exists()


def test_export_dashboard_generates_compact_output(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    _write_latest(latest_dir, OBSERVERS[0], {"observer": OBSERVERS[0], "data_status": "ok"})

    export_dashboard.export_dashboard(latest_dir, dashboard_dir)

    summary_text = (dashboard_dir / "summary.json").read_text(encoding="utf-8")
    assert summary_text.endswith("\n")
    assert "\n " not in summary_text
    assert ": " not in summary_text


def _write_daily_media(daily_dir: Path, date: str, payload: dict) -> None:
    date_dir = daily_dir / date
    date_dir.mkdir(parents=True)
    (date_dir / f"{export_dashboard.MEDIA_OBSERVER}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_export_dashboard_writes_empty_media_history(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    daily_dir = tmp_path / "daily"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    daily_dir.mkdir()

    export_dashboard.export_dashboard(latest_dir, dashboard_dir, daily_dir)

    history = json.loads((dashboard_dir / "history" / "media-language-germany.json").read_text(encoding="utf-8"))
    assert history["observer"] == export_dashboard.MEDIA_OBSERVER
    assert history["points"] == []
    assert history["windows"] == {"7d": {"count": 0}, "30d": {"count": 0}}


def test_export_dashboard_writes_one_media_history_point(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    daily_dir = tmp_path / "daily"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    _write_daily_media(
        daily_dir,
        "2026-06-29",
        {
            "fear_index_overall": 4.17,
            "headline_count": 266,
            "source_groups": {
                "public_broadcast": {"fear_index": 3.8, "headlines": ["not exported"]},
                "private_media": {"fear_index": 5.1},
            },
            "top_terms": [
                {"term": "hitze", "count": 10},
                {"term": "krieg", "count": 9},
                {"term": "streit", "count": 8},
                {"term": "extra", "count": 7},
            ],
            "diagnostics": {"not": "exported"},
            "headlines": ["not exported"],
        },
    )

    export_dashboard.export_dashboard(latest_dir, dashboard_dir, daily_dir)

    history = json.loads((dashboard_dir / "history" / "media-language-germany.json").read_text(encoding="utf-8"))
    assert history["points"] == [
        {
            "date": "2026-06-29",
            "fear_index_overall": 4.17,
            "headline_count": 266,
            "private_media": 5.1,
            "public_broadcast": 3.8,
            "top_terms": ["hitze", "krieg", "streit"],
        }
    ]
    assert history["windows"]["7d"] == {"count": 1, "latest": 4.17, "min": 4.17, "max": 4.17, "avg": 4.17}


def test_export_dashboard_writes_multiple_points_with_7d_trend(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    daily_dir = tmp_path / "daily"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    for day, fear in enumerate([1.0, 2.0, 3.0], start=27):
        _write_daily_media(daily_dir, f"2026-06-{day}", {"fear_index_overall": fear, "headline_count": day})

    export_dashboard.export_dashboard(latest_dir, dashboard_dir, daily_dir)

    history = json.loads((dashboard_dir / "history" / "media-language-germany.json").read_text(encoding="utf-8"))
    assert [point["date"] for point in history["points"]] == ["2026-06-27", "2026-06-28", "2026-06-29"]
    assert history["windows"]["7d"] == {
        "count": 3,
        "latest": 3.0,
        "previous": 2.0,
        "delta": 1.0,
        "min": 1.0,
        "max": 3.0,
        "avg": 2.0,
    }


def test_export_dashboard_history_is_compact(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    daily_dir = tmp_path / "daily"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    _write_daily_media(daily_dir, "2026-06-29", {"fear_index_overall": 1.0})

    export_dashboard.export_dashboard(latest_dir, dashboard_dir, daily_dir)

    history_text = (dashboard_dir / "history" / "media-language-germany.json").read_text(encoding="utf-8")
    assert history_text.endswith("\n")
    assert "\n " not in history_text
    assert ": " not in history_text
    assert "diagnostics" not in history_text
    assert "headlines" not in history_text
