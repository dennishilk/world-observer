from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "scripts" / "heartbeat_and_publish_website.sh"


def test_hourly_publisher_runs_space_observer_before_dashboard_export() -> None:
    script = PUBLISHER.read_text(encoding="utf-8")
    space_call = 'observers/space-satellites/observer.py'
    export_call = 'scripts/export_dashboard.py'
    publish_call = 'scripts/publish_dashboard_to_pages.py'

    assert space_call in script
    assert 'WORLD_OBSERVER_DATE_UTC="$snapshot_date"' in script
    assert script.index(space_call) < script.index(export_call) < script.index(publish_call)
    assert "cached space-satellites observer" in script


def test_failed_space_cache_expires_only_after_two_hour_cooldown() -> None:
    script = PUBLISHER.read_text(encoding="utf-8")

    assert "RETRY_COOLDOWN_SECONDS = 2 * 60 * 60" in script
    assert "age_seconds >= RETRY_COOLDOWN_SECONDS" in script
    assert "path.unlink()" in script
    assert "There are still no immediate retries" in script


def test_failed_space_collection_restores_last_success_before_export() -> None:
    script = PUBLISHER.read_text(encoding="utf-8")

    recovery_log = "preserving last successful space-satellites snapshot when needed"
    export_log = "running export_dashboard.py"
    assert recovery_log in script
    assert "payload.get(\"status\") == \"ok\"" in script
    assert 'root / "data" / "latest" / "space-satellites.json"' in script
    assert 'root / "dashboard" / "latest" / "space-satellites.json"' in script
    assert "restored last successful snapshot" in script
    assert script.index(recovery_log) < script.index(export_log)
