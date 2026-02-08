"""Observer for minimal ASN visibility checks by country."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class ASNProbe:
    """Configuration for a single ASN probe."""

    asn: int
    probe_ip: str


@dataclass(frozen=True)
class CountryASNSource:
    """Input source describing ASNs for a country."""

    country: str
    asns: List[ASNProbe]


def _load_sources(path: Path) -> CountryASNSource:
    data = json.loads(path.read_text(encoding="utf-8"))
    country = data.get("country")
    asns = data.get("asns", [])
    parsed = [
        ASNProbe(asn=int(entry["asn"]), probe_ip=str(entry["probe_ip"]))
        for entry in asns
        if "asn" in entry and "probe_ip" in entry
    ]
    return CountryASNSource(country=country, asns=parsed)


def _check_reachability(ip_address: str, timeout_seconds: float = 3.0) -> bool:
    try:
        with socket.create_connection((ip_address, 443), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def run() -> Dict[str, Any]:
    """Run the observer and return a structured observation.

    This performs a single conservative reachability check per ASN.
    """

    timestamp = datetime.now(timezone.utc).isoformat()
    source_path = Path(__file__).with_name("asn_sources.json")
    countries: List[Dict[str, Any]] = []
    notes = "Reachability is based on a single TCP 443 probe per ASN."

    try:
        source = _load_sources(source_path)
        total_asns = len(source.asns)
        visible_asns = sum(
            1 for entry in source.asns if _check_reachability(entry.probe_ip)
        )
        visibility_ratio = (visible_asns / total_asns) if total_asns else 0.0
        countries.append(
            {
                "country": source.country,
                "total_asns": total_asns,
                "visible_asns": visible_asns,
                "visibility_ratio": visibility_ratio,
            }
        )
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        notes = "Unable to load ASN sources; no observations recorded."

    return {
        "observer": "asn-visibility-by-country",
        "timestamp": timestamp,
        "countries": countries,
        "notes": notes,
    }


def main() -> None:
    """Serialize the observation to JSON on stdout."""

    observation = run()
    print(json.dumps(observation, ensure_ascii=False))


if __name__ == "__main__":
    main()
