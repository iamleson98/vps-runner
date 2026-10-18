# Costs

## GitHub side: $0

- **Self-hosted runners are free** — GitHub bills only for *GitHub-hosted*
  runner minutes. Your VPS executes the jobs, so no runner-minute charges
  apply regardless of repository visibility.
- **Public repositories**: workflow minutes free (always).
- **Private repositories**: the announced $0.002/minute pricing for private
  repo minutes (Dec 2025 announcement) has been postponed and was not in
  effect as of October 2026 — private-repo minutes remain free with the
  included monthly allowance; self-hosted runner jobs were never part of that
  metering anyway.
- **PAT / API usage**: free; the controller's polling stays far below rate
  limits (2 requests per repo per 15 s at defaults).

## VPS side: your existing OVH plan

Nothing in this repo changes your OVH billing. For reference, the OVH VPS
2026/2027 ranges (US pricing, October 2026): VPS-1 (2 vCores / 4 GB / 40 GB
NVMe) from ~$4.50/mo up to VPS-4 (8 vCores / 24 GB / 200 GB NVMe) ~$23/mo —
unlimited traffic, anti-DDoS included.

Resource footprint of the stack itself:

| Component | Idle footprint |
|---|---|
| Controller container | ~60 MB RAM, <1% CPU (polls every 15 s) |
| Runner containers | zero when idle (scale-to-zero default) |
| Runner image on disk | ~1.2 GB (once) |
| Per-job disk churn | build cache of your jobs (pruned every 6 h) |

## What could ever cost money

- Nothing here. There is no cloud API in play, no object storage, no egress
  metering on GitHub's side, and the VPS plan is fixed-price.
- If you later move to a metered cloud, the only metered items would be
  container image pulls (GHCR free for public images).
