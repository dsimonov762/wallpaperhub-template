#!/bin/sh
# Applies the versioned SQL files of contracts/db-schema/postgres/<service>/ to a Postgres database, once each.
#
#   PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE   connection (standard libpq variables)
#   MIGRATIONS_DIR                                folder with V<n>__<name>.sql files
#
# Bookkeeping lives in the table contract_schema_migrations. A file that was applied and has changed since is an
# error (never edit an applied migration: add V2__...sql). Line endings do not matter: CRs are removed before the
# checksum, so a Windows checkout and a Linux checkout agree.
set -eu

: "${MIGRATIONS_DIR:?MIGRATIONS_DIR is required}"
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}"
export PGOPTIONS="${PGOPTIONS:--c client_min_messages=warning}"

psql_() { psql -X -q -v ON_ERROR_STOP=1 "$@"; }

psql_ -c "CREATE TABLE IF NOT EXISTS contract_schema_migrations (
            version    text PRIMARY KEY,
            filename   text NOT NULL,
            checksum   text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now())"

applied=0
skipped=0
# Version order, not alphabetical: V10 comes after V2.
for file in $(ls "$MIGRATIONS_DIR"/V*__*.sql 2>/dev/null | sort -V); do
  name="$(basename "$file")"
  version="${name%%__*}"
  checksum="$(tr -d '\r' < "$file" | sha256sum | cut -d' ' -f1)"
  known="$(psql_ -At -c "SELECT checksum FROM contract_schema_migrations WHERE version = '$version'")"
  if [ -n "$known" ]; then
    if [ "$known" != "$checksum" ]; then
      echo "ERROR: $name was applied before but its content changed (applied $known, now $checksum)." >&2
      echo "       Do not edit applied migrations; add a new version instead." >&2
      exit 1
    fi
    skipped=$((skipped + 1))
    continue
  fi
  echo "applying $name"
  # CRs removed on the fly; migration and bookkeeping row commit together or not at all
  tr -d '\r' < "$file" > /tmp/migration.sql
  psql_ --single-transaction -f /tmp/migration.sql \
        -c "INSERT INTO contract_schema_migrations (version, filename, checksum) VALUES ('$version', '$name', '$checksum')"
  applied=$((applied + 1))
done

echo "$PGDATABASE: $applied migration(s) applied, $skipped already up to date"
