from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from scripts import run_daily
from scripts import export_dashboard


def _load_observer(path: str):
    spec = importlib.util.spec_from_file_location(Path(path).parent.name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_asn_observer_internal_budget_returns_json_not_runner_timeout(tmp_path, monkeypatch) -> None:
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    monkeypatch.setattr(run_daily, "_repo_root", lambda: Path.cwd())
    monkeypatch.setenv("WORLD_OBSERVER_ASN_RUNTIME_BUDGET_S", "0")
    monkeypatch.setenv("WORLD_OBSERVER_OBSERVER_TIMEOUT_S", "120")

    ok, detail = run_daily._run_observer("asn-visibility-by-country", "2026-06-29", daily_dir)

    assert ok is True
    assert detail == "ok"
    payload = json.loads((daily_dir / "asn-visibility-by-country.json").read_text(encoding="utf-8"))
    assert payload["observer"] == "asn-visibility-by-country"
    assert payload["status"] == "partial"
    assert payload["data_status"] == "unavailable"
    assert payload["diagnostics"]["timeout"] is True
    assert payload["diagnostics"]["budget_exhausted"] is True
    assert isinstance(payload["diagnostics"]["duration_s"], (int, float))


def test_ipv6_locked_states_evaluated_with_zero_significant_is_valid(monkeypatch) -> None:
    module = _load_observer("observers/ipv6-locked-states/observer.py")
    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", "2026-06-29")
    for country, rate in {"CU": "0.0", "IR": "0.0", "KP": "0.0"}.items():
        monkeypatch.setenv(f"WORLD_OBSERVER_IPV6_LOCKED_STATES_MOCK_RATE_{country}", rate)

    payload = module.run()

    assert payload["data_status"] == "ok"
    assert payload["summary_stats"]["countries_evaluated"] == 3
    assert payload["summary_stats"]["significant_count"] == 0
    assert payload["significance"]["any_significant"] is False


def test_dashboard_export_uses_countries_evaluated_for_ipv6_and_excludes_planned_asn_cards(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    payloads = {
        "asn-visibility-by-country": {"observer": "asn-visibility-by-country", "data_status": "partial", "summary_stats": {"countries_evaluated": 4, "significant_count": 1}},
        "ipv6-global-compare": {"observer": "ipv6-global-compare", "data_status": "unavailable", "summary_stats": {"countries_evaluated": 0, "significant_count": 0}},
        "ipv6-locked-states": {"observer": "ipv6-locked-states", "data_status": "ok", "summary_stats": {"countries_evaluated": 3, "significant_count": 0}},
    }
    for observer, payload in payloads.items():
        (latest_dir / f"{observer}.json").write_text(json.dumps(payload), encoding="utf-8")

    export_dashboard.export_dashboard(latest_dir, dashboard_dir)
    internet = json.loads((dashboard_dir / "internet.json").read_text(encoding="utf-8"))
    cards = {card["observer"]: card for card in internet["observers"]}

    assert "asn-visibility-by-country" not in cards
    assert cards["ipv6-global-compare"]["primary_metric_name"] == "Countries evaluated"
    assert cards["ipv6-global-compare"]["primary_metric_value"] == 3
    assert cards["ipv6-locked-states"]["primary_metric_name"] == "Countries evaluated"
    assert cards["ipv6-locked-states"]["primary_metric_value"] == 3
    assert cards["ipv6-locked-states"]["secondary_metrics"]["Significant events"] == 0


def test_ipv6_global_compare_keeps_true_no_data_unavailable(tmp_path, monkeypatch) -> None:
    module = _load_observer("observers/ipv6-global-compare/observer.py")
    monkeypatch.setattr(module, "DAILY_ROOT", tmp_path / "daily")
    monkeypatch.setattr(module, "LATEST_DIR", tmp_path / "latest")
    monkeypatch.setattr(module, "LATEST_SUMMARY_PATH", tmp_path / "latest" / "summary.json")
    monkeypatch.setattr(module, "LATEST_CHART_PATH", tmp_path / "latest" / "chart.png")
    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", "2026-06-29")

    payload = module.run()

    assert payload["data_status"] == "unavailable"
    assert payload["summary_stats"]["countries_evaluated"] == 0
    assert payload["diagnostics"]["no_usable_input_data"] is True


def test_dashboard_export_normalizes_ipv6_global_evaluated_unavailable_to_partial(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    payload = {
        "observer": "ipv6-global-compare",
        "status": "unavailable",
        "data_status": "unavailable",
        "summary_stats": {"countries_evaluated": 3, "significant_count": 1},
    }
    (latest_dir / "ipv6-global-compare.json").write_text(json.dumps(payload), encoding="utf-8")

    export_dashboard.export_dashboard(latest_dir, dashboard_dir)
    internet = json.loads((dashboard_dir / "internet.json").read_text(encoding="utf-8"))
    card = next(card for card in internet["observers"] if card["observer"] == "ipv6-global-compare")

    assert card["status"] == "ok"
    assert card["data_status"] == "partial"
    assert card["primary_metric_name"] == "Countries evaluated"
    assert card["primary_metric_value"] == 3
    assert card["secondary_metrics"]["Significant events"] == 1


def test_dashboard_export_uses_ipv6_locked_count_for_empty_global_compare(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    payloads = {
        "ipv6-global-compare": {
            "observer": "ipv6-global-compare",
            "status": "unavailable",
            "data_status": "unavailable",
            "summary_stats": {"countries_evaluated": 0, "significant_count": 0},
        },
        "ipv6-locked-states": {
            "observer": "ipv6-locked-states",
            "data_status": "ok",
            "summary_stats": {"countries_evaluated": 3, "significant_count": 0},
        },
    }
    for observer, payload in payloads.items():
        (latest_dir / f"{observer}.json").write_text(json.dumps(payload), encoding="utf-8")

    export_dashboard.export_dashboard(latest_dir, dashboard_dir)
    internet = json.loads((dashboard_dir / "internet.json").read_text(encoding="utf-8"))
    card = next(card for card in internet["observers"] if card["observer"] == "ipv6-global-compare")

    assert card["status"] == "ok"
    assert card["data_status"] == "partial"
    assert card["primary_metric_name"] == "Countries evaluated"
    assert card["primary_metric_value"] == 3


def test_dashboard_export_normalizes_ipv6_locked_evaluated_unavailable_to_ok(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    payload = {
        "observer": "ipv6-locked-states",
        "status": "unavailable",
        "data_status": "unavailable",
        "summary_stats": {"countries_evaluated": 3, "significant_count": 0},
    }
    (latest_dir / "ipv6-locked-states.json").write_text(json.dumps(payload), encoding="utf-8")

    export_dashboard.export_dashboard(latest_dir, dashboard_dir)
    internet = json.loads((dashboard_dir / "internet.json").read_text(encoding="utf-8"))
    card = next(card for card in internet["observers"] if card["observer"] == "ipv6-locked-states")

    assert card["status"] == "ok"
    assert card["data_status"] == "ok"
    assert card["primary_metric_name"] == "Countries evaluated"
    assert card["primary_metric_value"] == 3
    assert card["secondary_metrics"]["Significant events"] == 0


def test_dashboard_export_asn_no_data_is_not_active_internet_card(tmp_path) -> None:
    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    latest_dir.mkdir()
    payload = {
        "observer": "asn-visibility-by-country",
        "status": "unavailable",
        "data_status": "unavailable",
        "summary_stats": {"countries_evaluated": 0, "significant_count": 0},
    }
    (latest_dir / "asn-visibility-by-country.json").write_text(json.dumps(payload), encoding="utf-8")

    export_dashboard.export_dashboard(latest_dir, dashboard_dir)
    internet = json.loads((dashboard_dir / "internet.json").read_text(encoding="utf-8"))

    assert all(card["observer"] != "asn-visibility-by-country" for card in internet["observers"])
