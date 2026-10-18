"""Deregister every runner this controller owns, from every allow-listed repo.

Used by deploy/uninstall.sh so that `Undeploy` leaves NOTHING behind on the
GitHub side. Also safe to run while the controller is down.

Run inside the controller image (it only needs `requests`):
    docker run --rm --env-file /opt/vps-runner/.env \\
        vps-runner/controller:latest python3 deregister.py [--dry-run]
"""

from __future__ import annotations

import sys

from config import load_config
from github_api import GitHubClient


def main() -> int:
    dry = "--dry-run" in sys.argv
    cfg = load_config()
    gh = GitHubClient(cfg)
    total = 0
    for scope in cfg.scopes:
        try:
            runners = gh.list_runners(scope)
        except Exception as exc:  # noqa: BLE001
            print(f"[deregister] could not list runners for {scope.owner}/{scope.name}: {exc}")
            continue
        ours = [r for r in runners if str(r.get("name", "")).startswith(cfg.container_prefix)]
        print(f"[deregister] {scope.owner}/{scope.name}: {len(ours)} runner(s) of ours")
        for r in ours:
            if dry:
                print(f"  would delete: {r.get('name')} (id={r.get('id')})")
                total += 1
                continue
            if gh.delete_runner(scope, r["id"]):
                print(f"  deleted: {r.get('name')}")
                total += 1
            else:
                print(f"  FAILED to delete: {r.get('name')} (id={r.get('id')})")
    print(f"[deregister] done: {total} runner(s) {'listed' if dry else 'removed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
