# Troubleshooting

Symptoms are grouped by area. The **Doctor** workflow (or
`bash scripts/doctor.sh` on the VPS) is always the first diagnostic step.

## Deploy workflow

**`cannot SSH - check VPS_SSH_HOST / VPS_SSH_USER / VPS_SSH_KEY / VPS_SSH_PORT`**
- Wrong IP/user: verify with `ssh <user>@<host>` from anywhere.
- Key not authorized: the public key printed by *Bootstrap deploy key* must be
  in `~/.ssh/authorized_keys` of exactly that user (mode 600, `~/.ssh` 700).
- Custom port: set secret `VPS_SSH_PORT`.
- Cloud firewall: OVH Control Panel → IP firewall / Security Groups must
  allow inbound TCP on your SSH port.

**`sudo -n` fails / install.sh not run**
- The SSH user must have passwordless sudo (OVH `ubuntu`/`debian` images do;
  hardened boxes may not). Either restore NOPASSWD sudo for this user or use
  `root` as `VPS_SSH_USER`.

**`controller healthz: unreachable` after install**
- `ssh <user>@<host> 'docker logs vps-runner-controller'` — usually a config
  error printed by `[config]` (missing `GITHUB_PAT` / `GITHUB_REPOSITORIES`)
  or a 401/404 auth check (bad PAT, or a repo in the allow-list the PAT
  cannot see).

## Runners not picking up jobs

**Job stays `queued` forever, status page shows `queued jobs > 0` but no runner spawns**
- Label mismatch: the workflow must use every custom label the runner has.
  Default label is `vps`, so `runs-on: [self-hosted, vps]` matches; a bare
  `runs-on: self-hosted` does NOT (by design — that would also grab other
  self-hosted runners you may add later).
- Check `MATCH_LABELS` equals `RUNNER_LABELS` in the rendered `.env`.
- Check the repo is actually in the `RUNNER_REPOS` allow-list.

**Status page shows `queued jobs: 0` but GitHub shows a queued job**
- The job may be waiting for *fork-PR approval* (repo Settings → Actions).
  Approved jobs start polling normally afterwards.
- The PAT may lack visibility of that repo (404 on the queue poll in logs).

**`JIT runner config failed ... HTTP 403`**
- PAT lacks runner admin rights on that repo: use a classic PAT with `repo`
  scope over all allow-listed repos (fine-grained: "Self-hosted runners: RW").

**`JIT runner config failed ... HTTP 404`**
- Repo name typo in `RUNNER_REPOS`, or Actions disabled on that repo.

**Runner container starts and exits immediately**
- `docker logs <runner-container-name>`: an expired/invalid JIT config
  (clock skew on the VPS — `timedatectl status`, enable NTP) or an actions
  version issue (runner v2.338.0 needs GitHub's current API).

## Cleanup

**Exited runner containers piling up**
- Normal lifespan is minutes (reaped 15 min after exit at the latest). If
  they accumulate, `docker logs vps-runner-controller | grep -i reap` and
  check for `docker rm` errors; stale GitHub-side runner records are
  deregistered after ~20 min offline.

**Disk filling up**
- `docker system prune -af --filter 'label!=vps-runner.keep'` (the controller
  does this automatically every 6 h). Build cache from your own jobs is the
  usual cause; prune more aggressively via `PRUNE_INTERVAL`.

**Want EVERYTHING gone**
- Run the **Undeploy** workflow (optionally with `purge`). It deregisters
  runners from GitHub first, then removes containers, images, volumes and
  the systemd unit. Docker itself is left installed.

## Access & security

**Rotate the PAT**
- Create a new token → update secret `RUNNER_GITHUB_PAT` → run **Deploy**.
  The old token dies instantly (controller exits on 401 and respawns with
  the new env on next deploy).

**Rotate the deploy key**
- Re-run *Bootstrap deploy key* (it overwrites secret `VPS_SSH_KEY`), replace
  the line in the VPS `authorized_keys`, remove the old public key.

**Status page**
- Localhost-only by default. Tunnel: `ssh -N -L 8080:localhost:8080 <user>@<host>`.
  If you expose it, set `STATUS_TOKEN` and open only port 8080 in the firewall.
