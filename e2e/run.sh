#!/usr/bin/env bash
# Wallpaper Hub e2e runner (Hurl).   Works in WSL, Git Bash and Linux/macOS shells.
#
#   ./run.sh gateway      facts only the gateway decides (health, problem+json, CORS, token routing, rate limit).
#                         Passes against the real services AND against the Prism mocks (make up-mocks).
#   ./run.sh system       README 4.1 user flows through every service (needs the real implementations).
#   ./run.sh all          system first, then gateway (its rate-limit test empties the registration bucket for a minute).
#
# Environment (all optional):  BASE_URL  KEYCLOAK_URL  REALM  CLIENT_ID  HURL (path/command of hurl)  HURL_ARGS
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
GROUP="${1:-gateway}"

# shellcheck disable=SC1091
set -a; . ./env/local.env; set +a
BASE_URL="${BASE_URL:-$base_url}"; KEYCLOAK_URL="${KEYCLOAK_URL:-$keycloak_url}"
REALM="${REALM:-$realm}"; CLIENT_ID="${CLIENT_ID:-$client_id}"

# ---- hurl: installed binary, else the official container ---------------------------------------------------------
HURL_CMD=()
if [ -n "${HURL:-}" ]; then HURL_CMD=("$HURL")
elif command -v hurl >/dev/null 2>&1; then HURL_CMD=(hurl)
elif command -v docker >/dev/null 2>&1; then
  echo "hurl not found, using the container ghcr.io/orange-opensource/hurl:8.1.0 (install hurl for speed: winget install hurl)"
  # Inside the container localhost is the container: reach the host through Docker Desktop's alias.
  BASE_URL="${BASE_URL//localhost/host.docker.internal}"; KEYCLOAK_URL="${KEYCLOAK_URL//localhost/host.docker.internal}"
  HURL_CMD=(docker run --rm --add-host=host.docker.internal:host-gateway -v "$HERE:/e2e" -w /e2e ghcr.io/orange-opensource/hurl:8.1.0)
else echo "need hurl (https://hurl.dev) or docker" >&2; exit 2; fi

mkdir -p .run
RUN_ID="$(date +%s | tail -c 7)$RANDOM"   # unique per run: usernames, titles, idempotency keys

token() {   # token <user> -> access token of a seeded realm user (password grant is enabled for the e2e-tests client)
  curl -sS --fail-with-body -X POST "$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token" \
    -d grant_type=password -d "client_id=$CLIENT_ID" -d "username=$1" -d password=password \
    | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p'
}

COMMON=(--test --jobs 1 --file-root . --variables-file env/local.env
        --variable "base_url=$BASE_URL" --variable "keycloak_url=$KEYCLOAK_URL" --variable "realm=$REALM"
        --variable "client_id=$CLIENT_ID" --variable "run_id=$RUN_ID"
        --report-junit ".run/junit-$GROUP.xml")

run_gateway() { "${HURL_CMD[@]}" "${COMMON[@]}" ${HURL_ARGS:-} gateway/10-*.hurl gateway/20-*.hurl gateway/25-*.hurl gateway/30-*.hurl gateway/99-*.hurl; }

run_system() {
  echo "fetching tokens for alice and mod from $KEYCLOAK_URL"
  ALICE="$(token alice)"; MOD="$(token mod)"
  [ -n "$ALICE" ] && [ -n "$MOD" ] || { echo "no token: is Keycloak up and the realm imported? (make logs S=keycloak)" >&2; exit 1; }
  # a picture nobody uploaded before (duplicate detection by SHA-256 and perceptual hash)
  PNG=fixtures/wallpaper-1920x1080.png; PNG2=fixtures/wallpaper-1920x1080.png
  for py in python3 python "py -3"; do
    if $py --version >/dev/null 2>&1; then
      $py fixtures/make_fixtures.py unique .run/upload.png && $py fixtures/make_fixtures.py unique .run/upload2.png
      PNG=.run/upload.png; PNG2=.run/upload2.png; break
    fi
  done
  [ "$PNG" = .run/upload.png ] || echo "no python found: using the committed picture (works once; later runs are rejected as DUPLICATE)"
  "${HURL_CMD[@]}" "${COMMON[@]}" ${HURL_ARGS:-} --variable "alice_token=$ALICE" --variable "mod_token=$MOD" \
      --variable "upload_png=$PNG" --variable "upload_png2=$PNG2" system/*.hurl
}

case "$GROUP" in
  gateway) run_gateway ;;
  system)  run_system ;;
  all)     run_system; run_gateway ;;
  *) echo "usage: $0 gateway|system|all" >&2; exit 2 ;;
esac
