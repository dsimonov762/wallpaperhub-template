#!/bin/sh
# Creates the catalog collections (validators) and indexes from contracts/db-schema/mongo/init.js. Idempotent.
#   MONGO_URI   e.g. mongodb://root:root@mongo:27017/?authSource=admin
#   INIT_JS     path of init.js (default /db-schema/mongo/init.js)
set -eu
: "${MONGO_URI:?MONGO_URI is required}"
INIT_JS="${INIT_JS:-/db-schema/mongo/init.js}"
tr -d '\r' < "$INIT_JS" > /tmp/init.js
mongosh "$MONGO_URI" --quiet --file /tmp/init.js
echo "catalog database initialised"
