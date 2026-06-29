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


def _write_daily_observer(daily_dir: Path, date: str, observer: str, payload: dict | str) -> None:
    date_dir = daily_dir / date
    date_dir.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (date_dir / f"{observer}.json").write_text(text, encoding="utf-8")


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


def test_export_dashboard_writes_internet_cards(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    _write_latest(
        latest_dir,
        "area51-reachability",
        {
            "observer": "area51-reachability",
            "data_status": "partial",
            "date_utc": "2026-06-29",
            "au": {"total": 71, "other": 17},
            "bucket_count": 1,
            "diagnostics": {"not": "exported"},
            "degraded_reason": "sample partial data",
        },
    )

    export_dashboard.export_dashboard(latest_dir, dashboard_dir)

    internet = json.loads((dashboard_dir / "internet.json").read_text(encoding="utf-8"))
    card = internet["observers"][0]
    assert card["observer"] == "area51-reachability"
    assert card["display_name"] == "Area51 Reachability"
    assert card["category"] == "internet"
    assert card["dashboard_priority"] == 10
    assert card["status"] == "partial"
    assert card["data_status"] == "partial"
    assert card["primary_metric_name"] == "au.total"
    assert card["primary_metric_value"] == 71
    assert card["last_seen_date"] == "2026-06-29"
    assert card["degraded_reason"] == "sample partial data"
    assert "diagnostics" not in json.dumps(card)


def test_export_dashboard_uses_observer_metadata_for_display_and_order(tmp_path, monkeypatch) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    metadata_path = tmp_path / "observer_metadata.json"
    latest_dir.mkdir()
    metadata_path.write_text(
        json.dumps(
            {
                "observers": [
                    {
                        "observer": "cuba-internet-weather",
                        "display_name": "Custom Cuba Weather",
                        "category": "internet",
                        "description": "Custom metadata.",
                        "tags": ["internet", "custom"],
                        "dashboard_priority": 1,
                        "planned": False,
                    },
                    {
                        "observer": "area51-reachability",
                        "display_name": "Custom Area 51",
                        "category": "internet",
                        "description": "Custom metadata.",
                        "tags": ["internet", "custom"],
                        "dashboard_priority": 2,
                        "planned": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(export_dashboard, "METADATA_PATH", str(metadata_path))
    _write_latest(latest_dir, "area51-reachability", {"observer": "area51-reachability", "data_status": "ok"})
    _write_latest(latest_dir, "cuba-internet-weather", {"observer": "cuba-internet-weather", "data_status": "ok"})

    export_dashboard.export_dashboard(latest_dir, dashboard_dir)

    internet = json.loads((dashboard_dir / "internet.json").read_text(encoding="utf-8"))
    assert [card["observer"] for card in internet["observers"]] == ["cuba-internet-weather", "area51-reachability"]
    assert internet["observers"][0]["display_name"] == "Custom Cuba Weather"
    assert internet["observers"][0]["dashboard_priority"] == 1


def test_export_dashboard_writes_planned_metadata_placeholders(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()

    export_dashboard.export_dashboard(latest_dir, dashboard_dir)

    society = json.loads((dashboard_dir / "society.json").read_text(encoding="utf-8"))
    environment = json.loads((dashboard_dir / "environment.json").read_text(encoding="utf-8"))
    assert [item["observer"] for item in society["items"]] == [
        "fuel-prices-germany",
        "electricity-prices-germany",
        "food-prices-germany",
        "housing-costs-germany",
        "deutsche-bahn-punctuality",
        "deutsche-post-reliability",
    ]
    assert [item["observer"] for item in environment["items"]] == [
        "weather-germany",
        "climate-germany",
        "natural-disasters-germany",
    ]
    assert all(item["planned"] is True for item in society["items"] + environment["items"])


def test_export_dashboard_falls_back_when_metadata_is_missing(tmp_path, monkeypatch) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    monkeypatch.setattr(export_dashboard, "METADATA_PATH", str(tmp_path / "missing.json"))
    _write_latest(latest_dir, "area51-reachability", {"observer": "area51-reachability", "data_status": "ok"})

    export_dashboard.export_dashboard(latest_dir, dashboard_dir)

    internet = json.loads((dashboard_dir / "internet.json").read_text(encoding="utf-8"))
    card = internet["observers"][0]
    assert card["display_name"] == "Area51 Reachability"
    assert card["category"] == "internet"
    assert card["dashboard_priority"] == 10_000


def test_export_dashboard_internet_card_falls_back_to_data_status(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    _write_latest(latest_dir, "cuba-internet-weather", {"observer": "cuba-internet-weather", "data_status": "unavailable"})

    export_dashboard.export_dashboard(latest_dir, dashboard_dir)

    internet = json.loads((dashboard_dir / "internet.json").read_text(encoding="utf-8"))
    card = internet["observers"][0]
    assert card["primary_metric_name"] == "data_status"
    assert card["primary_metric_value"] == "unavailable"


def test_export_dashboard_writes_internet_history(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    daily_dir = tmp_path / "daily"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    _write_daily_observer(daily_dir, "2026-06-27", "area51-reachability", {"data_status": "ok", "au": {"total": 1}})
    _write_daily_observer(daily_dir, "2026-06-28", "area51-reachability", {"data_status": "partial", "au": {"total": 3}})
    _write_daily_observer(daily_dir, "2026-06-29", "area51-reachability", {"data_status": "ok", "au": {"total": 6}})

    export_dashboard.export_dashboard(latest_dir, dashboard_dir, daily_dir)

    history = json.loads((dashboard_dir / "history" / "internet-observers.json").read_text(encoding="utf-8"))
    area51 = history["observers"]["area51-reachability"]
    assert area51["display_name"] == "Area51 Reachability"
    assert area51["points"] == [
        {"date": "2026-06-27", "value": 1, "data_status": "ok"},
        {"date": "2026-06-28", "value": 3, "data_status": "partial"},
        {"date": "2026-06-29", "value": 6, "data_status": "ok"},
    ]
    assert area51["windows"]["7d"] == {"count": 3, "latest": 6, "previous": 3, "delta": 3, "min": 1, "max": 6, "avg": 3.33}
    assert area51["windows"]["90d"]["count"] == 3


def test_export_dashboard_internet_history_skips_invalid_and_missing_daily_files(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    daily_dir = tmp_path / "daily"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    _write_daily_observer(daily_dir, "2026-06-28", "area51-reachability", "{not json")
    _write_daily_observer(daily_dir, "2026-06-29", "area51-reachability", {"data_status": "ok", "bucket_count": 2})
    (daily_dir / "2026-06-30").mkdir(parents=True)

    export_dashboard.export_dashboard(latest_dir, dashboard_dir, daily_dir)

    history = json.loads((dashboard_dir / "history" / "internet-observers.json").read_text(encoding="utf-8"))
    assert history["observers"]["area51-reachability"]["points"] == [
        {"date": "2026-06-29", "value": 2, "data_status": "ok"}
    ]


def _write_heartbeat(heartbeat_dir: Path, name: str, payload: dict | str) -> None:
    heartbeat_dir.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (heartbeat_dir / name).write_text(text, encoding="utf-8")


def test_export_dashboard_writes_latest_heartbeat(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    heartbeat_dir = tmp_path / "heartbeat"
    latest_dir.mkdir()
    _write_heartbeat(
        heartbeat_dir,
        "2026-06-29T14Z.json",
        {"timestamp_utc": "2026-06-29T14:00:00Z", "status": "alive"},
    )
    _write_heartbeat(
        heartbeat_dir,
        "2026-06-29T15Z.json",
        {"timestamp_utc": "2026-06-29T15:00:00Z", "status": "alive"},
    )

    export_dashboard.export_dashboard(latest_dir, dashboard_dir, heartbeat_dir=heartbeat_dir)

    heartbeat = json.loads((dashboard_dir / "heartbeat.json").read_text(encoding="utf-8"))
    assert heartbeat["status"] == "alive"
    assert heartbeat["latest_heartbeat_utc"] == "2026-06-29T15:00:00Z"
    assert heartbeat["heartbeat_file"] == "2026-06-29T15Z.json"
    assert isinstance(heartbeat["generated_at"], str)


def test_export_dashboard_writes_unavailable_heartbeat_when_empty(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    heartbeat_dir = tmp_path / "heartbeat"
    latest_dir.mkdir()

    export_dashboard.export_dashboard(latest_dir, dashboard_dir, heartbeat_dir=heartbeat_dir)

    heartbeat = json.loads((dashboard_dir / "heartbeat.json").read_text(encoding="utf-8"))
    assert heartbeat["status"] == "unavailable"
    assert heartbeat["latest_heartbeat_utc"] is None
    assert heartbeat["heartbeat_file"] is None
    assert isinstance(heartbeat["generated_at"], str)
