from __future__ import annotations

import gzip
import importlib.util
import io
import json
import sys
import tarfile
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODULE_PATH = ROOT / "observers" / "arch-package-count" / "observer.py"
spec = importlib.util.spec_from_file_location("arch_package_count", MODULE_PATH)
apc = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(apc)


def _db(package_names: list[str]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for name in package_names:
            content = f"%NAME%\n{name}\n".encode()
            info = tarfile.TarInfo(f"{name}-1.0-1/desc")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return gzip.compress(raw.getvalue())


def test_package_count_parsing_and_payload(tmp_path: Path) -> None:
    prior_dir = tmp_path / "state" / apc.OBSERVER
    prior_dir.mkdir(parents=True)
    (prior_dir / "2026-07-01.json").write_text(json.dumps({"current_package_count": 3}), encoding="utf-8")

    assert apc.parse_repository_package_count(_db(["alpha", "beta"])) == 2

    payload = apc.build_payload(
        "2026-07-02",
        5,
        {"core": 2, "extra": 3},
        {"api_attempts": 2, "parse_status": "ok"},
        root=tmp_path,
    )
    assert payload["observer"] == "arch-package-count"
    assert payload["category"] == "technology"
    assert payload["status"] == "ok"
    assert payload["data_status"] == "ok"
    assert payload["current_package_count"] == 5
    assert payload["unit"] == "packages"
    assert payload["repositories"] == ["core", "extra"]
    assert payload["repository_counts"] == {"core": 2, "extra": 3}
    assert payload["architecture"] == "x86_64"
    assert payload["source_url"]["core"].endswith("/core/os/x86_64/core.db")
    assert payload["averages"]["30d"] == 4.0
    assert payload["average_365d"] == 4.0
    assert payload["historical_min"] == 3
    assert payload["historical_max"] == 5
    assert payload["trend_delta"] == 2
    assert payload["trend_delta_percent"] == 66.67
    assert payload["trend_direction"] == "up"
    assert payload["observed_changes"] == [{"metric": "current_package_count", "delta": 2, "unit": "packages"}]


def test_unavailable_fallback_when_arch_source_unreachable(monkeypatch, tmp_path: Path) -> None:
    def fail_fetch(_url: str) -> bytes:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(apc, "fetch_repository_database", fail_fetch)
    payload = apc.run("2026-07-02", root=tmp_path)
    assert payload["status"] == "unavailable"
    assert payload["data_status"] == "unavailable"
    assert payload["current_package_count"] is None
    assert payload["repository_counts"] == {}
    assert "Arch repository database fetch/parse failed" in payload["diagnostics"]["reason"]
    assert (tmp_path / "state" / apc.OBSERVER / "2026-07-02.json").exists()
    assert (tmp_path / "data" / "latest" / f"{apc.OBSERVER}.json").exists()


def test_technology_dashboard_export_includes_arch_package_count(tmp_path: Path) -> None:
    from scripts import export_dashboard

    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    state_dir = tmp_path / "state"
    latest_dir.mkdir()
    for observer in export_dashboard.OBSERVERS:
        payload = {"observer": observer, "data_status": "ok", "date": "2026-07-02"}
        if observer == apc.OBSERVER:
            payload = apc.build_payload("2026-07-02", 15000, {"core": 300, "extra": 14700}, {"api_attempts": 2}, root=tmp_path)
        (latest_dir / f"{observer}.json").write_text(json.dumps(payload), encoding="utf-8")

    export_dashboard.export_dashboard(latest_dir, dashboard_dir, state_dir=state_dir)
    technology = json.loads((dashboard_dir / "technology.json").read_text(encoding="utf-8"))
    exported = next(observer for observer in technology["observers"] if observer["observer"] == apc.OBSERVER)
    assert exported["category"] == "technology"
    assert exported["primary_metric_value"] == 15000
    assert exported["primary_metric_unit"] == "packages"
    assert exported["primary_metric_name"] == "Arch Linux packages"
