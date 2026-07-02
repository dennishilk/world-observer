from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "observers" / "germany-electricity-prices" / "observer.py"
spec = importlib.util.spec_from_file_location("germany_electricity_prices_observer", MODULE_PATH)
electricity = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(electricity)


def test_static_ewe_tariff_is_ok_source(tmp_path):
    payload = electricity.build_payload("2026-07-02", root=tmp_path)

    assert payload["status"] == "ok"
    assert payload["data_status"] == "ok"
    assert payload["representative_household"]["postal_code"] == "26639"
    assert payload["current_price_eur_per_kwh"] == 0.2963
    assert payload["work_price_ct_per_kwh"] == 29.63
    assert payload["base_price_eur_per_year"] == 224.80
    assert payload["annual_cost_eur"] == 1261.85
    assert payload["monthly_cost_eur"] == 105.15
    assert payload["source"] == "static_tariff_observation"
    assert payload["source_type"] == "static_tariff_observation"
    assert payload["supplier"] == "EWE"
    assert payload["tariff"] == "Grundversorgung / EWE Strom comfort"
    assert payload["source_note"] == "manually configured documented tariff values"
    assert payload["diagnostics"]["api_attempts"] == 0
    assert payload["diagnostics"]["source_status"] == "static_tariff_loaded"
    assert "degraded_reason" not in payload


def test_imports_remain_supported_for_history(tmp_path):
    imports = tmp_path / "imports" / "germany-electricity-prices"
    imports.mkdir(parents=True)
    (imports / "history.csv").write_text(
        "date,price_eur_per_kwh,source,source_url,notes\n"
        "2026-07-01,0.30,local_csv,,documented import\n",
        encoding="utf-8",
    )

    payload = electricity.build_payload("2026-07-02", root=tmp_path)

    assert payload["current_price_eur_per_kwh"] == 0.2963
    assert {point["source"] for point in payload["history"]} == {"local_csv", "static_tariff_observation"}
    assert payload["import_diagnostics"] == [{"file": "history.csv", "status": "loaded", "accepted_rows": 1}]
