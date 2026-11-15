#!/bin/bash
# Seeds or resets the users of the Keycloak realm. Runs inside the keycloak image: kcadm.sh, bash and tr, nothing else
# (no curl, sed, grep, cut).
#   MODE                       seed (default) | reset
#   KC_URL KEYCLOAK_ADMIN KEYCLOAK_ADMIN_PASSWORD REALM
#   KEEP_USER_IDS              ids that reset keeps (the users of the realm export), space separated
#   SEED_USERS                 seed/out/keycloak-users.json
# seed  Admin API partial import with ifResourceExists=SKIP: the users get the UUIDs of the seed data (so token `sub` ==
#       account users.id == catalog author.id), existing ones are skipped.
# reset deletes every user except the kept ones. Service-account users are not listed by the users API and stay.
set -eu
MODE="${MODE:-seed}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
CFG=(--config /tmp/kcadm.config)
for ((i = 1; i <= 60; i++)); do
  "$KCADM" config credentials --server "$KC_URL" --realm master --user "$KEYCLOAK_ADMIN" --password "$KEYCLOAK_ADMIN_PASSWORD" "${CFG[@]}" >/dev/null 2>&1 && break
  [ "$i" = 60 ] && { echo "ERROR: cannot log in to $KC_URL as $KEYCLOAK_ADMIN" >&2; exit 1; }
  sleep 2
done
case "$MODE" in
  seed)
    tr -d '\r' < "${SEED_USERS:-/seed/out/keycloak-users.json}" > /tmp/users.json
    out="$("$KCADM" create partialImport -r "$REALM" -f /tmp/users.json -o "${CFG[@]}")"
    # the answer lists added / skipped / overwritten; print it compactly
    out="${out//[$' \t\r\n']/}"      # the image has no sed/grep/cut: bash only
    echo "keycloak: ${out%%,\"results\"*}}" ;;
  reset)
    n=0
    while IFS= read -r id; do
      id="${id%$'\r'}"
      [ -n "$id" ] || continue
      case " ${KEEP_USER_IDS} " in *" $id "*) continue ;; esac
      "$KCADM" delete "users/$id" -r "$REALM" "${CFG[@]}"
      n=$((n + 1))
    done < <("$KCADM" get users -r "$REALM" --fields id --format csv --noquotes -q max=10000 "${CFG[@]}")
    echo "keycloak: $n users deleted, the users of the realm export kept" ;;
  *) echo "unknown MODE $MODE" >&2; exit 2 ;;
esac
