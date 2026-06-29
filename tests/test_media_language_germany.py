from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OBSERVER_PATH = REPO_ROOT / "observers" / "media-language-germany" / "observer.py"


def _load_observer():
    spec = importlib.util.spec_from_file_location("media_language_germany_observer", OBSERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_keyword_scoring_counts_categories_and_terms() -> None:
    observer = _load_observer()
    result = observer.score_headlines([
        "Warnung vor Hitze und Klimawandel in Deutschland",
        "Wirtschaft unter Druck nach Energie-Preisen",
        "Sportverein feiert Sieg",
    ])

    assert result["headline_count"] == 3
    assert result["matched_headline_count"] == 2
    assert result["total_term_hits"] >= 4
    assert result["category_counts"]["climate"] >= 2
    assert result["category_counts"]["economy"] >= 2
    assert result["category_counts"]["general_alarm"] >= 1
    assert 0 < result["fear_index"] <= 100
    assert {entry["term"] for entry in result["top_terms"]}


def test_rss_parsing_with_sample_xml() -> None:
    observer = _load_observer()
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>Feed title</title>
      <item><title>Erste Nachricht</title></item>
      <item><title>Zweite Nachricht &amp;amp; Analyse</title></item>
    </channel></rss>
    """

    assert observer.parse_rss_titles(xml) == ["Erste Nachricht", "Zweite Nachricht & Analyse"]


def test_observer_returns_valid_json_with_unavailable_sources() -> None:
    observer = _load_observer()
    payload = observer.run(sources=[])

    assert payload["observer"] == "media-language-germany"
    assert payload["status"] == "ok"
    assert payload["data_status"] == "unavailable"
    assert payload["headline_count"] == 0
    assert payload["diagnostics"]["sources_attempted"] == 0
    json.dumps(payload)


def test_stdout_remains_json_only_with_empty_sources(monkeypatch) -> None:
    _load_observer()
    env = {"WORLD_OBSERVER_MEDIA_LANGUAGE_GERMANY_DISABLE_NETWORK": "1"}

    completed = subprocess.run(
        [sys.executable, str(OBSERVER_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert payload["observer"] == "media-language-germany"
    assert completed.stdout.strip().startswith("{")
    assert completed.stdout.strip().endswith("}")
