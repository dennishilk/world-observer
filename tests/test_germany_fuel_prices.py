from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "observers" / "germany-fuel-prices" / "observer.py"
spec = importlib.util.spec_from_file_location("germany_fuel_prices_observer", MODULE_PATH)
fuel = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(fuel)


def test_missing_import_degrades_cleanly(monkeypatch, tmp_path):
    monkeypatch.delenv("WORLD_OBSERVER_FUEL_API_KEY", raising=False)
    payload = fuel.build_payload("2026-06-30", {}, {"api_attempts": 0, "retries": 0, "http_status": None}, None, tmp_path)
    assert payload["status"] == "unavailable"
    assert payload["data_status"] == "unavailable"
    assert "No permitted fuel price import" in payload["degraded_reason"]
    assert payload["fuels"]["diesel"]["current_price"] is None


def test_imports_are_default_dashboard_source(tmp_path):
    imports = tmp_path / "imports" / "fuel-prices-germany"
    imports.mkdir(parents=True)
    (imports / "history.json").write_text('[{"date":"2026-06-29","fuel_type":"diesel","price_eur_per_liter":1.6,"source":"test","granularity":"daily"}]')
    payload = fuel.build_payload("2026-06-30", {}, {"api_attempts": 0}, root=tmp_path)
    assert payload["status"] == "ok"
    assert payload["data_status"] == "ok"
    assert payload["source"] == "imports/fuel-prices-germany"
    assert payload["fuels"]["diesel"]["current_price"] == 1.6
    assert payload["fuels"]["diesel"]["last_seen_date"] == "2026-06-30"


def test_successful_output_shape_and_neutral_changes(tmp_path):
    (tmp_path / "imports" / "fuel-prices-germany").mkdir(parents=True)
    (tmp_path / "imports" / "fuel-prices-germany" / "history.json").write_text('[{"date":"2026-06-29","fuel_type":"diesel","price_eur_per_liter":1.6,"source":"test","granularity":"daily"}]')
    payload = fuel.build_payload("2026-06-30", {"diesel": 1.7, "benzin": 1.8, "super_e10": 1.75}, {"api_attempts": 1}, root=tmp_path, source="Tankerkoenig/MTS-K API")
    assert "super_e10" not in payload["fuels"]
    diesel = payload["fuels"]["diesel"]
    for key in ("current_price", "average_30d", "average_365d", "record_low", "record_high", "trend_delta", "trend_delta_percent", "compared_with_365d_percent", "historical_min", "historical_max", "observed_changes", "last_seen_date", "status", "data_status"):
        assert key in diesel
    assert diesel["trend_delta"] == 0.1
    assert diesel["average_30d"] == 1.65
    assert diesel["record_low"] == 1.6
    assert diesel["record_high"] == 1.7
    assert "Price increased compared with the previous observation." in diesel["observed_changes"]
    forbidden = ("cause", "caused", "because", "politic", "manipulat")
    assert not any(term in " ".join(diesel["observed_changes"]).lower() for term in forbidden)


def test_malformed_import_duplicate_precedence_and_unsupported_ignored(tmp_path):
    imports = tmp_path / "imports" / "fuel-prices-germany"
    imports.mkdir(parents=True)
    (imports / "bad.json").write_text('{bad')
    (imports / "rows.csv").write_text("date,fuel_type,price_eur_per_liter,source,granularity\n2026-06-28,super_plus,1.9,test,daily\n2026-06-28,super_e10,1.8,test,daily\n2026-06-29,diesel,1.1,test,daily\n2026-06-27,diesel,1.5,test,daily\n")
    points, diagnostics = fuel.import_price_points(imports, {("2026-06-29", "diesel")})
    assert points == [{"date": "2026-06-27", "fuel_type": "diesel", "price": 1.5, "source": "test", "source_url": None, "granularity": "daily", "notes": None, "import_file": "rows.csv"}]
    reasons = " ".join(str(d.get("reason", "")) for d in diagnostics)
    assert "unsupported fuel_type" in reasons
    assert "duplicate date" in reasons
    assert any(d["file"] == "bad.json" and d["status"] == "ignored" for d in diagnostics)


def test_main_does_not_fetch_tankerkoenig_without_manual_opt_in(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WORLD_OBSERVER_FUEL_API_KEY", "dummy")
    monkeypatch.delenv("WORLD_OBSERVER_FUEL_ENABLE_TANKERKOENIG_API", raising=False)
    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", "2026-06-30")
    monkeypatch.setattr(fuel, "_repo_root", lambda: tmp_path)

    def fail_fetch(api_key):  # pragma: no cover - should never run
        raise AssertionError("Tankerkönig API should not be fetched without manual opt-in")

    monkeypatch.setattr(fuel, "_fetch_current_prices", fail_fetch)
    monkeypatch.setattr(fuel, "_fetch_public_average_prices", lambda: ({}, {"source": "public fuel average page", "fetch_url": "u", "fetched_at_utc": "t", "parse_status": "no_supported_prices", "fallback_used": True, "api_attempts": 1}, "public fuel average page page did not contain supported fuel prices"))
    fuel.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnostics"]["source"] == "public fuel average page"
    assert payload["diagnostics"]["tankerkoenig_automatic"] is False
    assert payload["status"] == "unavailable"
    assert "public fuel average page" in payload["degraded_reason"]


def test_swr_parser_extracts_supported_fuels_without_fake_values():
    text = (ROOT / "tests" / "fixtures" / "germany-fuel-prices" / "swr-average.txt").read_text(encoding="utf-8")
    assert fuel._parse_public_average_prices(text) == {"benzin": 1.95, "diesel": 1.78}


def test_ndr_parser_extracts_supported_fuels_without_fake_values():
    html = (ROOT / "tests" / "fixtures" / "germany-fuel-prices" / "ndr-average.html").read_text(encoding="utf-8")
    assert fuel._parse_public_average_prices(html) == {"benzin": 1.92, "diesel": 1.79}


def test_same_date_import_overrides_public_average_fetch(tmp_path):
    imports = tmp_path / "imports" / "fuel-prices-germany"
    imports.mkdir(parents=True)
    (imports / "history.json").write_text('[{"date":"2026-07-01","fuel_type":"diesel","price_eur_per_liter":1.6,"source":"local","granularity":"daily"}]')
    diagnostics = {"source": "public fuel average page", "fetch_url": "https://www.public_average.de/example", "fetched_at_utc": "2026-06-30T00:00:00Z", "parse_status": "ok", "fallback_used": False}
    payload = fuel.build_payload("2026-07-01", {"diesel": 1.7, "benzin": 1.8}, diagnostics, root=tmp_path, source="public fuel average page")
    assert payload["source"] == "imports/fuel-prices-germany"
    assert payload["fuels"]["diesel"]["current_price"] == 1.6
    assert payload["fuels"]["benzin"]["current_price"] == 1.8
    assert payload["diagnostics"]["fallback_used"] is True
    assert payload["diagnostics"]["local_import_override"] == ["diesel"]


def test_main_uses_public_average_not_tankerkoenig_without_manual_opt_in(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WORLD_OBSERVER_FUEL_API_KEY", "dummy")
    monkeypatch.delenv("WORLD_OBSERVER_FUEL_ENABLE_TANKERKOENIG_API", raising=False)
    monkeypatch.setenv("WORLD_OBSERVER_DATE_UTC", "2026-06-30")
    monkeypatch.setattr(fuel, "_repo_root", lambda: tmp_path)

    def fail_tankerkoenig(api_key):  # pragma: no cover - should never run
        raise AssertionError("Tankerkönig API should not be fetched without manual opt-in")

    monkeypatch.setattr(fuel, "_fetch_current_prices", fail_tankerkoenig)
    monkeypatch.setattr(fuel, "_fetch_public_average_prices", lambda: ({"diesel": 1.7}, {"source": "public fuel average page", "fetch_url": "u", "fetched_at_utc": "t", "parse_status": "ok", "fallback_used": False, "api_attempts": 1}, None))
    fuel.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnostics"]["source"] == "public fuel average page"
    assert payload["diagnostics"]["tankerkoenig_automatic"] is False
    assert payload["fuels"]["diesel"]["current_price"] == 1.7


def test_public_average_does_not_fetch_fallback_when_supported_fuels_present(monkeypatch):
    calls = []

    def fake_fetch(url, source_label):
        calls.append(source_label)
        return {"benzin": 1.92, "diesel": 1.79}, {"source": "www.ndr.de", "fetch_url": url, "fetched_at_utc": "t1", "parse_status": "ok", "api_attempts": 1, "http_status": 200}, None

    monkeypatch.setattr(fuel, "_fetch_public_average_url", fake_fetch)
    prices, diagnostics, reason = fuel._fetch_public_average_prices()
    assert reason is None
    assert prices == {"benzin": 1.92, "diesel": 1.79}
    assert calls == ["NDR public fuel average page"]
    assert diagnostics["primary_source"] == "www.ndr.de"
    assert diagnostics["fallback_used"] is False
    assert diagnostics["missing_fuels_after_primary"] == []
    assert diagnostics["priced_fuel_count"] == 2

def test_public_average_does_not_fetch_swr_when_ndr_has_all_fuels(monkeypatch):
    def fake_fetch(url, source_label):
        assert "NDR" in source_label
        return {"benzin": 1.92, "diesel": 1.79}, {"source": "www.ndr.de", "fetch_url": url, "fetched_at_utc": "t1", "parse_status": "ok", "api_attempts": 1, "http_status": 200}, None

    monkeypatch.setattr(fuel, "_fetch_public_average_url", fake_fetch)
    prices, diagnostics, reason = fuel._fetch_public_average_prices()
    assert reason is None
    assert prices == {"benzin": 1.92, "diesel": 1.79}
    assert diagnostics["fallback_used"] is False
    assert diagnostics["missing_fuels_after_primary"] == []
    assert diagnostics["priced_fuel_count"] == 2


def test_supported_fuels_available_keeps_observer_ok(tmp_path):
    diagnostics = {"source": "www.ndr.de", "primary_source": "www.ndr.de", "fallback_used": False, "missing_fuels_after_primary": [], "priced_fuel_count": 2}
    payload = fuel.build_payload("2026-07-01", {"benzin": 1.92, "diesel": 1.79, "super_e10": 1.86}, diagnostics, root=tmp_path, source="public fuel average page")
    assert payload["status"] == "ok"
    assert payload["data_status"] == "ok"
    assert "super_e10" not in payload["fuels"]
    assert payload["fuels"]["benzin"]["status"] == "ok"
    assert payload["fuels"]["diesel"]["status"] == "ok"
    assert payload["diagnostics"]["priced_fuel_count"] == 2
