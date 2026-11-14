#!/usr/bin/env bash
# Contract tooling. Run through make:  make contracts-lint | make contracts-breaking [BASE=origin/master]
#
#   scripts/contracts.sh lint                 Spectral (OpenAPI), buf lint (proto), Avro and GraphQL conventions
#   scripts/contracts.sh breaking [BASE]      compare contracts/ with the same folder at BASE and fail on breaking changes:
#                                               oasdiff (OpenAPI), buf breaking (proto), Avro compatibility, GraphQL breaking changes
#                                             BASE is a git ref (default origin/master, else master, else HEAD~1) or a folder that contains contracts/
#
# Environment:  CONTRACT_TOOLS=native      use Node on this machine instead of the tools image (scripts/ct.sh)
#               OASDIFF=<command>          oasdiff binary to use instead of the container (default: oasdiff on PATH, else docker)
#               OASDIFF_IMAGE              default tufin/oasdiff:v1.33.0
#               OASDIFF_FAIL_ON            ERR (default) or WARN: what makes oasdiff fail
#               AVRO_MODE                  BACKWARD (default, what Schema Registry enforces) or FULL
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
CT="$ROOT/scripts/ct.sh"
SPECS=(account media catalog notification)
rc=0
hdr() { printf '\n== %s\n' "$*"; }
fail() { rc=1; echo "FAILED: $*"; }

pybin() {
  [ -x .venv-validate/bin/python ] || python3 -m venv .venv-validate || exit 2
  .venv-validate/bin/pip install -q -r scripts/validate/requirements.txt || exit 2
  echo .venv-validate/bin/python
}

lint() {
  hdr "OpenAPI: Spectral with contracts/.spectral.yaml"
  files=(); for s in "${SPECS[@]}"; do files+=("contracts/openapi/$s.yaml"); done
  "$CT" spectral lint "${files[@]}" -r contracts/.spectral.yaml --fail-severity warn -f stylish && echo "ok" || fail "Spectral"
  hdr "Protobuf: buf lint (contracts/proto/buf.yaml)"
  "$CT" buf lint contracts/proto && echo "ok" || fail "buf lint"
  hdr "Avro and GraphQL conventions"
  "$(pybin)" scripts/contracts/check.py lint || fail "Avro/GraphQL lint"
}

resolve_base() {  # prints the folder that contains the base contracts/, empty when BASE has none
  local base="${1:-}" tmp="$ROOT/.contracts-base"
  rm -rf "$tmp"; mkdir -p "$tmp"
  if [ -n "$base" ] && [ -d "$base/contracts" ]; then cp -r "$base/contracts" "$tmp/contracts"; echo "$tmp"; return; fi
  command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repository: pass BASE=<folder containing contracts/>" >&2; return 2; }
  if [ -z "$base" ]; then
    for c in origin/master master HEAD~1; do git -C "$ROOT" rev-parse --verify -q "$c^{commit}" >/dev/null && { base="$c"; break; }; done
    [ -n "$base" ] || { echo "no base revision found (origin/master, master, HEAD~1); pass BASE=<git ref>" >&2; return 2; }
  fi
  git -C "$ROOT" rev-parse --verify -q "$base^{commit}" >/dev/null || { echo "unknown git ref: $base" >&2; return 2; }
  echo "base: $base ($(git -C "$ROOT" rev-parse --short "$base"))" >&2
  git -C "$ROOT" archive "$base" contracts 2>/dev/null | tar -x -C "$tmp" 2>/dev/null
  [ -d "$tmp/contracts" ] && echo "$tmp" || echo ""
}

run_oasdiff() {  # run_oasdiff <args>: paths are relative to the repo root
  if [ -n "${OASDIFF:-}" ]; then "$OASDIFF" "$@"
  elif command -v oasdiff >/dev/null 2>&1; then oasdiff "$@"
  elif command -v docker >/dev/null 2>&1; then
    docker run --rm -v "$ROOT:/repo" -w /repo "${OASDIFF_IMAGE:-tufin/oasdiff:v1.33.0}" "$@"
  else echo "need oasdiff or docker" >&2; return 2; fi
}

breaking() {
  local b; b="$(resolve_base "${1:-}")"; local st=$?
  trap 'rm -rf "$ROOT/.contracts-base"' EXIT
  [ $st -ne 0 ] && exit 2
  if [ -z "$b" ]; then echo "the base revision has no contracts/ folder: nothing to compare with"; exit 0; fi
  local base_rel=".contracts-base/contracts"

  hdr "OpenAPI: oasdiff breaking (fail on ${OASDIFF_FAIL_ON:-ERR})"
  for s in "${SPECS[@]}"; do
    if [ ! -f "$base_rel/openapi/$s.yaml" ]; then echo "  new   $s.yaml"; continue; fi
    if [ ! -f "contracts/openapi/$s.yaml" ]; then fail "contracts/openapi/$s.yaml was removed"; continue; fi
    echo "  $s.yaml"
    run_oasdiff breaking "$base_rel/openapi/$s.yaml" "contracts/openapi/$s.yaml" --fail-on "${OASDIFF_FAIL_ON:-ERR}" | sed 's/^/    /'
    [ "${PIPESTATUS[0]}" = 0 ] || fail "oasdiff $s.yaml"
  done

  hdr "Protobuf: buf breaking (FILE rules)"
  if [ -d "$base_rel/proto" ]; then "$CT" buf breaking contracts/proto --against "$base_rel/proto" && echo "ok" || fail "buf breaking"
  else echo "  no proto in the base revision"; fi

  hdr "Avro (${AVRO_MODE:-BACKWARD}) and GraphQL"
  "$(pybin)" scripts/contracts/check.py breaking "$base_rel" --avro-mode "${AVRO_MODE:-BACKWARD}" || fail "Avro/GraphQL"
}

case "${1:-}" in
  lint) lint ;;
  breaking) breaking "${2:-}" ;;
  *) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
echo
[ $rc = 0 ] && echo "contracts $1: ok" || echo "contracts $1: FAILED"
exit $rc
