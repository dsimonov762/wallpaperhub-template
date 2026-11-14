#!/usr/bin/env bash
# Tests the conformance suite itself: the reference stub must pass it in all four service personas, and a stub that
# deliberately breaks a rule must fail it. Run it when you change anything under conformance/ or docs/SERVICE-SPEC.md.
#   make conformance-selftest        needs Keycloak with the realm (make up-mocks) and Python 3
# Environment: KEYCLOAK_URL (default http://localhost:8180)   ISSUER (default <KEYCLOAK_URL>/realms/wallpaperhub, the iss of the tokens)
#              JWKS_URI   (default <KEYCLOAK_URL>/realms/wallpaperhub/protocol/openid-connect/certs)   HURL
# Not covered (needs the observability stack): T1-T3. Run `make conformance SVC=...` against a service started with make up-obs.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
KC="${KEYCLOAK_URL:-http://localhost:8180}"
ISSUER="${ISSUER:-http://localhost:8180/realms/wallpaperhub}"
JWKS="${JWKS_URI:-$KC/realms/wallpaperhub/protocol/openid-connect/certs}"
export KEYCLOAK_URL="$KC"
PY="${PYTHON:-python3}"; VENV="$HERE/.venv"
if [ ! -x "$VENV/bin/python" ]; then "$PY" -m venv "$VENV" || exit 2; fi
"$VENV/bin/pip" install -q -r reference-stub/requirements.txt || exit 2
mkdir -p "$HERE/.run"; pids=()
cleanup() { for p in "${pids[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done; wait 2>/dev/null; }
trap cleanup EXIT

start_stub() {   # start_stub <service> <http> <mgmt> [BREAK ids] -> log in .run/<service>.log
  local svc="$1" http="$2" mgmt="$3" brk="${4:-}"
  OTEL_SERVICE_NAME="$svc-service" OIDC_CLIENT_ID="$svc-svc" OIDC_ISSUER_URI="$ISSUER" OIDC_JWKS_URI="$JWKS" \
  HTTP_PORT="$http" MGMT_PORT="$mgmt" BIND_HOST=127.0.0.1 OTEL_SDK_DISABLED=true BREAK="$brk" \
    "$VENV/bin/python" reference-stub/stub.py > ".run/$svc.log" 2>&1 &
  pids+=("$!"); STUB_PID=$!
  for _ in $(seq 1 40); do curl -fs "http://127.0.0.1:$mgmt/health/live" >/dev/null 2>&1 && return 0; sleep 0.25; done
  echo "stub for $svc did not start:"; tail -5 ".run/$svc.log"; return 1
}
stop_stub() { kill "$STUB_PID" 2>/dev/null; wait "$STUB_PID" 2>/dev/null; }
fails=0
i=0
for svc in account media catalog notification; do
  i=$((i+1)); http=$((8100+i)); mgmt=$((8190+i))
  start_stub "$svc" "$http" "$mgmt" || { fails=$((fails+1)); continue; }
  extra=""; [ "$svc" = account ] && extra="--lifecycle"
  if [ -n "$extra" ]; then
    export SERVICE_CMD="$VENV/bin/python $HERE/reference-stub/stub.py"
    export OTEL_SERVICE_NAME="$svc-service" OIDC_CLIENT_ID="$svc-svc" OIDC_ISSUER_URI="$ISSUER" OIDC_JWKS_URI="$JWKS" HTTP_PORT=$((http+100)) MGMT_PORT=$((mgmt+100)) BIND_HOST=127.0.0.1 OTEL_SDK_DISABLED=true
  fi
  # with --lifecycle the lifecycle checks start their own copy on other ports (HTTP_PORT+100); this one is checked over HTTP and logs
  if "$HERE/run.sh" "$svc" --api "http://127.0.0.1:$http" --mgmt "http://127.0.0.1:$mgmt" --log-file ".run/$svc.log" --no-telemetry $extra > ".run/result-$svc.txt" 2>&1; then
    echo "PASS  the reference stub passes as $svc"
  else echo "FAIL  the reference stub does not pass as $svc:"; sed 's/^/      /' ".run/result-$svc.txt" | tail -30; fails=$((fails+1)); fi
  unset SERVICE_CMD; stop_stub
done

# negative tests: each broken stub must be caught, by the group named
neg() {   # neg <break id> <expected text in the output>
  start_stub account 8101 8191 "$1" || { fails=$((fails+1)); return; }
  out="$("$HERE/run.sh" account --api http://127.0.0.1:8101 --mgmt http://127.0.0.1:8191 --log-file .run/account.log --no-telemetry 2>&1)"; code=$?
  if [ $code -eq 1 ] && grep -q "$2" <<< "$out"; then echo "PASS  BREAK=$1 is caught ($2)"
  else echo "FAIL  BREAK=$1 was not caught as expected (exit $code, wanted '$2')"; sed 's/^/      /' <<< "$out" | tail -15; fails=$((fails+1)); fi
  stop_stub
}
neg M4 "FAIL M1-M4"
neg A3 "FAIL A0-A4"
neg E2 "FAIL E1-E6"
neg L2 "FAIL L2"
neg L3 "FAIL L3"

echo; if [ $fails -eq 0 ]; then echo "conformance self-test: ok"; else echo "conformance self-test: $fails failure(s)"; fi
exit $((fails > 0))
