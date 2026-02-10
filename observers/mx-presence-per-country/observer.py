"""Observer for aggregated MX presence per country with significance-only charting."""

from __future__ import annotations

import json
import math
import os
import random
import socket
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

OBSERVER = "mx-presence-per-country"
MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]
CONFIG_PATH = MODULE_DIR / "config.json"
DAILY_ROOT = REPO_ROOT / "data" / "daily"
LATEST_DIR = REPO_ROOT / "data" / "latest"
LATEST_SUMMARY_PATH = LATEST_DIR / "summary.json"
LATEST_CHART_PATH = LATEST_DIR / "chart.png"
RAW_LOCAL_DIR = REPO_ROOT / "state" / OBSERVER


@dataclass
class Config:
    country_domain_samples: Dict[str, List[str]]
    resolver: str
    dns_timeout_s: float
    smtp_timeout_s: float
    baseline_days: int
    sigma_mult: float
    mass_event_k: int
    top_countries_in_chart: int
    trend_days: int


def _date_utc() -> str:
    env_value = os.environ.get("WORLD_OBSERVER_DATE_UTC", "").strip()
    if env_value:
        try:
            return datetime.strptime(env_value, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def _load_json(path: Path, default: Any) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload
    except (OSError, json.JSONDecodeError):
        return default


def _detect_system_resolver() -> str:
    try:
        for line in Path("/etc/resolv.conf").read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("nameserver"):
                parts = stripped.split()
                if len(parts) >= 2:
                    return parts[1]
    except OSError:
        pass
    return "8.8.8.8"


def _load_config() -> Config:
    payload = _load_json(CONFIG_PATH, {})
    if not isinstance(payload, dict):
        payload = {}

    raw_samples = payload.get("country_domain_samples", {})
    samples: Dict[str, List[str]] = {}
    if isinstance(raw_samples, dict):
        for country, domains in raw_samples.items():
            if not isinstance(country, str) or not isinstance(domains, list):
                continue
            normalized_country = country.strip().upper()
            cleaned_domains = [str(domain).strip().lower() for domain in domains if str(domain).strip()]
            if normalized_country and cleaned_domains:
                samples[normalized_country] = cleaned_domains

    if not samples:
        samples = {
            "US": ["example.com", "example.org", "iana.org"],
            "DE": ["example.com", "example.org", "wikipedia.org"],
            "IN": ["example.com", "iana.org", "wikimedia.org"],
            "BR": ["example.com", "example.net", "wikipedia.org"],
            "JP": ["example.com", "example.org", "iana.org"],
        }

    resolver = str(payload.get("resolver", "")).strip() or _detect_system_resolver()

    return Config(
        country_domain_samples=samples,
        resolver=resolver,
        dns_timeout_s=max(0.5, float(payload.get("dns_timeout_s", 2.0))),
        smtp_timeout_s=max(0.5, float(payload.get("smtp_timeout_s", 2.0))),
        baseline_days=max(7, int(payload.get("baseline_days", 30))),
        sigma_mult=max(0.5, float(payload.get("sigma_mult", 2.0))),
        mass_event_k=max(1, int(payload.get("mass_event_k", 5))),
        top_countries_in_chart=max(3, int(payload.get("top_countries_in_chart", 6))),
        trend_days=max(3, int(payload.get("trend_days", 7))),
    )


def _encode_dns_name(name: str) -> bytes:
    result = b""
    for label in name.strip(".").split("."):
        encoded = label.encode("idna")
        result += bytes([len(encoded)]) + encoded
    return result + b"\x00"


def _decode_dns_name(packet: bytes, offset: int) -> Tuple[str, int]:
    labels: List[str] = []
    jumped = False
    cursor = offset
    end_offset = offset

    while cursor < len(packet):
        length = packet[cursor]
        if length == 0:
            cursor += 1
            if not jumped:
                end_offset = cursor
            break

        if length & 0xC0 == 0xC0:
            if cursor + 1 >= len(packet):
                break
            pointer = ((length & 0x3F) << 8) | packet[cursor + 1]
            if not jumped:
                end_offset = cursor + 2
            cursor = pointer
            jumped = True
            continue

        cursor += 1
        label = packet[cursor : cursor + length]
        labels.append(label.decode("utf-8", errors="ignore"))
        cursor += length
        if not jumped:
            end_offset = cursor

    return ".".join(labels), end_offset


def _query_mx(domain: str, resolver: str, timeout_s: float) -> Dict[str, Any]:
    txid = random.randint(0, 65535)
    header = struct.pack(">HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    question = _encode_dns_name(domain) + struct.pack(">HH", 15, 1)
    packet = header + question

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout_s)

    try:
        sock.sendto(packet, (resolver, 53))
        data, _ = sock.recvfrom(4096)
    except socket.timeout:
        return {"status": "timeout", "mx_hosts": []}
    except OSError:
        return {"status": "error", "mx_hosts": []}
    finally:
        sock.close()

    if len(data) < 12:
        return {"status": "error", "mx_hosts": []}

    resp_txid, flags, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", data[:12])
    if resp_txid != txid:
        return {"status": "error", "mx_hosts": []}

    rcode = flags & 0x000F
    if rcode == 3:
        return {"status": "nxdomain", "mx_hosts": []}
    if rcode != 0:
        return {"status": "error", "mx_hosts": []}

    offset = 12
    for _ in range(qdcount):
        _, offset = _decode_dns_name(data, offset)
        offset += 4

    mx_hosts: List[str] = []
    for _ in range(ancount):
        _, offset = _decode_dns_name(data, offset)
        if offset + 10 > len(data):
            return {"status": "error", "mx_hosts": []}
        rtype, _, _, rdlen = struct.unpack(">HHIH", data[offset : offset + 10])
        offset += 10
        rdata_end = offset + rdlen
        if rdata_end > len(data):
            return {"status": "error", "mx_hosts": []}

        if rtype == 15 and rdlen >= 3:
            preference = struct.unpack(">H", data[offset : offset + 2])[0]
            host, _ = _decode_dns_name(data, offset + 2)
            if host:
                mx_hosts.append(f"{preference}:{host}")
        offset = rdata_end

    if not mx_hosts:
        return {"status": "ok", "mx_hosts": []}

    mx_hosts_sorted = [item.split(":", 1)[1] for item in sorted(mx_hosts)]
    return {"status": "ok", "mx_hosts": mx_hosts_sorted}


def _mx_reachability(mx_hosts: List[str], timeout_s: float) -> str:
    if not mx_hosts:
        return "not_applicable"

    attempts = mx_hosts[:2]
    saw_timeout = False
    for host in attempts:
        try:
            with socket.create_connection((host, 25), timeout=timeout_s):
                return "success"
        except socket.timeout:
            saw_timeout = True
        except OSError:
            continue

    if saw_timeout:
        return "timeout"
    return "unreachable"


def _probe_country(country: str, domains: List[str], config: Config) -> Dict[str, Any]:
    sample_size = len(domains)
    present = 0
    absent = 0
    unreachable = 0
    timeout = 0
    completed = 0
    local_raw: List[Dict[str, str]] = []

    for domain in domains:
        mx_query = _query_mx(domain, config.resolver, config.dns_timeout_s)
        status = str(mx_query.get("status", "error"))
        mx_hosts = mx_query.get("mx_hosts", []) if isinstance(mx_query.get("mx_hosts"), list) else []

        if status == "timeout":
            timeout += 1
            local_raw.append({"domain": domain, "dns": "timeout", "smtp": "not_applicable"})
            continue

        if status != "ok":
            absent += 1
            completed += 1
            local_raw.append({"domain": domain, "dns": status, "smtp": "not_applicable"})
            continue

        completed += 1
        if mx_hosts:
            present += 1
            smtp_status = _mx_reachability(mx_hosts, config.smtp_timeout_s)
            if smtp_status == "timeout":
                timeout += 1
            elif smtp_status == "unreachable":
                unreachable += 1
            local_raw.append({"domain": domain, "dns": "present", "smtp": smtp_status})
        else:
            absent += 1
            local_raw.append({"domain": domain, "dns": "absent", "smtp": "not_applicable"})

    def _rate(value: int) -> float:
        return round((value / sample_size), 6) if sample_size else 0.0

    return {
        "country": country,
        "sample_size": sample_size,
        "mx_present_count": present,
        "mx_unreachable_count": unreachable,
        "mx_present_rate": _rate(present),
        "mx_absent_rate": _rate(absent),
        "mx_unreachable_rate": _rate(unreachable),
        "mx_timeout_rate": _rate(timeout),
        "data_completeness": round((completed / sample_size), 6) if sample_size else 0.0,
        "_local_raw": local_raw,
    }


def _daily_files_up_to(date_str: str) -> List[Path]:
    paths = sorted(DAILY_ROOT.glob(f"*/{OBSERVER}.json"))
    return [path for path in paths if path.parent.name <= date_str]


def _history_metric(date_str: str, country: str, metric: str, baseline_days: int) -> List[float]:
    values: List[float] = []
    for path in _daily_files_up_to(date_str):
        payload = _load_json(path, {})
        if not isinstance(payload, dict) or payload.get("date_utc") == date_str:
            continue
        countries = payload.get("countries", [])
        if not isinstance(countries, list):
            continue
        for row in countries:
            if not isinstance(row, dict):
                continue
            if str(row.get("country", "")).upper() != country.upper():
                continue
            metric_value = row.get(metric)
            if isinstance(metric_value, (int, float)):
                values.append(float(metric_value))
    if len(values) > baseline_days:
        values = values[-baseline_days:]
    return values


def _mean_std(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0}
    avg = sum(values) / len(values)
    var = sum((item - avg) ** 2 for item in values) / len(values)
    return {"mean": round(avg, 6), "std": round(math.sqrt(var), 6)}


def _z(value: float, baseline: Dict[str, float]) -> float:
    std = baseline.get("std", 0.0)
    if std <= 0:
        return 0.0
    return round((value - baseline.get("mean", 0.0)) / std, 6)


def _last_7_summary(date_str: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in _daily_files_up_to(date_str)[-7:]:
        payload = _load_json(path, {})
        if not isinstance(payload, dict):
            continue
        stats = payload.get("summary_stats", {})
        rows.append(
            {
                "date_utc": payload.get("date_utc", path.parent.name),
                "significant_count": int(stats.get("significant_count", 0) or 0),
                "mass_event": bool(stats.get("mass_event", False)),
            }
        )
    return rows


def _save_local_raw(date_str: str, country_rows: List[Dict[str, Any]]) -> None:
    RAW_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "observer": OBSERVER,
        "date_utc": date_str,
        "raw": [
            {
                "country": row["country"],
                "samples": row.get("_local_raw", []),
            }
            for row in country_rows
        ],
    }
    (RAW_LOCAL_DIR / f"{date_str}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _encode_png_rgb(width: int, height: int, pixels: List[List[Tuple[int, int, int]]], metadata: Dict[str, str]) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))

    text_chunks = []
    for key, value in metadata.items():
        text_chunks.append(
            _png_chunk(
                b"tEXt",
                key.encode("latin1", errors="ignore") + b"\x00" + value.encode("latin1", errors="ignore"),
            )
        )

    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            r, g, b = pixels[y][x]
            raw.extend((r, g, b))
    idat = _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
    iend = _png_chunk(b"IEND", b"")
    return signature + ihdr + b"".join(text_chunks) + idat + iend


def _render_chart(date_str: str, triggers: List[str], countries: List[Dict[str, Any]], trend_rows: List[Dict[str, Any]], config: Config) -> None:
    width, height = 900, 420
    bg = (246, 248, 252)
    pixels = [[bg for _ in range(width)] for _ in range(height)]

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for row in countries:
        drop = max(0.0, -float(row["z"]["mx_present_rate"]))
        increase = max(0.0, float(row["z"]["mx_unreachable_rate"]))
        scored.append((max(drop, increase), row))

    top = [row for _, row in sorted(scored, key=lambda item: item[0], reverse=True)[: config.top_countries_in_chart]]

    bar_left = 40
    bar_top = 50
    bar_height = 28
    bar_gap = 14
    max_bar_w = 560

    for idx, row in enumerate(top):
        severity = max(
            max(0.0, -float(row["z"]["mx_present_rate"])),
            max(0.0, float(row["z"]["mx_unreachable_rate"])),
        )
        normalized = min(1.0, severity / max(0.1, config.sigma_mult * 2))
        y0 = bar_top + idx * (bar_height + bar_gap)
        y1 = min(height - 1, y0 + bar_height)
        bar_w = int(max_bar_w * max(0.03, normalized))
        color = (min(255, int(130 + 120 * normalized)), max(20, int(185 - 110 * normalized)), 85)

        for y in range(y0, y1):
            for x in range(bar_left, min(width - 1, bar_left + bar_w)):
                pixels[y][x] = color

    rows = trend_rows[-config.trend_days :]
    trend_left = 40
    trend_width = 700
    base_y = 350
    max_sig = max([int(row.get("significant_count", 0)) for row in rows] + [1])

    if rows:
        step = max(1, trend_width // max(1, len(rows) - 1))
        for idx, row in enumerate(rows):
            sig_count = int(row.get("significant_count", 0))
            x = trend_left + idx * step
            y = base_y - int((sig_count / max_sig) * 90)
            for yy in range(max(0, y - 2), min(height, y + 3)):
                for xx in range(max(0, x - 2), min(width, x + 3)):
                    pixels[yy][xx] = (20, 60, 150)

    metadata = {
        "Title": f"MX Presence Significance {date_str}",
        "Observer": OBSERVER,
        "Triggers": " | ".join(triggers) if triggers else "n/a",
        "TopCountries": "; ".join(
            f"{row['country']}:zP={row['z']['mx_present_rate']:.2f},zU={row['z']['mx_unreachable_rate']:.2f}" for row in top
        ),
        "RecentTrend": "; ".join(
            f"{row['date_utc']}:sig={row['significant_count']},mass={row['mass_event']}" for row in rows
        ),
    }

    png = _encode_png_rgb(width, height, pixels, metadata)
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_CHART_PATH.write_bytes(png)


def _write_latest_summary(date_str: str, any_significant: bool, last_7_days: List[Dict[str, Any]]) -> None:
    summary: Dict[str, Any] = {
        "observer": OBSERVER,
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
        "latest_date_utc": date_str,
        "last_7_days": last_7_days,
    }
    if any_significant and LATEST_CHART_PATH.exists():
        summary["chart_path"] = "data/latest/chart.png"

    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run() -> Dict[str, Any]:
    config = _load_config()
    date_str = _date_utc()

    country_rows: List[Dict[str, Any]] = []
    for country, domains in sorted(config.country_domain_samples.items()):
        country_rows.append(_probe_country(country, domains, config))

    _save_local_raw(date_str, country_rows)

    significant_count = 0
    triggers: List[str] = []

    for row in country_rows:
        present_history = _history_metric(date_str, row["country"], "mx_present_rate", config.baseline_days)
        unreach_history = _history_metric(date_str, row["country"], "mx_unreachable_rate", config.baseline_days)

        present_baseline = _mean_std(present_history)
        unreach_baseline = _mean_std(unreach_history)

        z_present = _z(float(row["mx_present_rate"]), present_baseline)
        z_unreach = _z(float(row["mx_unreachable_rate"]), unreach_baseline)

        enough_history_present = len(present_history) >= 5
        enough_history_unreach = len(unreach_history) >= 5

        sig_present = enough_history_present and z_present < -config.sigma_mult
        sig_unreach = enough_history_unreach and z_unreach > config.sigma_mult

        if sig_present:
            triggers.append(f"z(mx_present_rate)<-{config.sigma_mult} ({row['country']}={z_present:.2f})")
        if sig_unreach:
            triggers.append(f"z(mx_unreachable_rate)>{config.sigma_mult} ({row['country']}={z_unreach:.2f})")

        is_significant = bool(sig_present or sig_unreach)
        if is_significant:
            significant_count += 1

        row["baseline_30d"] = {
            "mx_present_rate": present_baseline,
            "mx_unreachable_rate": unreach_baseline,
        }
        row["z"] = {
            "mx_present_rate": z_present,
            "mx_unreachable_rate": z_unreach,
        }
        row["is_significant"] = is_significant

    mass_event = significant_count >= config.mass_event_k
    if mass_event:
        triggers.append(f"mass_event>= {config.mass_event_k}")

    any_significant = significant_count > 0 or mass_event
    if os.environ.get("WORLD_OBSERVER_MX_FORCE_SIGNIFICANT", "").strip() == "1":
        any_significant = True
        triggers.append("forced_for_testing")

    if any_significant:
        _render_chart(date_str, sorted(set(triggers)), country_rows, _last_7_summary(date_str), config)
    elif LATEST_CHART_PATH.exists():
        LATEST_CHART_PATH.unlink()

    completeness_values = [float(row.get("data_completeness", 0.0)) for row in country_rows]
    if not completeness_values or max(completeness_values) <= 0:
        data_status = "unavailable"
    elif min(completeness_values) < 1.0:
        data_status = "partial"
    else:
        data_status = "ok"

    output = {
        "observer": OBSERVER,
        "date_utc": date_str,
        "data_status": data_status,
        "countries": [
            {
                "country": row["country"],
                "sample_size": row["sample_size"],
                "mx_present_rate": row["mx_present_rate"],
                "mx_absent_rate": row["mx_absent_rate"],
                "mx_unreachable_rate": row["mx_unreachable_rate"],
                "mx_timeout_rate": row["mx_timeout_rate"],
                "data_completeness": row["data_completeness"],
                "mx_present_count": row["mx_present_count"],
                "mx_unreachable_count": row["mx_unreachable_count"],
                "baseline_30d": row["baseline_30d"],
                "z": row["z"],
                "is_significant": row["is_significant"],
            }
            for row in country_rows
        ],
        "summary_stats": {
            "countries_evaluated": len(country_rows),
            "significant_count": significant_count,
            "mass_event": mass_event,
        },
        "significance": {
            "sigma_mult": config.sigma_mult,
            "any_significant": any_significant,
            "triggers": sorted(set(triggers)),
        },
    }

    day_dir = DAILY_ROOT / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / f"{OBSERVER}.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    last_7 = _last_7_summary(date_str)
    if not any(item["date_utc"] == date_str for item in last_7):
        last_7.append({"date_utc": date_str, "significant_count": significant_count, "mass_event": mass_event})
    last_7 = sorted(last_7, key=lambda row: row["date_utc"])[-7:]
    _write_latest_summary(date_str, any_significant, last_7)

    return output


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
