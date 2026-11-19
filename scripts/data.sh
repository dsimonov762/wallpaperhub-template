#!/usr/bin/env bash
# make seed | make reset | make reseed : runs the one-shot jobs of the compose profile `data` (infra/data/*.sh).
#   scripts/data.sh seed|reset|reseed      YES=1 skips the question before a reset
set -u
cd "$(dirname "$0")/.." || exit 1
ACTION="${1:-}"
COMPOSE=(docker compose --project-directory infra -f infra/docker-compose.yml --profile infra --profile data)
JOBS=(data-keycloak data-account-db data-media-db data-catalog-db data-catalog-search data-redis data-s3)

case "$ACTION" in seed|reset|reseed) ;; *) echo "usage: $0 seed|reset|reseed" >&2; exit 2 ;; esac

for need in postgres-account mongo redis; do
  [ -n "$("${COMPOSE[@]}" ps -q --status running "$need" 2>/dev/null)" ] || {
    echo "The infrastructure is not running ($need is down). Start it first: make up" >&2; exit 1; }
done
[ -f seed/out/account.sql ] || { echo "seed/out is missing: run make seed-build" >&2; exit 1; }

run_phase() {  # run_phase seed|reset
  local mode="$1" failed=0 j c code
  echo "== $mode"
  DATA_MODE="$mode" "${COMPOSE[@]}" up -d --no-deps --force-recreate "${JOBS[@]}" >/dev/null || { echo "could not start the jobs" >&2; return 1; }
  for j in "${JOBS[@]}"; do
    c="$("${COMPOSE[@]}" ps -aq "$j")"
    code="$(docker wait "$c")"
    if [ "$code" = 0 ]; then echo "  ok      $j"; else echo "  FAILED  $j (exit $code)"; failed=1; fi
    docker logs "$c" 2>&1 | grep -v '^Picked up' | grep . | sed 's/^/            /' | tail -12
  done
  "${COMPOSE[@]}" rm -f -s "${JOBS[@]}" >/dev/null 2>&1 || true
  return $failed
}

confirm_reset() {
  [ "${YES:-0}" = 1 ] && return 0
  cat <<'TXT'
This deletes ALL data of the local stack (not only the seed data):
  Postgres account + media   every row of every table (schemas stay)
  MongoDB catalog            every document (collections, validators, indexes stay)
  Elasticsearch              every document of the wallpapers index
  Redis (both instances)     everything: caches, rate limits, idempotency keys, inboxes, preferences
  S3                         every object in both buckets
  Keycloak                   every user except alice, mod and admin (the realm itself stays)
Kafka topics, schemas in the registry and Keycloak clients are not touched.
TXT
  if [ ! -t 0 ]; then echo "Not a terminal: run  make $ACTION YES=1  to confirm." >&2; return 1; fi
  read -r -p "Type 'yes' to continue: " answer
  [ "$answer" = yes ] || { echo "aborted"; return 1; }
}

case "$ACTION" in
  seed) run_phase seed || exit 1 ;;
  reset) confirm_reset || exit 1; run_phase reset || exit 1 ;;
  reseed) confirm_reset || exit 1; run_phase reset || exit 1; run_phase seed || exit 1 ;;
esac
if [ "$ACTION" != reset ]; then
  cat <<'TXT'

Log in with any user of seed/CATALOG.md, password: password (alice, mod = moderator, admin, bob, carol, ...).
A running service may still hold cached data from before: restart it if something looks stale (make reset flushes Redis).
TXT
fi
