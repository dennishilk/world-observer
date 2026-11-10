#!/usr/bin/env python3
"""Read-only WoW Forever character snapshot for dennishilk.com.

Run as nebu on Worldnode. Secrets are read only from a private credentials file.
No token, raw provider payload, or long-term character history is published.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_BASE = "https://eu.api.blizzard.com/profile/wow/character/dennis-hilk"
OAUTH_URL = "https://oauth.battle.net/token"
NAMESPACE = "profile-forever-eu"
DEFAULT_CREDENTIALS = Path.home() / ".config/wow-forever-observer/credentials"
DEFAULT_OUTPUT = Path("/srv/www/dennishilk.github.io/world-observer/data/wow-forever-dennis-hilk.json")
USER_AGENT = "DennisHilk-WoW-Forever-Observer/1.0 (personal read-only character dashboard)"
MAX_RESPONSE_BYTES = 2_000_000


class CollectorError(Exception):
    """Sanitized error suitable for logs without credentials."""


def credentials(path: Path) -> tuple[str, str]:
    if path.is_symlink() or not path.is_file():
        raise CollectorError("Credentials file missing or is a symlink")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise CollectorError("Credentials permissions must exclude group/other access")
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 2 or not lines[0] or not lines[1]:
        raise CollectorError("Credentials must contain exactly two nonempty lines")
    return lines[0], lines[1]


def request_json(request: urllib.request.Request, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise CollectorError(f"Provider returned HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise CollectorError("Provider connection failed") from None
    except TimeoutError:
        raise CollectorError("Provider request timed out") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise CollectorError("Provider response exceeded size limit")
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise CollectorError("Provider returned invalid JSON") from None
    if not isinstance(obj, dict):
        raise CollectorError("Provider returned an unexpected JSON value")
    return obj


def access_token(client_id: str, client_secret: str, timeout: float) -> str:
    auth = base64.b64encode((client_id + ":" + client_secret).encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        OAUTH_URL,
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": "Basic " + auth,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    data = request_json(req, timeout)
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise CollectorError("Provider did not issue an access token")
    return token


def profile_resource(token: str, endpoint: str, timeout: float) -> dict:
    if endpoint not in ("", "/equipment", "/professions"):
        raise CollectorError("Unexpected API resource")
    params = urllib.parse.urlencode({"namespace": NAMESPACE, "locale": "de_DE"})
    req = urllib.request.Request(
        API_BASE + endpoint + "?" + params,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    return request_json(req, timeout)


def valid_int(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def optional_int(source: dict, key: str, maximum: int) -> int | None:
    val = source.get(key)
    return val if valid_int(val, 0, maximum) else None


def snapshot(profile: dict, gear: dict, jobs: dict, now: datetime) -> dict:
    if profile.get("name") != "Dennis" or profile.get("surname") != "Hilk":
        raise CollectorError("Character identity did not match Dennis Hilk")
    level = profile.get("level")
    if not valid_int(level, 1, 100):
        raise CollectorError("Invalid character level")
    character = {"name": "Dennis", "surname": "Hilk", "level": level}
    for key, maximum in (
        ("experience", 1_000_000_000),
        ("average_item_level", 10_000),
        ("last_login_timestamp", 9_000_000_000_000),
    ):
        val = optional_int(profile, key, maximum)
        if val is not None:
            character[key] = val

    equipped_items = gear.get("equipped_items", [])
    if not isinstance(equipped_items, list):
        raise CollectorError("Unexpected equipment response")
    equipment = []
    for item in equipped_items:
        if not isinstance(item, dict):
            continue
        slot = item.get("slot", {})
        slot_name = slot.get("name") if isinstance(slot, dict) else None
        name = item.get("name")
        if not isinstance(slot_name, str) or not isinstance(name, str):
            continue
        if not 0 < len(slot_name) <= 100 or not 0 < len(name) <= 140:
            continue
        entry = {"slot": slot_name, "name": name}
        lvl = item.get("level")
        if isinstance(lvl, dict):
            item_level = optional_int(lvl, "value", 10_000)
            if item_level is not None:
                entry["item_level"] = item_level
        equipment.append(entry)

    professions = []
    for category in ("primaries", "secondaries"):
        group = jobs.get(category, [])
        if not isinstance(group, list):
            raise CollectorError("Unexpected professions response")
        for record in group:
            if not isinstance(record, dict):
                continue
            profession = record.get("profession", {})
            name = profession.get("name") if isinstance(profession, dict) else None
            if not isinstance(name, str) or not 0 < len(name) <= 100:
                continue
            tiers = record.get("tiers", [])
            if not isinstance(tiers, list):
                continue
            for tier in tiers[:8]:
                if not isinstance(tier, dict):
                    continue
                points = tier.get("skill_points")
                maximum = tier.get("max_skill_points")
                if valid_int(points, 0, 1000) and valid_int(maximum, 1, 1000):
                    professions.append({
                        "name": name,
                        "skill_points": points,
                        "max_skill_points": maximum,
                    })
    now = now.astimezone(timezone.utc)
    # Intentionally short retention; no permanent API-derived history in Git.
    expires = now + timedelta(days=7)
    iso = lambda moment: moment.isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "source": "blizzard-forever-eu",
        "last_success_at": iso(now),
        "expires_at": iso(expires),
        "character": character,
        "equipment": equipment,
        "professions": professions,
    }


def publish_atomic(output: Path, data: dict) -> None:
    if not output.parent.is_dir():
        raise CollectorError("Public output directory does not exist")
    fd, temp_name = tempfile.mkstemp(prefix=".wow-forever-", suffix=".tmp", dir=output.parent)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, output)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch WoW Forever public character snapshot")
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate without publishing")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 60:
        parser.error("--timeout must be 1..60 seconds")
    try:
        client_id, secret = credentials(args.credentials)
        token = access_token(client_id, secret, args.timeout)
        profile = profile_resource(token, "", args.timeout)
        gear = profile_resource(token, "/equipment", args.timeout)
        jobs = profile_resource(token, "/professions", args.timeout)
        data = snapshot(profile, gear, jobs, datetime.now(timezone.utc))
        if not args.dry_run:
            publish_atomic(args.output, data)
    except (CollectorError, OSError) as exc:
        # Never print provider response bodies, tokens, IDs or credentials.
        message = str(exc) if isinstance(exc, CollectorError) else type(exc).__name__
        print("WoW Forever collector failed: " + message, file=sys.stderr)
        return 1
    label = "Validated" if args.dry_run else "Published"
    print(f"{label}: Dennis Hilk level {data['character']['level']}; "
          f"{len(data['equipment'])} equipped items; "
          f"{len(data['professions'])} profession tiers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
