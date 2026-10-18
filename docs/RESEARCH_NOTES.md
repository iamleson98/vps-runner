# Research notes (2026-10-18)

Primary sources consulted for the VPS pivot. All statements in README /
SETUP_OVH / COST trace back to these.

## Runner restriction: why per-repo JIT is the right mechanism

1. **Runner groups are organization-level only.**
   docs.github.com — "Managing access to self-hosted runners using groups":
   "All organizations have a single default runner group. Organization owners
   using the GitHub Team plan can create additional organization-level runner
   groups." A personal account has no runner groups, so per-repo registration
   is the only personal-account restriction primitive.

2. **The `GITHUB_REPOSITORIES` env var is no longer documented.** Older
   community references mention it for org runners; it does not appear in the
   current "Adding self-hosted runners" docs page (verified 2026-10-18), so it
   is not relied on anywhere in this repo.

3. **Just-in-time runners are the officially recommended hardening.**
   docs.github.com — "Security hardening for GitHub Actions", *Hardening for
   self-hosted runners*: "To improve runner registration security, you can use
   the REST API to create ephemeral, just-in-time (JIT) runners. These
   self-hosted runners perform at most one job before being automatically
   removed from the repository, organization, or enterprise."
   → This is exactly the "clean removal per job" requirement, enforced by
   GitHub rather than by our cleanup code.

4. **REST API surface used** (docs.github.com REST reference, API version
   2026-03-10, verified 2026-10-18):
   - `POST /repos/{owner}/{repo}/actions/runners/generate-jitconfig` — body
     `{name, labels[], work_folder}`; requires admin on the repo; classic PAT
     `repo` scope; fine-grained: "Self-hosted runners: RW".
   - `GET  /repos/{owner}/{repo}/actions/runners` — list (for stale cleanup).
   - `DELETE /repos/{owner}/{repo}/actions/runners/{id}` — deregister.
   - `GET  /repos/{owner}/{repo}/actions/workflow-jobs?status=queued` —
     queue introspection (label-filtered client-side).
   - Registration tokens expire after one hour (docs) — JIT configs avoid
     handling tokens altogether.

## Fork-PR safety

- docs.github.com — "Security hardening for GitHub Actions":
  "self-hosted runners should almost never be used for public repositories…
  any user can open pull requests against the repository and compromise the
  environment." Mitigations in place: allow-list of your own repos only;
  "Require approval for all outside collaborators" repo setting for fork PR
  workflows (approval requirements configurable at repository, organization,
  or enterprise level per the "Approving workflow runs from public forks"
  doc); never use `pull_request_target` with untrusted code.
- Also from the same doc: environments with required reviewers help but
  "these workflows are not run in an isolated environment" — isolation here
  comes from single-job JIT containers + memory caps.

## Runner version pinning

- actions/runner latest release (GitHub API, 2026-10-18): **v2.338.0**
  (published 2026-10-06).
  - linux-x64 tarball sha256:
    `af4b794c1bc41d73d40535e3fe092a39f9679cd8d965954c2aca25a05ca41d32`
  - linux-arm64 tarball sha256:
    `628b4a7258487b80c1d3c221095a7ded349f5ae0175fd3dfab708d07428f041b`
  - Both pinned and verified in `runner-image/Dockerfile`.

## OVH VPS facts (for the sizing table)

- OVHcloud US VPS 2027 range (us.ovhcloud.com/vps, checked 2026-10-18):
  VPS-1: 2 vCores / 4 GB / 40 GB NVMe / 500 Mbps, from $4.54/mo;
  VPS-2: 4 vCores / 8 GB / 75 GB NVMe / 1 Gbps, from $8.50/mo;
  VPS-3: 6 vCores / 12 GB / 100 GB NVMe / 2 Gbps, from $12.32/mo;
  VPS-4: 8 vCores / 24 GB / 200 GB NVMe / 3 Gbps, from $23.37/mo.
  All: KVM virtualization, x86_64 (Intel platforms observed by third-party
  benchmarks: vpsbenchmarks.com / CLN.io 2026 tests — Haswell cores, NVMe
  ~3000 MiB/s), Ubuntu/Debian images available, unlimited traffic, anti-DDoS.
- 2026 range equivalents (VPS-2 2026: 6 vCPU / 12 GB / 100 GB) — existing
  customers keep their configs (OVHcloud blog, "VPS 2027" announcement,
  June 2026: "no automatic change… no forced migration").

## GitHub pricing (unchanged from the previous audit, re-verified)

- Self-hosted runners free (GitHub billing docs).
- Private-repo minute pricing ($0.002/min, announced Dec 2025) postponed;
  not in effect as of October 2026 (github.blog changelog + press coverage).
