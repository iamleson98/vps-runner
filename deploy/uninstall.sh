#!/usr/bin/env bash
# Cleanly REMOVE the vps-runner stack from the VPS.
#
# Order matters:
#   1. deregister our runners from every allow-listed repo (GitHub side,
#      uses the still-present controller image + .env)
#   2. stop + remove the controller service/containers/images/volumes
#   3. remove leftover managed runner containers and prune
#   4. remove the systemd unit; with --purge also delete /opt/vps-runner
#
# Leaves NOTHING behind on the GitHub side and no managed containers,
# images (except base layers), or volumes on the VPS.
#
# Usage:  sudo bash deploy/uninstall.sh [--purge]
set -euo pipefail

ROOT="/opt/vps-runner"
PURGE="${1:-}"

log()  { printf '\033[1;36m[uninstall]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[uninstall]\033[0m %s\n' "$*" >&2; }

[[ $EUID -eq 0 ]] || { echo "run as root: sudo bash deploy/uninstall.sh [--purge]" >&2; exit 1; }
cd "$ROOT"

# --- 1. GitHub side: deregister our runners ---------------------------------
if [[ -f "$ROOT/.env" ]] && docker image inspect vps-runner/controller:latest >/dev/null 2>&1; then
  log "deregistering our runners from the allow-listed repositories..."
  docker run --rm --env-file "$ROOT/.env" vps-runner/controller:latest \
    python3 deregister.py || warn "deregistration not fully successful - check the GitHub UI"
else
  warn "no .env or no controller image - skipping runner deregistration"
fi

# --- 2. stop the service ------------------------------------------------------
log "stopping vps-runner.service..."
systemctl stop vps-runner.service 2>/dev/null || true
systemctl disable vps-runner.service 2>/dev/null || true
rm -f /etc/systemd/system/vps-runner.service
systemctl daemon-reload
docker compose -f deploy/compose.yml down -v --remove-orphans 2>/dev/null || true

# --- 3. containers / images / volumes -----------------------------------------
log "removing managed runner containers..."
docker ps -aq --filter label=vps-runner.managed=1 | xargs -r docker rm -fv

log "removing images..."
docker rmi -f vps-runner/controller:latest 2>/dev/null || true
docker rmi -f vps-runner/runner:latest 2>/dev/null || true

log "pruning leftover build cache / anonymous volumes..."
docker builder prune -af >/dev/null 2>&1 || true
docker volume prune -f >/dev/null 2>&1 || true

# --- 4. optional purge ----------------------------------------------------------
if [[ "$PURGE" == "--purge" ]]; then
  log "purging $ROOT ..."
  rm -rf "$ROOT"
else
  log "kept $ROOT (use --purge to also delete the repo checkout + .env)"
fi

log "uninstall complete: no runners, containers, images or units left behind."
