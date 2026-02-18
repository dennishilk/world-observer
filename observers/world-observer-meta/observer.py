"""Meta observer for aggregating daily outputs."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

OBSERVER_NAME = "world-observer-meta"
DAILY_DIR_ENV = "WORLD_OBSERVER_DAILY_DIR"


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _coerce_date(date_value: Optional[object]) -> Tuple[str, List[str]]:
    warnings: List[str] = []
    if date_value is None:
        return _today_utc(), warnings
    if isinstance(date_value, datetime):
        return date_value.date().isoformat(), warnings
    if isinstance(date_value, date):
        return date_value.isoformat(), warnings
    if isinstance(date_value, str):
        try:
            parsed = datetime.strptime(date_value, "%Y-%m-%d")
        except ValueError:
            warnings.append(
                f"Invalid date '{date_value}' supplied; defaulted to today's UTC date."
            )
            return _today_utc(), warnings
        return parsed.date().isoformat(), warnings
    warnings.append("Unsupported date type supplied; defaulted to today's UTC date.")
    return _today_utc(), warnings


def _expected_observers(daily_dir: Optional[Path]) -> Tuple[List[str], List[str]]:
    warnings: List[str] = []
    if daily_dir is None:
        return [], warnings

    repo_root = daily_dir.parent.parent.parent
    observers_dir = repo_root / "observers"
    if not observers_dir.exists():
        warnings.append(f"observers directory not found at {observers_dir}")
        return [], warnings

    names = sorted(
        path.name
        for path in observers_dir.iterdir()
        if path.is_dir() and path.name != OBSERVER_NAME and (path / "observer.py").exists()
    )
    return names, warnings


def _daily_dir_from_env(date_str: str) -> Tuple[Optional[Path], List[str]]:
    warnings: List[str] = []
    daily_dir_value = os.environ.get(DAILY_DIR_ENV, "").strip()
    if not daily_dir_value:
        warnings.append(f"{DAILY_DIR_ENV} not set; cannot scan daily observer outputs.")
        return None, warnings

    daily_dir = Path(daily_dir_value)
    expected_suffix = Path("data") / "daily" / date_str
    if daily_dir.name != date_str:
        warnings.append(
            f"{DAILY_DIR_ENV} points to '{daily_dir}', which does not end with '{expected_suffix}'."
        )
    return daily_dir, warnings


def _load_json(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path.name}: {exc}"
    if not isinstance(payload, dict):
        return None, f"{path.name}: root JSON value is not an object"
    return payload, None


def _collect_observations(
    daily_dir: Path,
    expected_observers: Iterable[str],
) -> Tuple[Dict[str, Dict[str, Any]], List[str], List[str], List[str]]:
    observations: Dict[str, Dict[str, Any]] = {}
    missing_inputs: List[str] = []
    failed_inputs: List[str] = []
    degraded_inputs: List[str] = []

    for observer_name in sorted(expected_observers):
        path = daily_dir / f"{observer_name}.json"
        if not path.exists():
            missing_inputs.append(observer_name)
            continue
        payload, error = _load_json(path)
        if error:
            failed_inputs.append(error)
            continue
        if payload.get("status") == "error":
            failed_inputs.append(f"{path.name}: status is error")
            continue
        data_status = payload.get("data_status")
        if data_status in {"partial", "unavailable", "error"}:
            degraded_inputs.append(f"{observer_name}:{data_status}")
        observations[observer_name] = payload

    return observations, missing_inputs, failed_inputs, degraded_inputs


def _safe_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _extract_highlights(observations: Dict[str, Dict[str, Any]]) -> Dict[str, Optional[float]]:
    highlights: Dict[str, Optional[float]] = {
        "internet_shrinkage_index": None,
        "global_reachability_score": None,
        "silent_countries_count": None,
    }

    shrinkage = observations.get("internet-shrinkage-index")
    if shrinkage:
        highlights["internet_shrinkage_index"] = _safe_number(shrinkage.get("index"))

    reachability = observations.get("global-reachability-score")
    if reachability:
        highlights["global_reachability_score"] = _safe_number(
            reachability.get("global_reachability_score")
        )

    silent = observations.get("silent-countries-list")
    if silent:
        highlights["silent_countries_count"] = _safe_number(
            silent.get("silent_countries_count")
        )

    return highlights


def run(date_value: Optional[object] = None) -> Dict[str, Any]:
    """Aggregate daily observer outputs into a neutral summary."""

    date_str, warnings = _coerce_date(date_value)
    daily_dir, daily_dir_warnings = _daily_dir_from_env(date_str)
    warnings.extend(daily_dir_warnings)
    expected, expected_warnings = _expected_observers(daily_dir)
    warnings.extend(expected_warnings)

    observations: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = sorted(expected)
    failed_inputs: List[str] = []
    degraded_inputs: List[str] = []
    if daily_dir is not None:
        observations, missing_inputs, failed_inputs, degraded_inputs = _collect_observations(daily_dir, expected)
        observers_run = sorted(observations.keys())
        missing = sorted(set(missing_inputs) | (set(expected) - set(observers_run)))
    else:
        observers_run = []

    if daily_dir is not None and not daily_dir.exists():
        missing = sorted(expected)
        observers_run = []
        failed_inputs.append(f"{daily_dir}: directory does not exist")

    highlights = _extract_highlights(observations)

    notes_parts = []
    if warnings:
        notes_parts.extend(warnings)
    if missing:
        notes_parts.append(f"Missing observers: {', '.join(missing)}")
    if failed_inputs:
        notes_parts.append(f"Failed inputs: {', '.join(failed_inputs)}")
    if degraded_inputs:
        notes_parts.append(f"Degraded observers: {', '.join(sorted(degraded_inputs))}")
    notes = " | ".join(notes_parts) if notes_parts else ""  # neutral, optional

    summary: Dict[str, Any] = {
        "observer": OBSERVER_NAME,
        "date": date_str,
        "observers_run": observers_run,
        "observers_missing": missing,
        "observers_degraded": sorted(degraded_inputs),
        "highlights": highlights,
        "notes": notes,
    }

    return summary


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    summary = run()
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
