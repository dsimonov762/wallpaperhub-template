#!/usr/bin/env bash
# Installs kubeconform (pinned) into a folder and adds it to the PATH of the following GitHub Actions steps.   scripts/ci/install-kubeconform.sh [DEST]
set -eu
# renovate: datasource=github-releases depName=yannh/kubeconform extractVersion=^v(?<version>.+)$
default_version=0.7.0
V="${KUBECONFORM_VERSION:-$default_version}"; DEST="${1:-$HOME/.local/bin}"
URL="${KUBECONFORM_URL:-https://github.com/yannh/kubeconform/releases/download/v$V/kubeconform-linux-amd64.tar.gz}"
tmp="$(mktemp -d)"; mkdir -p "$DEST"; trap 'rm -rf "$tmp"' EXIT
curl -fsSL "$URL" -o "$tmp/kc.tgz" && tar -xzf "$tmp/kc.tgz" -C "$tmp" kubeconform
install -m 755 "$tmp/kubeconform" "$DEST/"
[ -n "${GITHUB_PATH:-}" ] && echo "$DEST" >> "$GITHUB_PATH"
echo "installed: kubeconform $("$DEST/kubeconform" -v)"
