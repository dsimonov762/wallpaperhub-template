#!/bin/sh
# Seeds or resets one Postgres database of the stack.
#   MODE          seed (default) | reset
#   PG*           libpq connection (PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE)
#   SQL_FILE      seed file (seed/out/account.sql or media.sql)
#   PROBE_TABLE   a table of the schema, to fail with a clear message when the schema is not there yet
# seed  inserts what is missing (ON CONFLICT DO NOTHING) in one transaction; running it twice changes nothing.
# reset empties every table of the public schema except the bookkeeping tables of migration tools (the schema stays).
set -eu
MODE="${MODE:-seed}"
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}" PGOPTIONS="${PGOPTIONS:--c client_min_messages=warning}"
psql_() { psql -X -q -v ON_ERROR_STOP=1 "$@"; }

[ -n "$(psql_ -At -c "SELECT to_regclass('public.${PROBE_TABLE}')")" ] || {
  echo "ERROR: table ${PROBE_TABLE} does not exist in database ${PGDATABASE}." >&2
  echo "       Create the schema first: make schemas (or start the service once, so its own migrations run)." >&2
  exit 1; }

case "$MODE" in
  seed)
    tr -d '\r' < "$SQL_FILE" > /tmp/seed.sql
    psql_ --single-transaction -f /tmp/seed.sql
    echo "${PGDATABASE}: seeded, ${PROBE_TABLE} now has $(psql_ -At -c "SELECT count(*) FROM ${PROBE_TABLE}") rows" ;;
  reset)
    psql_ <<'SQL'
DO $$
DECLARE t text;
BEGIN
  SELECT string_agg(format('%I.%I', schemaname, tablename), ', ') INTO t FROM pg_tables
   WHERE schemaname = 'public'
     AND tablename !~ '^(contract_schema_migrations|flyway_schema_history|databasechangelog|databasechangeloglock|alembic_version|schema_migrations|goose_db_version|__EFMigrationsHistory|_prisma_migrations|django_migrations|knex_migrations|knex_migrations_lock|gorp_migrations|atlas_schema_revisions|_sqlx_migrations|__diesel_schema_migrations|refinery_schema_history|seaql_migrations|schema_version|migrations)$';
  IF t IS NOT NULL THEN EXECUTE 'TRUNCATE TABLE ' || t || ' RESTART IDENTITY CASCADE'; END IF;
END $$;
SQL
    echo "${PGDATABASE}: all tables emptied (schema and migration bookkeeping kept)" ;;
  *) echo "unknown MODE $MODE" >&2; exit 2 ;;
esac
