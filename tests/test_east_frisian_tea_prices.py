import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "observers" / "east-frisian-tea-prices" / "observer.py"
spec = importlib.util.spec_from_file_location("east_frisian_tea_prices", MODULE_PATH)
tea = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(tea)

HTML = '''
<html><head>
<meta property="product:price:amount" content="9,99">
<meta property="product:price:currency" content="EUR">
<meta property="product:availability" content="instock">
<meta property="product:ean" content="4008837201054">
<meta property="product:category" content="Ostfriesentee">
<meta property="product:brand" content="Bünting Tee">
</head></html>
'''


def test_parses_combi_product_meta_tags() -> None:
    observation, diagnostics = tea.parse_product_meta(HTML)
    assert observation == {"price": 9.99, "currency": "EUR", "ean": "4008837201054", "availability": "instock"}
    assert diagnostics["brand"] == "Bünting Tee"
    assert diagnostics["availability"] == "instock"


def test_german_decimal_comma_price_parsing() -> None:
    assert tea.parse_german_decimal("9,99") == 9.99
    assert tea.parse_german_decimal("1.234,56") == 1234.56


def test_ean_validation() -> None:
    observation, diagnostics = tea.parse_product_meta(HTML.replace("4008837201054", "123"))
    assert observation is None
    assert any("EAN validation failed" in error for error in diagnostics["validation_errors"])


def test_eur_currency_validation() -> None:
    observation, diagnostics = tea.parse_product_meta(HTML.replace('content="EUR"', 'content="USD"'))
    assert observation is None
    assert any("currency validation failed" in error for error in diagnostics["validation_errors"])


def test_manual_seed_and_current_price_produces_trend_delta(tmp_path) -> None:
    payload = tea.build_payload(
        "2026-07-01",
        {"price": 9.99, "currency": "EUR", "ean": "4008837201054", "availability": "instock"},
        {"parse_status": "parsed_meta_tags"},
        root=tmp_path,
    )
    assert payload["trend_delta"] == 0.01
    assert payload["history"] == [
        {"date": "2026-06-30", "value": 9.98, "source": "manual_seed", "seed_note": tea.MANUAL_SEED["seed_note"]},
        {"date": "2026-07-01", "value": 9.99, "source": "combi_product_meta"},
    ]


def test_history_export_appears_in_dashboard_society_json(tmp_path) -> None:
    from scripts import export_dashboard

    latest_dir = tmp_path / "latest"
    dashboard_dir = tmp_path / "dashboard"
    state_dir = tmp_path / "state"
    latest_dir.mkdir()
    for observer in export_dashboard.OBSERVERS:
        payload = {"observer": observer, "data_status": "ok", "date": "2026-07-01"}
        if observer == export_dashboard.TEA_OBSERVER:
            payload = tea.build_payload(
                "2026-07-01",
                {"price": 9.99, "currency": "EUR", "ean": "4008837201054", "availability": "instock"},
                {"parse_status": "parsed_meta_tags"},
                root=tmp_path,
            )
        (latest_dir / f"{observer}.json").write_text(json.dumps(payload), encoding="utf-8")

    export_dashboard.export_dashboard(latest_dir, dashboard_dir, state_dir=state_dir)
    society = json.loads((dashboard_dir / "society.json").read_text(encoding="utf-8"))
    exported = next(observer for observer in society["observers"] if observer["observer"] == export_dashboard.TEA_OBSERVER)
    assert exported["history"] == [
        {"date": "2026-06-30", "value": 9.98, "source": "manual_seed", "seed_note": tea.MANUAL_SEED["seed_note"]},
        {"date": "2026-07-01", "value": 9.99, "source": "combi_product_meta"},
    ]
