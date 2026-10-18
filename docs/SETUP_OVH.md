# Setup guide: GitHub Actions runners on your OVH VPS

This guide gets the runner service deployed on your existing OVH VPS, entirely
through GitHub Actions (no laptop needed). **Read the "Information you must
provide" section first** — that is the list of things only you know, and the
deploy cannot proceed without them.

---

## 1. How it works (60 seconds)

```
                GitHub                                    your OVH VPS
 ┌──────────────────────────────┐              ┌────────────────────────────────┐
 │ repo: iamleson98/vps-runner  │              │ /opt/vps-runner (docker)       │
 │  ├ Deploy workflow (SSH) ────┼─────────────►│  └ controller container        │
 │  ├ Undeploy workflow (SSH) ──┼─────────────►│     polls ONLY allow-listed    │
 │  ├ Doctor workflow (SSH) ────┼─────────────►│     repos for queued jobs      │
 │  └ secrets: PAT, SSH key ────┘              │     spawns JIT runner pods     │
 │                                              │  └ JIT runner containers       │
 │ your repos (allow-list):                     │     one job → deregistered    │
 │  runs-on: [self-hosted, vps] ───────────────►│     by GitHub → rm -v → gone  │
 └──────────────────────────────┘              └────────────────────────────────┘
```

Three guarantees you asked for, and where they are enforced:

1. **Only your repos, never forks of other repos**
   - The controller polls **only** the repositories in the `RUNNER_REPOS`
     allow-list (`GITHUB_REPOSITORIES` on the VPS). Runners are created with
     per-repo just-in-time configurations, so a runner registered for repo A
     can physically never pick up a job from repo B.
   - Fork pull requests are a *repo settings* concern: set
     *Settings → Actions → General → Fork pull request workflows from outside
     collaborators → **Require approval for all outside collaborators*** in
     every allow-listed repo. With that, a fork PR workflow stays queued until
     you approve it manually.
2. **Clean removal after every job** — three layers:
   - GitHub JIT semantics: the runner "performs at most one job before being
     automatically removed" (official wording, see docs/RESEARCH_NOTES.md).
   - The container exits and the controller reaps it with `docker rm -v`
     (anonymous volumes included), plus a 6-hourly `docker prune`.
   - The **Undeploy** workflow removes *everything*: deregisters runners from
     GitHub, removes containers/images/volumes/systemd unit, optionally the
     whole `/opt/vps-runner` directory.
3. **Always free** — the OVH VPS is already paid by you; GitHub charges
   nothing for self-hosted runners or workflow minutes on public repos
   (see docs/COST.md).

---

## 2. Information you must provide

These are the ONLY inputs the deployment needs. Fill this in and you are ready:

### A. VPS access (3 secrets + optional port)

| What | Goes where | Example | Notes |
|---|---|---|---|
| Public IP or hostname | repo secret `VPS_SSH_HOST` | `1.2.3.4` or `vps.example.com` | OVH Control Panel → your VPS → IPv4 |
| SSH username | repo secret `VPS_SSH_USER` | `ubuntu`, `debian`, `root` | must have **passwordless sudo** (OVH images ship `ubuntu`/`debian` users with NOPASSWD sudo; `root` also works) |
| SSH port | repo secret `VPS_SSH_PORT` | `22` (default if unset) | only if you changed sshd |
| SSH private key | repo secret `VPS_SSH_KEY` | *generated for you* | step 4 below creates it; you only paste the **public** key into the VPS |

> The key stays in GitHub secrets; the public key goes into
> `~/.ssh/authorized_keys` of that SSH user on the VPS.

### B. VPS facts (needed to size the pool — tell these to the assistant or set the variables yourself)

| What | Where to look | Drives |
|---|---|---|
| vCPU cores | `nproc` on the VPS / OVH plan page | `MAX_RUNNERS` (default 2) |
| RAM | `free -h` / OVH plan page | `RUNNER_MEMORY_GB` (default 2.5) |
| Free disk | `df -h /` | comfort margin; runner image ≈ 1.2 GB, each job adds build cache |
| OS + version | `cat /etc/os-release` | Ubuntu 20.04/22.04/24.04 or Debian 11/12 are supported (docker is auto-installed if missing) |

Recommended settings by OVH plan (2026/2027 ranges):

| Plan | vCPU | RAM | `MAX_RUNNERS` | `RUNNER_MEMORY_GB` |
|---|---|---|---|---|
| VPS-1 | 2 | 4 GB | 1 | 2 |
| VPS-2 | 4 | 8 GB | 2 | 3 |
| VPS-3 | 6 | 12 GB | 3 | 3.5 |
| VPS-4 | 8 | 24 GB | 4 | 5 |

### C. GitHub inputs (1 secret + 1 variable)

| What | Goes where | Value |
|---|---|---|
| PAT | repo secret `RUNNER_GITHUB_PAT` | **classic PAT, `repo` scope** (or `public_repo` if all allow-listed repos are public). No expiration recommended, rotate at will — deleting it instantly stops the controller from spawning runners. |
| Repo allow-list | repo **variable** `RUNNER_REPOS` | e.g. `iamleson98/website,iamleson98/api` — comma-separated `owner/repo`. **This is the "only my repos" switch.** Adding a repo later = edit this variable + run Deploy again. Removing a repo = same; its runners vanish on the next Undeploy/Deploy cycle. |

Optional tuning variables (safe defaults if unset): `MAX_RUNNERS`,
`MIN_RUNNERS` (default 0 = scale-to-zero, runners spawn only when jobs are
queued), `RUNNER_MEMORY_GB`, `RUNNER_LABELS` (default `vps`),
`MOUNT_DOCKER_SOCK` (default `true`).

---

## 3. One-time click-path (15 minutes)

**Step 1 — PAT.** GitHub → your avatar → *Settings → Developer settings →
Personal access tokens (classic) → Generate new token*, tick **repo**,
generate, copy. In the `vps-runner` repo: *Settings → Secrets and variables →
Actions → Secrets → New repository secret* → name `RUNNER_GITHUB_PAT`, value
= the token.

**Step 2 — deploy key.** In `vps-runner`: *Actions → Bootstrap deploy key →
Run workflow*. It generates a fresh keypair, auto-saves the private key as
secret `VPS_SSH_KEY`, and prints the public key in the run summary.

**Step 3 — authorize the key on the VPS.** On the VPS:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "<paste the public key from the run summary>" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

**Step 4 — VPS secrets.** In `vps-runner` repo secrets, add `VPS_SSH_HOST`
and `VPS_SSH_USER` (+ `VPS_SSH_PORT` only if not 22).

**Step 5 — allow-list variable.** *Settings → Secrets and variables →
Actions → Variables → New repository variable* → name `RUNNER_REPOS`, value
`owner/repo,...`. Set `MAX_RUNNERS` / `RUNNER_MEMORY_GB` here too if your
plan differs from the default.

**Step 6 — deploy.** *Actions → Deploy → Run workflow*. Watch it go green;
it SSHes in, installs docker if missing, builds the images, starts
`vps-runner.service`, and verifies the health endpoint.

**Step 7 — point a workflow at the runners.** In an allow-listed repo:

```yaml
jobs:
  build:
    runs-on: [self-hosted, vps]
```

Push and watch the status page:
`ssh -N -L 8080:localhost:8080 <user>@<vps-ip>` → http://127.0.0.1:8080

---

## 4. Day-2 operations

| Task | How |
|---|---|
| Add another repo to the allow-list | edit `RUNNER_REPOS` variable → run **Deploy** |
| Remove a repo from the allow-list | edit `RUNNER_REPOS` variable → run **Deploy** (its stale runners are deregistered automatically within ~20 min) |
| Change pool size / memory / label | edit the variable → run **Deploy** (.env is re-rendered every time) |
| Update the runner software | run **Deploy** (images are rebuilt; pinned version lives in `runner-image/Dockerfile`) |
| Health check | *Actions → Doctor* (also runs automatically every Monday 03:00 UTC) |
| Stop everything cleanly | *Actions → Undeploy* — deregisters runners from GitHub, removes containers/images/volumes/unit; tick **purge** to also delete `/opt/vps-runner` |
| Rotate the PAT | create new token → update secret `RUNNER_GITHUB_PAT` → run **Deploy** |

## 5. Security checklist

- [ ] Fork PRs require approval in every allow-listed repo (*Settings →
      Actions → General → "Require approval for all outside collaborators"*).
- [ ] No `pull_request_target` workflows checking out untrusted refs in the
      allow-listed repos.
- [ ] `STATUS_TOKEN` secret set if you ever expose port 8080 beyond localhost
      (default: status page is localhost-only, via SSH tunnel).
- [ ] VPS sshd is key-only (`PasswordAuthentication no`) — Doctor warns you.
- [ ] PAT scope is exactly `repo` (or `public_repo`), nothing broader.
- [ ] `MOUNT_DOCKER_SOCK=false` if your jobs never need docker builds
      (sock mount is root-equivalent — acceptable for your own repos only).

## 6. What gets installed on the VPS (audit list)

| Item | Path / name | Removed by Undeploy? |
|---|---|---|
| Repo checkout | `/opt/vps-runner` | with `--purge` |
| Config | `/opt/vps-runner/.env` (mode 600) | with `--purge` |
| Controller container + image | `vps-runner-controller`, `vps-runner/controller:latest` | yes |
| Runner containers + image | label `vps-runner.managed=1`, `vps-runner/runner:latest` | yes (`rm -v` + image rm) |
| systemd unit | `/etc/systemd/system/vps-runner.service` | yes |
| Docker engine itself | `/usr/bin/docker` … | **no** (pre-existing or auto-installed; remove yourself if desired) |
| GitHub-side runners | per allow-listed repo | yes (deregistered before teardown) |
