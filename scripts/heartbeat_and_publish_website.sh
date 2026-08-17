#!/usr/bin/env bash
# Production heartbeat + dashboard website publisher.
#
# This script is intentionally conservative: it runs the existing project
# scripts, copies dashboard exports to the local GitHub Pages checkout, and only
# commits/pushes the Pages checkout when tracked dashboard files actually
# changed. It does not run git clean or remove state files except for an expired
# failed Space / Satellites same-day cache entry so that a policy-compliant
# recovery attempt can occur after the CelesTrak update interval.

set -Eeuo pipefail
IFS=$'\n\t'

log() {
  printf '[heartbeat_and_publish_website] %s\n' "$*"
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pages_repo="${WORLD_OBSERVER_PAGES_REPO:-$HOME/dennishilk.github.io}"
python_bin="${PYTHON:-python3}"
snapshot_date="$(date -u +%F)"
space_state="$repo_root/state/space-satellites/${snapshot_date}.json"

cd "$repo_root"

log "running heartbeat_push.py"
"$python_bin" scripts/heartbeat_push.py

# The dedicated Space / Satellites observer normally caches every UTC date in
# state/. A failed cache entry must not suppress recovery for the entire day,
# though: CelesTrak GP data has a two-hour update interval, so a failed attempt
# is allowed to expire after two hours. There are still no immediate retries.
log "checking space-satellites failed-cache age"
"$python_bin" - "$space_state" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RETRY_COOLDOWN_SECONDS = 2 * 60 * 60
path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(0)

try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(0)

if not isinstance(payload, dict) or payload.get("status") == "ok":
    raise SystemExit(0)

value = payload.get("collected_at_utc")
if not isinstance(value, str) or not value.strip():
    raise SystemExit(0)

candidate = value.strip()
if candidate.endswith("Z"):
    candidate = candidate[:-1] + "+00:00"
try:
    collected_at = datetime.fromisoformat(candidate)
except ValueError:
    raise SystemExit(0)
if collected_at.tzinfo is None:
    collected_at = collected_at.replace(tzinfo=timezone.utc)

age_seconds = (datetime.now(timezone.utc) - collected_at.astimezone(timezone.utc)).total_seconds()
if age_seconds >= RETRY_COOLDOWN_SECONDS:
    path.unlink()
    print(f"expired failed cache after {age_seconds / 3600:.2f}h: {path.name}")
PY

# Calling the observer hourly still produces at most one successful collection
# per UTC day. After a source failure, the block above permits another attempt
# only after the two-hour cooldown.
log "running cached space-satellites observer"
WORLD_OBSERVER_DATE_UTC="$snapshot_date" "$python_bin" observers/space-satellites/observer.py >/dev/null

# A transient CelesTrak timeout or other source failure must not replace the
# website's last complete snapshot with an empty/partial one. Keep the failed
# daily state for diagnostics, but restore the newest earlier successful state
# into data/latest and dashboard/latest until a later recovery attempt succeeds.
log "preserving last successful space-satellites snapshot when needed"
"$python_bin" - "$repo_root" "$snapshot_date" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
date_str = sys.argv[2]
state_dir = root / "state" / "space-satellites"
current_path = state_dir / f"{date_str}.json"


def load(path: Path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


current = load(current_path)
if current is None or current.get("status") == "ok":
    raise SystemExit(0)

last_success = None
for path in sorted(state_dir.glob("*.json"), reverse=True):
    payload = load(path)
    if payload is not None and payload.get("observer") == "space-satellites" and payload.get("status") == "ok":
        last_success = payload
        break

if last_success is None:
    raise SystemExit(0)

serialized = json.dumps(last_success, ensure_ascii=False, indent=2) + "\n"
for target in (
    root / "data" / "latest" / "space-satellites.json",
    root / "dashboard" / "latest" / "space-satellites.json",
):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialized, encoding="utf-8")

print(
    "restored last successful snapshot "
    f"from {last_success.get('date', 'unknown')} after current source failure"
)
PY

log "running export_dashboard.py"
"$python_bin" scripts/export_dashboard.py

log "publishing dashboard to ${pages_repo}"
"$python_bin" scripts/publish_dashboard_to_pages.py --pages-repo "$pages_repo"

cd "$pages_repo"

# Stage only the dashboard export managed by publish_dashboard_to_pages.py.
git add -- world-observer/dashboard

if git diff --cached --quiet -- world-observer/dashboard; then
  log "no dashboard changes to publish"
  exit 0
fi

log "committing dashboard changes"
git commit -m "world-observer: publish dashboard ${snapshot_date}" -- world-observer/dashboard

log "pushing dashboard changes"
git push

log "dashboard publish completed"
