#!/usr/bin/env bash
# Production heartbeat + dashboard website publisher.
#
# This script is intentionally conservative: it runs the existing project
# scripts, copies dashboard exports to the local GitHub Pages checkout, and only
# commits/pushes the Pages checkout when tracked dashboard files actually
# changed. It does not run git clean or remove state files.

set -Eeuo pipefail
IFS=$'\n\t'

log() {
  printf '[heartbeat_and_publish_website] %s\n' "$*"
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pages_repo="${WORLD_OBSERVER_PAGES_REPO:-$HOME/dennishilk.github.io}"
python_bin="${PYTHON:-python3}"
snapshot_date="$(date -u +%F)"

cd "$repo_root"

log "running heartbeat_push.py"
"$python_bin" scripts/heartbeat_push.py

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
