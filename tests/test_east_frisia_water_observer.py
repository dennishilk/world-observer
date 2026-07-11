from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path("observers/east-frisia-water-observer/observer.py")
SPEC = importlib.util.spec_from_file_location("east_frisia_water_observer", MODULE_PATH)
observer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = observer
assert SPEC.loader is not None
SPEC.loader.exec_module(observer)


def test_scaffold_payload_is_valid_and_pending() -> None:
    payload = observer.build_payload()

    assert payload["observer"] == "east-frisia-water-observer"
    assert payload["category"] == "Environment"
    assert payload["data_status"] == "adapter_pending"
    assert payload["live_adapters_enabled"] is False
    assert payload["diagnostics"]["api_attempts"] == 0
    assert payload["diagnostics"]["retries"] == 0
    assert [item["adapter"] for item in payload["adapters"]] == ["dwd", "nlwkn", "wsv", "bsh"]
    assert all(item["status"] == "adapter_pending" for item in payload["adapters"])
    assert all(item["source_research"]["official_url"].startswith("https://") for item in payload["adapters"])
    assert payload["recommendation"]["integrate_first"] == "nlwkn"
