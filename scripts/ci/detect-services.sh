#!/usr/bin/env bash
# Finds the service implementations to test: every services/<service>/<impl>/Dockerfile of account, media, catalog,
# notification. Prints the matrix for GitHub Actions; with $GITHUB_OUTPUT set it also writes matrix= and any=.
#   scripts/ci/detect-services.sh [BASE_REV]
# With BASE_REV (a pull request) an implementation is skipped when nothing relevant changed since BASE_REV: relevant
# is its own folder and the shared things every service depends on (contracts, infra, conformance, scripts, tools, Makefile, workflows).
# FORCE_ALL=1 tests every implementation.
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
BASE="${1:-}"
changed=""; all=1
if [ -n "$BASE" ] && [ "${FORCE_ALL:-}" != 1 ]; then
  changed="$(git diff --name-only "$BASE"...HEAD 2>/dev/null || git diff --name-only "$BASE" HEAD)"
  if ! printf '%s\n' "$changed" | grep -Eq '^(contracts/|infra/|conformance/|scripts/|tools/|Makefile$|\.github/)'; then all=0; fi
fi
items=""
for svc in account media catalog notification; do
  for df in services/$svc/*/Dockerfile; do
    [ -f "$df" ] || continue
    dir="$(dirname "$df")"
    if [ "$all" = 0 ] && ! printf '%s\n' "$changed" | grep -q "^$dir/"; then continue; fi
    items="$items{\"service\":\"$svc\",\"dir\":\"$dir\"},"
  done
done
items="${items%,}"
matrix="{\"include\":[${items}]}"; any=false; [ -n "$items" ] && any=true
echo "$matrix"
if [ -n "${GITHUB_OUTPUT:-}" ]; then { echo "matrix=$matrix"; echo "any=$any"; } >> "$GITHUB_OUTPUT"; fi
