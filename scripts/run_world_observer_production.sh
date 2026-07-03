#!/usr/bin/env bash
# Production systemd entrypoint for the world-observer daily pipeline.
#
# This wrapper intentionally delegates observer work to the existing project
# scripts. It does not change observer behavior, run git clean, or delete state.
# It is safe for systemd ExecStart and exits successfully when there are no
# dashboard changes to publish.

set -Eeuo pipefail
IFS=$'\n\t'

log() {
  printf '[run_world_observer_production] %s\n' "$*"
}

run() {
  log "running: $*"
  "$@"
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON:-python3}"
pages_repo="${WORLD_OBSERVER_PAGES_REPO:-$HOME/dennishilk.github.io}"
snapshot_date="${WORLD_OBSERVER_DATE_UTC:-$(date -u +%F)}"

cd "$repo_root"

log "starting production run for ${snapshot_date}"

# Run the existing daily observer orchestration. This updates daily/latest data
# and publishes repository changes according to scripts/run_daily_cron.py.
run "$python_bin" scripts/run_daily_cron.py --date "$snapshot_date"

# Write and publish a heartbeat unless explicitly disabled. This preserves the
# existing heartbeat script behavior, including its own locking and retention.
if [[ "${WORLD_OBSERVER_SKIP_HEARTBEAT:-0}" == "1" ]]; then
  log "heartbeat skipped because WORLD_OBSERVER_SKIP_HEARTBEAT=1"
else
  run "$python_bin" scripts/heartbeat_push.py
fi

# Export the dashboard from the latest observer data, then copy it into the
# local GitHub Pages checkout.
run "$python_bin" scripts/export_dashboard.py
run "$python_bin" scripts/publish_dashboard_to_pages.py --pages-repo "$pages_repo"

cd "$pages_repo"

# Stage only the dashboard files managed by publish_dashboard_to_pages.py.
git add -- world-observer/dashboard

if git diff --cached --quiet -- world-observer/dashboard; then
  log "no dashboard changes to publish"
  exit 0
fi

log "committing dashboard changes"
git commit -m "world-observer: publish dashboard ${snapshot_date}" -- world-observer/dashboard

log "pushing dashboard changes"
git push

log "production run completed"
