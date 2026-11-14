#!/bin/sh
# Registers every contracts/avro/<topic>.avsc as subject "<topic>-value" (TopicNameStrategy).
# Re-registering an unchanged schema is a no-op. An incompatible change makes the registry
# answer 409 and this job fail, which is the schema-evolution exercise from README 5.6.
set -eu

REGISTRY="${SCHEMA_REGISTRY_URL:-http://schema-registry:8081}"
DIR="${AVRO_DIR:-/contracts/avro}"
count=0

for file in "$DIR"/*.avsc; do
  [ -e "$file" ] || continue
  topic="$(basename "$file" .avsc)"
  subject="${topic}-value"

  # Wrap the schema file into {"schema": "<escaped json string>"} using only busybox tools
  schema="$(tr -d '\r\n' < "$file" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  payload="{\"schema\":\"${schema}\"}"

  printf 'registering %s -> ' "$subject"
  wget -qO- \
    --header='Content-Type: application/vnd.schemaregistry.v1+json' \
    --post-data="$payload" \
    "${REGISTRY}/subjects/${subject}/versions" \
    || { echo; echo "FAILED to register ${subject} (incompatible change, or invalid schema?)"; exit 1; }
  echo
  count=$((count + 1))
done

echo "registered ${count} schema(s)"
