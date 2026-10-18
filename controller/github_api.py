"""GitHub API client for the vps-runner controller.

PAT-only auth. Provides:
  * just-in-time (JIT) runner configurations - the modern, recommended way to
    spin up ephemeral runners: one API call returns an encoded config that
    registers a runner which "performs at most one job before being
    automatically removed" (GitHub security hardening docs). No registration
    token is ever handled or cached.
  * runner inventory / deletion per watched repository (stale-runner cleanup)
  * queued-job introspection per watched repository (autoscaling signal)

Only repositories from the configured allow-list (cfg.scopes) are ever
contacted - see config.py.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger("github")

API = "https://api.github.com"
COMMON_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "vps-runner-controller",
}
MAX_PAGES = 5


class GitHubClient:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.packages.urllib3.util.retry.Retry(
                total=2, backoff_factor=0.5, status_forcelist=(502, 503, 504), allowed_methods=None
            )
        )
        self.session.mount("https://", adapter)

    # ------------------------------------------------------------------ auth

    def _headers(self) -> dict[str, str]:
        return {**COMMON_HEADERS, "Authorization": f"token {self.cfg.github_pat}"}

    def check_auth(self) -> None:
        """Cheap call that verifies the token actually works. Raises on failure."""
        if not self.cfg.scopes:  # pragma: no cover - validation forbids this
            return
        scope = self.cfg.scopes[0]
        url = f"{API}/repos/{scope.owner}/{scope.name}"
        code, body = self._request("GET", url)
        if code == 401:
            raise SystemExit("[github] authentication failed (401). Check GITHUB_PAT.")
        if code == 404:
            raise SystemExit(
                f"[github] repository {scope.owner}/{scope.name} not visible to this PAT "
                "(wrong name, or the PAT lacks access)."
            )
        if code not in (200, 202):
            log.warning("auth check returned HTTP %s for %s", code, url)

    # --------------------------------------------------------------- plumbing

    def _request(self, method: str, url: str, **kw: Any) -> tuple[int, Any]:
        kw.setdefault("timeout", 20)
        resp = self.session.request(method, url, headers=self._headers(), **kw)
        body = None
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        return resp.status_code, body

    def _get(self, url: str, params: dict | None = None) -> tuple[int, Any]:
        return self._request("GET", url, params=params)

    def _paginate(self, url: str, params: dict | None = None) -> list[dict]:
        """Paginate endpoints that return {workflow_jobs|runners: [...]}."""
        items: list[dict] = []
        params = dict(params or {})
        params["per_page"] = 100
        for _ in range(MAX_PAGES):
            code, body = self._get(url, params)
            if code == 404:
                return items
            if code != 200:
                log.warning("GET %s -> HTTP %s", url, code)
                return items
            page: list[dict] = []
            if isinstance(body, dict):
                page = body.get("workflow_jobs") or body.get("runners") or []
            items.extend(page)
            if len(page) < 100:
                break
            params["page"] = params.get("page", 1) + 1
        return items

    # ------------------------------------------------------------------ API

    def jit_config(self, scope, runner_name: str, labels: list[str]) -> str:
        """Create a just-in-time runner configuration for ONE repository.

        Returns the encoded JIT config to pass to `run.sh --jitconfig`.
        The created runner accepts at most one job and is then removed from
        the repository automatically by GitHub - this is what guarantees
        clean removal per job.
        """
        url = f"{API}/repos/{scope.owner}/{scope.name}/actions/runners/generate-jitconfig"
        payload = {"name": runner_name, "labels": labels, "work_folder": "_work"}
        code, body = self._request("POST", url, json=payload)
        if code == 401:
            raise RuntimeError(f"JIT config for {scope.owner}/{scope.name} failed: HTTP 401 (bad PAT)")
        if code == 403:
            raise RuntimeError(
                f"JIT config for {scope.owner}/{scope.name} failed: HTTP 403 "
                "(PAT lacks admin/runner permissions on this repo)"
            )
        if code == 404:
            raise RuntimeError(
                f"JIT config for {scope.owner}/{scope.name} failed: HTTP 404 "
                "(repo not found for this PAT, or Actions disabled)"
            )
        if code != 201:
            raise RuntimeError(f"JIT config for {scope.owner}/{scope.name} failed: HTTP {code} {body}")
        log.info("JIT runner config created for %s (name=%s)", scope.slug, runner_name)
        return body["encoded_jit_config"]

    def list_runners(self, scope) -> list[dict]:
        url = f"{API}/repos/{scope.owner}/{scope.name}/actions/runners"
        return self._paginate(url)

    def delete_runner(self, scope, runner_id: int) -> bool:
        url = f"{API}/repos/{scope.owner}/{scope.name}/actions/runners/{runner_id}"
        code, _ = self._request("DELETE", url)
        ok = code in (202, 204)
        if not ok:
            log.warning("delete runner %s -> HTTP %s", runner_id, code)
        return ok

    def queued_jobs(self, scope) -> int:
        """Number of queued jobs that OUR labels can serve in this repository."""
        url = f"{API}/repos/{scope.owner}/{scope.name}/actions/workflow-jobs"
        jobs = self._paginate(url, {"status": "queued"})
        if not jobs:
            # Fallback: count queued workflow *runs* (coarser, but keeps scaling alive
            # if the job-level endpoint is unavailable to the token).
            code, body = self._get(
                f"{API}/repos/{scope.owner}/{scope.name}/actions/runs",
                {"status": "queued", "per_page": 1},
            )
            if code == 200 and isinstance(body, dict):
                total = body.get("total_count", 0)
                if total:
                    log.warning(
                        "workflow-jobs endpoint empty; falling back to queued runs count=%s for %s",
                        total, scope.slug,
                    )
                    return int(total)
            return 0
        match = set(self.cfg.match_labels)
        matched = sum(1 for j in jobs if match.intersection(j.get("labels") or []))
        return matched
