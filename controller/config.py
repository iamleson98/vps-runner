"""Configuration for the vps-runner controller (env-driven).

The controller watches ONLY the repositories listed in GITHUB_REPOSITORIES
(the allow-list). Runners are registered per-repository as just-in-time (JIT)
ephemeral runners, so jobs from any other repository can never reach this VPS.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    v = os.environ.get(name)
    try:
        return int(v) if v not in (None, "") else default
    except ValueError:
        raise SystemExit(f"[config] {name}={v!r} is not an integer") from None


def _float(name: str, default: float) -> float:
    v = os.environ.get(name)
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        raise SystemExit(f"[config] {name}={v!r} is not a number") from None


def _split_csv(name: str) -> list[str]:
    v = os.environ.get(name, "")
    return [p.strip() for p in v.split(",") if p.strip()]


@dataclass
class Scope:
    """One watched repository (owner/name). This is the hard allow-list unit."""

    owner: str
    name: str

    @property
    def slug(self) -> str:
        base = f"{self.owner}-{self.name}"
        return "".join(c if c.isalnum() else "-" for c in base.lower()).strip("-")

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"


@dataclass
class Config:
    # --- GitHub auth ---------------------------------------------------------
    # Classic PAT with `repo` scope (or `public_repo` for public repos only).
    # Fine-grained PATs also work: "Self-hosted runners: RW", "Actions: R",
    # "Metadata: R" on every allow-listed repository.
    github_pat: str = ""

    # --- allow-list ------------------------------------------------------------
    # ONLY these repositories are polled and served. This is the enforcement
    # point for "run only for my repos": nothing outside this list is ever
    # contacted, and JIT runners are registered inside these repos only.
    github_repositories: list[str] = field(default_factory=list)  # ["owner/repo", ...]

    # --- runners ---------------------------------------------------------------
    runner_labels: str = "vps"
    match_labels: list[str] = field(default_factory=lambda: ["vps"])
    min_runners: int = 0
    max_runners: int = 2
    runner_image: str = "vps-runner/runner:latest"
    runner_memory_gb: float = 2.5
    runner_cpus: str = ""  # empty = uncapped
    mount_docker_sock: bool = True
    container_prefix: str = "gha-runner"

    # --- ops ---------------------------------------------------------------------
    poll_interval: int = 15
    housekeep_interval: int = 300
    prune_interval: int = 6 * 3600

    # --- status -------------------------------------------------------------------
    status_bind: str = "0.0.0.0"
    status_port: int = 8080
    status_token: str = ""

    # ---------------------------------------------------------------------------

    @property
    def scopes(self) -> list[Scope]:
        out: list[Scope] = []
        for full in self.github_repositories:
            if "/" not in full:
                raise SystemExit(f"[config] GITHUB_REPOSITORIES entry {full!r} must look like 'owner/repo'")
            o, r = full.split("/", 1)
            out.append(Scope(owner=o, name=r))
        return out

    @property
    def runner_label_list(self) -> list[str]:
        return [p.strip() for p in self.runner_labels.split(",") if p.strip()]

    def validate(self) -> None:
        errors: list[str] = []
        if not self.github_pat:
            errors.append("GITHUB_PAT is required (classic PAT with 'repo' scope)")
        if not self.github_repositories:
            errors.append("GITHUB_REPOSITORIES is required (comma-separated owner/repo allow-list)")
        if self.min_runners < 0 or self.max_runners < 1 or self.min_runners > self.max_runners:
            errors.append("need 0 <= MIN_RUNNERS <= MAX_RUNNERS with MAX_RUNNERS >= 1")
        if self.runner_memory_gb <= 0:
            errors.append("RUNNER_MEMORY_GB must be > 0")
        if not self.match_labels:
            errors.append("MATCH_LABELS must not be empty")
        if errors:
            raise SystemExit("[config] invalid configuration:\n  - " + "\n  - ".join(errors))


def load_config() -> Config:
    cfg = Config(
        github_pat=os.environ.get("GITHUB_PAT", "").strip(),
        github_repositories=_split_csv("GITHUB_REPOSITORIES"),
        runner_labels=os.environ.get("RUNNER_LABELS", "vps"),
        match_labels=_split_csv("MATCH_LABELS") or ["vps"],
        min_runners=_int("MIN_RUNNERS", 0),
        max_runners=_int("MAX_RUNNERS", 2),
        runner_image=os.environ.get("RUNNER_IMAGE", "vps-runner/runner:latest"),
        runner_memory_gb=_float("RUNNER_MEMORY_GB", 2.5),
        runner_cpus=os.environ.get("RUNNER_CPUS", "").strip(),
        mount_docker_sock=_bool("MOUNT_DOCKER_SOCK", True),
        container_prefix=os.environ.get("CONTAINER_PREFIX", "gha-runner"),
        poll_interval=max(5, _int("POLL_INTERVAL", 15)),
        housekeep_interval=max(30, _int("HOUSEKEEP_INTERVAL", 300)),
        prune_interval=max(600, _int("PRUNE_INTERVAL", 6 * 3600)),
        status_bind=os.environ.get("STATUS_BIND", "0.0.0.0"),
        status_port=_int("STATUS_PORT", 8080),
        status_token=os.environ.get("STATUS_TOKEN", "").strip(),
    )
    cfg.validate()
    return cfg
