#!/usr/bin/env bash
# Applies the canonical Postgres schema to two empty databases, loads seed/out/{account,media}.sql twice (the second run must
# change nothing) and counts the rows. Connection: libpq variables (PGHOST ...) of a server you can create databases on;
# without PGHOST a throw-away postgres container is started (make seed-test-sql).
set -euo pipefail
cd "$(dirname "$0")/../.."
cleanup() { [ -z "${CONTAINER:-}" ] || docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
if [ -z "${PGHOST:-}" ]; then
  trap cleanup EXIT
  CONTAINER="$(docker run -d --rm -e POSTGRES_PASSWORD=seedtest -p 127.0.0.1::5432 postgres:18.6-trixie)"
  PGPORT="$(docker port "$CONTAINER" 5432/tcp | head -1 | sed 's/.*://')"
  export PGHOST=127.0.0.1 PGPORT PGUSER=postgres PGPASSWORD=seedtest
  for _ in $(seq 1 60); do pg_isready -q 2>/dev/null || docker exec "$CONTAINER" pg_isready -q -h 127.0.0.1 && break; sleep 1; done
  sleep 2
fi
P() { psql -X -q -v ON_ERROR_STOP=1 "$@"; }
for db in account media; do
  P -d postgres -c "DROP DATABASE IF EXISTS seedtest_$db" -c "CREATE DATABASE seedtest_$db"
  for f in $(ls contracts/db-schema/postgres/$db/V*__*.sql | sort -V); do P -d "seedtest_$db" -f "$f"; done
  P -d "seedtest_$db" --single-transaction -f "seed/out/$db.sql"
  P -d "seedtest_$db" --single-transaction -f "seed/out/$db.sql"
done
# idempotency in numbers: the second load must not have added a row
a="$(P -d seedtest_account -At -c "SELECT (SELECT count(*) FROM users) || '/' || (SELECT count(*) FROM audit_log)")"
m="$(P -d seedtest_media -At -c "SELECT (SELECT count(*) FROM media_asset) || '/' || (SELECT count(*) FROM media_variant)")"
echo "after two loads: users/audit_log=$a media_asset/media_variant=$m"
read -r n_users n_assets < <(python3 -c "import json; m = json.load(open('seed/out/manifest.json')); print(len(m['users']), len(m['assets']))")
[ "${a%%/*}" = "$n_users" ] || { echo "FAIL: $n_users users in the seed, ${a%%/*} in the database" >&2; exit 1; }
[ "${m%%/*}" = "$n_assets" ] || { echo "FAIL: $n_assets assets in the seed, ${m%%/*} in the database" >&2; exit 1; }
P -d postgres -c "DROP DATABASE seedtest_account" -c "DROP DATABASE seedtest_media"
echo "seed SQL OK"
