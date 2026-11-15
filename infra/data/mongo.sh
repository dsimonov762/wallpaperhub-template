#!/bin/sh
# Seeds or resets the catalog database of MongoDB.
#   MODE        seed (default) | reset
#   MONGO_URI   e.g. mongodb://root:root@mongo:27017/?authSource=admin
#   SEED_JS     seed/out/catalog.js
# seed  upserts with $setOnInsert (nothing that exists is changed) and keeps the $jsonSchema validators active.
# reset deletes every document of every collection of the catalog database; collections, validators and indexes stay.
set -eu
MODE="${MODE:-seed}"
: "${MONGO_URI:?MONGO_URI is required}"
mongosh "$MONGO_URI" --quiet --eval '
  const names = db.getSiblingDB("catalog").getCollectionNames();
  if (!names.includes("wallpapers")) { print("MISSING"); }' > /tmp/probe.txt
if grep -q MISSING /tmp/probe.txt; then
  echo "ERROR: the catalog collections do not exist. Create them first: make schemas (or start catalog-service once)." >&2
  echo "       (A seed into a missing collection would create it WITHOUT validator and unique indexes.)" >&2
  exit 1
fi
case "$MODE" in
  seed)
    tr -d '\r' < "${SEED_JS:-/seed/out/catalog.js}" > /tmp/catalog.js
    mongosh "$MONGO_URI" --quiet --file /tmp/catalog.js ;;
  reset)
    mongosh "$MONGO_URI" --quiet --eval '
      const c = db.getSiblingDB("catalog");
      for (const n of c.getCollectionNames()) {
        if (n.startsWith("system.")) continue;
        const r = c.getCollection(n).deleteMany({});
        print("catalog." + n + ": " + r.deletedCount + " documents deleted");
      }' ;;
  *) echo "unknown MODE $MODE" >&2; exit 2 ;;
esac
