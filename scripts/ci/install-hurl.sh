#!/usr/bin/env bash
# Installs hurl and hurlfmt (pinned) into a folder and adds it to the PATH of the following GitHub Actions steps.
# If the download fails nothing is installed and e2e/run.sh uses the hurl container instead.   scripts/ci/install-hurl.sh [DEST]
set -u
V="${HURL_VERSION:-8.1.0}"; DEST="${1:-$HOME/.local/bin}"
URL="${HURL_URL:-https://github.com/Orange-OpenSource/hurl/releases/download/$V/hurl-$V-x86_64-unknown-linux-gnu.tar.gz}"
tmp="$(mktemp -d)"; mkdir -p "$DEST"
if curl -fsSL "$URL" -o "$tmp/hurl.tgz" && tar -xzf "$tmp/hurl.tgz" -C "$tmp" && bin="$(ls -d "$tmp"/hurl-*/bin 2>/dev/null | head -1)" && [ -x "$bin/hurl" ]; then
  install -m 755 "$bin/hurl" "$bin/hurlfmt" "$DEST/"
  [ -n "${GITHUB_PATH:-}" ] && echo "$DEST" >> "$GITHUB_PATH"
  echo "installed: $("$DEST/hurl" --version | head -1)"
else
  echo "could not install hurl from $URL: e2e/run.sh will use the container ghcr.io/orange-opensource/hurl:$V"
fi
rm -rf "$tmp"
