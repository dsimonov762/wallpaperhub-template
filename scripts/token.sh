#!/usr/bin/env bash
# Access tokens from the local Keycloak, for curl, Bruno, Postman, the IDE, or a service you run in host mode.
#
#   scripts/token.sh [options] [user]            a realm user (default: alice); password is `password` for every seeded user
#   scripts/token.sh --client catalog-svc        a service account (client credentials) - the token other services present
#
#   --decode        print the header and claims of the token (sub, roles, audience, expiry) instead of the token
#   --header        print `Authorization: Bearer <token>`      curl -H "$(scripts/token.sh --header bob)" localhost:8080/api/v1/users/me
#   --json          print the whole answer of Keycloak (access_token, refresh_token, expires_in ...)
#   --no-cache      always ask Keycloak (default: reuse a token of this user while it has more than 30 seconds left)
#   --list          the users and clients you can ask for
# Environment: KEYCLOAK_URL (default http://localhost:8180, or PORT_KEYCLOAK of infra/.env)  REALM (wallpaperhub)  CLIENT_ID (e2e-tests)
#              PASSWORD (password)  <NAME>_SVC_SECRET (as infra/.env; default <name>-svc-dev-secret)
# Needs curl; python3 is used for --decode and the expiry when it exists. Cache: .token-cache/ (git-ignored, mode 600).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/infra/.env" ] && { set -a; . "$ROOT/infra/.env" 2>/dev/null; set +a; }
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:${PORT_KEYCLOAK:-8180}}"; REALM="${REALM:-wallpaperhub}"; CLIENT_ID="${CLIENT_ID:-e2e-tests}"
PASSWORD="${PASSWORD:-password}"
MODE=token; CACHE=1; CLIENT=""; WHO=""

usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; }
list() {
  echo "users (password: $PASSWORD)    alice (user), mod (moderator), admin (administrator)"
  if [ -f "$ROOT/seed/out/manifest.json" ] && command -v python3 >/dev/null 2>&1; then
    echo "                              after make seed: $(python3 -c "import json; print(', '.join(u['username'] for u in json.load(open('$ROOT/seed/out/manifest.json'))['users'] if u['in_keycloak'] and u['username'] not in ('alice','mod','admin')))")"
  fi
  echo "service clients (--client)    account-svc media-svc catalog-svc notification-svc gateway"
}
while [ $# -gt 0 ]; do
  case "$1" in
    --decode) MODE=decode ;; --header) MODE=header ;; --json) MODE=json ;; --no-cache) CACHE=0 ;;
    --client) CLIENT="${2:-}"; [ -n "$CLIENT" ] || { echo "--client needs a client id" >&2; exit 2; }; shift ;;
    --list) list; exit 0 ;; -h|--help) usage; exit 0 ;;
    -*) echo "unknown option $1" >&2; usage >&2; exit 2 ;;
    *) WHO="$1" ;;
  esac; shift
done
[ -n "$CLIENT" ] || WHO="${WHO:-alice}"
KEY="${CLIENT:-user-$WHO}"
TOK_URL="$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token"
# the cache key covers everything that changes the answer, so another Keycloak, realm, client or password never gets a stale token
CACHE_DIR="$ROOT/.token-cache"; CACHE_FILE="$CACHE_DIR/$KEY-$(printf '%s' "$KEYCLOAK_URL|$REALM|$CLIENT_ID|$PASSWORD" | cksum | cut -d' ' -f1)"

field() { sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p"; }          # string field of a flat JSON answer
numfield() { sed -n "s/.*\"$1\":\([0-9]*\).*/\1/p"; }

fetch() {  # fetch -> full JSON answer of Keycloak on stdout
  if [ -n "$CLIENT" ]; then
    local name="${CLIENT%-svc}" var secret
    var="$(echo "$name" | tr 'a-z-' 'A-Z_')_SVC_SECRET"; secret="${!var:-$name-svc-dev-secret}"
    curl -sS --max-time 15 -X POST "$TOK_URL" -d grant_type=client_credentials -d "client_id=$CLIENT" --data-urlencode "client_secret=$secret"
  else
    curl -sS --max-time 15 -X POST "$TOK_URL" -d grant_type=password -d "client_id=$CLIENT_ID" --data-urlencode "username=$WHO" --data-urlencode "password=$PASSWORD"
  fi
}

answer=""; token=""; now="$(date +%s)"
if [ "$CACHE" = 1 ] && [ "$MODE" != json ] && [ -f "$CACHE_FILE" ]; then
  { read -r exp; read -r cached; } < "$CACHE_FILE"
  [ -n "${exp:-}" ] && [ "$exp" -gt $((now + 30)) ] 2>/dev/null && token="$cached"
fi
if [ -z "$token" ]; then
  answer="$(fetch)" || { echo "cannot reach Keycloak at $KEYCLOAK_URL (make up, then make ps)" >&2; exit 1; }
  token="$(printf '%s' "$answer" | field access_token)"
  if [ -z "$token" ]; then
    err="$(printf '%s' "$answer" | field error_description)"; [ -n "$err" ] || err="$(printf '%s' "$answer" | head -c 300)"
    echo "no token for ${CLIENT:-user $WHO}: $err" >&2
    [ -z "$CLIENT" ] && echo "(is Keycloak up with the realm imported, and does the user exist? see: $0 --list)" >&2
    exit 1
  fi
  ttl="$(printf '%s' "$answer" | numfield expires_in)"
  if [ "$CACHE" = 1 ]; then
    mkdir -p "$CACHE_DIR"; chmod 700 "$CACHE_DIR" 2>/dev/null
    umask 077; printf '%s\n%s\n' "$((now + ${ttl:-300}))" "$token" > "$CACHE_FILE"
  fi
fi

b64json() {  # decode one JWT segment
  python3 - "$1" <<'PY'
import base64, json, sys
seg = sys.argv[1]
print(json.dumps(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))), indent=2, ensure_ascii=False))
PY
}
case "$MODE" in
  token) printf '%s\n' "$token" ;;
  header) printf 'Authorization: Bearer %s\n' "$token" ;;
  json) [ -n "$answer" ] || answer="$(fetch)"; printf '%s\n' "$answer" ;;
  decode)
    command -v python3 >/dev/null 2>&1 || { echo "--decode needs python3 (or paste the token into https://jwt.io)" >&2; exit 1; }
    IFS=. read -r h p _ <<< "$token"
    echo "header:";  b64json "$h"
    echo "claims:";  b64json "$p"
    python3 - "$p" <<'PY'
import base64, json, sys, time
seg = sys.argv[1]
c = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
left = int(c.get("exp", 0) - time.time())
print(f"expires in {left} s ({time.strftime('%H:%M:%S', time.localtime(c.get('exp', 0)))} local time)" if left > 0 else "EXPIRED")
PY
    ;;
esac
