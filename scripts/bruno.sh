#!/usr/bin/env bash
# Run the Bruno collection (bruno/) from the command line, as one of the seeded users, against the local stack.
#
#   scripts/bruno.sh                       the whole collection as alice
#   scripts/bruno.sh --env admin           as another user (alice, mod, admin, bob, carol, ... see bruno/environments/)
#   scripts/bruno.sh catalog/wallpapers    one folder or file (everything after the options goes to `bru run`)
#   scripts/bruno.sh --tags read           only the requests tagged `read` (GET) - nothing is changed
#   scripts/bruno.sh --junit out.xml       a JUnit report (other `bru run` options work the same way)
#
# The requests that need a role the user does not have (tags `admin`, `moderator`) are left out: the roles are read from
# the user's token, so `--env admin` runs everything and `--env alice` skips what would answer 403.
# Environment: BASE_URL (http://localhost:<PORT_GATEWAY or 8080>)  KEYCLOAK_URL (http://localhost:<PORT_KEYCLOAK or 8180>)
#              BRU (default: npx --yes @usebruno/cli@4.3.0 - needs Node 20+; BRU=bru uses an installed one)
# Needs the stack: make up-mocks (gateway + mocks: the answers are examples) or make up-apps (real services), and make seed
# for the ids of the environments.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/infra/.env" ] && { set -a; . "$ROOT/infra/.env" 2>/dev/null; set +a; }
BASE_URL="${BASE_URL:-http://localhost:${PORT_GATEWAY:-8080}}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:${PORT_KEYCLOAK:-8180}}"; export KEYCLOAK_URL
BRU="${BRU:-npx --yes @usebruno/cli@4.3.0}"
ENV_NAME=alice; EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_NAME="${2:-}"; [ -n "$ENV_NAME" ] || { echo "--env needs a name" >&2; exit 2; }; shift ;;
    --junit) EXTRA+=(--reporter-junit "${2:?--junit needs a file}"); shift ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) EXTRA+=("$1") ;;
  esac; shift
done
[ -f "$ROOT/bruno/environments/$ENV_NAME.bru" ] || {
  echo "no environment '$ENV_NAME'; available: $(cd "$ROOT/bruno/environments" && ls *.bru | sed 's/\.bru$//' | tr '\n' ' ')" >&2; exit 2; }
command -v node >/dev/null 2>&1 || [ "$BRU" != "${BRU#bru}" ] || { echo "Node 20+ is needed to run the Bruno CLI (or install it and use BRU=bru)" >&2; exit 1; }

# roles of the user -> requests to leave out
claims="$("$ROOT/scripts/token.sh" --decode "$ENV_NAME" 2>&1)" || { echo "$claims" >&2; exit 1; }
EXCLUDE=""
case "$claims" in *'"MODERATOR"'*) ;; *) EXCLUDE="moderator" ;; esac
case "$claims" in *'"ADMIN"'*) ;; *) EXCLUDE="${EXCLUDE:+$EXCLUDE,}admin" ;; esac
ARGS=(run --env "$ENV_NAME" --env-var "baseUrl=$BASE_URL" --env-var "keycloakUrl=$KEYCLOAK_URL")
[ -z "$EXCLUDE" ] || ARGS+=(--exclude-tags "$EXCLUDE")

echo "bruno: $ENV_NAME against $BASE_URL${EXCLUDE:+ (skipping tags: $EXCLUDE)}" >&2
cd "$ROOT/bruno" || exit 1
# shellcheck disable=SC2086
exec $BRU "${ARGS[@]}" ${EXTRA[@]+"${EXTRA[@]}"}
