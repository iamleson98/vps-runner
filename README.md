# vps-runner — GitHub Actions self-hosted runners on your own VPS (OVH)

CI-driven, queue-aware, and strictly limited to the repositories you allow-list.
Deploy, update, health-check and **cleanly remove** everything from GitHub
Actions workflows — no laptop, no cloud accounts, always free on the GitHub side.

> Full setup walkthrough: **[docs/SETUP_OVH.md](docs/SETUP_OVH.md)** (what info
> to provide, click-paths, sizing table, day-2 operations).

## Highlights

- **Repo allow-list by construction** — the controller polls only the repos in
  the `RUNNER_REPOS` variable, and every runner is a *per-repository*
  just-in-time (JIT) runner. A runner created for repo A can never execute a
  job from repo B. Fork-PR approval is a one-click repo setting (checklist in
  the setup guide).
- **One job, one container, zero residue** — JIT runners are automatically
  removed from GitHub after a single job; the controller reaps the stopped
  container with `docker rm -v` and prunes images/volumes/build cache every
  6 hours. The **Undeploy** workflow additionally deregisters runners and
  wipes containers, images, volumes and the systemd unit from the VPS.
- **Scale-to-zero** — by default no runner is running while the queue is
  empty (`MIN_RUNNERS=0`); a runner appears within seconds of a job queuing,
  up to `MAX_RUNNERS` concurrent jobs.
- **CI-first operations** — Deploy / Undeploy / Doctor / key-bootstrap are all
  GitHub workflows; the VPS `.env` is re-rendered from secrets + variables on
  every deploy, so GitHub is the single source of truth.
- **Pinned & verified** — actions/runner v2.338.0 (sha256-verified in the
  image build), non-root runner user, per-container memory caps.

## Architecture

```
GitHub                                        VPS (/opt/vps-runner, docker)
┌───────────────────────────┐    SSH     ┌──────────────────────────────────┐
│ vps-runner repo (CI)      ├───────────►│ install.sh / uninstall.sh        │
│  Deploy / Undeploy /      │            │ systemd: vps-runner.service      │
│  Doctor / Bootstrap-key   │            │  └ controller (python, 60 MB)    │
├───────────────────────────┤            │     poll allow-listed repos      │
│ secrets: RUNNER_GITHUB_PAT│            │     spawn JIT runner containers  │
│  VPS_SSH_KEY/HOST/USER    │            │  └ JIT runner containers         │
│ variable: RUNNER_REPOS    │            │     run.sh --jitconfig → 1 job   │
├───────────────────────────┤            │     → deregister → rm -v → gone  │
│ your repos (allow-list)   │◄───────────┤                                  │
│  runs-on: [self-hosted,vps]   jobs     └──────────────────────────────────┘
└───────────────────────────┘
```

## Quickstart (15 min)

1. Add secret `RUNNER_GITHUB_PAT` (classic PAT, `repo` scope).
2. Run **Bootstrap deploy key** workflow; paste the printed public key into
   the VPS `~/.ssh/authorized_keys`.
3. Add secrets `VPS_SSH_HOST`, `VPS_SSH_USER` (optionally `VPS_SSH_PORT`).
4. Add variable `RUNNER_REPOS` = `owner/repo,...` (the allow-list).
5. Run **Deploy**.
6. In an allow-listed repo use `runs-on: [self-hosted, vps]`.

Details, sizing table and security checklist: [docs/SETUP_OVH.md](docs/SETUP_OVH.md).

## Configuration

Everything is env-driven (rendered to `/opt/vps-runner/.env` by Deploy):

| Variable | Default | Meaning |
|---|---|---|
| `GITHUB_PAT` | — | classic PAT, `repo` scope (secret `RUNNER_GITHUB_PAT`) |
| `GITHUB_REPOSITORIES` | — | **allow-list** of `owner/repo` (variable `RUNNER_REPOS`) |
| `RUNNER_LABELS` / `MATCH_LABELS` | `vps` | runner labels; workflows use `runs-on: [self-hosted, vps]` |
| `MIN_RUNNERS` / `MAX_RUNNERS` | `0` / `2` | pool bounds (scale-to-zero default) |
| `RUNNER_MEMORY_GB` | `2.5` | per-runner `docker --memory` cap |
| `RUNNER_CPUS` | empty | per-runner `docker --cpus` cap |
| `MOUNT_DOCKER_SOCK` | `true` | sibling docker builds inside jobs |
| `POLL_INTERVAL` | `15` | seconds between queue polls |
| `STATUS_TOKEN` | empty | protects the status page if exposed |

Sizing guide for OVH plans: see [docs/SETUP_OVH.md](docs/SETUP_OVH.md#2-information-you-must-provide).

## Runner mode decision (why containers, why JIT)

- **Ephemeral JIT containers** implement exactly the two properties you
  asked for: clean cleanup per job (GitHub removes the runner record after
  one job; we remove the container and its volumes) and no cross-repo
  leakage (JIT configs are issued per repository by design).
- Host-installed runners would give no isolation between jobs and no
  per-repo enforcement stronger than ours, while losing container memory
  caps — so the Docker approach was kept.
- Org-level runner groups (an alternative restriction mechanism) do not
  exist on personal accounts, which is why per-repo JIT is the right tool
  here. Research references: [docs/RESEARCH_NOTES.md](docs/RESEARCH_NOTES.md).

## Repository layout

```
.github/workflows/   bootstrap-ssh-key, deploy, undeploy, doctor
controller/          python autoscaler (multi-repo allow-list, JIT spawn)
runner-image/        pinned actions/runner v2.338.0 + docker CLI (x64 default)
deploy/              compose.yml, install.sh, uninstall.sh, systemd unit
scripts/             ci_deploy.sh (SSH deploy), doctor.sh
examples/            ready-to-use workflow for your repos
docs/                SETUP_OVH, COST, TROUBLESHOOTING, RESEARCH_NOTES
```

## Security model

- The PAT never leaves GitHub secrets + the VPS `.env` (mode 600, inside the
  controller container only).
- The deploy key is a dedicated keypair (bootstrap workflow), not your
  personal SSH key; deleting `VPS_SSH_KEY` + removing the authorized_key line
  cuts CI access instantly.
- Runner containers run as a non-root `runner` user with sudo, capped memory,
  and are single-job by construction.
- Caveat, stated plainly: mounting `/var/run/docker.sock` into runner
  containers (default, for docker builds in CI) is root-equivalent for job
  code. That is acceptable *only* because jobs come exclusively from your
  allow-listed repos with fork approval enforced. Set
  `MOUNT_DOCKER_SOCK=false` to disable.

## Costs

GitHub side: $0 — self-hosted runners are free, and workflow minutes on
public repos are free (private-repo minute pricing was postponed; see
docs/COST.md). VPS side: your existing OVH plan; nothing here changes it.
