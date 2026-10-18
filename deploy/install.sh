#!/usr/bin/env bash
# Install / update the vps-runner stack on the VPS.
#
# The repository is rsynced to /opt/vps-runner by the Deploy GitHub workflow
# (scripts/ci_deploy.sh) which also renders /opt/vps-runner/.env from repo
# secrets + variables BEFORE calling this script. Local `make deploy` works
# the same way (it expects you edited .env yourself).
#
# Idempotent: safe to re-run on every deploy.
set -euo pipefail

ROOT="/opt/vps-runner"

log()  { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root: sudo bash deploy/install.sh"

cd "$ROOT"

# --- docker (OVH VPS images do not always ship docker) ----------------------
if ! command -v docker >/dev/null; then
  log "docker not found - installing via get.docker.com ..."
  if command -v curl >/dev/null; then
    curl -fsSL https://get.docker.com | sh
  elif command -v wget >/dev/null; then
    wget -qO- https://get.docker.com | sh
  else
    die "neither curl nor wget found - install one first: apt-get install -y curl"
  fi
  systemctl enable --now docker.service
fi
docker compose version >/dev/null 2>&1 \
  || die "docker compose plugin missing (install docker-compose-plugin)"

# --- images -------------------------------------------------------------------
log "building runner image (pinned + checksum-verified actions/runner)..."
docker build -q -t vps-runner/runner:latest runner-image/

log "building controller image..."
docker compose -f deploy/compose.yml build controller

# --- config --------------------------------------------------------------------
mkdir -p "$ROOT/secrets"
touch "$ROOT/secrets/.gitkeep"

if [[ ! -f "$ROOT/.env" ]]; then
  cp .env.example "$ROOT/.env"
  chmod 600 "$ROOT/.env"
  warn "created $ROOT/.env from the template - EDIT IT NOW (GITHUB_PAT / GITHUB_REPOSITORIES)."
else
  chmod 600 "$ROOT/.env"
  log "using existing $ROOT/.env"
fi

# --- service ---------------------------------------------------------------------
install -m 644 deploy/vps-runner.service /etc/systemd/system/vps-runner.service
systemctl daemon-reload
systemctl enable vps-runner.service

if grep -qE '^GITHUB_PAT=.+\S' "$ROOT/.env" 2>/dev/null \
   && grep -qE '^GITHUB_REPOSITORIES=.+\S' "$ROOT/.env" 2>/dev/null; then
  systemctl restart vps-runner.service
  log "controller started (docker compose up -d --wait)"
else
  warn "controller NOT started yet: fill in GITHUB_PAT and GITHUB_REPOSITORIES in"
  warn "$ROOT/.env, then: sudo systemctl restart vps-runner.service"
fi

log "install done. Useful commands:"
log "  docker logs -f vps-runner-controller              # controller logs"
log "  docker ps --filter label=vps-runner.managed=1     # live runners"
log "  ssh -N -L 8080:localhost:8080 <user>@<vps-ip>      # status page tunnel"
