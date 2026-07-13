#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
log(){ printf '[run_horizon_observer_production] %s\n' "$*"; }
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
python_bin="${PYTHON:-$repo_root/.venv/bin/python}"
[[ -x "$python_bin" ]] || python_bin="${PYTHON:-python3}"
lock_dir="${WORLD_OBSERVER_LOCK_DIR:-$repo_root/state}"
mkdir -p "$lock_dir" data/latest dashboard/latest
exec 9>"$lock_dir/horizon_observer.lock"
if ! flock -n 9; then log "another Horizon run is active; skipping"; exit 0; fi
# Avoid colliding with the daily orchestrator while it owns its production lock.
exec 8>"$repo_root/state/daily_run.lock"
if ! flock -n 8; then log "daily production run is active; skipping"; exit 0; fi
website_out="${WORLD_OBSERVER_HORIZON_WEBSITE_OUTPUT:-/srv/www/dennishilk.github.io/world-observer/dashboard/latest/horizon-observer.json}"
tmp="$(mktemp "$repo_root/state/horizon-observer.XXXXXX.json")"
cleanup(){ rm -f "$tmp"; }
trap cleanup EXIT
log "generating Horizon Observer JSON"
if ! "$python_bin" observers/horizon-observer/observer.py > "$tmp"; then log "observer failed; preserving previous output"; exit 1; fi
if ! "$python_bin" -m json.tool "$tmp" >/dev/null; then log "JSON validation failed; preserving previous output"; exit 1; fi
install_atomic(){ local src="$1" dest="$2" dir; dir="$(dirname "$dest")"; mkdir -p "$dir"; local t; t="$(mktemp "$dir/.horizon-observer.XXXXXX")"; cp "$src" "$t"; chmod 0644 "$t"; mv -f "$t" "$dest"; }
install_atomic "$tmp" data/latest/horizon-observer.json
install_atomic "$tmp" dashboard/latest/horizon-observer.json
install_atomic "$tmp" "$website_out"
log "updated Horizon Observer runtime JSON only"
