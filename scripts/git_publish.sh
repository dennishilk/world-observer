#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

snapshot_date="$(date -u +%F)"
deploy_key="${WORLD_OBSERVER_DEPLOY_KEY:-$HOME/.ssh/id_ed25519_world_observer}"

if [[ -f "$deploy_key" ]]; then
  export GIT_SSH_COMMAND="ssh -i $deploy_key -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
fi

# Stage project outputs and updates.
git add -A

if git diff --cached --quiet; then
  echo "[git_publish] no staged changes"
  exit 0
fi

git commit -m "world-observer: daily snapshot ${snapshot_date}"
git push
