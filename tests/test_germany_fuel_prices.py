from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "observers" / "germany-fuel-prices" / "observer.py"
spec = importlib.util.spec_from_file_location("germany_fuel_prices_observer", MODULE_PATH)
fuel = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(fuel)


def test_missing_api_key_degrades_cleanly(monkeypatch, tmp_path):
    monkeypatch.delenv("WORLD_OBSERVER_FUEL_API_KEY", raising=False)
    payload = fuel.build_payload("2026-06-30", {}, {"api_attempts": 0, "retries": 0, "http_status": None}, "WORLD_OBSERVER_FUEL_API_KEY is not configured", tmp_path)
    assert payload["status"] == "unavailable"
    assert payload["data_status"] == "unavailable"
    assert "WORLD_OBSERVER_FUEL_API_KEY" in payload["degraded_reason"]
    assert payload["fuels"]["diesel"]["current_price"] is None


def test_successful_output_shape_and_neutral_changes(tmp_path):
    (tmp_path / "imports" / "fuel-prices-germany").mkdir(parents=True)
    (tmp_path / "imports" / "fuel-prices-germany" / "history.json").write_text('[{"date":"2026-06-29","fuel_type":"diesel","price_eur_per_liter":1.6,"source":"test","granularity":"daily"}]')
    payload = fuel.build_payload("2026-06-30", {"diesel": 1.7, "benzin": 1.8, "super_e10": 1.75}, {"api_attempts": 1}, root=tmp_path)
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
    (imports / "rows.csv").write_text("date,fuel_type,price_eur_per_liter,source,granularity\n2026-06-28,super_plus,1.9,test,daily\n2026-06-29,diesel,1.1,test,daily\n2026-06-27,diesel,1.5,test,daily\n")
    points, diagnostics = fuel.import_price_points(imports, {("2026-06-29", "diesel")})
    assert points == [{"date": "2026-06-27", "fuel_type": "diesel", "price": 1.5, "source": "test", "source_url": None, "granularity": "daily", "notes": None, "import_file": "rows.csv"}]
    reasons = " ".join(str(d.get("reason", "")) for d in diagnostics)
    assert "unsupported fuel_type" in reasons
    assert "duplicate date" in reasons
    assert any(d["file"] == "bad.json" and d["status"] == "ignored" for d in diagnostics)
