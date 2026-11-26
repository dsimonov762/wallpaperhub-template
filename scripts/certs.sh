#!/usr/bin/env bash
# Local HTTPS certificates with mkcert (https://github.com/FiloSottile/mkcert): a private CA that your browser trusts, and a certificate from it
# for the gateway (and Keycloak).    make certs        details: docs/HTTPS.md
#
#   scripts/certs.sh             create infra/certs/wallpaperhub.pem + -key.pem (+ rootCA.pem, the public CA certificate for tools) when missing or about to expire
#   scripts/certs.sh --install   also run  mkcert -install  (adds the CA to the trust stores: browsers, Java, the OS)
#   scripts/certs.sh --check     only report: certificate present, current, trusted?  (exit 1 when not)
#   scripts/certs.sh --force     create again
# CERT_NAMES="localhost 127.0.0.1 ..."  replaces the default list of names the certificate is valid for.
#
# Works in Linux/macOS, WSL (with the CA of Windows, so that the browsers of Windows trust it) and Git Bash.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/infra/certs"
NAMES="${CERT_NAMES:-localhost 127.0.0.1 ::1 host.docker.internal gateway keycloak wallpaperhub.localhost *.wallpaperhub.localhost}"
MODE="make"
for a in "$@"; do case "$a" in --install) MODE="install";; --check) MODE="check";; --force) FORCE=1;; -h|--help) sed -n 2,12p "$0"; exit 0;; *) echo "unknown option $a" >&2; exit 2;; esac; done
FORCE="${FORCE:-0}"

say() { printf '%s\n' "$*"; }
die() { printf 'certs: %s\n' "$*" >&2; exit 1; }

WSL=0; grep -qi microsoft /proc/version 2>/dev/null && WSL=1

# ---- which mkcert --------------------------------------------------------------------------------------------------------------------
MKCERT=""; WINEXE=""
command -v mkcert >/dev/null 2>&1 && MKCERT="mkcert"
if command -v mkcert.exe >/dev/null 2>&1; then WINEXE="mkcert.exe"; [ -z "$MKCERT" ] && MKCERT="mkcert.exe"; fi
if [ -z "$MKCERT" ]; then
  [ "$MODE" = check ] && die "mkcert not found"
  die "mkcert not found. Install it:  Windows: winget install FiloSottile.mkcert   |   Ubuntu/WSL: sudo apt install mkcert   |   macOS: brew install mkcert
(in WSL install it on BOTH sides: the Windows one adds the CA to the trust store of your Windows browsers, the Ubuntu one writes the files here)"
fi

# WSL: the browser lives in Windows, so the CA has to be the one of Windows (mkcert.exe -install put it in the Windows trust store);
# a Linux mkcert is then told to use that very CA directory instead of making a second one nobody trusts.
if [ "$WSL" = 1 ] && [ -n "$WINEXE" ] && [ "$MKCERT" = "mkcert" ]; then
  WINCA="$(mkcert.exe -CAROOT 2>/dev/null | tr -d '\r')"
  if [ -n "$WINCA" ] && command -v wslpath >/dev/null 2>&1; then CAROOT="$(wslpath -u "$WINCA")"; export CAROOT; fi
fi
CAROOT_DIR="$($MKCERT -CAROOT 2>/dev/null | tr -d '\r')"
[ "$MKCERT" = "mkcert.exe" ] && [ "$WSL" = 1 ] && command -v wslpath >/dev/null 2>&1 && CAROOT_DIR="$(wslpath -u "$CAROOT_DIR")"

if [ "$MODE" = install ]; then
  say "mkcert -install (adds the local CA to the trust stores; a Windows dialog may ask you to confirm)"
  if [ -n "$WINEXE" ] && [ "$WSL" = 1 ]; then mkcert.exe -install; else $MKCERT -install; fi
  CAROOT_DIR="$($MKCERT -CAROOT 2>/dev/null | tr -d '\r')"
  [ "$WSL" = 1 ] && [ "$MKCERT" = "mkcert.exe" ] && CAROOT_DIR="$(wslpath -u "$CAROOT_DIR")"
fi

[ -f "$CAROOT_DIR/rootCA.pem" ] || die "no local CA yet ($CAROOT_DIR/rootCA.pem). Run once:  scripts/certs.sh --install   (or: mkcert -install; in WSL run mkcert.exe -install in PowerShell)"

# ---- is what we have current? -------------------------------------------------------------------------------------------------------
current=0
if [ -f "$OUT/wallpaperhub.pem" ] && [ -f "$OUT/wallpaperhub-key.pem" ] && [ -f "$OUT/names.txt" ] && [ "$(cat "$OUT/names.txt")" = "$NAMES" ] \
   && cmp -s "$CAROOT_DIR/rootCA.pem" "$OUT/rootCA.pem" 2>/dev/null; then
  if command -v openssl >/dev/null 2>&1; then openssl x509 -in "$OUT/wallpaperhub.pem" -noout -checkend $((30*86400)) >/dev/null 2>&1 && current=1
  else current=1; fi
fi
if [ "$MODE" = check ]; then
  [ "$current" = 1 ] && say "certificate current: $OUT/wallpaperhub.pem" && exit 0
  say "no current certificate in infra/certs (names changed, CA changed, expiring, or never made): make certs"; exit 1
fi
if [ "$current" = 1 ] && [ "$FORCE" != 1 ]; then
  say "certificate is current ($OUT/wallpaperhub.pem). --force makes a new one."
else
  mkdir -p "$OUT"
  # run inside infra/certs with relative names: works the same for mkcert.exe (Git Bash, WSL) as for a native mkcert
  # shellcheck disable=SC2086
  (cd "$OUT" && $MKCERT -cert-file wallpaperhub.pem -key-file wallpaperhub-key.pem $NAMES)
  [ -f "$OUT/wallpaperhub.pem" ] || die "mkcert did not write the certificate"
  # the gateway and Keycloak containers run as other users than you; this is a key of a local development CA
  chmod 644 "$OUT/wallpaperhub-key.pem" "$OUT/wallpaperhub.pem" 2>/dev/null || true
  cp "$CAROOT_DIR/rootCA.pem" "$OUT/rootCA.pem"   # the PUBLIC certificate of the CA, for curl --cacert, NODE_EXTRA_CA_CERTS, ... never the rootCA-key.pem
  printf '%s' "$NAMES" > "$OUT/names.txt"
  say "wrote infra/certs/wallpaperhub.pem, wallpaperhub-key.pem and rootCA.pem"
fi
command -v openssl >/dev/null 2>&1 && openssl x509 -in "$OUT/wallpaperhub.pem" -noout -enddate | sed 's/^notAfter=/valid until /'
say "names: $NAMES"
say "next:  make up-https   (the gateway on https://localhost:\${PORT_GATEWAY_TLS:-8443})   docs/HTTPS.md"
