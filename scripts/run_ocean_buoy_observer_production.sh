#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
log() { printf '[ocean-buoy-observer] %s\n' "$*"; }

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$root"
python="${PYTHON:-$root/.venv/bin/python}"; [[ -x "$python" ]] || python="${PYTHON:-python3}"
observer="${WORLD_OBSERVER_OCEAN_BUOY_OBSERVER:-observers/ocean-buoy-observer/observer.py}"
latest="${WORLD_OBSERVER_LATEST_DIR:-data/latest}"
dashboard="${WORLD_OBSERVER_DASHBOARD_DIR:-dashboard}"
snapshots="${WORLD_OBSERVER_OCEAN_BUOY_SNAPSHOT_DIR:-data/hourly/ocean-buoy-observer}"
history="${WORLD_OBSERVER_OCEAN_BUOY_HISTORY_DIR:-state/ocean-buoy-observer-history}"
state="${WORLD_OBSERVER_STATE_DIR:-state}"
website_out="${WORLD_OBSERVER_OCEAN_BUOY_WEBSITE_OUTPUT:-/srv/www/dennishilk.github.io/world-observer/dashboard/latest/ocean-buoy-observer.json}"
stamp="${WORLD_OBSERVER_TIMESTAMP_UTC:-$(date -u +%Y-%m-%dT%H-%M-%SZ)}"
day="${WORLD_OBSERVER_DATE_UTC:-${stamp:0:10}}"
mkdir -p "$latest" "$dashboard" "$snapshots" "$history" "$state"

exec 9>"$state/ocean_buoy_observer.lock"
if ! flock -n 9; then log 'another run is active; skipping'; exit 0; fi
exec 8>"$state/daily_run.lock"
if ! flock -n 8; then log 'daily workflow is active; skipping'; exit 0; fi

tmp="$(mktemp "$state/ocean-buoy.XXXXXX.json")"; trap 'rm -f "$tmp"' EXIT
if ! "$python" "$observer" >"$tmp"; then log 'ERROR collection failed; last-known-good retained'; exit 1; fi
if ! "$python" "$observer" --validate "$tmp"; then log 'ERROR validation failed; last-known-good retained'; exit 2; fi

atomic() { local src="$1" dst="$2" dir stage; dir="$(dirname "$dst")"; mkdir -p "$dir"; stage="$(mktemp "$dir/.ocean-buoy.XXXXXX")"; cp -- "$src" "$stage"; chmod 0644 "$stage"; mv -f -- "$stage" "$dst"; }
atomic "$tmp" "$latest/ocean-buoy-observer.json"
atomic "$tmp" "$snapshots/$stamp.json"

aggregate="$(mktemp "$state/ocean-buoy-aggregate.XXXXXX.json")"
"$python" - "$tmp" "$day" >"$aggregate" <<'PY'
import json, sys
p=json.load(open(sys.argv[1], encoding="utf-8"))
print(json.dumps({"observer":"ocean-buoy-observer","date":sys.argv[2],"generated_at":p["observer"]["generated_at"],"observer_status":p["observer"]["status"],"statistics":p["statistics"],"coverage":p["coverage"]},sort_keys=True,separators=(",",":")))
PY
atomic "$aggregate" "$history/$day.json"; rm -f "$aggregate"

"$python" scripts/export_dashboard.py --latest-dir "$latest" --dashboard-dir "$dashboard"
atomic "$dashboard/latest/ocean-buoy-observer.json" "$website_out"

removed=0
while IFS= read -r -d '' file; do rm -f -- "$file"; removed=$((removed+1)); done < <(find "$snapshots" -maxdepth 1 -type f -name '????-??-??T??-??-??Z.json' ! -newermt '7 days ago' -print0)
log "updated latest, dashboard, snapshot, and compact daily history; pruned $removed snapshot(s)"
