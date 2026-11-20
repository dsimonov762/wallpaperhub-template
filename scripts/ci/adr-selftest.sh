#!/usr/bin/env bash
# make adr-selftest: does scripts/adr.py catch what docs/adr/README.md says it catches, and do `new` and `--supersedes` keep the records consistent?
# Works on a fixture of two records in a temporary folder; nothing in docs/adr/ is touched. Needs only python3.
set -euo pipefail
cd "$(dirname "$0")/../.." || exit 1
export PYTHONDONTWRITEBYTECODE=1   # the checks import scripts/adr.py; leave no __pycache__ in the repository
ADR="$PWD/scripts/adr.py"
SRC="$PWD/docs/adr"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
fail=0

fixture() {
  rm -rf "$W/t"
  mkdir -p "$W/t/docs/adr"
  cp "$SRC/template.md" "$SRC/README.md" "$W/t/docs/adr/"
  printf '# Guide\n\n## Why it works (and how)\n\ntext\n' > "$W/t/docs/guide.md"
  for n in 1 2; do
    cat > "$W/t/docs/adr/000$n-choice-$n.md" <<REC
# 000$n. Choice $n

- Status: Accepted
- Date: 2026-01-05

## Context

Why. See [the guide](../guide.md#why-it-works-and-how). An example in code is not checked: \`[x](../nothing.md)\`.

## Decision

We will.

## Consequences

It costs.
REC
  done
  adr index >/dev/null
}
adr() { ADR_DIR="$W/t/docs/adr" python3 "$ADR" "$@"; }
sub() { python3 - "$@" <<'PY'
import sys
p, old, new = sys.argv[1:4]
t = open(p, encoding="utf-8").read()
assert old in t, f"{old!r} not in {p}"
open(p, "w", encoding="utf-8", newline="\n").write(t.replace(old, new, 1))
PY
}
R() { echo "$W/t/docs/adr/$1"; }

ok() { # description, command...
  local d=$1; shift
  if out=$("$@" 2>&1); then echo "  ok    $d"; else echo "  FAIL  $d"; echo "$out" | sed 's/^/        /'; fail=1; fi
}
bad() { # description, expected text, command...
  local d=$1 want=$2; shift 2
  if out=$("$@" 2>&1); then echo "  FAIL  $d (it passed)"; fail=1
  elif grep -qF -- "$want" <<<"$out"; then echo "  ok    $d"
  else echo "  FAIL  $d: no '$want' in:"; echo "$out" | sed 's/^/        /'; fail=1; fi
}

fixture; ok   "two good records pass (a link inside backticks is not followed)" adr check
fixture; sub "$(R 0001-choice-1.md)" "../guide.md#why" "../missing.md#why"
bad "a link to a missing file"            "no such file"                         adr check
fixture; sub "$(R 0001-choice-1.md)" "#why-it-works-and-how" "#nope"
bad "a link to a heading that is not there" "has no heading with that anchor"    adr check
fixture; sub "$(R 0001-choice-1.md)" "# 0001." "# 0007."
bad "a title number that differs from the file name" "the title says 0007"       adr check
fixture; sub "$(R 0001-choice-1.md)" $'## Consequences\n\nIt costs.\n' ""
bad "a missing section"                   "missing section '## Consequences'"    adr check
fixture; sub "$(R 0001-choice-1.md)" "We will." "<!-- to do -->"
bad "a section that holds only a comment" "section '## Decision' is empty"       adr check
fixture; sub "$(R 0002-choice-2.md)" "Status: Accepted" "Status: Maybe"
bad "an unknown status"                   "Status is 'Maybe'"                    adr check
fixture; sub "$(R 0002-choice-2.md)" "2026-01-05" "2026-13-45"
bad "a date that is not a date"           "is not a date"                        adr check
fixture; mv "$(R 0002-choice-2.md)" "$(R 0004-choice-2.md)"; sub "$(R 0004-choice-2.md)" "# 0002." "# 0004."
bad "a gap in the numbering"              "numbering: expected 0002"             adr check
fixture; : > "$(R notes.txt)"
bad "a file that is not a record"         "not a record"                         adr check
fixture; sub "$(R 0002-choice-2.md)" $'- Date: 2026-01-05\n' $'- Date: 2026-01-05\n- Supersedes: [0001](0001-choice-1.md)\n'
bad "supersedes without the other side"   "does not say 'Superseded by' this record" adr check
fixture; sub "$(R 0001-choice-1.md)" "Status: Accepted" "Status: Superseded"
bad "Superseded without a successor"      "needs '- Superseded by"               adr check
fixture; sub "$(R README.md)" "| Choice 1 |" "| Choice one |"
bad "a stale index"                       "out of date: run  make adr-index"     adr check
fixture; sub "$(R README.md)" "<!-- adr-index:end -->" ""
bad "an index without its markers"        "needs the two markers"                adr check

# new: the record is a template, so it cannot be committed by accident; filled in, it passes
fixture; ok   "new creates the next record"            adr new "Third choice"
test -f "$(R 0003-third-choice.md)" || { echo "  FAIL  0003-third-choice.md was not created"; fail=1; }
bad "a record that is still the template" "is empty"                             adr check
python3 - "$(R 0003-third-choice.md)" <<'PY'
import re, sys
p = sys.argv[1]
t = open(p, encoding="utf-8").read()
t = re.sub(r"<!--.*?-->", "Filled in.", t, flags=re.S)
open(p, "w", encoding="utf-8", newline="\n").write(t)
PY
ok   "filled in, the index is current and it passes"  adr check
bad "a title with no letters"              "needs letters or digits"              adr new "!!!"
fixture; ok   "new --supersedes"                        adr new "Replace the first" --supersedes 1
grep -q "^- Status: Superseded$" "$(R 0001-choice-1.md)" && grep -q "Superseded by: \[0003\](0003-replace-the-first.md)" "$(R 0001-choice-1.md)" \
  || { echo "  FAIL  0001 was not marked as superseded by 0003"; fail=1; }
grep -q "Supersedes: \[0001\](0001-choice-1.md)" "$(R 0003-replace-the-first.md)" || { echo "  FAIL  0003 does not name 0001"; fail=1; }
bad "superseding a record twice"           "already superseded"                   adr new "Again" --supersedes 1
bad "superseding a record that is not there" "there is no record 0009"            adr new "Nothing" --supersedes 9

# the slug function must agree with GitHub for every heading the README's own table of contents links to
python3 - <<'PY' && echo "  ok    every anchor of the README table of contents resolves" || { echo "  FAIL  the anchor function disagrees with the README"; fail=1; }
import importlib.util, re, sys
spec = importlib.util.spec_from_file_location("adr", "scripts/adr.py"); adr = importlib.util.module_from_spec(spec); spec.loader.exec_module(adr)
toc = re.findall(r"\]\(#([^)]+)\)", open("README.md", encoding="utf-8").read())
have = adr.anchors_of("README.md")
missing = [a for a in toc if a not in have]
sys.exit(f"missing: {missing}" if missing or not toc else 0)
PY

[ "$fail" = 0 ] && echo "adr selftest: all cases behave" || { echo "adr selftest FAILED"; exit 1; }
