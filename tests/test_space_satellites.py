from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODULE_PATH = ROOT / "observers" / "space-satellites" / "observer.py"
spec = importlib.util.spec_from_file_location("space_satellites", MODULE_PATH)
space = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(space)

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def rows(prefix: str, count: int, *, inclination: float = 53.0) -> list[dict[str, str]]:
    return [
        {
            "OBJECT_NAME": f"{prefix}-{index}",
            "NORAD_CAT_ID": str(100000 + index),
            "EPOCH": f"2026-08-15T{8 + index:02d}:00:00.000000",
            "INCLINATION": str(inclination + index),
        }
        for index in range(count)
    ]


def fake_fetcher(query_group: str):
    counts = {
        "STATIONS": 2,
        "STARLINK": 3,
        "ONEWEB": 2,
        "GPS-OPS": 2,
        "GALILEO": 2,
        "CUBESAT": 2,
    }
    payload = rows(query_group, counts[query_group])
    return payload, {
        "url": space._group_url(query_group),
        "http_status": 200,
        "bytes": 100 + counts[query_group],
        "record_count": counts[query_group],
    }


def test_group_url_uses_documented_csv_gp_query() -> None:
    assert space._group_url("GPS-OPS") == (
        "https://celestrak.org/NORAD/elements/gp.php?GROUP=GPS-OPS&FORMAT=CSV"
    )


def test_group_summary_is_per_group_and_epoch_based() -> None:
    summary = space.summarize_group(rows("TEST", 3, inclination=50.0), NOW)
    assert summary["record_count"] == 3
    assert summary["unique_catalog_ids"] == 3
    assert summary["epoch_count"] == 3
    assert summary["oldest_epoch_utc"] == "2026-08-15T08:00:00Z"
    assert summary["newest_epoch_utc"] == "2026-08-15T10:00:00Z"
    assert summary["median_epoch_age_hours"] == 3.0
    assert summary["mean_inclination_deg"] == 51.0


def test_success_payload_keeps_groups_separate_and_never_invents_global_total(tmp_path: Path) -> None:
    payload = space.build_payload(
        "2026-08-15",
        root=tmp_path,
        fetcher=fake_fetcher,
        collected_at=NOW,
    )

    assert payload["observer"] == "space-satellites"
    assert payload["category"] == "technology"
    assert payload["status"] == "ok"
    assert payload["data_status"] == "ok"
    assert payload["summary"]["groups_requested"] == 6
    assert payload["summary"]["groups_available"] == 6
    assert payload["summary"]["groups_may_overlap"] is True
    assert payload["summary"]["global_satellite_total_calculated"] is False
    assert payload["groups"]["starlink"]["record_count"] == 3
    assert payload["groups"]["oneweb"]["record_count"] == 2
    assert payload["groups"]["gps_ops"]["query_group"] == "GPS-OPS"
    assert payload["groups"]["cubesat"]["unique_catalog_ids"] == 2
    assert "total_satellites" not in json.dumps(payload)
    assert "satellite_total" not in json.dumps(payload)
    assert payload["methodology"]["no_global_total_from_group_sums"] is True
    assert payload["diagnostics"]["api_attempts"] == 6
    assert payload["diagnostics"]["retries"] == 0


def test_collection_stops_after_first_source_error(tmp_path: Path) -> None:
    calls: list[str] = []

    def failing_fetcher(query_group: str):
        calls.append(query_group)
        if query_group == "STARLINK":
            raise space.SourceFetchError(
                "CelesTrak returned HTTP 403",
                url=space._group_url(query_group),
                http_status=403,
            )
        return fake_fetcher(query_group)

    payload = space.build_payload(
        "2026-08-15",
        root=tmp_path,
        fetcher=failing_fetcher,
        collected_at=NOW,
    )

    assert calls == ["STATIONS", "STARLINK"]
    assert payload["status"] == "partial"
    assert payload["groups"]["stations"]["status"] == "ok"
    assert payload["groups"]["starlink"]["status"] == "unavailable"
    assert payload["groups"]["oneweb"]["status"] == "not_attempted"
    assert payload["groups"]["cubesat"]["status"] == "not_attempted"
    assert payload["diagnostics"]["api_attempts"] == 2
    assert payload["diagnostics"]["http_status"] == 403
    assert payload["methodology"]["stop_after_first_source_error"] is True


def test_run_persists_state_latest_and_dashboard_snapshot_without_network(tmp_path: Path) -> None:
    payload = space.run(
        "2026-08-15",
        root=tmp_path,
        fetcher=fake_fetcher,
        collected_at=NOW,
    )

    state_path = tmp_path / "state" / space.OBSERVER / "2026-08-15.json"
    latest_path = tmp_path / "data" / "latest" / f"{space.OBSERVER}.json"
    dashboard_path = tmp_path / "dashboard" / "latest" / f"{space.OBSERVER}.json"
    assert state_path.exists()
    assert latest_path.exists()
    assert dashboard_path.exists()
    assert json.loads(state_path.read_text(encoding="utf-8"))["groups"]["starlink"]["record_count"] == 3
    assert json.loads(latest_path.read_text(encoding="utf-8"))["summary"]["groups_available"] == 6
    assert json.loads(dashboard_path.read_text(encoding="utf-8"))["source"]["provider"] == "CelesTrak"
    assert payload["history"][-1]["starlink_records"] == 3


def test_second_run_same_utc_day_uses_cache_and_makes_zero_source_requests(tmp_path: Path) -> None:
    first = space.run(
        "2026-08-15",
        root=tmp_path,
        fetcher=fake_fetcher,
        collected_at=NOW,
    )
    calls: list[str] = []

    def must_not_fetch(query_group: str):
        calls.append(query_group)
        raise AssertionError("same-day cached observer must not call CelesTrak")

    second = space.run(
        "2026-08-15",
        root=tmp_path,
        fetcher=must_not_fetch,
        collected_at=NOW,
    )
    assert calls == []
    assert second == first
    assert (tmp_path / "dashboard" / "latest" / f"{space.OBSERVER}.json").exists()


def test_failed_day_is_cached_instead_of_automatically_retrying_source(tmp_path: Path) -> None:
    calls: list[str] = []

    def fail_first(query_group: str):
        calls.append(query_group)
        raise space.SourceFetchError(
            "CelesTrak returned HTTP 503",
            url=space._group_url(query_group),
            http_status=503,
        )

    first = space.run("2026-08-15", root=tmp_path, fetcher=fail_first, collected_at=NOW)
    assert first["status"] == "unavailable"
    assert calls == ["STATIONS"]

    def must_not_retry(_query_group: str):
        raise AssertionError("source errors are cached for the UTC day")

    second = space.run("2026-08-15", root=tmp_path, fetcher=must_not_retry, collected_at=NOW)
    assert second == first


def test_history_uses_published_daily_group_counts_without_summing(tmp_path: Path) -> None:
    state_dir = tmp_path / "state" / space.OBSERVER
    state_dir.mkdir(parents=True)
    (state_dir / "2026-08-14.json").write_text(
        json.dumps(
            {
                "date": "2026-08-14",
                "groups": {
                    "starlink": {"record_count": 2},
                    "oneweb": {"record_count": 1},
                    "stations": {"record_count": 4},
                },
            }
        ),
        encoding="utf-8",
    )

    payload = space.build_payload(
        "2026-08-15",
        root=tmp_path,
        fetcher=fake_fetcher,
        collected_at=NOW,
    )
    assert payload["history"][0] == {
        "date": "2026-08-14",
        "stations_records": 4,
        "starlink_records": 2,
        "oneweb_records": 1,
    }
    assert payload["history"][-1]["date"] == "2026-08-15"
    assert "total" not in payload["history"][-1]


def test_selected_groups_are_small_explicit_observation_surfaces() -> None:
    assert [group["query"] for group in space.GROUPS] == [
        "STATIONS",
        "STARLINK",
        "ONEWEB",
        "GPS-OPS",
        "GALILEO",
        "CUBESAT",
    ]
    assert "ACTIVE" not in [group["query"] for group in space.GROUPS]
    assert space.MAX_RESPONSE_BYTES <= 20_000_000
