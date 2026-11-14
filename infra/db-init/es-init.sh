#!/bin/sh
# Creates the Elasticsearch index wallpapers-v1 and the alias wallpapers (contracts/db-schema/elasticsearch).
set -eu
export BODY="${BODY:-/db-schema/elasticsearch/wallpapers-v1.json}"
tr -d '\r' < /db-schema/elasticsearch/create-index.sh > /tmp/create-index.sh
sh /tmp/create-index.sh
