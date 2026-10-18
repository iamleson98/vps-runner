#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ci_deploy.sh - deploy/update the vps-runner stack on the VPS from CI.
#
# Runs on a GitHub-hosted runner. Reads from environment (wired by
# .github/workflows/deploy.yml):
#
#   VPS_SSH_HOST   (secret)  VPS ip/hostname                      [required]
#   VPS_SSH_USER   (secret)  ssh username (root or a sudo user)    [required]
#   VPS_SSH_PORT   (secret)  ssh port                              [optional, 22]
#   VPS_SSH_KEY    (secret)  ssh PRIVATE key (deploy key generated
#                            by the Bootstrap workflow)             [required]
#   GITHUB_PAT     (secret)  PAT used by the controller            [required]
#
#   RUNNER_REPOS         (variable) allow-list "owner/repo,owner2/repo2"
#   MAX_RUNNERS          (variable) default 2
#   MIN_RUNNERS          (variable) default 0
#   RUNNER_MEMORY_GB     (variable) default 2.5
#   RUNNER_LABELS        (variable) default "vps"
#   MOUNT_DOCKER_SOCK    (variable) default true
#   STATUS_TOKEN         (secret, optional) protects the status page
#
# The .env on the VPS is fully re-rendered from these on every deploy, so
# GitHub stays the single source of truth (no manual VPS editing).
# ---------------------------------------------------------------------------
set -euo pipefail

die() { printf '\033[1;31m[deploy]\033[0m %s\n' "$*" >&2; exit 1; }
log() { printf '\033[1;36m[deploy]\033[0m %s\n' "$*"; }

: "${VPS_SSH_HOST:?VPS_SSH_HOST is required}"
: "${VPS_SSH_USER:?VPS_SSH_USER is required}"
: "${VPS_SSH_KEY:?VPS_SSH_KEY is required}"
: "${GITHUB_PAT:?GITHUB_PAT is required}"
: "${RUNNER_REPOS:?RUNNER_REPOS is required (repo variable, allow-list 'owner/repo,...')}"

PORT="${VPS_SSH_PORT:-22}"
REMOTE_TARGET="/opt/vps-runner"

# --- ssh key file -------------------------------------------------------------
KEY_FILE="$(mktemp)"
trap 'rm -f "$KEY_FILE"' EXIT
printf '%s\n' "$VPS_SSH_KEY" > "$KEY_FILE"
chmod 600 "$KEY_FILE"

SSH_BASE=(ssh -i "$KEY_FILE" -p "$PORT"
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout=15
  -o ServerAliveInterval=30
  "${VPS_SSH_USER}@${VPS_SSH_HOST}")
RSYNC_RSH="ssh -i $KEY_FILE -p $PORT -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"

# --- connectivity ---------------------------------------------------------------
log "testing SSH connectivity to ${VPS_SSH_USER}@${VPS_SSH_HOST}:${PORT} ..."
"${SSH_BASE[@]}" 'echo connected: $(whoami)@$(hostname)' >/dev/null \
  || die "cannot SSH - check VPS_SSH_HOST / VPS_SSH_USER / VPS_SSH_KEY / VPS_SSH_PORT"

# --- render .env from secrets + variables -----------------------------------------
log "rendering .env from GitHub secrets/variables ..."
ENV_FILE="$(mktemp)"
{
  echo "# rendered by ci_deploy.sh at $(date -u +%Y-%m-%dT%H:%M:%SZ) - do not edit on the VPS"
  echo "GITHUB_PAT=${GITHUB_PAT}"
  echo "GITHUB_REPOSITORIES=${RUNNER_REPOS}"
  echo "MIN_RUNNERS=${MIN_RUNNERS:-0}"
  echo "MAX_RUNNERS=${MAX_RUNNERS:-2}"
  echo "RUNNER_MEMORY_GB=${RUNNER_MEMORY_GB:-2.5}"
  echo "RUNNER_LABELS=${RUNNER_LABELS:-vps}"
  echo "MATCH_LABELS=${MATCH_LABELS:-${RUNNER_LABELS:-vps}}"
  echo "RUNNER_CPUS=${RUNNER_CPUS:-}"
  echo "MOUNT_DOCKER_SOCK=${MOUNT_DOCKER_SOCK:-true}"
  echo "RUNNER_IMAGE=${RUNNER_IMAGE:-vps-runner/runner:latest}"
  echo "CONTAINER_PREFIX=${CONTAINER_PREFIX:-gha-runner}"
  echo "POLL_INTERVAL=${POLL_INTERVAL:-15}"
  echo "PRUNE_INTERVAL=${PRUNE_INTERVAL:-21600}"
  echo "STATUS_BIND=0.0.0.0"
  echo "STATUS_PORT=${STATUS_PORT:-8080}"
  echo "STATUS_TOKEN=${STATUS_TOKEN:-}"
} > "$ENV_FILE"

# --- prepare remote dir (works for root and sudo users) ----------------------------
"${SSH_BASE[@]}" "sudo -n mkdir -p '$REMOTE_TARGET' && (sudo -n chown -R \$(whoami): '$REMOTE_TARGET' 2>/dev/null || true)"

# --- make sure rsync exists on the VPS (minimal images may lack it) ------------------
if ! "${SSH_BASE[@]}" 'command -v rsync >/dev/null'; then
  log "installing rsync on the VPS ..."
  "${SSH_BASE[@]}" 'sudo -n apt-get update -qq && sudo -n apt-get install -y -qq rsync' \
    || die "rsync is missing on the VPS and could not be installed (apt failed)"
fi

# --- push repo + config --------------------------------------------------------------
log "rsyncing repository to ${VPS_SSH_USER}@${VPS_SSH_HOST}:${REMOTE_TARGET} ..."
rsync -az --delete --rsh "$RSYNC_RSH" \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude 'secrets/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  ./ "${VPS_SSH_USER}@${VPS_SSH_HOST}:${REMOTE_TARGET}/"

scp -q -i "$KEY_FILE" -P "$PORT" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new \
  "$ENV_FILE" "${VPS_SSH_USER}@${VPS_SSH_HOST}:${REMOTE_TARGET}/.env.incoming"
"${SSH_BASE[@]}" "mv '$REMOTE_TARGET/.env.incoming' '$REMOTE_TARGET/.env' && chmod 600 '$REMOTE_TARGET/.env'"
rm -f "$ENV_FILE"

# --- run install (idempotent) ----------------------------------------------------------
log "running install.sh on the VPS ..."
"${SSH_BASE[@]}" "cd '$REMOTE_TARGET' && sudo -n bash deploy/install.sh" \
  || die "install.sh failed on the VPS (see log above)"

# --- verify ------------------------------------------------------------------------------
log "verifying controller health ..."
sleep 5
HEALTH=$("${SSH_BASE[@]}" 'curl -fsS -m 10 http://127.0.0.1:8080/healthz 2>/dev/null || echo unreachable' || true)
if [[ "$HEALTH" == "ok" ]]; then
  log "controller is healthy (healthz: ok)"
else
  # first boot may need a few more seconds for auth check
  sleep 15
  HEALTH=$("${SSH_BASE[@]}" 'curl -fsS -m 10 http://127.0.0.1:8080/healthz 2>/dev/null || echo unreachable' || true)
  [[ "$HEALTH" == "ok" ]] && log "controller is healthy (healthz: ok)" \
    || die "controller healthz: $HEALTH - inspect with: ssh ${VPS_SSH_USER}@${VPS_SSH_HOST} 'docker logs vps-runner-controller'"
fi

log "deploy complete."
log "runners will appear automatically when a job with runs-on: [self-hosted, ${RUNNER_LABELS:-vps}] queues up."
