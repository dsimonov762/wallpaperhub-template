#!/usr/bin/env bash
# Wallpaper Hub service conformance suite. Language-agnostic: it talks HTTP to a running service, reads its stdout log and
# asks Tempo / Loki / Prometheus. What is checked is docs/SERVICE-SPEC.md; the IDs below are the ones of that document.
#
#   ./run.sh <account|media|catalog|notification> [options]
#
#   --api URL        base URL of the service API         (default: the host port of docker-compose.yml, or env API_URL)
#   --mgmt URL       base URL of the management port     (default likewise, or env MGMT_URL)
#   --log-file PATH  read the log of the service from a file (host mode: `my-service 2>&1 | tee service.log`)
#   --container NAME read the log with `docker logs NAME`   (default: the compose container of the service)
#   --no-logs        skip L1-L3        --no-telemetry   skip T1-T3 (they need `make up-obs`)
#   --lifecycle      also run C1 and S1; these stop the service (needs SERVICE_CMD or CONTAINER, see checks/lifecycle.sh)
#   --require VAR    the variable C1 unsets (default OIDC_ISSUER_URI)
#
# Other environment: KEYCLOAK_URL REALM CLIENT_ID (as e2e/run.sh)  TEMPO_URL LOKI_URL PROM_URL  HURL (hurl command)
# Exit code: 0 all checks passed (skipped ones are listed), 1 a check failed, 2 the suite could not run.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
SVC="${1:-}"; [ $# -gt 0 ] && shift
[ -f "$HERE/services/$SVC.env" ] || { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

NO_LOGS=0; NO_TEL=0; LIFECYCLE=0; REQUIRE=OIDC_ISSUER_URI; LOG_FILE=""
set -a; . "$HERE/services/$SVC.env"; set +a
API_URL="${API_URL:-$API_URL_DEFAULT}"; MGMT_URL="${MGMT_URL:-$MGMT_URL_DEFAULT}"; CONTAINER="${CONTAINER:-$LOG_CONTAINER_DEFAULT}"
while [ $# -gt 0 ]; do
  case "$1" in
    --api) API_URL="$2"; shift ;; --mgmt) MGMT_URL="$2"; shift ;; --log-file) LOG_FILE="$2"; shift ;;
    --container) CONTAINER="$2"; shift ;; --no-logs) NO_LOGS=1 ;; --no-telemetry) NO_TEL=1 ;;
    --lifecycle) LIFECYCLE=1 ;; --require) REQUIRE="$2"; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac; shift
done
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8180}"; REALM="${REALM:-wallpaperhub}"; CLIENT_ID="${CLIENT_ID:-e2e-tests}"
TEMPO_URL="${TEMPO_URL:-http://localhost:3200}"; LOKI_URL="${LOKI_URL:-http://localhost:3100}"; PROM_URL="${PROM_URL:-http://localhost:9090}"
PY=""; for p in python3 python; do command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info[0] != 3)' 2>/dev/null && { PY="$p"; break; }; done

# ---- hurl: installed binary, else the official container ---------------------------------------------------------------
HURL_CMD=(); HURL_API="$API_URL"; HURL_MGMT="$MGMT_URL"
if [ -n "${HURL:-}" ]; then HURL_CMD=("$HURL")
elif command -v hurl >/dev/null 2>&1; then HURL_CMD=(hurl)
elif command -v docker >/dev/null 2>&1; then
  echo "hurl not found, using the container ghcr.io/orange-opensource/hurl:8.1.0 (install hurl for speed: winget install hurl)"
  HURL_API="${API_URL//localhost/host.docker.internal}"; HURL_MGMT="${MGMT_URL//localhost/host.docker.internal}"
  HURL_CMD=(docker run --rm --add-host=host.docker.internal:host-gateway -v "$HERE:/c" -w /c ghcr.io/orange-opensource/hurl:8.1.0)
else echo "need hurl (https://hurl.dev) or docker" >&2; exit 2; fi

# ---- tokens ------------------------------------------------------------------------------------------------------------
tok_url="$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token"
# Keycloak over https (make up-https HTTPS_ISSUER=1): trust the mkcert CA of this repo (make certs)
CURL_CA=()
case "$KEYCLOAK_URL" in https://*)
  if [ -f "$ROOT/infra/certs/rootCA.pem" ]; then CURL_CA=(--cacert "$ROOT/infra/certs/rootCA.pem")
  else echo "KEYCLOAK_URL is https but infra/certs/rootCA.pem is missing: make certs" >&2; fi ;;
esac
json_field() { sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p"; }
user_token() {  # user_token <user>
  curl -sS ${CURL_CA[@]+"${CURL_CA[@]}"} -X POST "$tok_url" -d grant_type=password -d "client_id=$CLIENT_ID" -d "username=$1" -d password=password | json_field access_token; }
client_token() {  # client_token <client id> : client credentials, secret from the compose defaults
  local var; var="$(echo "${1%-svc}" | tr a-z A-Z)_SVC_SECRET"
  curl -sS ${CURL_CA[@]+"${CURL_CA[@]}"} -X POST "$tok_url" -d grant_type=client_credentials -d "client_id=$1" -d "client_secret=${!var:-$1-dev-secret}" | json_field access_token; }
GOOD="$(user_token alice)"; LIST_TOKEN="$(user_token "$LIST_USER")"; VAL_TOKEN="$(user_token "$VALIDATION_USER")"
WRONG_AUD="$(client_token "$BAD_AUD_CLIENT")"
if [ -z "$GOOD" ] || [ -z "$LIST_TOKEN" ] || [ -z "$VAL_TOKEN" ] || [ -z "$WRONG_AUD" ]; then
  echo "no token from $tok_url: is Keycloak up and the realm imported? (make up, then make logs S=keycloak)" >&2; exit 2; fi
# change one character of the signature, 10 from the end: the last characters carry unused base64 bits and may decode to the same bytes
n=${#GOOD}; c="${GOOD:$((n-10)):1}"; [ "$c" = "A" ] && r="B" || r="A"
TAMPERED="${GOOD:0:$((n-10))}$r${GOOD:$((n-9))}"

rand_hex() { od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'; }
TRACE_ID="$(rand_hex 16)"; SPAN_ID="$(rand_hex 8)"

bundle() {  # bundle <lang> <key> : text of contracts/i18n/messages.<lang>.json
  sed -n "s/^ *\"$2\": *\"\(.*\)\",\{0,1\} *\$/\1/p" "$ROOT/contracts/i18n/messages.$1.json" | head -1 | sed 's/\\"/"/g'; }

# ---- results -----------------------------------------------------------------------------------------------------------
FAILS=0; SKIPS=()
say_hurl() {  # say_hurl <label> <file> [extra args]
  local label="$1" file="$2"; shift 2
  if out="$("${HURL_CMD[@]}" --test --jobs 1 --file-root . "$@" "${FILE_PREFIX}$file" 2>&1)"; then echo "PASS $label"
  else echo "FAIL $label"; echo "$out" | sed 's/^/     /' | head -40; FAILS=$((FAILS+1)); fi
}
FILE_PREFIX=""; [ "${HURL_CMD[0]}" = docker ] && FILE_PREFIX="http/" || FILE_PREFIX="$HERE/http/"
V=(--variable "api_url=$HURL_API" --variable "mgmt_url=$HURL_MGMT" --variable "protected_path=$PROTECTED_PATH"
   --variable "good_token=$GOOD" --variable "tampered_token=$TAMPERED" --variable "wrong_aud_token=$WRONG_AUD"
   --variable "bad_aud_client=$BAD_AUD_CLIENT" --variable "list_path=$LIST_PATH" --variable "list_token=$LIST_TOKEN"
   --variable "trace_id=$TRACE_ID" --variable "span_id=$SPAN_ID"
   --variable "validation_path=$VALIDATION_PATH" --variable "validation_token=$VAL_TOKEN")
for lang in en de es; do
  V+=(--variable "${lang}_not_found_title=$(bundle $lang problem.not-found.title)"
      --variable "${lang}_not_found_detail=$(bundle $lang problem.not-found.detail)")
done
V+=(--variable "de_validation_title=$(bundle de problem.validation-failed.title)")

echo "== conformance of $SVC: api $API_URL, management $MGMT_URL"
if ! curl -fsS -o /dev/null --max-time 5 "$MGMT_URL/health/live" 2>/dev/null; then
  echo "FAIL M1: $MGMT_URL/health/live is not reachable. Is the service running? (host mode: make host SVC=$SVC, then start it in the IDE)"; exit 1; fi

say_hurl "M1-M4   management endpoints"        10-management.hurl "${V[@]}"
say_hurl "A0-A4   authentication"              20-authentication.hurl "${V[@]}"
say_hurl "E1-E6   error format, i18n, trace id" 30-errors.hurl "${V[@]}"
if [ "$VALIDATION" = multipart ]; then
  say_hurl "E3      validation errors (multipart)" 31-validation-multipart.hurl "${V[@]}"
else say_hurl "E3      validation errors (json)"    31-validation-json.hurl "${V[@]}"; fi

# ---- logs --------------------------------------------------------------------------------------------------------------
if [ "$NO_LOGS" = 1 ]; then SKIPS+=("L1-L3 (--no-logs)")
elif [ -z "$PY" ]; then SKIPS+=("L1-L3 (no python3 on this machine)")
else
  src=(--docker "$CONTAINER"); [ -n "$LOG_FILE" ] && src=(--file "$LOG_FILE")
  if [ -z "$LOG_FILE" ] && ! { command -v docker >/dev/null 2>&1 && docker inspect "$CONTAINER" >/dev/null 2>&1; }; then
    SKIPS+=("L1-L3 (no container $CONTAINER; in host mode pass --log-file)")
  else
    if out="$("$PY" -I "$HERE/checks/logs.py" "${src[@]}" --trace-id "$TRACE_ID" --secret conformance-secret-pw --secret leak-check@example.test \
              --secret "$GOOD" --secret "$WRONG_AUD" 2>&1)"; then echo "$out" | sed 's/^/     /'
    else echo "$out" | sed 's/^/     /'; FAILS=$((FAILS+1)); fi
  fi
fi

# ---- telemetry ---------------------------------------------------------------------------------------------------------
if [ "$NO_TEL" = 1 ]; then SKIPS+=("T1-T3 (--no-telemetry)")
elif [ -z "$PY" ]; then SKIPS+=("T1-T3 (no python3 on this machine)")
elif ! curl -fsS -o /dev/null --max-time 3 "$PROM_URL/-/ready" 2>/dev/null; then SKIPS+=("T1-T3 (Prometheus not reachable at $PROM_URL: make up-obs)")
else
  if out="$("$PY" -I "$HERE/checks/telemetry.py" --service "$OTEL_NAME" --trace-id "$TRACE_ID" --tempo "$TEMPO_URL" --loki "$LOKI_URL" --prom "$PROM_URL" 2>&1)"; then
    echo "$out" | sed 's/^/     /'; else echo "$out" | sed 's/^/     /'; FAILS=$((FAILS+1)); fi
fi

# ---- lifecycle ---------------------------------------------------------------------------------------------------------
if [ "$LIFECYCLE" = 1 ]; then
  if [ -n "${SERVICE_CMD:-}" ]; then LC_CONTAINER=""; else LC_CONTAINER="$CONTAINER"; fi
  if out="$(MGMT_URL="$MGMT_URL" COMPOSE_SERVICE="$SVC" CONTAINER="$LC_CONTAINER" REPO_ROOT="$ROOT" bash "$HERE/checks/lifecycle.sh" "$REQUIRE" 2>&1)"; then
    echo "$out" | sed 's/^/     /'
  else echo "$out" | sed 's/^/     /'; FAILS=$((FAILS+1)); fi
else SKIPS+=("C1, S1 (stop the service; add --lifecycle)"); fi

echo
[ ${#SKIPS[@]} -gt 0 ] && { echo "skipped: ${SKIPS[*]}"; }
if [ "$FAILS" = 0 ]; then echo "conformance of $SVC: all executed checks passed"; exit 0; fi
echo "conformance of $SVC: $FAILS group(s) failed"; exit 1
