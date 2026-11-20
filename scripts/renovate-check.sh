#!/usr/bin/env bash
# make renovate-check: is .github/renovate.json5 a valid Renovate configuration? (strict: unknown keys, bad regular expressions, bad rule options are errors)
# Offline, takes a few seconds once the package is cached. docs/RENOVATE.md
#
#   RENOVATE_VERSION   the Renovate release to check with. Renovate itself keeps this default current (a regex manager in .github/renovate.json5 reads it).
#   --if-possible      for the git hook: when neither Node 24.11+ nor a running Docker is there, say so and succeed (CI runs the check; a hook must not
#                      fail a commit because of a tool that is not installed). Without the flag the script fails (exit 2), as `make renovate-check` should.
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

RENOVATE_VERSION="${RENOVATE_VERSION:-44.255.0}"

# Renovate 44 needs Node 24.11+ (or 26.13+). Older Node: use the container instead.
node_ok() {
  command -v node >/dev/null 2>&1 && command -v npx >/dev/null 2>&1 &&
    node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit((a === 24 && b >= 11) || (a === 26 && b >= 13) || a > 26 ? 0 : 1)'
}

if node_ok; then
  echo "renovate-config-validator $RENOVATE_VERSION (npx)"
  exec npx --yes --package "renovate@$RENOVATE_VERSION" renovate-config-validator --strict
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "renovate-config-validator $RENOVATE_VERSION (container; Node 24.11+ would make this faster: no image to pull)"
  exec docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/repo" -w /repo --entrypoint renovate-config-validator \
    "ghcr.io/renovatebot/renovate:$RENOVATE_VERSION" --strict
elif [ "${1:-}" = "--if-possible" ]; then
  echo "renovate-check skipped: it needs Node 24.11+ (with npx) or a running Docker, and neither is available here. CI runs it; to run it now: start Docker Desktop, then make renovate-check" >&2
  exit 0
else
  echo "need Node 24.11+ (with npx) or a running Docker to run Renovate's config validator" >&2
  exit 2
fi
