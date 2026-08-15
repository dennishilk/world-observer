from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "scripts" / "heartbeat_and_publish_website.sh"


def test_hourly_publisher_runs_cached_space_observer_before_dashboard_export() -> None:
    script = PUBLISHER.read_text(encoding="utf-8")
    space_call = 'observers/space-satellites/observer.py'
    export_call = 'scripts/export_dashboard.py'
    publish_call = 'scripts/publish_dashboard_to_pages.py'

    assert space_call in script
    assert 'WORLD_OBSERVER_DATE_UTC="$snapshot_date"' in script
    assert script.index(space_call) < script.index(export_call) < script.index(publish_call)
    assert "cached space-satellites observer" in script
