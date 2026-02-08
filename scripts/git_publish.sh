#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

snapshot_date="$(date -u +%F)"

# Stage daily outputs and observer updates if any.
git add data/ reports/ observers/ >/dev/null 2>&1 || true

if git diff --cached --quiet; then
  exit 0
fi

git commit -m "world-observer: daily snapshot ${snapshot_date}" >/dev/null

git push >/dev/null
