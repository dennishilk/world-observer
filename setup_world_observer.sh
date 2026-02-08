#!/usr/bin/env bash
# setup_world_observer.sh
#
# Purpose:
#   Minimal, reproducible Debian 13 setup for the "world-observer" project.
#   This script is intentionally boring and safe: no Docker, no databases,
#   no tokens, no firewall changes, no cloud-specific assumptions.
#
# Philosophy:
#   - Long-term maintainability > convenience
#   - Idempotent and safe to re-run
#   - SSH deploy key only (repo-scoped)
#   - Minimal services, headless server
#
# Usage:
#   sudo bash setup_world_observer.sh

set -euo pipefail

OBSERVER_USER="${SUDO_USER:-$(whoami)}"

log() {
  printf '\n[world-observer] %s\n' "$*"
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)." >&2
    exit 1
  fi
}

ensure_directory() {
  local dir="$1"
  local owner="$2"
  local group="$3"
  local mode="$4"

  if [[ ! -d "$dir" ]]; then
    mkdir -p "$dir"
  fi
  chown "$owner:$group" "$dir"
  chmod "$mode" "$dir"
}

ensure_line_in_file() {
  local line="$1"
  local file="$2"

  if [[ ! -f "$file" ]]; then
    touch "$file"
  fi
  if ! grep -Fxq "$line" "$file"; then
    echo "$line" >> "$file"
  fi
}

require_root

if ! getent passwd "$OBSERVER_USER" >/dev/null 2>&1; then
  echo "ERROR: User '$OBSERVER_USER' does not exist. Create the user first and re-run." >&2
  exit 1
fi

OBSERVER_HOME="$(getent passwd "$OBSERVER_USER" | cut -d: -f6)"
if [[ -z "$OBSERVER_HOME" || ! -d "$OBSERVER_HOME" ]]; then
  echo "ERROR: User '$OBSERVER_USER' does not have a valid home directory." >&2
  exit 1
fi

log "Updating base system and installing required packages..."
export DEBIAN_FRONTEND=noninteractive
apt update
apt upgrade -y
apt install -y \
  python3 \
  python3-venv \
  python3-pip \
  git \
  cron \
  openssh-client \
  ca-certificates \
  curl \
  jq \
  tmux \
  htop \
  unzip \
  locales \
  tzdata \
  zram-tools \
  fonts-dejavu-core \
  fonts-dejavu-extra

log "Ensuring locale en_US.UTF-8 is available..."
if ! locale -a | grep -qx "en_US.utf8"; then
  echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen
  locale-gen
fi
update-locale LANG=en_US.UTF-8

log "Setting timezone to UTC..."
if [[ -f /etc/timezone ]]; then
  echo "UTC" > /etc/timezone
fi
timedatectl set-timezone UTC

# User creation intentionally removed: the installer now uses an existing user
# (derived from sudo) to avoid SSH and account-management conflicts.

log "Ensuring /opt/world-observer exists and is owned by ${OBSERVER_USER}..."
ensure_directory "/opt/world-observer" "$OBSERVER_USER" "$OBSERVER_USER" "0755"

log "Configuring Python virtual environment for ${OBSERVER_USER}..."
if [[ ! -d /opt/world-observer/.venv ]]; then
  sudo -u "$OBSERVER_USER" python3 -m venv /opt/world-observer/.venv
fi
sudo -u "$OBSERVER_USER" /opt/world-observer/.venv/bin/pip install --upgrade pip
sudo -u "$OBSERVER_USER" /opt/world-observer/.venv/bin/pip install dnspython
sudo -u "$OBSERVER_USER" /opt/world-observer/.venv/bin/pip install pillow

log "Configuring zram (memory pressure smoothing / OOM protection)..."
# zram-tools reads /etc/default/zramswap on Debian.
# We explicitly set LZ4 compression and size to 50% of system RAM.
ensure_line_in_file "ALGO=lz4" /etc/default/zramswap
ensure_line_in_file "PERCENT=50" /etc/default/zramswap
systemctl enable --now zramswap.service

log "Preparing SSH deploy key for GitHub (${OBSERVER_USER} user)..."
sudo -u "$OBSERVER_USER" mkdir -p "${OBSERVER_HOME}/.ssh"
sudo -u "$OBSERVER_USER" chmod 700 "${OBSERVER_HOME}/.ssh"

if [[ ! -f "${OBSERVER_HOME}/.ssh/id_ed25519_world_observer" ]]; then
  sudo -u "$OBSERVER_USER" ssh-keygen \
    -t ed25519 \
    -f "${OBSERVER_HOME}/.ssh/id_ed25519_world_observer" \
    -N "" \
    -C "world-observer-deploy-key"
fi
sudo -u "$OBSERVER_USER" chmod 600 "${OBSERVER_HOME}/.ssh/id_ed25519_world_observer"
sudo -u "$OBSERVER_USER" chmod 644 "${OBSERVER_HOME}/.ssh/id_ed25519_world_observer.pub"

log "PUBLIC KEY (add as GitHub Deploy Key with read/write access):"
cat "${OBSERVER_HOME}/.ssh/id_ed25519_world_observer.pub"

cat <<'INSTRUCTIONS'

Add this key as a DEPLOY KEY in your GitHub repository:
  Path: GitHub → Repo → Settings → Deploy Keys
  Access: Read/Write required

Press Enter to continue once the deploy key is added.
INSTRUCTIONS
read -r </dev/tty || true

log "Writing SSH config for GitHub..."
if [[ ! -f "${OBSERVER_HOME}/.ssh/config" ]]; then
  sudo -u "$OBSERVER_USER" touch "${OBSERVER_HOME}/.ssh/config"
fi
sudo -u "$OBSERVER_USER" chmod 600 "${OBSERVER_HOME}/.ssh/config"
sudo -u "$OBSERVER_USER" tee "${OBSERVER_HOME}/.ssh/config" >/dev/null <<'SSHCONF'
Host github.com
  IdentityFile ~/.ssh/id_ed25519_world_observer
  IdentitiesOnly yes
SSHCONF

log "Configuring git identity for ${OBSERVER_USER}..."
sudo -u "$OBSERVER_USER" git config --global user.name "world-observer"
sudo -u "$OBSERVER_USER" git config --global user.email "observer@localhost"

log "Validating SSH connectivity to GitHub..."
set +e
sudo -u "$OBSERVER_USER" ssh -T git@github.com
ssh_status=$?
set -e
if [[ "$ssh_status" -eq 1 || "$ssh_status" -eq 0 ]]; then
  log "SSH connection to GitHub succeeded (expected exit code 1 or 0)."
else
  echo "WARNING: SSH connection to GitHub failed (exit code: $ssh_status)." >&2
fi

log "Ensuring cron service is enabled and running..."
systemctl enable --now cron

log "Creating commented cron example..."
cat <<'CRONEX' > /opt/world-observer/cron_example.txt
# Example daily cron job for world-observer (commented out):
# 0 2 * * * cd /opt/world-observer && \
#   source .venv/bin/activate && \
#   python scripts/run_daily.py && \
#   bash scripts/git_publish.sh
CRONEX
chown "$OBSERVER_USER:$OBSERVER_USER" /opt/world-observer/cron_example.txt
chmod 0644 /opt/world-observer/cron_example.txt

cat <<'SECURITY'

SECURITY NOTES (not applied automatically):
  Recommended outbound firewall policy (default deny):
    - Allow DNS: 53 (udp/tcp) and 853 (tcp)
    - Allow HTTPS: 443 (tcp)
    - Allow SSH to github.com: 22 (tcp)
  Do NOT open inbound ports unless required for administration.

SECURITY

log "Verifying PNG generation prerequisites..."
if ! sudo -u "$OBSERVER_USER" /opt/world-observer/.venv/bin/python -c "from PIL import Image, ImageDraw, ImageFont"; then
  echo "ERROR: PNG generation prerequisites missing (Pillow import failed)." >&2
  exit 1
fi
log "PNG generation prerequisites OK"

log "Setup complete. Review the output above for deploy key instructions and notes."
