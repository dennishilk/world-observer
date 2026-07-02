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


def test_does_not_guess_invalid_v7_archive_url_when_no_official_archive_or_patch(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_fetch(_url: str):
        return {"releases": [{"moniker": "stable", "version": "7.1.2"}]}

    def fake_head(url: str):
        calls.append(url)
        return 123, 200

    monkeypatch.setattr(lks, "fetch_json", fake_fetch)
    monkeypatch.setattr(lks, "head_content_length", fake_head)

    payload = lks.run("2026-07-02", root=tmp_path)

    assert payload["status"] == "unavailable"
    assert payload["source_url"] is None
    assert calls == []
    assert "https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.1.2.tar.xz" not in json.dumps(payload)
    assert payload["diagnostics"]["reason"] == "no kernel source archive URL available in release metadata"


def test_successful_content_length_extraction_from_valid_tarball_url(monkeypatch, tmp_path: Path) -> None:
    tarball_url = "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.16.1.tar.xz"

    def fake_fetch(_url: str):
        return {"releases": [{"moniker": "stable", "version": "6.16.1", "source": tarball_url}]}

    def fake_head(url: str):
        assert url == tarball_url
        return 145_500_000, 200

    monkeypatch.setattr(lks, "fetch_json", fake_fetch)
    monkeypatch.setattr(lks, "head_content_length", fake_head)

    payload = lks.run("2026-07-02", root=tmp_path)

    assert payload["status"] == "ok"
    assert payload["current_size_bytes"] == 145_500_000
    assert payload["current_size_mb"] == 145.5
    assert payload["source_url"] == tarball_url
    assert payload["diagnostics"]["tarball_url"] == tarball_url


def test_patch_url_candidates_try_fallback_after_404(monkeypatch, tmp_path: Path) -> None:
    patch_url = "https://cdn.kernel.org/pub/linux/kernel/v6.x/patch-6.16.1.xz"
    calls: list[str] = []

    def fake_fetch(_url: str):
        return {"releases": [{"moniker": "stable", "version": "6.16.1", "patch": patch_url}]}

    def fake_head(url: str):
        calls.append(url)
        if url.endswith(".tar.xz"):
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        return 144_000_000, 200

    monkeypatch.setattr(lks, "fetch_json", fake_fetch)
    monkeypatch.setattr(lks, "head_content_length", fake_head)

    payload = lks.run("2026-07-02", root=tmp_path)

    assert payload["status"] == "ok"
    assert payload["source_url"] == "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.16.1.tar.gz"
    assert calls[:2] == [
        "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.16.1.tar.xz",
        "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.16.1.tar.gz",
    ]


def test_selects_next_stable_release_when_first_stable_tarball_404(monkeypatch, tmp_path: Path) -> None:
    invalid_url = "https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.1.2.tar.xz"
    valid_url = "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.18.37.tar.xz"
    calls: list[str] = []

    def fake_fetch(_url: str):
        return {
            "releases": [
                {"moniker": "mainline", "version": "7.2-rc1", "source": "https://git.kernel.org/torvalds/t/linux-7.2-rc1.tar.gz"},
                {"moniker": "stable", "version": "7.1.2", "iseol": False, "source": invalid_url},
                {"moniker": "stable", "version": "6.18.37", "iseol": False, "source": valid_url, "released": {"isodate": "2026-06-27"}},
            ]
        }

    def fake_head(url: str):
        calls.append(url)
        if url == invalid_url:
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        assert url == valid_url
        return 151_000_000, 200

    monkeypatch.setattr(lks, "fetch_json", fake_fetch)
    monkeypatch.setattr(lks, "head_content_length", fake_head)

    payload = lks.run("2026-07-02", root=tmp_path)

    assert payload["status"] == "ok"
    assert payload["version"] == "6.18.37"
    assert payload["release_date"] == "2026-06-27"
    assert payload["source_url"] == valid_url
    assert calls == [invalid_url, valid_url]


def test_unavailable_output_does_not_publish_invalid_guessed_v7_source_url(monkeypatch, tmp_path: Path) -> None:
    invalid_url = "https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.1.2.tar.xz"

    def fake_fetch(_url: str):
        return {"releases": [{"moniker": "stable", "version": "7.1.2", "iseol": False, "source": invalid_url}]}

    def fake_head(url: str):
        assert url == invalid_url
        raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr(lks, "fetch_json", fake_fetch)
    monkeypatch.setattr(lks, "head_content_length", fake_head)

    payload = lks.run("2026-07-02", root=tmp_path)

    assert payload["status"] == "unavailable"
    assert payload["version"] is None
    assert payload["release_date"] is None
    assert payload["source_url"] is None
    assert invalid_url not in json.dumps({key: payload[key] for key in ("version", "release_date", "source_url")})
