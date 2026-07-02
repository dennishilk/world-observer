from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODULE_PATH = ROOT / "observers" / "linux-kernel-size" / "observer.py"
spec = importlib.util.spec_from_file_location("linux_kernel_size", MODULE_PATH)
lks = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(lks)


def test_latest_stable_release_selects_highest_stable_version() -> None:
    payload = {
        "releases": [
            {"moniker": "longterm", "version": "6.12.1"},
            {"moniker": "stable", "version": "6.15.4", "source": "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.15.4.tar.xz"},
            {"moniker": "stable", "version": "6.16.1", "source": "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.16.1.tar.xz"},
        ]
    }
    assert lks.latest_stable_release(payload)["version"] == "6.16.1"


def test_successful_output_contains_dashboard_fields(tmp_path: Path) -> None:
    prior_dir = tmp_path / "state" / lks.OBSERVER
    prior_dir.mkdir(parents=True)
    (prior_dir / "2026-07-01.json").write_text(json.dumps({"current_size_mb": 140.0, "version": "6.15.4"}), encoding="utf-8")

    payload = lks.build_payload(
        "2026-07-02",
        {"moniker": "stable", "version": "6.16.1", "source": "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.16.1.tar.xz", "released": {"timestamp": "2026-07-01T00:00:00+00:00"}},
        145_500_000,
        {"api_attempts": 1, "retries": 0, "http_status": 200},
        root=tmp_path,
    )
    assert payload["observer"] == "linux-kernel-size"
    assert payload["category"] == "technology"
    assert payload["status"] == "ok"
    assert payload["current_size_mb"] == 145.5
    assert payload["current_size_bytes"] == 145_500_000
    assert payload["version"] == "6.16.1"
    assert payload["release_date"] == "2026-07-01T00:00:00+00:00"
    assert payload["average_30d"] == 142.75
    assert payload["historical_min"] == 140.0
    assert payload["historical_max"] == 145.5
    assert payload["trend_delta"] == 5.5
    assert payload["trend_delta_percent"] == 3.93
    assert payload["history"][-1]["value"] == 145.5


def test_unavailable_when_kernel_org_cannot_be_reached(monkeypatch, tmp_path: Path) -> None:
    def fail_fetch(_url: str):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(lks, "fetch_json", fail_fetch)
    payload = lks.run("2026-07-02", root=tmp_path)
    assert payload["status"] == "unavailable"
    assert payload["data_status"] == "unavailable"
    assert payload["current_size_mb"] is None
    assert "kernel.org fetch failed" in payload["diagnostics"]["reason"]
    assert (tmp_path / "state" / lks.OBSERVER / "2026-07-02.json").exists()
    assert (tmp_path / "data" / "latest" / f"{lks.OBSERVER}.json").exists()


def test_technology_dashboard_export(tmp_path: Path) -> None:
    from scripts import export_dashboard

    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    state_dir = tmp_path / "state"
    latest_dir.mkdir()
    for observer in export_dashboard.OBSERVERS:
        payload = {"observer": observer, "data_status": "ok", "date": "2026-07-02"}
        if observer == lks.OBSERVER:
            payload = lks.build_payload("2026-07-02", {"moniker": "stable", "version": "6.16.1"}, 145_500_000, {}, root=tmp_path)
        (latest_dir / f"{observer}.json").write_text(json.dumps(payload), encoding="utf-8")

    export_dashboard.export_dashboard(latest_dir, dashboard_dir, state_dir=state_dir)
    technology = json.loads((dashboard_dir / "technology.json").read_text(encoding="utf-8"))
    exported = next(observer for observer in technology["observers"] if observer["observer"] == lks.OBSERVER)
    assert exported["category"] == "technology"
    assert exported["primary_metric_value"] == 145.5
    assert exported["primary_metric_unit"] == "MB"
