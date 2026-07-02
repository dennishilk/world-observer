from __future__ import annotations

import importlib.util
import json
import lzma
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODULE_PATH = ROOT / "observers" / "debian-package-count" / "observer.py"
spec = importlib.util.spec_from_file_location("debian_package_count", MODULE_PATH)
dpc = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(dpc)


def test_successful_package_index_parsing_and_payload(tmp_path: Path) -> None:
    prior_dir = tmp_path / "state" / dpc.OBSERVER
    prior_dir.mkdir(parents=True)
    (prior_dir / "2026-07-01.json").write_text(json.dumps({"current_package_count": 2}), encoding="utf-8")

    package_index = lzma.compress(b"Package: alpha\nVersion: 1\n\nPackage: beta\nVersion: 2\n")
    assert dpc.parse_package_count(package_index) == 2

    payload = dpc.build_payload("2026-07-02", 3, {"api_attempts": 1, "parse_status": "ok"}, root=tmp_path)
    assert payload["observer"] == "debian-package-count"
    assert payload["category"] == "technology"
    assert payload["status"] == "ok"
    assert payload["data_status"] == "ok"
    assert payload["current_package_count"] == 3
    assert payload["unit"] == "packages"
    assert payload["suite"] == "stable"
    assert payload["architecture"] == "amd64"
    assert payload["component"] == "main"
    assert payload["source_url"].endswith("/dists/stable/main/binary-amd64/Packages.xz")
    assert payload["average_30d"] == 2.5
    assert payload["average_365d"] == 2.5
    assert payload["historical_min"] == 2
    assert payload["historical_max"] == 3
    assert payload["trend_delta"] == 1
    assert payload["trend_delta_percent"] == 50.0
    assert payload["observed_changes"] == [{"metric": "current_package_count", "delta": 1, "unit": "packages"}]


def test_unavailable_fallback_when_debian_source_unreachable(monkeypatch, tmp_path: Path) -> None:
    def fail_fetch(_url: str) -> bytes:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(dpc, "fetch_package_index", fail_fetch)
    payload = dpc.run("2026-07-02", root=tmp_path)
    assert payload["status"] == "unavailable"
    assert payload["data_status"] == "unavailable"
    assert payload["current_package_count"] is None
    assert "Debian Packages index fetch/parse failed" in payload["diagnostics"]["reason"]
    assert (tmp_path / "state" / dpc.OBSERVER / "2026-07-02.json").exists()
    assert (tmp_path / "data" / "latest" / f"{dpc.OBSERVER}.json").exists()


def test_dashboard_technology_export_includes_debian_package_count(tmp_path: Path) -> None:
    from scripts import export_dashboard

    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    state_dir = tmp_path / "state"
    latest_dir.mkdir()
    for observer in export_dashboard.OBSERVERS:
        payload = {"observer": observer, "data_status": "ok", "date": "2026-07-02"}
        if observer == dpc.OBSERVER:
            payload = dpc.build_payload("2026-07-02", 73000, {"api_attempts": 1, "parse_status": "ok"}, root=tmp_path)
        (latest_dir / f"{observer}.json").write_text(json.dumps(payload), encoding="utf-8")

    export_dashboard.export_dashboard(latest_dir, dashboard_dir, state_dir=state_dir)
    technology = json.loads((dashboard_dir / "technology.json").read_text(encoding="utf-8"))
    exported = next(observer for observer in technology["observers"] if observer["observer"] == dpc.OBSERVER)
    assert exported["category"] == "technology"
    assert exported["primary_metric_value"] == 73000
    assert exported["primary_metric_unit"] == "packages"
    assert exported["primary_metric_name"] == "Debian packages"
