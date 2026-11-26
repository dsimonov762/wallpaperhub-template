#!/usr/bin/env bash
# Waits until a service container answers 200 on its /health/ready (management port), so that a conformance run or an
# e2e test does not start while the process is still booting. Works for any language and any image: the check runs on
# the host with curl, so the image needs no curl, wget or shell (distroless images are fine).
#
#   scripts/wait-ready.sh <account|media|catalog|notification> [timeout-seconds]      (default 180)
#
# The address comes from conformance/services/<name>.env (the host port of docker-compose.yml); MGMT_URL overrides it
# (host mode). Fails early when the container has exited; on a timeout it prints the state and the end of the log.
# Why not a Compose healthcheck: wait-healthy.sh waits only for containers that have one, and a healthcheck would need a
# client inside every image. Exit code: 0 ready, 1 not ready in time or the container died, 2 usage.
set -u
SVC="${1:-}"; timeout="${2:-180}"
HERE="$(cd "$(dirname "$0")" && pwd)"; ENVF="$HERE/../conformance/services/$SVC.env"
[ -n "$SVC" ] && [ -f "$ENVF" ] || { echo "usage: scripts/wait-ready.sh <account|media|catalog|notification> [timeout-seconds]" >&2; exit 2; }
case "$timeout" in ''|*[!0-9]*) echo "timeout must be a number of seconds, got: $timeout" >&2; exit 2;; esac
command -v curl >/dev/null 2>&1 || { echo "wait-ready: curl is needed on this machine" >&2; exit 2; }
set -a
# shellcheck source=/dev/null
. "$ENVF"
set +a
MGMT_URL="${MGMT_URL:-$MGMT_URL_DEFAULT}"; CONTAINER="${CONTAINER:-$LOG_CONTAINER_DEFAULT}"
url="$MGMT_URL/health/ready"
start=$(date +%s); end=$(( start + timeout )); code="000"; shown=0

state() { command -v docker >/dev/null 2>&1 && docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true; }

echo "waiting for $SVC: $url (up to ${timeout}s)"
while :; do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url" 2>/dev/null || true)"
  if [ "$code" = 200 ]; then echo "$SVC is ready after $(( $(date +%s) - start ))s"; exit 0; fi
  st="$(state)"
  if [ "$st" = exited ] || [ "$st" = dead ]; then
    echo "FAIL: the container $CONTAINER is $st (last answer from $url: HTTP $code)"
    docker logs --tail 40 "$CONTAINER" 2>&1 | sed 's/^/  | /'; exit 1; fi
  if [ "$(date +%s)" -ge "$end" ]; then
    echo "FAIL: $url did not answer 200 within ${timeout}s (last answer: HTTP $code; 000 = no connection, 503 = a dependency is missing)"
    if [ -n "$st" ]; then echo "container $CONTAINER: $st"; docker logs --tail 40 "$CONTAINER" 2>&1 | sed 's/^/  | /'; fi
    exit 1; fi
  n=$(( ($(date +%s) - start) / 15 ))
  [ "$n" -gt "$shown" ] && { shown=$n; echo "  still waiting ($(( $(date +%s) - start ))s, HTTP $code${st:+, container $st})"; }
  sleep 1
done
