#!/usr/bin/env python3
"""The Markdown documentation is consistent. Standard library only.  make docs-check

  - every relative link points at a file or folder that exists, and a #anchor at a heading that exists
  - every `make <target>` that a document shows as a command (in backticks or a code block) is a target of the Makefile;
    docs/ROADMAP.md is exempt, it describes targets that a package will add
  - every document in docs/ is listed in docs/README.md, and every work package heading of docs/ROADMAP.md is in its map table
  - AGENTS.md and CLAUDE.md exist and CLAUDE.md imports AGENTS.md

Links inside code (fenced blocks, `inline code`) are examples and are not checked. DOCS_ROOT=<dir> checks another tree (the self-test does).
What each document is for: docs/README.md.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.environ.get("DOCS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP_DIRS = {".git", "node_modules", "__pycache__", "out", "build", "dist"}
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
MAKE_RE = re.compile(r"(?:^|[;&|(]\s*|\$\s+)(?:sudo\s+)?make\s+([a-z][a-z0-9_-]*)")
PLANNED_TARGETS_IN = {os.path.join("docs", "ROADMAP.md")}            # describes targets that do not exist yet
INLINE_RE = re.compile(r"`([^`\n]*)`")
errors = []


def err(path, line, msg):
    errors.append(f"{os.path.relpath(path, ROOT)}{':' + str(line) if line else ''}: {msg}")


def slug(heading):
    """GitHub's anchor for a heading."""
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    h = h.replace("`", "").replace("*", "").strip().lower()
    h = re.sub(r"[^\w\- ]", "", h, flags=re.UNICODE)
    return h.replace(" ", "-")


def markdown_files():
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "-co", "--exclude-standard", "*.md"],
                             capture_output=True, text=True, check=True).stdout.split("\n")
        files = [os.path.join(ROOT, f) for f in out if f and os.path.isfile(os.path.join(ROOT, f))]
        if files:
            return sorted(files)
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for d, dirs, names in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".venv")]
        found += [os.path.join(d, n) for n in names if n.endswith(".md")]
    return sorted(found)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def prose_lines(text):
    """(number, line, in_code_block)."""
    fenced = False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE_RE.match(line):
            fenced = not fenced
            continue
        yield n, line, fenced


_anchor_cache = {}


def anchors_of(path):
    if path not in _anchor_cache:
        found, seen = set(), {}
        for _, line, code in prose_lines(read(path)):
            if code:
                continue
            m = HEADING_RE.match(line)
            if m:
                s = slug(m.group(1))
                k = seen.get(s, 0)
                seen[s] = k + 1
                found.add(s if k == 0 else f"{s}-{k}")
        _anchor_cache[path] = found
    return _anchor_cache[path]


def makefile_targets():
    path = os.path.join(ROOT, "Makefile")
    if not os.path.isfile(path):
        return None
    targets = set()
    for line in read(path).splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+(?:\s+[A-Za-z0-9_.-]+)*)\s*:(?!=)", line)
        if m and not line.startswith(("\t", ".", "#")):
            targets.update(m.group(1).split())
    return targets


def check_links(path):
    base = os.path.dirname(path)
    for n, line, code in prose_lines(read(path)):
        if code:
            continue
        stripped = INLINE_RE.sub("", line)
        for m in LINK_RE.finditer(stripped):
            target = m.group(1)
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("//"):
                continue                                              # http:, https:, mailto: ...
            file_part, _, anchor = target.partition("#")
            dest = path if file_part == "" else os.path.normpath(os.path.join(base, file_part))
            if not os.path.exists(dest):
                err(path, n, f"link to '{target}': no such file or folder")
            elif anchor and os.path.isfile(dest) and dest.endswith(".md") and anchor not in anchors_of(dest):
                err(path, n, f"link to '{target}': {os.path.relpath(dest, ROOT)} has no heading with that anchor")


def check_make_targets(path, targets):
    if targets is None or os.path.relpath(path, ROOT) in PLANNED_TARGETS_IN:
        return
    for n, line, code in prose_lines(read(path)):
        texts = [re.sub(r"\s#.*$", "", line).strip()] if code else [t.strip() for t in INLINE_RE.findall(line)]
        for t in texts:
            for m in MAKE_RE.finditer(t):
                name = m.group(1)
                if name.endswith(("-", "_")) or t[m.end():m.end() + 1] == "-" or t[m.end():m.end() + 3] == "...":
                    continue                                          # a pattern such as `make k8s-up-...`
                if name not in targets:
                    err(path, n, f"'make {name}' is not a target of the Makefile")


def check_docs_index(files):
    index = os.path.join(ROOT, "docs", "README.md")
    docs = [f for f in files if os.path.dirname(f) == os.path.join(ROOT, "docs")]
    if not docs:
        return
    if not os.path.isfile(index):
        err(os.path.join(ROOT, "docs"), 0, "docs/README.md (the documentation map) is missing")
        return
    linked = set()
    for _, line, code in prose_lines(read(index)):
        if code:
            continue
        for m in LINK_RE.finditer(INLINE_RE.sub("", line)):
            linked.add(os.path.normpath(os.path.join(os.path.dirname(index), m.group(1).partition("#")[0])))
    for d in docs:
        if d != index and d not in linked:
            err(index, 0, f"{os.path.relpath(d, ROOT)} is not listed in the documentation map")
    adr = os.path.join(ROOT, "docs", "adr", "README.md")
    if os.path.isfile(adr) and adr not in linked:
        err(index, 0, "docs/adr/README.md is not listed in the documentation map")


def check_roadmap():
    road = os.path.join(ROOT, "docs", "ROADMAP.md")
    if not os.path.isfile(road):
        return
    text = read(road)
    headings = re.findall(r"^###\s+(WP-[A-Z]+\d+)\b", text, re.M)
    in_map = set(re.findall(r"^\|\s*\[([A-Z]+\d+)\]\(#wp-", text, re.M))
    for wp in headings:
        if wp[3:] not in in_map:
            err(road, 0, f"{wp} has a section but is not in the map table")
    for wp in sorted(in_map):
        if f"WP-{wp}" not in headings:
            err(road, 0, f"the map table lists {wp} but there is no '### WP-{wp}' section")


def check_agent_files():
    agents, claude = os.path.join(ROOT, "AGENTS.md"), os.path.join(ROOT, "CLAUDE.md")
    if not os.path.isfile(agents):
        err(agents, 0, "AGENTS.md is missing")
    if not os.path.isfile(claude):
        err(claude, 0, "CLAUDE.md is missing (it contains the line @AGENTS.md)")
    elif "@AGENTS.md" not in read(claude).split():
        err(claude, 0, "CLAUDE.md must import AGENTS.md with a line '@AGENTS.md'")


def main():
    files = markdown_files()
    targets = makefile_targets()
    for f in files:
        check_links(f)
        check_make_targets(f, targets)
    check_docs_index(files)
    check_roadmap()
    check_agent_files()
    if errors:
        print("\n".join(errors))
        print(f"\ndocs-check: {len(errors)} problem(s) in {len(files)} Markdown files")
        return 1
    print(f"docs-check: {len(files)} Markdown files: links, anchors, make targets and the documentation map are consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
