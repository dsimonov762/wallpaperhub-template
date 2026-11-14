#!/usr/bin/env bash
# C1 (fail fast on missing configuration) and S1 (graceful shutdown) of docs/SERVICE-SPEC.md.
# These stop or start the service, so they are opt-in (LIFECYCLE=1 in run.sh) and not part of the default run.
#
#   Process mode: the service runs as a command on your machine (host mode, the reference stub, CI)
#     SERVICE_CMD="python3 stub.py" MGMT_URL=http://127.0.0.1:8081 lifecycle.sh <required-var>
#       the command must run with the environment of the caller; the script unsets <required-var> for C1
#   Docker mode: the service is a compose service
#     COMPOSE_SERVICE=account CONTAINER=wallpaperhub-account-1 lifecycle.sh <required-var>
#       S1 sends SIGTERM to the running container (it stays stopped afterwards: make up-apps restarts it)
set -u
VAR="${1:-OIDC_ISSUER_URI}"
rc=0
pass() { echo "PASS $1${2:+: $2}"; }
fail() { echo "FAIL $1: $2"; rc=1; }

if [ -n "${SERVICE_CMD:-}" ]; then
  # C1: without $VAR the process must exit non-zero within 30 s and say which variable is missing
  out="$(env -u "$VAR" timeout 30 bash -c "exec $SERVICE_CMD" 2>&1)"; code=$?
  if [ "$code" = 124 ]; then fail C1 "still running 30 s after start without $VAR (it must fail fast)"
  elif [ "$code" = 0 ]; then fail C1 "exited 0 without $VAR"
  elif ! grep -q "$VAR" <<< "$out"; then fail C1 "exited $code but the output does not name $VAR"
  else pass C1 "exit $code, names $VAR"; fi

  # S1: start, wait for ready, SIGTERM, expect a clean exit within 30 s
  bash -c "exec $SERVICE_CMD" >/dev/null 2>&1 & pid=$!
  up=0; for _ in $(seq 1 40); do curl -fs "${MGMT_URL:?set MGMT_URL}/health/ready" >/dev/null 2>&1 && { up=1; break; }; sleep 0.5; done
  if [ "$up" = 0 ]; then kill -9 "$pid" 2>/dev/null; fail S1 "service did not become ready in 20 s"
  else
    start=$(date +%s); kill -TERM "$pid"
    for _ in $(seq 1 60); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid"; fail S1 "still running 30 s after SIGTERM"
    else wait "$pid"; code=$?
      if [ "$code" = 0 ] || [ "$code" = 143 ]; then pass S1 "exit $code after $(( $(date +%s) - start )) s"; else fail S1 "exit code $code"; fi
    fi
  fi

elif [ -n "${CONTAINER:-}" ]; then
  svc="${COMPOSE_SERVICE:?set COMPOSE_SERVICE}"
  out="$(docker compose --project-directory "${REPO_ROOT:-.}/infra" -f "${REPO_ROOT:-.}/infra/docker-compose.yml" --profile infra --profile apps \
         run --rm --no-deps -e "$VAR=" "$svc" 2>&1 & sleep 0; wait)" ; code=$?
  # `timeout` around docker run would kill the client, not the container: judge by exit code and output instead
  if [ "$code" = 0 ]; then fail C1 "exited 0 with an empty $VAR"
  elif ! grep -q "$VAR" <<< "$out"; then fail C1 "exited $code but the output does not name $VAR"
  else pass C1 "exit $code, names $VAR"; fi
  start=$(date +%s); docker kill -s TERM "$CONTAINER" >/dev/null
  code="$(timeout 35 docker wait "$CONTAINER")"
  if [ -z "$code" ]; then fail S1 "container still running 35 s after SIGTERM"
  elif [ "$code" = 0 ] || [ "$code" = 143 ]; then pass S1 "exit $code after $(( $(date +%s) - start )) s"
  else fail S1 "exit code $code"; fi
else
  echo "SKIP C1,S1: set SERVICE_CMD (process mode) or CONTAINER and COMPOSE_SERVICE (docker mode)"
fi
exit $rc
