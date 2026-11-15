#!/bin/sh
# Seeds or resets the Elasticsearch index behind the alias `wallpapers`.
#   MODE      seed (default) | reset
#   ES_URL    e.g. http://elasticsearch:9200
#   BULK      seed/out/catalog.es.ndjson
# seed  bulk-creates one document per PUBLISHED wallpaper; documents that already exist (409) are left alone.
# reset deletes every document; the index, mapping and alias stay.
set -eu
MODE="${MODE:-seed}"
ES_URL="${ES_URL:-http://elasticsearch:9200}"
CURL="curl -sS --fail-with-body ${ES_CURL_ARGS:-}"
# shellcheck disable=SC2086
$CURL -o /dev/null -I "$ES_URL/wallpapers" 2>/dev/null || {
  echo "ERROR: the alias wallpapers does not exist. Create the index first: make schemas (or start catalog-service once)." >&2; exit 1; }
case "$MODE" in
  seed)
    tr -d '\r' < "${BULK:-/seed/out/catalog.es.ndjson}" > /tmp/bulk.ndjson
    # shellcheck disable=SC2086
    out="$($CURL -X POST "$ES_URL/_bulk?refresh=true" -H 'Content-Type: application/x-ndjson' --data-binary @/tmp/bulk.ndjson)"
    # a failed item has "error":{"type":"...exception"}; version_conflict_engine_exception just means "already there"
    bad="$(printf '%s' "$out" | grep -oE '"type" *: *"[a-z_]*exception"' | grep -vc version_conflict_engine_exception || true)"
    if [ "$bad" != 0 ]; then echo "ERROR: $bad bulk item(s) failed:" >&2; printf '%s\n' "$out" | head -c 1500 >&2; exit 1; fi
    created="$(printf '%s' "$out" | grep -oE '"result" *: *"created"' | grep -c . || true)"
    echo "search: $created documents indexed, $(( $(grep -c '^{"create"' /tmp/bulk.ndjson) - created )) already there" ;;
  reset)
    # shellcheck disable=SC2086
    $CURL -X POST "$ES_URL/wallpapers/_delete_by_query?refresh=true&conflicts=proceed&wait_for_completion=true" \
      -H 'Content-Type: application/json' -d '{"query":{"match_all":{}}}' | tr ',' '\n' | grep '"deleted"' | tr -d ' ' | sed 's/^/search: /'
    ;;
  *) echo "unknown MODE $MODE" >&2; exit 2 ;;
esac
