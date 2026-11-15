#!/bin/sh
# Seeds or resets the two Redis instances.
#   MODE                     seed (default) | reset
#   REDIS_SHARED_HOST        the cache instance (zset:trending)
#   REDIS_NOTIFICATION_HOST  the instance that is notification-service's database (inboxes, notifications, preferences)
# seed  runs seed/out/*.redis (plain commands); HSET/ZADD/EXPIRE are idempotent, so running it twice changes nothing.
# reset FLUSHALL on both: caches, counters, rate limits and idempotency keys go with the data, which is what you want
#       after the databases were emptied (a stale cache:user:{id} would serve a user that no longer exists).
set -eu
MODE="${MODE:-seed}"
run() {  # run <host> <file>
  tr -d '\r' < "$2" > /tmp/commands.redis
  out="$(redis-cli -h "$1" < /tmp/commands.redis)"
  # every answer of these commands is an integer or OK; anything else is an error message
  bad="$(printf '%s\n' "$out" | grep -vxE '[0-9]+|OK' || true)"
  [ -z "$bad" ] || { echo "ERROR: $1 rejected commands of $2:" >&2; printf '%s\n' "$bad" | head -5 >&2; exit 1; }
  echo "redis $1: $(grep -c . /tmp/commands.redis) commands applied, $(redis-cli -h "$1" dbsize | tr -d '\r') keys"
}
case "$MODE" in
  seed)
    run "$REDIS_NOTIFICATION_HOST" "${SEED_NOTIFICATION:-/seed/out/notification.redis}"
    run "$REDIS_SHARED_HOST" "${SEED_SHARED:-/seed/out/shared.redis}" ;;
  reset)
    for h in "$REDIS_NOTIFICATION_HOST" "$REDIS_SHARED_HOST"; do
      redis-cli -h "$h" FLUSHALL | grep -qx OK && echo "redis $h: flushed"
    done ;;
  *) echo "unknown MODE $MODE" >&2; exit 2 ;;
esac
