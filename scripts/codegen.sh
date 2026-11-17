#!/usr/bin/env bash
# Generate code from contracts/. Output goes to gen/ (not committed). Run through make:  make codegen TARGET=...
#
#   scripts/codegen.sh typescript                       types for the four OpenAPI specs: gen/typescript/<service>.d.ts, then type-checked
#   scripts/codegen.sh openapi GENERATOR SERVICE [args] any openapi-generator generator (spring, go-server, python-fastapi, csharp, ...):
#                                                       gen/<GENERATOR>/<SERVICE>/   e.g.  make codegen TARGET=openapi GEN="spring account"
#   scripts/codegen.sh proto TEMPLATE                   buf generate contracts/proto --template TEMPLATE (a buf.gen.yaml you write for your language)
#
# Environment: CONTRACT_TOOLS=native (see scripts/ct.sh)   OPENAPI_GENERATOR_IMAGE (default openapitools/openapi-generator-cli:v7.27.0)
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"; CT="$ROOT/scripts/ct.sh"
SPECS=(account media catalog notification)
case "${1:-}" in
  typescript)
    mkdir -p gen/typescript
    for s in "${SPECS[@]}"; do "$CT" openapi-typescript "contracts/openapi/$s.yaml" -o "gen/typescript/$s.d.ts" >/dev/null; echo "  gen/typescript/$s.d.ts"; done
    "$CT" tsc --noEmit --strict gen/typescript/*.d.ts && echo "type-check: ok"
    ;;
  openapi)
    gen="${2:?generator name, e.g. spring}"; svc="${3:?service: ${SPECS[*]}}"; shift 3
    [ -f "contracts/openapi/$svc.yaml" ] || { echo "no contracts/openapi/$svc.yaml" >&2; exit 2; }
    command -v docker >/dev/null || { echo "need docker" >&2; exit 2; }
    mkdir -p "gen/$gen/$svc"
    docker run --rm -u "$(id -u):$(id -g)" -v "$ROOT:/repo" -w /repo "${OPENAPI_GENERATOR_IMAGE:-openapitools/openapi-generator-cli:v7.27.0}" \
      generate -i "contracts/openapi/$svc.yaml" -g "$gen" -o "gen/$gen/$svc" "$@"
    ;;
  proto)
    tpl="${2:?path of a buf.gen.yaml}"; "$CT" buf generate contracts/proto --template "$tpl"
    ;;
  *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
