#!/usr/bin/env bash
# make github-selftest: does scripts/github-setup.py catch what it says it catches (a required check that no job provides, an unknown label, ...),
# and does `apply` update instead of create the second time? Works on a copy in a temporary folder with a stand-in for `gh`; no network, nothing in the repository is touched.
set -euo pipefail
cd "$(dirname "$0")/../.." || exit 1
export PYTHONDONTWRITEBYTECODE=1
PY="${PYTHON:-python3}"; [ -x .venv-validate/bin/python ] && PY="$PWD/.venv-validate/bin/python"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
fail=0

fixture() {
  rm -rf "$W/t"; mkdir -p "$W/t/scripts"
  cp -r .github "$W/t/.github"; cp scripts/github-setup.py "$W/t/scripts/"
}
run() { (cd "$W/t" && "$PY" scripts/github-setup.py "$@"); }
expect_ok() { if run check >"$W/out" 2>&1; then echo "ok    $1"; else echo "FAIL  $1 (expected a pass)"; cat "$W/out"; fail=1; fi; }
expect_error() {
  if run check >"$W/out" 2>&1; then echo "FAIL  $1 (expected an error, got a pass)"; fail=1
  elif grep -qF -- "$2" "$W/out"; then echo "ok    $1"; else echo "FAIL  $1 (error without '$2')"; cat "$W/out"; fail=1; fi
}

fixture; expect_ok "the shipped files are consistent"
fixture; sed -i 's/"context": "ok"/"context": "ci \/ ok"/' "$W/t/.github/rulesets/master.json"; expect_error "a required check that is not a job of ci.yml" "is not a job name of ci.yml"
fixture; sed -i 's/labels: \["bug"\]/labels: ["no-such-label"]/' "$W/t/.github/ISSUE_TEMPLATE/bug_report.yml"; expect_error "an issue template with an unknown label" "'no-such-label' is not in labels.json"
fixture; sed -i 's/- adr$/- ghost/; s/\[adr, documentation\]/[ghost, documentation]/' "$W/t/.github/release.yml"; expect_error "release.yml with an unknown label" "'ghost' is not in labels.json"
fixture; sed -i 's/"color": "d73a4a"/"color": "#d73a4a"/' "$W/t/.github/labels.json"; expect_error "a label color with #" "six hex digits"
fixture; "$PY" - "$W/t/.github/repository.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["topics"] += ["Not Valid"]; json.dump(d, open(p, "w"))
PY
expect_error "an invalid topic" "topic 'Not Valid'"

# apply: first run creates, second run updates (the stand-in answers like a repository that already has everything)
fixture
cat > "$W/gh" <<'GH'
#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]; method = a[a.index("--method") + 1]; path = a[-1] if "--input" not in a else a[a.index("--input") - 1]
open(os.environ["LOG"], "a").write(f"{method} {path}\n")
if method == "GET":
    if path.endswith("/rulesets"): print(os.environ.get("RULESETS", "[]"))
    elif path == "/user": print('{"id": 1, "login": "me"}')
    elif path == "/repos/o/r": print(os.environ.get("REPO_INFO", '{"permissions": {"admin": true}}')); sys.exit(1 if os.environ.get("REPO_INFO") == "MISSING" else 0)
    elif "/labels/" in path:
        if os.environ.get("EXISTS"): print('{"name": "x"}')
        else: sys.stderr.write("HTTP 404\n"); sys.exit(1)
    elif "deployment-branch-policies" in path: print('{"branch_policies": []}')
    else: print("{}")
GH
chmod +x "$W/gh"
: > "$W/log1"; : > "$W/log2"
GH="$W/gh" LOG="$W/log1" run apply --repo o/r >/dev/null
GH="$W/gh" LOG="$W/log2" EXISTS=1 RULESETS='[{"id":7,"name":"master"},{"id":8,"name":"release tags"}]' run apply --repo o/r >/dev/null
chk() { if grep -q "$2" "$W/$1"; then echo "ok    $3"; else echo "FAIL  $3"; fail=1; fi; }
chk log1 "^POST /repos/o/r/rulesets$" "first run creates the rulesets"
chk log1 "^POST /repos/o/r/labels$" "first run creates the labels"
chk log2 "^PUT /repos/o/r/rulesets/7$" "second run updates the ruleset it finds"
chk log2 "^PATCH /repos/o/r/labels/area%3Agateway$" "second run updates the labels it finds"
if grep -q "^POST /repos/o/r/rulesets$\|^POST /repos/o/r/labels$" "$W/log2"; then echo "FAIL  second run created something"; fail=1; else echo "ok    second run creates no ruleset and no label"; fi

# which repository: --repo, then GH_REPO, then the origin remote (plain URLs, and ssh host aliases that `ssh -G` resolves to github.com)
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
mkdir -p "$W/bin"
cat > "$W/bin/ssh" <<'SSH'
#!/bin/sh
# stand-in for `ssh -G <alias>`: what the alias would resolve to
case "$2" in gh-acme) echo "hostname github.com" ;; *) echo "hostname gitlab.com" ;; esac
SSH
chmod +x "$W/bin/ssh"
origin() { fixture; git init -q "$W/t"; git -C "$W/t" remote add origin "$1"; }
repo_of() { PATH="$W/bin:$PATH" run apply --dry-run "$@" 2>&1 | sed -n '1s/^DRY RUN, nothing is sent: repository \([^ ]*\) (.*$/\1/p'; }
expect_repo() {  # description, expected OWNER/NAME, then the arguments of apply; the origin (and variables) are set by the caller
  got="$(repo_of "${@:3}")"
  if [ "$got" = "$2" ]; then echo "ok    $1"; else echo "FAIL  $1 (got '$got', wanted '$2')"; fail=1; fi
}
expect_repo_error() {  # description, text of the error, then the arguments of apply
  if out="$(PATH="$W/bin:$PATH" run apply --dry-run "${@:3}" 2>&1)"; then echo "FAIL  $1 (expected an error, got a pass)"; fail=1
  elif grep -qF -- "$2" <<<"$out"; then echo "ok    $1"; else echo "FAIL  $1 (error without '$2')"; echo "$out"; fail=1; fi
}
origin https://github.com/acme/widgets.git;                expect_repo "origin: https URL" acme/widgets
origin git@github.com:acme/widgets.git;                    expect_repo "origin: scp-style URL" acme/widgets
origin ssh://git@ssh.github.com:443/acme/widgets.git;      expect_repo "origin: ssh over port 443" acme/widgets
origin git@gh-acme:acme/widgets.git;                       expect_repo "origin: ssh host alias that leads to github.com" acme/widgets
origin git@gl-acme:acme/widgets.git;                       expect_repo_error "origin: ssh host alias that leads elsewhere" "does not lead to GitHub"
origin https://gitlab.com/acme/widgets.git;                expect_repo_error "origin: another forge" "does not lead to GitHub"
origin git@gh-acme:acme/widgets.git;                       GH_REPO=env/wins expect_repo "GH_REPO beats the origin remote" env/wins
origin git@gh-acme:acme/widgets.git;                       GH_REPO=env/loses expect_repo "--repo beats GH_REPO" flag/wins --repo flag/wins
origin git@gh-acme:acme/widgets.git;                       expect_repo_error "--repo that is not OWNER/NAME" "is not OWNER/NAME" --repo widgets
fixture;                                                   expect_repo_error "no origin remote" "cannot read the 'origin' remote"

# who is acting: stops unless the account is an admin of the repository; says who it is
: > "$W/logw"
if out="$(GH="$W/gh" LOG="$W/logw" REPO_INFO='{"permissions": {"admin": false}}' run apply --repo o/r 2>&1)"; then echo "FAIL  a non-admin was allowed to apply"; fail=1
elif grep -q "not an admin" <<<"$out" && ! grep -q "^PATCH\|^PUT\|^POST" "$W/logw"; then echo "ok    a non-admin is refused before anything is sent"; else echo "FAIL  non-admin refusal"; echo "$out"; fail=1; fi
if out="$(GH="$W/gh" LOG="$W/logw" REPO_INFO=MISSING run apply --repo o/r 2>&1)"; then echo "FAIL  an unreadable repository was allowed"; fail=1
elif grep -q "cannot be read as me" <<<"$out"; then echo "ok    a repository the account cannot read stops the run, naming the account"; else echo "FAIL  unreadable repository"; echo "$out"; fail=1; fi
if out="$(GH="$W/gh" LOG="$W/logw" run apply --repo o/r --only about 2>&1)" && grep -q "^acting as me" <<<"$out"; then echo "ok    the run says which account it acts as"; else echo "FAIL  acting-as line"; echo "$out"; fail=1; fi
if out="$(PATH="$W/bin:$PATH" run apply --dry-run --repo o/r 2>&1)" && ! grep -q "acting as" <<<"$out"; then echo "ok    a dry run does not need credentials"; else echo "FAIL  dry run"; fail=1; fi

[ "$fail" = 0 ] && echo "github-selftest: all good" || { echo "github-selftest: failed"; exit 1; }
