#!/usr/bin/env bash
# JIT ephemeral runner entrypoint: run exactly ONE job, then exit.
#
# The controller (or plain `docker run`) provides:
#   RUNNER_JITCONFIG  encoded just-in-time runner configuration created via
#                     POST /repos/{owner}/{repo}/actions/runners/generate-jitconfig
#
# JIT semantics (GitHub): the runner "performs at most one job before being
# automatically removed" from the repository. run.sh exits with the job's
# exit code; the controller then reaps this container with `docker rm -v`.
set -euo pipefail

: "${RUNNER_JITCONFIG:?RUNNER_JITCONFIG is required (generate via the GitHub API)}"

echo "[entrypoint] starting JIT runner (one job, then self-removal)"
rc=0
./run.sh --jitconfig "${RUNNER_JITCONFIG}" || rc=$?

echo "[entrypoint] runner finished with rc=${rc}"
exit "${rc}"
