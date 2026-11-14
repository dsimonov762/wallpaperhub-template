#!/usr/bin/env bash
# Runs a contract tool from tools/contract-tools (spectral, buf, openapi-typescript, tsc) with the repo as the working directory.
#   scripts/ct.sh spectral lint contracts/openapi/account.yaml
# CONTRACT_TOOLS=docker (default)  image wallpaperhub/contract-tools:local, built on first use; nothing to install
# CONTRACT_TOOLS=native            node_modules under tools/contract-tools (npm ci on first use); needs Node 20+
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; DIR="$ROOT/tools/contract-tools"; IMAGE="wallpaperhub/contract-tools:local"
if [ "${CONTRACT_TOOLS:-docker}" = native ]; then
  [ -x "$DIR/node_modules/.bin/spectral" ] || { echo "installing contract tools (npm ci)..." >&2; (cd "$DIR" && npm ci --no-audit --no-fund >&2); }
  cd "$ROOT"; PATH="$DIR/node_modules/.bin:$PATH" exec "$@"
fi
command -v docker >/dev/null 2>&1 || { echo "need docker (or CONTRACT_TOOLS=native with Node 20+)" >&2; exit 2; }
if [ -n "${CONTRACT_TOOLS_REBUILD:-}" ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "building $IMAGE (once)..." >&2; docker build -q -t "$IMAGE" "$DIR" >&2
fi
exec docker run --rm -v "$ROOT:/repo" -w /repo -u "$(id -u):$(id -g)" -e HOME=/tmp "$IMAGE" "$@"
