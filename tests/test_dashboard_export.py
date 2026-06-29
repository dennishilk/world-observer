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

    assert sorted(written) == sorted(export_dashboard.OUTPUT_FILES)
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
