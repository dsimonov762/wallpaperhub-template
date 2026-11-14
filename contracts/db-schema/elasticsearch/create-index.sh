#!/bin/sh
# Creates the versioned index wallpapers-v1 and the alias `wallpapers` (README 6.4). Idempotent.
#   ES_URL=http://localhost:9200 ./create-index.sh
# Needs curl (the elasticsearch image has it). For a secured cluster add:  ES_CURL_ARGS="-u elastic:password"
set -eu

ES_URL="${ES_URL:-http://localhost:9200}"
INDEX="${INDEX:-wallpapers-v1}"
BODY="${BODY:-$(dirname "$0")/wallpapers-v1.json}"
# shellcheck disable=SC2086
CURL="curl -sS --fail-with-body ${ES_CURL_ARGS:-}"

if $CURL -o /dev/null -I "$ES_URL/$INDEX" 2>/dev/null; then
  echo "index $INDEX already exists, nothing to do"
  exit 0
fi

$CURL -X PUT "$ES_URL/$INDEX" -H 'Content-Type: application/json' --data-binary "@$BODY"
echo
echo "created $INDEX with alias wallpapers"

# Reindexing to a new mapping (README 6.4): create wallpapers-v2 the same way (without the alias), POST _reindex from
# wallpapers-v1, then swap atomically:
#   POST /_aliases {"actions":[{"remove":{"index":"wallpapers-v1","alias":"wallpapers"}},{"add":{"index":"wallpapers-v2","alias":"wallpapers"}}]}
