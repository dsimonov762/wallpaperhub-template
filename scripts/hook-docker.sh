#!/usr/bin/env bash
# Runs a command from a git hook, but only when Docker is there. Used by the pre-push hooks of .pre-commit-config.yaml.
#
#   scripts/hook-docker.sh make lint                 needs the docker CLI with compose (no daemon: `compose config` only reads files)
#   scripts/hook-docker.sh --daemon make contracts-lint     needs a running Docker daemon (builds and runs the tool image)
#
# On Windows + WSL the docker CLI only exists while Docker Desktop is running. A hook that fails a push because of that is noise: CI runs the same
# checks and is the gate, so without Docker this says so and succeeds. Run the same command by hand once Docker is up.
set -u
need="compose"
if [ "${1:-}" = "--daemon" ]; then need="daemon"; shift; fi

if [ "$need" = "daemon" ]; then
  docker info >/dev/null 2>&1 && exec "$@"
  reason="Docker is not running"
else
  docker compose version >/dev/null 2>&1 && exec "$@"
  reason="the docker CLI (with compose) is not available, Docker Desktop is probably not running"
fi
echo "skipped '$*': $reason. CI runs it; to run it now: start Docker, then $*" >&2
exit 0
