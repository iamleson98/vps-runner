#!/usr/bin/env python3
"""Smoke tests for the vps-runner autoscaler (no docker, no network).

Run:  python3 scripts/smoke_autoscaler.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CTRL = os.path.join(os.path.dirname(HERE), "controller")
sys.path.insert(0, CTRL)

from autoscaler import Autoscaler, EXITED_REAP_AFTER_S, OFFLINE_DEREG_AFTER_S, REGISTRATION_GRACE_S  # noqa: E402
from config import Config, load_config  # noqa: E402

PASS = 0
FAIL = 0


def check(cond: bool, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ ok ] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}")


def make_cfg(**kw) -> Config:
    base = dict(
        github_pat="token",
        github_repositories=["acme/alpha", "acme/beta"],
        min_runners=0,
        max_runners=4,
    )
    base.update(kw)
    return Config(**base)


class FakeGH:
    def __init__(self, queued=None, runners=None, jit_fail=False):
        self.queued = queued or {}
        self.runners = runners or []
        self.jit_fail = jit_fail
        self.jit_calls = []       # (slug, name, labels)
        self.deleted = []         # (slug, runner_id)

    def queued_jobs(self, scope):
        return self.queued.get(scope.slug, 0)

    def list_runners(self, scope):
        return [r for r in self.runners if r.get("slug") == scope.slug]

    def jit_config(self, scope, name, labels):
        if self.jit_fail:
            raise RuntimeError("HTTP 403")
        self.jit_calls.append((scope.slug, name, labels))
        return f"JIT::{scope.slug}::{name}"

    def delete_runner(self, scope, runner_id):
        self.deleted.append((scope.slug, runner_id))
        return True


class FakeDM:
    def __init__(self, containers=None, fail_spawn=False):
        self.containers = containers or []
        self.fail_spawn = fail_spawn
        self.spawned = []         # (name, slug, jit)
        self.removed = []
        self.stopped = []

    def list_containers(self):
        return [dict(c) for c in self.containers]

    def spawn_runner(self, name, scope, jit):
        if self.fail_spawn:
            return False
        self.spawned.append((name, scope.slug, jit))
        self.containers.append({"name": name, "State": "running"})
        return True

    def remove_containers(self, names, force=False):
        for n in names:
            if n not in self.removed:
                self.removed.append(n)
            self.containers = [c for c in self.containers if c["name"] != n]

    def stop_containers(self, names, grace=60):
        for n in names:
            if n not in self.stopped:
                self.stopped.append(n)

    def disk_free_gb(self):
        return 12.5

    def prune(self):
        return []


def gh_runner(name, slug, status="online", busy=False):
    return {"name": name, "slug": slug, "status": status, "busy": busy, "id": abs(hash(name)) % 100000}


def cont(name, state="running"):
    return {"name": name, "State": state}


print("== config ==")
os.environ.pop("GITHUB_PAT", None)
os.environ.pop("GITHUB_REPOSITORIES", None)
for k in list(os.environ):
    if k.startswith(("MIN_", "MAX_", "RUNNER_", "MATCH_", "MOUNT_")):
        os.environ.pop(k)
try:
    load_config()
    check(False, "missing GITHUB_PAT/GITHUB_REPOSITORIES rejected")
except SystemExit:
    check(True, "missing GITHUB_PAT/GITHUB_REPOSITORIES rejected")
os.environ["GITHUB_PAT"] = "t"
os.environ["GITHUB_REPOSITORIES"] = "acme/alpha,acme/beta"
cfg = load_config()
check([s.slug for s in cfg.scopes] == ["acme-alpha", "acme-beta"], "scopes parsed")
check(cfg.runner_label_list == ["vps"], "default label list")
check(cfg.min_runners == 0 and cfg.max_runners == 2, "pool defaults (0..2)")

print("== scale-up (weighted, JIT) ==")
cfg = make_cfg()
gh = FakeGH(queued={"acme-alpha": 3, "acme-beta": 1})
dm = FakeDM()
sc = Autoscaler(cfg, gh, dm)
sc.tick()
check(len(gh.jit_calls) == 4, "4 JIT configs for 4 queued jobs")
check(len(dm.spawned) == 4, "4 containers spawned")
per_repo = {}
for slug, name, labels in gh.jit_calls:
    per_repo[slug] = per_repo.get(slug, 0) + 1
check(per_repo.get("acme-alpha") == 3 and per_repo.get("acme-beta") == 1, "weighted toward deeper queue")
check(all(labels == ["vps"] for _, _, labels in gh.jit_calls), "labels passed to JIT")
check(all(jit.startswith("JIT::") for _, _, jit in dm.spawned), "JIT config handed to container")
check(sc.state["desired"] == 4 and sc.state["containers_running"] == 4, "state reflects scale-up")

print("== busy accounting (no runaway spawn) ==")
cfg = make_cfg()
gh = FakeGH(
    queued={},
    runners=[gh_runner("gha-runner-acme-alpha-1", "acme-alpha", busy=True),
             gh_runner("gha-runner-acme-beta-2", "acme-beta", busy=True)],
)
dm = FakeDM(containers=[cont("gha-runner-acme-alpha-1"), cont("gha-runner-acme-beta-2")])
sc = Autoscaler(cfg, gh, dm)
sc.tick()
check(len(dm.spawned) == 0, "busy runners satisfy demand - no extra spawn")
check(sc.state["desired"] == 2, "desired = busy when queue empty")

print("== scale-down (grace, newest-first, busy untouched) ==")
cfg = make_cfg()
now = time.time()
gh = FakeGH(runners=[gh_runner("gha-runner-acme-alpha-busy", "acme-alpha", busy=True)])
dm = FakeDM(containers=[
    cont("gha-runner-acme-alpha-busy"),
    cont("gha-runner-acme-alpha-old"),
    cont("gha-runner-acme-alpha-new"),
])
sc = Autoscaler(cfg, gh, dm)
sc._spawn_ts["gha-runner-acme-alpha-old"] = now - 2 * REGISTRATION_GRACE_S
sc._spawn_ts["gha-runner-acme-alpha-new"] = now - REGISTRATION_GRACE_S + 5  # too young
sc._spawn_ts["gha-runner-acme-alpha-busy"] = now - 2 * REGISTRATION_GRACE_S
sc.tick()  # busy=1 -> desired=1, running=3 -> scale down
check(dm.stopped == ["gha-runner-acme-alpha-old"], "only old idle runner stopped")
check(all("busy" not in n for n in dm.stopped), "busy runner never stopped")

print("== exited reap ==")
cfg = make_cfg()
gh = FakeGH()
dm = FakeDM(containers=[cont("gha-runner-acme-alpha-x", "exited")])
sc = Autoscaler(cfg, gh, dm)
sc._spawn_ts["gha-runner-acme-alpha-x"] = time.time() - (EXITED_REAP_AFTER_S + 60)
sc.tick()
check("gha-runner-acme-alpha-x" in dm.removed, "exited container reaped")
check(dm.list_containers() == [], "container gone from inventory")

print("== stale offline deregistration ==")
cfg = make_cfg()
gh = FakeGH(runners=[gh_runner("gha-runner-acme-alpha-ghost", "acme-alpha", status="offline")])
dm = FakeDM()  # no container for it
sc = Autoscaler(cfg, gh, dm)
sc._offline_seen["gha-runner-acme-alpha-ghost"] = time.time() - (OFFLINE_DEREG_AFTER_S + 60)
sc.tick()
check(len(gh.deleted) == 1 and gh.deleted[0][0] == "acme-alpha", "ghost runner deregistered from its repo")

print("== spawn-failure cooldown ==")
cfg = make_cfg()
gh = FakeGH(queued={"acme-alpha": 5}, jit_fail=True)
dm = FakeDM()
sc = Autoscaler(cfg, gh, dm)
for _ in range(3):
    sc.tick()
check(sc.state["spawn_paused_until"] > time.time(), "cooldown armed after repeated JIT failures")
n_calls = len(gh.jit_calls)
sc.tick()
check(len(gh.jit_calls) == n_calls, "no JIT calls while paused")

print("== one repo failing does not block others ==")
cfg = make_cfg()
gh = FakeGH(queued={"acme-alpha": 2})
gh.queued_jobs = lambda scope: (_ for _ in ()).throw(RuntimeError("HTTP 503")) if scope.slug == "acme-alpha" else 1
dm = FakeDM()
sc = Autoscaler(cfg, gh, dm)
sc.tick()
check(len(dm.spawned) == 1 and dm.spawned[0][1] == "acme-beta", "healthy repo still served")

print("== state snapshot ==")
snap = sc.snapshot()
check("repos" in snap and set(snap["repos"]) == {"acme-alpha", "acme-beta"}, "allow-list exposed in status")

print("== deregister.py (undeploy helper) ==")
import deregister  # noqa: E402

os.environ["GITHUB_PAT"] = "t"
os.environ["GITHUB_REPOSITORIES"] = "acme/alpha,acme/beta"
fake = FakeGH(runners=[
    gh_runner("gha-runner-acme-alpha-1", "acme-alpha", status="offline"),
    gh_runner("gha-runner-acme-beta-2", "acme-beta", status="online"),
    gh_runner("someone-elses-runner", "acme-beta", status="online"),
])
deregister.GitHubClient = lambda cfg: fake
sys.argv = ["deregister.py"]
rc = deregister.main()
check(rc == 0, "deregister exits 0")
check(len(fake.deleted) == 2, "removed exactly our 2 runners (other people's untouched)")

print("== runner entrypoint (JIT propagation) ==")
with tempfile.TemporaryDirectory() as td:
    runner_dir = os.path.join(td, "actions-runner")
    os.makedirs(runner_dir)
    fake_run = os.path.join(runner_dir, "run.sh")
    with open(fake_run, "w") as fh:
        fh.write('#!/bin/sh\necho "jit=$*"\nexit 7\n')
    os.chmod(fake_run, 0o755)
    entry = os.path.join(runner_dir, "entrypoint_under_test.sh")
    src = os.path.join(os.path.dirname(HERE), "runner-image", "entrypoint.sh")
    with open(src) as fh:
        body = fh.read().replace("./run.sh", '"$PWD/run.sh"')
    with open(entry, "w") as fh:
        fh.write(body)
    os.chmod(entry, 0o755)
    env = dict(os.environ, RUNNER_JITCONFIG="ENCODED_JIT_TOKEN_123")
    proc = subprocess.run(["bash", entry], cwd=runner_dir, env=env, capture_output=True, text=True)
    check(proc.returncode == 7, "entrypoint propagates job exit code")
    check("jit=--jitconfig" in proc.stdout and "ENCODED_JIT_TOKEN_123" in proc.stdout,
          "JIT config passed to run.sh via --jitconfig")

print()
print(f"summary: {PASS} ok, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
