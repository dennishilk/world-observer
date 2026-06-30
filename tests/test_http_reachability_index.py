import importlib.util
import json
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path("observers/http-reachability-index/observer.py")
SPEC = importlib.util.spec_from_file_location("http_reachability_index_observer", MODULE_PATH)
observer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = observer
SPEC.loader.exec_module(observer)


def test_observer_emits_valid_json() -> None:
    result = subprocess.run([sys.executable, str(MODULE_PATH)], capture_output=True, text=True, timeout=45, check=False)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["observer"] == "http-reachability-index"
    assert payload["status"] == "ok"
    assert payload["data_status"] in {"ok", "partial", "unavailable"}
    assert payload["summary"]["targets_checked"] == 8


def test_partial_reachability_works(monkeypatch) -> None:
    outcomes = {"https://ok.example": True, "https://fail.example": False}

    def fake_check_target(url: str, timeout_s: float):
        return {"url": url, "reachable": outcomes[url], "http_status": 200 if outcomes[url] else None, "response_ms": 10.0 if outcomes[url] else None, "error": None if outcomes[url] else "failed"}

    monkeypatch.setattr(observer, "check_target", fake_check_target)
    payload = observer.run(["https://ok.example", "https://fail.example"], target_timeout_s=0.1, total_runtime_budget_s=2.0)
    assert payload["status"] == "ok"
    assert payload["data_status"] == "partial"
    assert payload["summary"]["targets_reachable"] == 1
    assert payload["summary"]["targets_failed"] == 1


def test_all_fail_returns_unavailable_but_status_ok(monkeypatch) -> None:
    monkeypatch.setattr(observer, "check_target", lambda url, timeout_s: {"url": url, "reachable": False, "http_status": None, "response_ms": None, "error": "failed"})
    payload = observer.run(["https://fail-a.example", "https://fail-b.example"], target_timeout_s=0.1, total_runtime_budget_s=2.0)
    assert payload["status"] == "ok"
    assert payload["data_status"] == "unavailable"
    assert payload["summary"]["targets_reachable"] == 0
