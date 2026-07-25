#!/usr/bin/env bash
# Hourly, last-known-good production entrypoint for Earthquake Observer.
set -Eeuo pipefail
IFS=$'\n\t'

log() { printf '[run_earthquake_observer_production] %s\n' "$*"; }

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${PYTHON:-$repo_root/.venv/bin/python}"
[[ -x "$python_bin" ]] || python_bin="${PYTHON:-python3}"
observer="${WORLD_OBSERVER_EARTHQUAKE_OBSERVER:-observers/earthquake-observer/observer.py}"
latest_dir="${WORLD_OBSERVER_LATEST_DIR:-data/latest}"
dashboard_dir="${WORLD_OBSERVER_DASHBOARD_DIR:-dashboard}"
hourly_dir="${WORLD_OBSERVER_EARTHQUAKE_HOURLY_DIR:-data/hourly/earthquake-observer}"
state_dir="${WORLD_OBSERVER_STATE_DIR:-state}"
snapshot_hour="${WORLD_OBSERVER_HOUR_UTC:-$(date -u +%Y-%m-%dT%H)}"

mkdir -p "$state_dir" "$latest_dir" "$dashboard_dir" "$hourly_dir"
exec 9>"$state_dir/earthquake_observer.lock"
if ! flock -n 9; then
  log "another Earthquake Observer run is active; skipping"
  exit 0
fi

# The daily runner uses this lock. Skipping is safer than racing its export.
exec 8>"$state_dir/daily_run.lock"
if ! flock -n 8; then
  log "daily production run is active; skipping"
  exit 0
fi

tmp="$(mktemp "$state_dir/earthquake-observer.XXXXXX.json")"
cleanup() { rm -f "$tmp"; }
trap cleanup EXIT

log "collecting Earthquake Observer payload"
if ! "$python_bin" "$observer" >"$tmp"; then
  log "ERROR: observer failed; preserving previous known-good latest file"
  exit 1
fi

if ! "$python_bin" - "$tmp" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    raw = open(path, "rb").read()
    if not raw.strip():
        raise ValueError("empty output")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("JSON root is not an object")
    if payload.get("status") == "error" or payload.get("data_status") == "error" or payload.get("error"):
        raise ValueError("explicit error payload")
    events = payload.get("events")
    if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
        raise ValueError("payload has no usable events array")
except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
    print(f"Earthquake payload validation failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
then
  log "ERROR: validation failed; preserving previous known-good latest file"
  exit 1
fi

install_atomic() {
  local source="$1" destination="$2" destination_dir staging
  destination_dir="$(dirname "$destination")"
  mkdir -p "$destination_dir"
  staging="$(mktemp "$destination_dir/.earthquake-observer.XXXXXX")"
  cp -- "$source" "$staging"
  chmod 0644 "$staging"
  mv -f -- "$staging" "$destination"
}

install_atomic "$tmp" "$latest_dir/earthquake-observer.json"
install_atomic "$tmp" "$hourly_dir/$snapshot_hour.json"

log "refreshing dashboard export"
"$python_bin" scripts/export_dashboard.py --latest-dir "$latest_dir" --dashboard-dir "$dashboard_dir"

removed=0
while IFS= read -r -d '' expired; do
  rm -f -- "$expired"
  removed=$((removed + 1))
done < <(find "$hourly_dir" -maxdepth 1 -type f -name '????-??-??T??.json' ! -newermt '7 days ago' -print0)

log "updated latest, dashboard, and hourly snapshot $snapshot_hour.json; removed $removed snapshot(s) older than 7 days"
