from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_observer(slug: str) -> ModuleType:
    path = ROOT / "observers" / slug / "observer.py"
    spec = importlib.util.spec_from_file_location(slug.replace("-", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_population_uses_official_snapshots_and_suppresses_basis_break_delta() -> None:
    observer = load_observer("wiesmoor-population")
    payload = observer.build_payload()

    assert payload["latest_official_observation"]["reference_date"] == "2024-12-31"
    assert payload["latest_official_observation"]["population"] == 13875
    assert payload["latest_official_observation"]["census_basis"] == "Zensus 2022"
    assert payload["year_on_year"]["latest_interval_status"] == "not_comparable_due_to_census_basis_change"
    assert payload["year_on_year"]["latest_comparable_change"] == {
        "status": "comparable",
        "from_reference_date": "2022-12-31",
        "to_reference_date": "2023-12-31",
        "absolute_change": 108,
        "percent_change": 0.8,
        "census_basis": "Zensus 2011",
    }
    assert all(item["source_url"].startswith("https://www.destatis.de/") for item in payload["history"])


def test_finance_keeps_actual_plan_and_forecast_explicit_and_reconciled() -> None:
    observer = load_observer("wiesmoor-finance")
    payload = observer.build_payload()
    periods = {item["fiscal_year"]: item for item in payload["reporting_periods"]}

    assert periods[2024]["value_status"] == "ACTUAL"
    assert periods[2025]["value_status"] == "PLAN"
    assert periods[2026]["value_status"] == "PLAN"
    assert periods[2027]["value_status"] == "FORECAST"
    assert periods[2029]["result_budget_eur"]["overall_result"] == -796400
    assert payload["latest_budget_plan"]["liquidity_credit_ceiling"] == 14500000
    assert payload["diagnostics"]["reconciliation_checks"] == "passed"


def test_energy_aggregates_in_memory_and_publishes_no_unit_level_fields() -> None:
    observer = load_observer("wiesmoor-energy")
    rows = [
        {
            "Ort": "Wiesmoor",
            "Plz": "26639",
            "EnergietraegerName": "Solare Strahlungsenergie",
            "BetriebsStatusName": "In Betrieb",
            "Bruttoleistung": 12.5,
            "Nettonennleistung": 10,
            "InbetriebnahmeDatum": "/Date(1577836800000)/",
            "EinheitMastrNummer": "must-not-escape",
            "NameStromerzeugungseinheit": "must-not-escape",
            "Strasse": "must-not-escape",
            "Anlagenbetreiber": "must-not-escape",
        },
        {
            "Ort": "Wiesmoor",
            "Plz": "26639",
            "EnergietraegerName": "Solare Strahlungsenergie",
            "BetriebsStatusName": "In Planung",
            "Bruttoleistung": 20,
            "Nettonennleistung": 18,
            "InbetriebnahmeDatum": "/Date(1893456000000)/",
        },
        {
            "Ort": "Wiesmoor",
            "Plz": "26639",
            "EnergietraegerName": "Wind",
            "BetriebsStatusName": "In Betrieb",
            "Bruttoleistung": 1000,
            "Nettonennleistung": 1000,
            "InbetriebnahmeDatum": "/Date(1609459200000)/",
        },
        {
            "Ort": "Wiesmoor",
            "Plz": "99999",
            "EnergietraegerName": "Wind",
            "BetriebsStatusName": "In Betrieb",
            "Bruttoleistung": 9000,
            "Nettonennleistung": 9000,
        },
    ]

    def fake_fetch(page: int, page_size: int):
        assert page == 1
        assert page_size == observer.PAGE_SIZE
        return {"Data": rows, "Total": len(rows)}, {"api_attempts": 1, "retries": 0, "http_status": 200}

    payload = observer.build_payload(fake_fetch)
    assert payload["status"] == "ok"
    assert payload["totals"]["listed_units"] == 3
    assert payload["totals"]["operational_units"] == 2
    assert payload["totals"]["installed_net_nominal_capacity_kw_operational"] == 1010
    assert payload["privacy"]["unit_records_published"] is False
    encoded = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("must-not-escape", "EinheitMastrNummer", "NameStromerzeugungseinheit", "Strasse", "Anlagenbetreiber"):
        assert forbidden not in encoded
    assert "production" in " ".join(payload["do_not_interpret_as"])


def test_groundwater_excludes_sentinels_and_labels_regional_proxy() -> None:
    observer = load_observer("wiesmoor-groundwater")
    stations_payload = {
        "getStammdatenResult": [
            {
                "STA_ID": 14773010,
                "STA_Nummer": 9850631,
                "Name": "Remels",
                "Ort": "Remels",
                "WGS84Rechtswert": 53.3087128516657,
                "WGS84Hochwert": 7.73958335239652,
            }
        ]
    }
    series_payload = {
        "getPegelDatenspurenResult": {
            "Name": "Remels",
            "Ort": "Remels",
            "Betreiber": "NLWKN Aurich",
            "Landkreis": "Leer",
            "Hydrogeologischer_Teilraum": "Oldenburgisch-Ostfriesische Geest",
            "MS_GOK_mNHN": 8.61,
            "Parameter": [{
                "Datenspuren": [{
                    "Pegelstaende": [
                        {"DatumUTC": "/Date(1786492800000)/", "Wert": -777, "Grundwasserstandsklasse": "-"},
                        {"DatumUTC": "/Date(1786320000000)/", "Wert": 4.43, "Grundwasserstandsklasse": "niedrig"},
                        {"DatumUTC": "/Date(1786233600000)/", "Wert": 4.44, "Grundwasserstandsklasse": "normal"},
                    ]
                }]
            }],
        }
    }

    def fake_fetch(url: str):
        body = stations_payload if "allegrundwasserstationen" in url else series_payload
        return body, {"api_attempts": 1, "retries": 0, "http_status": 200}

    payload = observer.build_payload(fake_fetch)
    assert payload["status"] == "ok"
    assert payload["observation_mode"] == "regional_proxy"
    assert payload["proxy_label"] == "Regional reference station / Regionale Referenzmessstelle"
    assert payload["reference_station"]["name"] == "Remels"
    assert [item["water_level_m_nhn"] for item in payload["history"]] == [4.44, 4.43]
    assert payload["latest_official_observation"]["official_groundwater_class"] == "niedrig"
    assert payload["latest_official_observation"]["derived_depth_below_ground_m"] == 4.18
    assert all(item["water_level_m_nhn"] not in observer.MISSING_SENTINELS for item in payload["history"])


def test_development_lists_official_documents_without_inventing_stage() -> None:
    observer = load_observer("wiesmoor-development")
    root = '<a href="/">Parent</a><a href="A11_2_Aenderung/">A11</a><a href="C16/">C16</a>'
    a11 = '<a href="/auslegung/">Parent</a><a href="A11_2_Aend_BekanntmachungHomepage_04092025.pdf">Notice</a>'
    c16 = '<a href="/auslegung/">Parent</a><a href="Wies_BBP_C16_Plan_2024-06-24.pdf">Plan</a>'

    def fake_fetch(url: str):
        if url == observer.LISTING_URL:
            body = root
        elif "A11_2_Aenderung" in url:
            body = a11
        else:
            body = c16
        return body, {"api_attempts": 1, "retries": 0, "http_status": 200}

    payload = observer.build_payload(fake_fetch)
    assert payload["status"] == "ok"
    assert payload["listed_collection_count"] == 2
    assert payload["listed_document_count"] == 2
    assert all(item["project_stage"] == "not_inferred" for item in payload["listed_collections"])
    assert {item["date"] for item in payload["document_timeline"]} == {"2024-06-24", "2025-09-04"}
    assert all(item["date_type"] == "document_date_from_official_filename" for item in payload["document_timeline"])


def test_all_new_observers_emit_common_contract() -> None:
    for slug in ("wiesmoor-population", "wiesmoor-finance"):
        payload = load_observer(slug).build_payload()
        assert payload["observer"] == slug
        assert payload["date"]
        assert payload["collected_at_utc"].endswith("Z")
        assert payload["status"] == "ok"
        assert payload["data_status"] == "ok"
        assert payload["sources"]
        assert payload["limitations"]
        assert payload["do_not_interpret_as"]


def test_live_adapters_fail_closed_without_synthetic_values() -> None:
    def broken_fetch(*_args, **_kwargs):
        raise TimeoutError("simulated upstream timeout")

    energy = load_observer("wiesmoor-energy").build_payload(broken_fetch)
    assert energy["status"] == "unavailable"
    assert energy["totals"] == {}
    assert energy["categories"] == []
    assert energy["commissioning_history"] == []

    groundwater = load_observer("wiesmoor-groundwater").build_payload(broken_fetch)
    assert groundwater["status"] == "unavailable"
    assert groundwater["reference_station"] is None
    assert groundwater["latest_official_observation"] is None
    assert groundwater["history"] == []

    development = load_observer("wiesmoor-development").build_payload(broken_fetch)
    assert development["status"] == "unavailable"
    assert development["listed_collections"] == []
    assert development["document_timeline"] == []


def test_development_degrades_independently_when_one_collection_breaks() -> None:
    observer = load_observer("wiesmoor-development")
    root = '<a href="A11_2_Aenderung/">A11</a><a href="C16/">C16</a>'

    def partial_fetch(url: str):
        if url == observer.LISTING_URL:
            return root, {"api_attempts": 1, "retries": 0, "http_status": 200}
        if "A11_2_Aenderung" in url:
            raise TimeoutError("simulated collection timeout")
        return '<a href="C16_Plan_2024-06-24.pdf">Plan</a>', {
            "api_attempts": 1,
            "retries": 0,
            "http_status": 200,
        }

    payload = observer.build_payload(partial_fetch)
    assert payload["status"] == "partial"
    assert payload["data_status"] == "partial"
    assert payload["diagnostics"]["collection_errors"] == 1
    collections = {item["official_identifier"]: item for item in payload["listed_collections"]}
    assert collections["A11_2_Aenderung"]["status"] == "collection_listed_documents_unavailable"
    assert collections["C16"]["document_count"] == 1


def test_static_reference_validation_rejects_corrupt_source_data(tmp_path: Path) -> None:
    population = load_observer("wiesmoor-population")
    population_source = json.loads(population.SOURCE_DATA.read_text(encoding="utf-8"))
    population_source["observations"][-1]["male"] = 1
    bad_population = tmp_path / "bad-population.json"
    bad_population.write_text(json.dumps(population_source), encoding="utf-8")
    with pytest.raises(ValueError, match="sex totals"):
        population.load_reference(bad_population)

    finance = load_observer("wiesmoor-finance")
    finance_source = json.loads(finance.SOURCE_DATA.read_text(encoding="utf-8"))
    finance_source["reporting_periods"][2]["value_status"] = "ESTIMATE"
    bad_finance = tmp_path / "bad-finance.json"
    bad_finance.write_text(json.dumps(finance_source), encoding="utf-8")
    with pytest.raises(ValueError, match="explicit PLAN, ACTUAL, or FORECAST"):
        finance.load_reference(bad_finance)
