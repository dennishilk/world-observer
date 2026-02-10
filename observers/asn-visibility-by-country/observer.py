"""Observer for ASN visibility by country using passive BGP RIB snapshots."""

from __future__ import annotations

import bz2
import gzip
import json
import math
import os
import struct
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
OBSERVER = "asn-visibility-by-country"
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
FIXED_CHART_PATH = REPO_ROOT / "data" / "latest" / "chart.png"


def _date_utc() -> date:
    injected = os.getenv("WORLD_OBSERVER_DATE_UTC")
    if injected:
        return date.fromisoformat(injected)
    return datetime.now(timezone.utc).date()


def _load_config() -> Dict[str, Any]:
    raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    return {
        "collectors": raw.get("collectors", {"ris": ["rrc00"], "routeviews": ["route-views2"]}),
        "rib_time_window_utc": raw.get("rib_time_window_utc", ["0000", "0200"]),
        "baseline_window_days": int(raw.get("baseline_window_days", 30)),
        "sigma_mult": float(raw.get("sigma_mult", 2.0)),
        "step_threshold_pct": float(raw.get("step_threshold_pct", 15.0)),
        "mass_event_k": int(raw.get("mass_event_k", 5)),
        "top_n": int(raw.get("top_n", 15)),
        "cache_paths": raw.get(
            "cache_paths",
            {
                "rib": "observers/asn-visibility-by-country/.cache/rib",
                "as2org": "observers/asn-visibility-by-country/.cache/as2org",
            },
        ),
    }


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _http_download(url: str, destination: Path) -> bool:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "world-observer/1.0"})
        with urllib.request.urlopen(request, timeout=45) as response:
            destination.write_bytes(response.read())
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _iter_rib_candidates(target_date: date, collectors: Dict[str, List[str]], window: List[str]) -> Iterator[Tuple[str, str]]:
    month = target_date.strftime("%Y.%m")
    ymd = target_date.strftime("%Y%m%d")
    times = [window[0], window[-1]] if window else ["0000", "0200"]

    for collector in collectors.get("ris", []):
        for hhmm in times:
            url = f"https://data.ris.ripe.net/{collector}/{month}/bview.{ymd}.{hhmm}.gz"
            filename = f"ris-{collector}-{ymd}-{hhmm}.gz"
            yield url, filename

    for collector in collectors.get("routeviews", []):
        for hhmm in times:
            url = (
                f"https://archive.routeviews.org/{collector}/bgpdata/{month}/RIBS/"
                f"rib.{ymd}.{hhmm}.bz2"
            )
            filename = f"rv-{collector}-{ymd}-{hhmm}.bz2"
            yield url, filename


def _open_compressed(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rb")
    if path.suffix == ".bz2":
        return bz2.open(path, "rb")
    return path.open("rb")


def _parse_as_path_attribute(attr_type: int, payload: bytes) -> Iterable[int]:
    # AS_PATH (2-byte ASN) and AS4_PATH (4-byte ASN)
    asn_size = 4 if attr_type == 17 else 2
    offset = 0
    found: List[int] = []

    while offset + 2 <= len(payload):
        seg_type = payload[offset]
        seg_len = payload[offset + 1]
        offset += 2
        byte_len = seg_len * asn_size
        if seg_type not in (1, 2, 3, 4) or offset + byte_len > len(payload):
            break
        for idx in range(seg_len):
            start = offset + idx * asn_size
            chunk = payload[start : start + asn_size]
            if asn_size == 2:
                asn = struct.unpack("!H", chunk)[0]
            else:
                asn = struct.unpack("!I", chunk)[0]
            if 0 < asn < 4294967295:
                found.append(asn)
        offset += byte_len

    return found


def _extract_asns_from_attrs(attrs: bytes) -> Iterable[int]:
    offset = 0
    asns: List[int] = []

    while offset + 2 <= len(attrs):
        flags = attrs[offset]
        attr_type = attrs[offset + 1]
        offset += 2

        if flags & 0x10:
            if offset + 2 > len(attrs):
                break
            attr_len = struct.unpack("!H", attrs[offset : offset + 2])[0]
            offset += 2
        else:
            if offset + 1 > len(attrs):
                break
            attr_len = attrs[offset]
            offset += 1

        payload = attrs[offset : offset + attr_len]
        offset += attr_len

        if attr_type in (2, 17):
            asns.extend(_parse_as_path_attribute(attr_type, payload))

    return asns


def _consume_nlri_prefixes(data: bytes, offset: int, v6: bool) -> int:
    width = 16 if v6 else 4
    while offset < len(data):
        plen = data[offset]
        offset += 1
        nbytes = (plen + 7) // 8
        offset += nbytes + width
    return offset


def _extract_unique_asns_from_mrt(mrt_path: Path) -> set[int]:
    discovered: set[int] = set()
    with _open_compressed(mrt_path) as fh:
        blob = fh.read()

    offset = 0
    total = len(blob)
    while offset + 12 <= total:
        _, msg_type, subtype, msg_len = struct.unpack("!IHHI", blob[offset : offset + 12])
        offset += 12
        payload = blob[offset : offset + msg_len]
        offset += msg_len

        if len(payload) != msg_len:
            break

        # TABLE_DUMP_V2 RIB entries (IPv4/IPv6 unicast) are subtypes 2/4.
        if msg_type == 13 and subtype in (2, 4):
            o = 0
            if len(payload) < 5:
                continue
            o += 4  # sequence number
            prefix_len = payload[o]
            o += 1
            o += (prefix_len + 7) // 8
            if o + 2 > len(payload):
                continue
            entry_count = struct.unpack("!H", payload[o : o + 2])[0]
            o += 2
            for _ in range(entry_count):
                if o + 8 > len(payload):
                    break
                o += 2  # peer index
                o += 4  # originated timestamp
                attr_len = struct.unpack("!H", payload[o : o + 2])[0]
                o += 2
                attrs = payload[o : o + attr_len]
                o += attr_len
                discovered.update(_extract_asns_from_attrs(attrs))

        # BGP4MP entries can carry AS_PATH in update attributes.
        if msg_type == 16 and subtype in (1, 4):
            o = 0
            if subtype == 4 and len(payload) >= 16:
                o += 16
            elif subtype == 1 and len(payload) >= 12:
                o += 12
            else:
                continue

            if o + 4 > len(payload):
                continue
            o += 2  # interface index
            afi = struct.unpack("!H", payload[o : o + 2])[0]
            o += 2
            v6 = afi == 2
            addr_len = 16 if v6 else 4
            if o + (addr_len * 2) + 4 > len(payload):
                continue
            o += addr_len * 2
            if o + 2 > len(payload):
                continue
            o += 2  # bgp marker rest starts with length (2) + type (1)
            if o + 1 > len(payload):
                continue
            o += 1
            if o + 1 > len(payload):
                continue
            o += 1
            if o + 2 > len(payload):
                continue
            withdrawn_len = struct.unpack("!H", payload[o : o + 2])[0]
            o += 2 + withdrawn_len
            if o + 2 > len(payload):
                continue
            attrs_len = struct.unpack("!H", payload[o : o + 2])[0]
            o += 2
            attrs = payload[o : o + attrs_len]
            discovered.update(_extract_asns_from_attrs(attrs))
            o += attrs_len
            _consume_nlri_prefixes(payload, o, v6)

    return discovered


def _download_as2org(cache_dir: Path, target_date: date) -> Optional[Path]:
    yyyy = target_date.strftime("%Y")
    mm = target_date.strftime("%m")
    stamp = target_date.strftime("%Y%m01")
    candidates = [
        f"https://publicdata.caida.org/datasets/as-organizations/{yyyy}/{mm}/"
        f"{stamp}.as-org2info.txt.gz",
        "https://publicdata.caida.org/datasets/as-organizations/2026/01/20260101.as-org2info.txt.gz",
    ]
    for url in candidates:
        destination = cache_dir / Path(url).name
        if destination.exists() or _http_download(url, destination):
            return destination
    return None


def _load_asn_country_map(path: Path) -> Dict[int, str]:
    mapping: Dict[int, str] = {}
    org_country: Dict[str, str] = {}

    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 5:
                continue
            if parts[0].isdigit() and parts[1].startswith("-"):
                # format variant not expected
                continue

            if len(parts) >= 5 and parts[0].isdigit() and parts[2].isdigit() and parts[3]:
                # aut|changed|aut_name|org_id|opaque_id|source
                try:
                    asn = int(parts[0])
                except ValueError:
                    continue
                org_id = parts[3]
                country = org_country.get(org_id, "unknown")
                mapping[asn] = country
            elif len(parts) >= 5 and parts[0].startswith("ORG-"):
                # org_id|changed|org_name|country|source
                org_country[parts[0]] = parts[3] or "unknown"

    # second pass ensures late org entries are applied
    if any(country == "unknown" for country in mapping.values()):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [part.strip() for part in line.split("|")]
                if len(parts) >= 5 and parts[0].isdigit() and parts[2].isdigit() and parts[3]:
                    asn = int(parts[0])
                    org_id = parts[3]
                    mapping[asn] = org_country.get(org_id, mapping.get(asn, "unknown"))

    return mapping


def _historical_country_counts(target_date: date, baseline_days: int) -> Dict[str, List[int]]:
    by_country: Dict[str, List[int]] = defaultdict(list)
    daily_root = REPO_ROOT / "data" / "daily"
    if not daily_root.exists():
        return by_country

    # Simpler deterministic scan by day offset.
    for offset in range(baseline_days, 0, -1):
        day = target_date.fromordinal(target_date.toordinal() - offset)
        payload_path = daily_root / day.isoformat() / f"{OBSERVER}.json"
        if not payload_path.exists():
            continue
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for country in payload.get("countries", []):
            key = str(country.get("country", "unknown"))
            count = country.get("asn_visible_count")
            if isinstance(count, int):
                by_country[key].append(count)

    return by_country


def _baseline_stats(values: List[int]) -> Tuple[float, float]:
    if not values:
        return 0.0, 0.0
    return float(mean(values)), float(pstdev(values))


def _significance(count: int, avg: float, std: float, sigma_mult: float, step_threshold_pct: float) -> Tuple[float, float, float, bool]:
    delta = float(count) - avg
    delta_pct = (delta / avg * 100.0) if avg > 0 else (100.0 if count > 0 else 0.0)
    z = (delta / std) if std > 0 else (0.0 if delta == 0 else math.copysign(float("inf"), delta))
    is_sig = (abs(z) > sigma_mult) or (abs(delta_pct) >= step_threshold_pct)
    return delta, delta_pct, z, is_sig


def _write_latest_summary(target_date: date, significant_count: int, mass_event: bool, chart_exists: bool) -> None:
    latest_dir = _ensure_dir(REPO_ROOT / "data" / "latest")
    summary_path = latest_dir / "summary.json"
    now = datetime.now(timezone.utc).isoformat()
    summary: Dict[str, Any] = {
        "last_run_utc": now,
        "latest_date_utc": target_date.isoformat(),
        "last_7_days": [],
    }

    for offset in range(6, -1, -1):
        day = target_date.fromordinal(target_date.toordinal() - offset)
        payload_path = REPO_ROOT / "data" / "daily" / day.isoformat() / f"{OBSERVER}.json"
        day_sig = 0
        day_mass = False
        if payload_path.exists():
            try:
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
                stats = payload.get("summary_stats", {})
                day_sig = int(stats.get("significant_count", 0))
                day_mass = bool(stats.get("mass_event", False))
            except (OSError, json.JSONDecodeError, ValueError, TypeError):
                pass
        if day == target_date:
            day_sig = significant_count
            day_mass = mass_event
        summary["last_7_days"].append(
            {
                "date_utc": day.isoformat(),
                "significant_count": day_sig,
                "mass_event": day_mass,
            }
        )

    if chart_exists:
        summary["chart_path"] = "data/latest/chart.png"

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_png(path: Path, width: int, height: int, pixels: List[List[Tuple[int, int, int]]]) -> None:
    import binascii
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data))
            + tag
            + data
            + struct.pack("!I", binascii.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for r, g, b in row:
            raw.extend((r, g, b))

    ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), level=9)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    path.write_bytes(png)


def _maybe_generate_chart(countries: List[Dict[str, Any]], top_n: int, should_generate: bool) -> bool:
    if not should_generate:
        return False

    movers = sorted(countries, key=lambda row: abs(float(row["z"])), reverse=True)[:top_n]
    if not movers:
        return False

    width, height = 900, 500
    bg = (245, 247, 250)
    axis = (35, 35, 35)
    pos = (42, 157, 143)
    neg = (209, 73, 91)
    pixels = [[bg for _ in range(width)] for _ in range(height)]

    mid_y = height // 2
    for x in range(50, width - 20):
        pixels[mid_y][x] = axis

    deltas = [float(row["delta_pct"]) for row in movers]
    scale = max(max(abs(v) for v in deltas), 1.0)
    max_bar_height = (height // 2) - 40
    plot_left = 60
    plot_width = width - 100
    bar_space = max(plot_width // len(movers), 1)
    bar_width = max(int(bar_space * 0.7), 1)

    for idx, value in enumerate(deltas):
        x0 = plot_left + idx * bar_space + (bar_space - bar_width) // 2
        x1 = min(x0 + bar_width, width - 20)
        bar_height = int((abs(value) / scale) * max_bar_height)
        if value >= 0:
            y0, y1 = mid_y - bar_height, mid_y
            color = pos
        else:
            y0, y1 = mid_y, mid_y + bar_height
            color = neg
        for y in range(max(y0, 0), min(y1, height - 1)):
            for x in range(max(x0, 0), max(x1, 0)):
                pixels[y][x] = color

    _ensure_dir(FIXED_CHART_PATH.parent)
    _write_png(FIXED_CHART_PATH, width, height, pixels)
    return True


def _forced_counts_from_env() -> Optional[Counter[str]]:
    raw = os.getenv("WORLD_OBSERVER_FORCE_COUNTRY_COUNTS_JSON")
    if not raw:
        return None
    parsed = json.loads(raw)
    counter: Counter[str] = Counter()
    for country, count in parsed.items():
        counter[str(country)] = int(count)
    return counter


def run() -> Dict[str, Any]:
    config = _load_config()
    target_date = _date_utc()
    notes: List[str] = [
        "ASN country assignment uses CAIDA AS2Org organization-country as a proxy.",
        "Output stores only per-country counts; ASN identifiers are not emitted.",
    ]

    forced = _forced_counts_from_env()
    country_counts: Counter[str] = Counter()
    unknown_count = 0
    data_status = "ok"

    if forced is not None:
        country_counts = forced
        notes.append("Country counts were injected via WORLD_OBSERVER_FORCE_COUNTRY_COUNTS_JSON for simulation.")
    else:
        cache = config["cache_paths"]
        rib_cache = _ensure_dir(REPO_ROOT / cache["rib"])
        as2org_cache = _ensure_dir(REPO_ROOT / cache["as2org"])

        downloaded_rib: Optional[Path] = None
        for url, filename in _iter_rib_candidates(target_date, config["collectors"], config["rib_time_window_utc"]):
            destination = rib_cache / filename
            if destination.exists() or _http_download(url, destination):
                downloaded_rib = destination
                notes.append(f"Used RIB snapshot source: {url}")
                break

        as2org_path = _download_as2org(as2org_cache, target_date)

        if not downloaded_rib or not as2org_path:
            data_status = "unavailable"
            if not downloaded_rib:
                notes.append("No reachable RIS/RouteViews RIB snapshot found in configured window.")
            if not as2org_path:
                notes.append("No reachable CAIDA AS2Org dataset found for mapping.")
        else:
            discovered_asns = _extract_unique_asns_from_mrt(downloaded_rib)
            asn_country = _load_asn_country_map(as2org_path)
            for asn in discovered_asns:
                country = asn_country.get(asn, "unknown")
                if country == "unknown":
                    unknown_count += 1
                country_counts[country] += 1

    baseline = _historical_country_counts(target_date, config["baseline_window_days"])
    countries_payload: List[Dict[str, Any]] = []

    significant_count = 0
    for country, count in sorted(country_counts.items()):
        history = baseline.get(country, [])
        avg, std = _baseline_stats(history)
        delta, delta_pct, z, is_sig = _significance(
            count,
            avg,
            std,
            config["sigma_mult"],
            config["step_threshold_pct"],
        )
        significant_count += int(is_sig)
        countries_payload.append(
            {
                "country": country,
                "asn_visible_count": int(count),
                "baseline_30d": {"mean": round(avg, 4), "std": round(std, 4)},
                "delta": round(delta, 4),
                "delta_pct": round(delta_pct, 4),
                "z": z if math.isinf(z) else round(z, 4),
                "is_significant": is_sig,
            }
        )

    any_significant = significant_count > 0
    mass_event = significant_count >= config["mass_event_k"]
    triggers: List[str] = []
    if any_significant:
        triggers.append("country-level threshold exceeded")
    if mass_event:
        triggers.append("mass_event_k reached")

    chart_written = _maybe_generate_chart(countries_payload, config["top_n"], any_significant or mass_event)
    _write_latest_summary(target_date, significant_count, mass_event, chart_written)

    payload: Dict[str, Any] = {
        "observer": OBSERVER,
        "date_utc": target_date.isoformat(),
        "data_status": data_status,
        "countries": countries_payload,
        "summary_stats": {
            "countries_evaluated": len(countries_payload),
            "significant_count": significant_count,
            "mass_event": mass_event,
        },
        "significance": {
            "sigma_mult": config["sigma_mult"],
            "step_threshold_pct": config["step_threshold_pct"],
            "any_significant": any_significant,
            "triggers": triggers,
        },
        "notes": notes,
    }
    if unknown_count:
        payload["summary_stats"]["unknown_count"] = unknown_count

    return payload


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
