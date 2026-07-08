#!/usr/bin/env bash
# Production hourly refresh for the Wiesmoor weather observer only.
#
# This intentionally does not run scripts/run_daily.py or any other observer.
# It refreshes the canonical latest payload, exports dashboard JSON, and then
# publishes the dashboard data using the same local website checkout model as
# the daily production scripts.

set -euo pipefail
IFS=$'\n\t'

log() {
  printf '[refresh_wiesmoor_weather] %s\n' "$*"
}

run() {
  log "running: $*"
  "$@"
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON:-python3}"
pages_repo="${WORLD_OBSERVER_PAGES_REPO:-/srv/www/dennishilk.github.io}"
sync_script="${WORLD_OBSERVER_WEBSITE_SYNC_SCRIPT:-${pages_repo}/scripts/sync-world-observer-dashboard.sh}"
snapshot_date="${WORLD_OBSERVER_DATE_UTC:-$(date -u +%F)}"
observer="wiesmoor-weather"

daily_dir="${repo_root}/data/daily/${snapshot_date}"
latest_dir="${repo_root}/data/latest"
dashboard_latest_dir="${repo_root}/dashboard/latest"
tmp_payload="$(mktemp "${TMPDIR:-/tmp}/wiesmoor-weather.XXXXXX.json")"

cleanup() {
  rm -f "$tmp_payload"
}
trap cleanup EXIT

cd "$repo_root"

log "starting hourly Wiesmoor weather refresh for ${snapshot_date}"

run "$python_bin" "observers/${observer}/observer.py" > "$tmp_payload"
run "$python_bin" -m json.tool "$tmp_payload" >/dev/null

run mkdir -p "$daily_dir" "$latest_dir"
run cp "$tmp_payload" "${daily_dir}/${observer}.json"
run cp "${daily_dir}/${observer}.json" "${latest_dir}/${observer}.json"

run "$python_bin" scripts/export_dashboard.py

if [[ ! -s "${dashboard_latest_dir}/${observer}.json" ]]; then
  log "dashboard latest payload was not exported: ${dashboard_latest_dir}/${observer}.json"
  exit 1
fi

if [[ -x "$sync_script" ]]; then
  log "publishing dashboard with website sync script: ${sync_script}"
  run "$sync_script"
else
  log "website sync script not executable at ${sync_script}; using publish_dashboard_to_pages.py"
  run "$python_bin" scripts/publish_dashboard_to_pages.py --pages-repo "$pages_repo"
fi

log "hourly Wiesmoor weather refresh completed"
