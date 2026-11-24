#!/usr/bin/env bash
# make docs-selftest: does scripts/docs-check.py catch what it says it catches? Works on a fixture in a temporary folder; nothing in the repository is touched. Needs only python3.
set -euo pipefail
cd "$(dirname "$0")/../.." || exit 1
export PYTHONDONTWRITEBYTECODE=1
CHECK="$PWD/scripts/docs-check.py"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
fail=0

fixture() {
  rm -rf "$W/t"
  mkdir -p "$W/t/docs"
  printf '@AGENTS.md\n' > "$W/t/CLAUDE.md"
  printf '# Agents\n\n## Rules\n\nSee [the guide](docs/guide.md#why-it-works-and-how) and `make lint`.\n' > "$W/t/AGENTS.md"
  printf '# Guide\n\n## Why it works (and how)\n\ntext. Back to [rules](../AGENTS.md#rules). Run `make lint` or `make k8s-up-...`.\n\n```\nmake lint   # make the thing\n[x](nothing.md)\n```\n' > "$W/t/docs/guide.md"
  printf '# Map\n\n- [guide](guide.md)\n' > "$W/t/docs/README.md"
  printf 'lint: ## x\n\t@true\n\n.PHONY: lint\n' > "$W/t/Makefile"
}
run() { DOCS_ROOT="$W/t" python3 "$CHECK"; }
expect_ok() {
  if run >"$W/out" 2>&1; then echo "ok    $1"; else echo "FAIL  $1 (expected a pass)"; cat "$W/out"; fail=1; fi
}
expect_error() {   # name, text that must appear in the output
  if run >"$W/out" 2>&1; then echo "FAIL  $1 (expected an error, got a pass)"; fail=1
  elif grep -qF -- "$2" "$W/out"; then echo "ok    $1"
  else echo "FAIL  $1 (error without '$2')"; cat "$W/out"; fail=1; fi
}

fixture; expect_ok "a consistent tree passes; code and patterns are not checked"
fixture; printf '\nSee [gone](missing.md).\n' >> "$W/t/docs/guide.md"; expect_error "a link to a missing file" "no such file"
fixture; printf '\nSee [x](guide.md#nope).\n' >> "$W/t/docs/guide.md"; expect_error "a link to a missing anchor" "no heading with that anchor"
fixture; printf '\nRun `make nothing-here`.\n' >> "$W/t/docs/guide.md"; expect_error "a make target that does not exist" "'make nothing-here' is not a target"
fixture; printf '# Other\n' > "$W/t/docs/other.md"; expect_error "a document missing from the map" "other.md is not listed"
fixture; printf 'no import\n' > "$W/t/CLAUDE.md"; expect_error "CLAUDE.md without the import" "@AGENTS.md"
fixture; rm "$W/t/AGENTS.md"; expect_error "AGENTS.md missing" "AGENTS.md is missing"
fixture; printf '# Road\n\n| WP |\n|---|\n| [S1](#wp-s1-a) |\n\n### WP-S1: a\n\n### WP-S2: b\n' > "$W/t/docs/ROADMAP.md"; printf -- '- [road](ROADMAP.md)\n' >> "$W/t/docs/README.md"
expect_error "a work package that is not in the map table" "WP-S2 has a section"

[ "$fail" = 0 ] && echo "docs-selftest: all good" || { echo "docs-selftest: failed"; exit 1; }
