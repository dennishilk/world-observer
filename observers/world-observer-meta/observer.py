"""Meta observer for aggregating daily outputs."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

OBSERVER_NAME = "world-observer-meta"
SUMMARY_JSON = "summary.json"
SUMMARY_MD = "summary.md"


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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _expected_observers() -> List[str]:
    observers_dir = _repo_root() / "observers"
    if not observers_dir.exists():
        return []
    names = [
        path.name
        for path in observers_dir.iterdir()
        if path.is_dir() and path.name != OBSERVER_NAME
    ]
    return sorted(names)


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
) -> Tuple[Dict[str, Dict[str, Any]], List[str], List[str]]:
    observations: Dict[str, Dict[str, Any]] = {}
    failed_inputs: List[str] = []
    duplicates: List[str] = []

    if not daily_dir.exists():
        return observations, failed_inputs, duplicates

    json_files = sorted(
        [path for path in daily_dir.iterdir() if path.suffix == ".json"],
        key=lambda path: path.name,
    )

    for path in json_files:
        if path.name == SUMMARY_JSON:
            continue
        payload, error = _load_json(path)
        if error:
            failed_inputs.append(error)
            continue
        observer_name = payload.get("observer")
        if not isinstance(observer_name, str) or not observer_name:
            failed_inputs.append(f"{path.name}: missing 'observer' field")
            continue
        if observer_name in observations:
            duplicates.append(observer_name)
        observations[observer_name] = payload

    return observations, failed_inputs, duplicates


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


def _format_summary_md(
    date_str: str,
    expected: Iterable[str],
    observations: Dict[str, Dict[str, Any]],
    missing: Iterable[str],
    failed: Iterable[str],
    highlights: Dict[str, Optional[float]],
) -> str:
    missing_set = set(missing)
    failed_names = {item.split(":", 1)[0] for item in failed}

    lines = [f"# world-observer-meta daily summary ({date_str})", ""]

    highlight_map = {
        "internet-shrinkage-index": "internet_shrinkage_index",
        "global-reachability-score": "global_reachability_score",
        "silent-countries-list": "silent_countries_count",
    }

    for observer_name in expected:
        lines.append(f"## {observer_name}")
        if observer_name in observations:
            lines.append("- Status: output present")
            highlight_key = highlight_map.get(observer_name)
            if highlight_key:
                value = highlights.get(highlight_key)
                if value is None:
                    lines.append("- Highlight: not reported in output")
                else:
                    lines.append(f"- Highlight ({highlight_key}): {value}")
            else:
                lines.append("- Highlight: none extracted")
        elif observer_name in missing_set:
            lines.append("- Status: missing output")
        elif observer_name in failed_names:
            lines.append("- Status: output unreadable or malformed")
        else:
            lines.append("- Status: missing output")
        lines.append("")

    if failed:
        lines.append("## failed inputs")
        for item in failed:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run(date_value: Optional[object] = None) -> Dict[str, Any]:
    """Aggregate daily observer outputs into a neutral summary."""

    date_str, warnings = _coerce_date(date_value)
    daily_dir = _repo_root() / "data" / "daily" / date_str
    expected = _expected_observers()

    observations, failed_inputs, duplicates = _collect_observations(daily_dir)

    observers_run = sorted(observations.keys())
    missing = sorted(set(expected) - set(observers_run))

    if duplicates:
        failed_inputs.append(
            "duplicate observer outputs found; most recent file used: "
            + ", ".join(sorted(set(duplicates)))
        )

    highlights = _extract_highlights(observations)

    notes_parts = []
    if warnings:
        notes_parts.extend(warnings)
    if missing:
        notes_parts.append(f"Missing observers: {', '.join(missing)}")
    if failed_inputs:
        notes_parts.append(f"Failed inputs: {', '.join(failed_inputs)}")
    notes = " | ".join(notes_parts) if notes_parts else ""  # neutral, optional

    summary: Dict[str, Any] = {
        "observer": OBSERVER_NAME,
        "date": date_str,
        "observers_run": observers_run,
        "observers_missing": missing,
        "highlights": highlights,
        "notes": notes,
    }

    daily_dir.mkdir(parents=True, exist_ok=True)
    summary_path = daily_dir / SUMMARY_JSON
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")

    summary_md = _format_summary_md(
        date_str,
        expected,
        observations,
        missing,
        failed_inputs,
        highlights,
    )
    (daily_dir / SUMMARY_MD).write_text(summary_md, encoding="utf-8")

    return summary


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    summary = run()
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
