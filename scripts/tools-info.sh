#!/usr/bin/env bash
# Prints where the web UIs of `make up-tools` are, with the connection details already in the links.   scripts/tools-info.sh [kafka-ui adminer mongo-ui]
cd "$(dirname "$0")/.."
[ -f infra/.env ] && { set -a; . infra/.env 2>/dev/null; set +a; }
want=" ${*:-kafka-ui adminer mongo-ui} "
host="localhost"
echo
echo "Web UIs (loopback only, no login, full rights${TOOLS_READONLY:+; TOOLS_READONLY=$TOOLS_READONLY}):"
[[ "$want" == *" kafka-ui "* ]] && echo "  Kafka UI   http://$host:${PORT_KAFKA_UI:-8082}    cluster wallpaperhub: topics, Avro messages, consumer groups, schemas"
if [[ "$want" == *" adminer "* ]]; then
  a="http://$host:${PORT_ADMINER:-8083}"
  echo "  Adminer    $a    System PostgreSQL; password = PG_<NAME>_PASSWORD of infra/.env, default = the user name"
  echo "               account   $a/?pgsql=postgres-account&username=account&db=account"
  echo "               media     $a/?pgsql=postgres-media&username=media&db=media"
  echo "               keycloak  $a/?pgsql=postgres-keycloak&username=keycloak&db=keycloak"
fi
[[ "$want" == *" mongo-ui "* ]] && echo "  Mongoku    http://$host:${PORT_MONGO_UI:-8084}    MongoDB, connection preconfigured; database: catalog"
echo
echo "Topics, tables, collections and indexes exist after  make up ;  sample data:  make seed"
