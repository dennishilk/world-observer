#!/usr/bin/env bash
# setup_world_observer.sh
#
# Purpose:
#   Re-runnable Debian setup for the "world-observer" project.
#   No Docker, no cloud lock-in, and no observer logic changes.

set -euo pipefail

OBSERVER_USER="${SUDO_USER:-$(whoami)}"
OBSERVER_HOME="$(eval echo "~${OBSERVER_USER}")"
OBSERVER_GROUP="${OBSERVER_GROUP:-$OBSERVER_USER}"
REPO_DIR="${REPO_DIR:-${OBSERVER_HOME}/world-observer}"
VENV_DIR="${REPO_DIR}/.venv"
SSH_KEY_PATH="${OBSERVER_HOME}/.ssh/id_ed25519_world_observer"
LOG_DIR="${REPO_DIR}/logs"

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

  mkdir -p "$dir"
  chown "$owner:$group" "$dir"
  chmod "$mode" "$dir"
}

ensure_line_in_file() {
  local line="$1"
  local file="$2"

  touch "$file"
  if ! grep -Fxq "$line" "$file"; then
    echo "$line" >> "$file"
  fi
}

ensure_user() {
  if getent passwd "$OBSERVER_USER" >/dev/null 2>&1; then
    log "Using existing user: ${OBSERVER_USER}"
    return
  fi

  log "Creating dedicated user: ${OBSERVER_USER}"
  useradd --create-home --shell /bin/bash "$OBSERVER_USER"
}

configure_locale_timezone() {
  log "Ensuring locale en_US.UTF-8 is available..."
  ensure_line_in_file "en_US.UTF-8 UTF-8" /etc/locale.gen
  locale-gen en_US.UTF-8
  update-locale LANG=en_US.UTF-8

  log "Setting timezone to UTC..."
  if command -v timedatectl >/dev/null 2>&1; then
    timedatectl set-timezone UTC || true
  fi
  ln -snf /usr/share/zoneinfo/UTC /etc/localtime
  echo "UTC" > /etc/timezone
}

configure_zram() {
  log "Configuring zram swap defaults..."
  ensure_line_in_file "ALGO=lz4" /etc/default/zramswap
  ensure_line_in_file "PERCENT=50" /etc/default/zramswap
  ensure_line_in_file "PRIORITY=100" /etc/default/zramswap
  systemctl enable --now zramswap.service
}

configure_ssh_for_github() {
  local ssh_dir="${OBSERVER_HOME}/.ssh"
  local ssh_config="${ssh_dir}/config"

  log "Preparing SSH deploy key for GitHub..."
  ensure_directory "$ssh_dir" "$OBSERVER_USER" "$OBSERVER_GROUP" "0700"

  if [[ ! -f "$SSH_KEY_PATH" ]]; then
    sudo -u "$OBSERVER_USER" ssh-keygen -t ed25519 -N "" -C "world-observer-deploy-key" -f "$SSH_KEY_PATH"
  fi

  chown "$OBSERVER_USER:$OBSERVER_GROUP" "$SSH_KEY_PATH" "${SSH_KEY_PATH}.pub"
  chmod 600 "$SSH_KEY_PATH"
  chmod 644 "${SSH_KEY_PATH}.pub"

  cat > "$ssh_config" <<SSHCONF
Host github.com
  HostName github.com
  User git
  IdentityFile ${SSH_KEY_PATH}
  IdentitiesOnly yes
  AddKeysToAgent no
SSHCONF
  chown "$OBSERVER_USER:$OBSERVER_GROUP" "$ssh_config"
  chmod 600 "$ssh_config"

  log "PUBLIC KEY (add to GitHub Deploy Keys with read/write access):"
  cat "${SSH_KEY_PATH}.pub"

  log "Configuring git identity for ${OBSERVER_USER}..."
  sudo -u "$OBSERVER_USER" git config --global user.name "world-observer"
  sudo -u "$OBSERVER_USER" git config --global user.email "observer@localhost"

  log "Testing SSH connectivity to GitHub..."
  set +e
  sudo -u "$OBSERVER_USER" ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -T git@github.com
  local ssh_status=$?
  set -e

  if [[ "$ssh_status" -eq 0 || "$ssh_status" -eq 1 ]]; then
    log "SSH connectivity check completed successfully (exit code ${ssh_status})."
  else
    echo "WARNING: SSH connectivity test failed with exit code ${ssh_status}." >&2
  fi
}


configure_repo_git_ssh() {
  if [[ ! -d "${REPO_DIR}/.git" ]]; then
    log "Skipping repository git SSH config (no .git directory at ${REPO_DIR})."
    return
  fi

  local origin_url
  origin_url="$(sudo -u "$OBSERVER_USER" git -C "$REPO_DIR" remote get-url origin 2>/dev/null || true)"
  if [[ -z "$origin_url" ]]; then
    log "No origin remote configured; skipping remote rewrite."
  elif [[ "$origin_url" =~ ^https://github.com/(.+/.+)\.git$ ]]; then
    local repo_path="${BASH_REMATCH[1]}"
    sudo -u "$OBSERVER_USER" git -C "$REPO_DIR" remote set-url origin "git@github.com:${repo_path}.git"
    log "Updated origin remote to SSH for ${repo_path}."
  fi

  sudo -u "$OBSERVER_USER" git -C "$REPO_DIR" config core.sshCommand "ssh -i ${SSH_KEY_PATH} -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
}

install_cron_jobs() {
  local heartbeat_job="0 * * * * /bin/bash -lc 'cd ${REPO_DIR} && . ${VENV_DIR}/bin/activate && python scripts/heartbeat_push.py >> ${LOG_DIR}/cron.log 2>&1'"
  local daily_job="5 2 * * * /bin/bash -lc 'cd ${REPO_DIR} && . ${VENV_DIR}/bin/activate && python scripts/run_daily.py >> ${LOG_DIR}/cron.log 2>&1 && python visualizations/generate_significance_png.py >> ${LOG_DIR}/cron.log 2>&1 && scripts/git_publish.sh >> ${LOG_DIR}/cron.log 2>&1'"

  local existing
  existing="$(sudo -u "$OBSERVER_USER" crontab -l 2>/dev/null || true)"

  if ! printf '%s\n' "$existing" | grep -Fqx "$heartbeat_job"; then
    existing="${existing}"$'\n'"${heartbeat_job}"
  fi

  if ! printf '%s\n' "$existing" | grep -Fqx "$daily_job"; then
    existing="${existing}"$'\n'"${daily_job}"
  fi

  printf '%s\n' "$existing" | awk 'NF' | sudo -u "$OBSERVER_USER" crontab -
}

require_root

log "Updating package index and installing required packages..."
export DEBIAN_FRONTEND=noninteractive
apt update
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

ensure_user
configure_locale_timezone

log "Ensuring project directories and ownership..."
ensure_directory "/opt/world-observer" "$OBSERVER_USER" "$OBSERVER_GROUP" "0755"
ensure_directory "$REPO_DIR" "$OBSERVER_USER" "$OBSERVER_GROUP" "0755"
ensure_directory "$LOG_DIR" "$OBSERVER_USER" "$OBSERVER_GROUP" "0755"

log "Configuring Python virtual environment and libraries..."
if [[ ! -d "$VENV_DIR" ]]; then
  sudo -u "$OBSERVER_USER" python3 -m venv "$VENV_DIR"
fi
sudo -u "$OBSERVER_USER" "$VENV_DIR/bin/pip" install --upgrade pip
if [[ -f "$REPO_DIR/requirements.txt" ]]; then
  sudo -u "$OBSERVER_USER" "$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"
else
  sudo -u "$OBSERVER_USER" "$VENV_DIR/bin/pip" install dnspython matplotlib pillow
fi

configure_zram
configure_ssh_for_github
configure_repo_git_ssh

log "Ensuring cron service is enabled and running..."
systemctl enable --now cron

log "Installing idempotent cron jobs for ${OBSERVER_USER}..."
install_cron_jobs

log "Verifying PNG generation prerequisites..."
if sudo -u "$OBSERVER_USER" "$VENV_DIR/bin/python" -c "from PIL import Image, ImageDraw, ImageFont"; then
  log "PNG generation prerequisites OK"
else
  echo "ERROR: Pillow import check failed." >&2
  exit 1
fi

log "Setup complete."
log "Cron logs: ${LOG_DIR}/cron.log"
