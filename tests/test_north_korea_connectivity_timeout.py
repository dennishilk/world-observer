from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path("observers/north-korea-connectivity/observer.py")
SPEC = importlib.util.spec_from_file_location("north_korea_connectivity_observer", MODULE_PATH)
assert SPEC and SPEC.loader
observer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = observer
SPEC.loader.exec_module(observer)


def test_probe_once_records_failures_and_timeouts() -> None:
    budget = observer.ProbeBudget(5.0)

    observer._dns_probe = lambda host, timeout_s: (False, None, True)
    observer._ping = lambda host, timeout_s: (False, True)
    observer._tls_probe = lambda host, timeout_s: (False, True)
    observer._tcp_probe = lambda host, port, timeout_s: (False, True)

    layers, diagnostics = observer._probe_once(["example.invalid"], 0.1, budget)
    budget_diagnostics = budget.diagnostics()

    assert diagnostics["api_attempts"] == 6
    assert budget_diagnostics["probes_attempted"] == 6
    assert budget_diagnostics["probes_failed"] == 6
    assert budget_diagnostics["timeouts"] == 6
    assert layers["dns"]["probe_count"] == 1
    assert layers["tcp"]["probe_count"] == 3


def test_run_emits_ok_json_when_probes_are_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(observer, "_load_targets", lambda: ["example.invalid"])
    monkeypatch.setattr(
        observer,
        "_load_config",
        lambda: {
            "baseline_days": 30,
            "sigma_mult": 2.0,
            "timeout_s": 0.1,
            "budget_s": 2.0,
            "time_to_silence_trials": 1,
            "time_to_silence_max_rounds": 1,
        },
    )
    monkeypatch.setattr(observer, "_dns_probe", lambda host, timeout_s: (False, None, True))
    monkeypatch.setattr(observer, "_ping", lambda host, timeout_s: (False, True))
    monkeypatch.setattr(observer, "_tls_probe", lambda host, timeout_s: (False, True))
    monkeypatch.setattr(observer, "_tcp_probe", lambda host, port, timeout_s: (False, True))
    monkeypatch.setattr(observer, "_generate_chart_if_needed", lambda *args, **kwargs: None)
    monkeypatch.setattr(observer, "_update_latest_summary", lambda *args, **kwargs: None)

    payload = observer.run()

    assert payload["status"] == "ok"
    assert payload["data_status"] in {"unavailable", "partial"}
    assert payload["diagnostics"]["probes_attempted"] > 0
    assert payload["diagnostics"]["probes_failed"] == payload["diagnostics"]["probes_attempted"]
    assert payload["diagnostics"]["timeouts"] == payload["diagnostics"]["probes_attempted"]
    assert payload["diagnostics"]["duration_s"] <= 2.0
