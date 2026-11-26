#!/usr/bin/env python3
"""The GitHub repository settings, as code.  Standard library only (the offline `check` also needs PyYAML, which .venv-validate has).

  github-setup.py check                       the files under .github/ are consistent: JSON, the required status check is a job of ci.yml, the labels that
                                              issue templates and release.yml use exist, limits of GitHub (topics, description, label descriptions)
  github-setup.py apply [--dry-run] [--only about,settings,security,actions,rulesets,environments,labels] [--repo OWNER/NAME]
                                              make the repository look like the files; safe to run again, only sets what the files say

Reads  .github/repository.json (description, topics, settings, security, actions, environments),  .github/rulesets/*.json,  .github/labels.json.
Talks to GitHub through the `gh` CLI, as the account of GH_TOKEN (a fine-grained token limited to this repository: nothing is stored) or else of `gh auth login`;
before it sends anything it says which account that is and stops unless the account is an admin of the repository. GH=<path> uses another binary (the tests use a stand-in).
Which repository: --repo OWNER/NAME, else the variable GH_REPO (the one `gh` itself reads), else the `origin` remote: https, ssh and scp-style URLs, also
through an ssh host alias from ~/.ssh/config (`ssh -G` says where the alias leads). The name is never stored in the files, so a copy of this repository works unchanged.
make github-check | github-plan | github-apply.  What is set and why: docs/REPOSITORY.md, docs/adr/0022-*.md
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GH = os.environ.get("GH", "gh")
API_VERSION = "2022-11-28"
STEPS = ("about", "settings", "security", "actions", "rulesets", "environments", "labels")
TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
GITHUB_HOSTS = {"github.com", "ssh.github.com"}  # GitHub Enterprise: the host in GH_HOST is accepted as well


def load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- check (offline)

def check():
    errors = []

    def err(msg):
        errors.append(msg)

    try:
        repo = load(".github/repository.json")
        labels = load(".github/labels.json")
    except (OSError, ValueError) as e:
        print(f"github-check: {e}")
        return 1
    rulesets = {}
    for p in sorted(glob.glob(os.path.join(ROOT, ".github", "rulesets", "*.json"))):
        try:
            rulesets[os.path.basename(p)] = load(os.path.relpath(p, ROOT))
        except ValueError as e:
            err(f"{os.path.relpath(p, ROOT)}: {e}")

    desc = repo.get("description", "")
    if not desc or len(desc) > 350:
        err(f"repository.json: description must be 1-350 characters (it has {len(desc)})")
    topics = repo.get("topics", [])
    if len(topics) > 20:
        err(f"repository.json: at most 20 topics (there are {len(topics)})")
    for t in topics:
        if not TOPIC_RE.match(t):
            err(f"repository.json: topic '{t}' must be lowercase letters, digits and hyphens, at most 50 characters")
    if len(set(topics)) != len(topics):
        err("repository.json: a topic is listed twice")
    for key in ("settings", "security", "actions", "environments"):
        if not isinstance(repo.get(key), dict):
            err(f"repository.json: '{key}' is missing")

    names = [x.get("name") for x in labels]
    if len(set(n.lower() for n in names)) != len(names):
        err("labels.json: a label name is used twice")
    for x in labels:
        if not re.match(r"^[0-9a-f]{6}$", x.get("color", "")):
            err(f"labels.json: '{x.get('name')}' needs a color of six hex digits without '#'")
        if len(x.get("description", "")) > 100:
            err(f"labels.json: the description of '{x.get('name')}' is longer than 100 characters")

    # the required status check must be a job that ci.yml has
    try:
        import yaml
        with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
            ci = yaml.safe_load(f)
        job_names = {(j.get("name") or k) for k, j in ci["jobs"].items()}
    except ImportError:
        job_names = None
        print("github-check: PyYAML is not installed, the check of ci.yml is skipped (make github-check installs it)")
    except (OSError, KeyError, ValueError) as e:
        err(f"ci.yml: {e}")
        job_names = None
    for fname, rs in rulesets.items():
        for k in ("name", "target", "enforcement", "rules"):
            if k not in rs:
                err(f"rulesets/{fname}: '{k}' is missing")
        for rule in rs.get("rules", []):
            if rule.get("type") == "required_status_checks" and job_names is not None:
                for c in rule["parameters"]["required_status_checks"]:
                    if c["context"] not in job_names:
                        err(f"rulesets/{fname}: the required check '{c['context']}' is not a job name of ci.yml ({', '.join(sorted(job_names))}); "
                            "GitHub would wait for it forever and nothing could be merged")
    if not any(any(r.get("type") == "required_status_checks" for r in rs.get("rules", [])) for rs in rulesets.values()):
        err("rulesets: no ruleset requires a status check")

    # labels used by the issue templates and by release.yml must exist
    used = {}
    for p in glob.glob(os.path.join(ROOT, ".github", "ISSUE_TEMPLATE", "*.yml")):
        try:
            import yaml
            with open(p, encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
        except ImportError:
            break
        except ValueError as e:
            err(f"{os.path.relpath(p, ROOT)}: {e}")
            continue
        for lab in doc.get("labels", []) or []:
            used.setdefault(lab, os.path.relpath(p, ROOT))
    rel = os.path.join(ROOT, ".github", "release.yml")
    if os.path.isfile(rel):
        try:
            import yaml
            with open(rel, encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
            ch = doc.get("changelog", {})
            for lab in (ch.get("exclude", {}) or {}).get("labels", []) or []:
                used.setdefault(lab, ".github/release.yml")
            for cat in ch.get("categories", []) or []:
                for lab in cat.get("labels", []) or []:
                    if lab != "*":
                        used.setdefault(lab, ".github/release.yml")
        except ImportError:
            pass
    for lab, where in sorted(used.items()):
        if lab.lower() not in {n.lower() for n in names}:
            err(f"{where}: the label '{lab}' is not in labels.json")

    # an environment's reviewers are user names or the word "owner"; tags and branches are lists
    for env, cfg in (repo.get("environments") or {}).items():
        if not re.match(r"^[a-z][a-z0-9-]*$", env):
            err(f"repository.json: environment name '{env}'")
        df = cfg.get("deploy_from", {})
        if not (df.get("branches") or df.get("tags")):
            err(f"repository.json: environment '{env}' can be deployed from no branch and no tag")

    if errors:
        print("\n".join(errors))
        print(f"\ngithub-check: {len(errors)} problem(s)")
        return 1
    print(f"github-check: repository.json, {len(rulesets)} rulesets, {len(labels)} labels: consistent with ci.yml and the templates")
    return 0


# ---------------------------------------------------------------- apply

class Gh:
    def __init__(self, repo, dry):
        self.repo, self.dry = repo, dry
        self.failed = []

    def call(self, method, path, body=None, ok_missing=False, quiet=False):
        """One REST call through `gh api`. Returns the parsed JSON (or None). In a dry run nothing is sent (reads return None)."""
        path = path.replace("{repo}", self.repo)
        shown = f"{method} {path}" + (f"\n    {json.dumps(body, sort_keys=True)}" if body is not None else "")
        if self.dry:
            if method != "GET":
                print("  " + shown)
            return None
        cmd = [GH, "api", "--method", method, "-H", f"X-GitHub-Api-Version: {API_VERSION}", "-H", "Accept: application/vnd.github+json", path]
        if body is not None:
            cmd += ["--input", "-"]
        try:
            r = subprocess.run(cmd, input=json.dumps(body) if body is not None else None, capture_output=True, text=True)
        except FileNotFoundError:
            sys.exit("github-setup: the GitHub CLI (gh) is not installed: https://cli.github.com, then `gh auth login`")
        if r.returncode != 0:
            msg = (r.stdout.strip() or r.stderr.strip()).replace("\n", " ")[:300]
            if ok_missing and "404" in (r.stderr + r.stdout):
                return None
            self.failed.append(f"{method} {path}: {msg}")
            print(f"  FAILED {shown.splitlines()[0]}\n         {msg}")
            return None
        if not quiet:
            print("  ok     " + shown.splitlines()[0])
        out = r.stdout.strip()
        try:
            return json.loads(out) if out else None
        except ValueError:
            return None


def apply(args):
    repo, source = resolve_repo(args.repo)
    only = set(args.only.split(",")) if args.only else set(STEPS)
    unknown = only - set(STEPS)
    if unknown:
        sys.exit(f"github-setup: unknown step(s) {', '.join(sorted(unknown))}; steps: {', '.join(STEPS)}")
    cfg = load(".github/repository.json")
    gh = Gh(repo, args.dry_run)
    print(f"{'DRY RUN, nothing is sent: ' if args.dry_run else ''}repository {repo} ({source})")
    if not args.dry_run:
        preflight(gh)

    if "about" in only:
        print("\nAbout: description, homepage, topics")
        gh.call("PATCH", "/repos/{repo}", {"description": cfg["description"], "homepage": cfg.get("homepage", "")})
        gh.call("PUT", "/repos/{repo}/topics", {"names": cfg["topics"]})

    if "settings" in only:
        print("\nFeatures and merge settings")
        gh.call("PATCH", "/repos/{repo}", cfg["settings"])

    if "security" in only:
        s = cfg["security"]
        print("\nSecurity")
        status = lambda on: {"status": "enabled" if on else "disabled"}
        gh.call("PATCH", "/repos/{repo}", {"security_and_analysis": {
            "secret_scanning": status(s["secret_scanning"]),
            "secret_scanning_push_protection": status(s["secret_scanning_push_protection"])}})
        gh.call("PUT" if s["dependabot_alerts"] else "DELETE", "/repos/{repo}/vulnerability-alerts")
        gh.call("PUT" if s["dependabot_security_updates"] else "DELETE", "/repos/{repo}/automated-security-fixes")
        gh.call("PUT" if s["private_vulnerability_reporting"] else "DELETE", "/repos/{repo}/private-vulnerability-reporting")
        if s.get("code_scanning"):
            gh.call("PATCH", "/repos/{repo}/code-scanning/default-setup",
                    {"state": s["code_scanning"]["state"], "query_suite": s["code_scanning"]["query_suite"],
                     "languages": s["code_scanning"]["languages"], "runner_type": "standard"})

    if "actions" in only:
        print("\nGitHub Actions: token permissions")
        gh.call("PUT", "/repos/{repo}/actions/permissions/workflow", cfg["actions"])

    if "rulesets" in only:
        print("\nRulesets")
        existing = gh.call("GET", "/repos/{repo}/rulesets", quiet=True) or []
        by_name = {r["name"]: r["id"] for r in existing}
        for p in sorted(glob.glob(os.path.join(ROOT, ".github", "rulesets", "*.json"))):
            rs = load(os.path.relpath(p, ROOT))
            if rs["name"] in by_name:
                gh.call("PUT", f"/repos/{{repo}}/rulesets/{by_name[rs['name']]}", rs)
            else:
                gh.call("POST", "/repos/{repo}/rulesets", rs)

    if "environments" in only:
        print("\nEnvironments")
        me = None
        for name, env in cfg["environments"].items():
            body = {"wait_timer": env.get("wait_timer", 0), "prevent_self_review": env.get("prevent_self_review", False),
                    "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
            reviewers = []
            for who in env.get("reviewers", []):
                if who == "owner":
                    if me is None:
                        me = gh.call("GET", "/user", quiet=True) or {"id": 0, "login": "(you)"}
                    reviewers.append({"type": "User", "id": me["id"]})
                else:
                    u = gh.call("GET", f"/users/{who}", quiet=True)
                    if u:
                        reviewers.append({"type": "User", "id": u["id"]})
            body["reviewers"] = reviewers
            gh.call("PUT", f"/repos/{{repo}}/environments/{name}", body)
            have = gh.call("GET", f"/repos/{{repo}}/environments/{name}/deployment-branch-policies", quiet=True) or {}
            present = {(x["name"], x.get("type", "branch")) for x in have.get("branch_policies", [])}
            wanted = [(b, "branch") for b in env["deploy_from"].get("branches", [])] + [(t, "tag") for t in env["deploy_from"].get("tags", [])]
            for pat, kind in wanted:
                if (pat, kind) not in present:
                    gh.call("POST", f"/repos/{{repo}}/environments/{name}/deployment-branch-policies", {"name": pat, "type": kind})

    if "labels" in only:
        print("\nLabels")
        for lab in load(".github/labels.json"):
            name = lab["name"]
            quoted = urllib.parse.quote(name, safe="")
            found = gh.call("GET", f"/repos/{{repo}}/labels/{quoted}", ok_missing=True, quiet=True)
            if found:
                gh.call("PATCH", f"/repos/{{repo}}/labels/{quoted}", {"color": lab["color"], "description": lab["description"]})
            else:
                gh.call("POST", "/repos/{repo}/labels", lab)

    print()
    if gh.failed:
        print(f"{len(gh.failed)} call(s) failed. The usual causes: not an admin of the repository (`gh auth status`), a feature that this plan or repository does not have,")
        print("or a setting that is managed elsewhere (code scanning with an advanced workflow). Everything else was applied; run again after fixing, it is safe.")
        return 1
    print("Done." if not args.dry_run else "Dry run finished: that is everything `apply` would send.")
    return 0


def preflight(gh):
    """Who is acting, and may they change this repository? Wrong account (several are common), a token for another repository, or no login at all stop here."""
    me = gh.call("GET", "/user", quiet=True)
    info = gh.call("GET", "/repos/{repo}", quiet=True)
    gh.failed.clear()
    who = (me or {}).get("login", "an account that GitHub did not name")
    if not info:
        sys.exit(f"github-setup: {gh.repo} cannot be read as {who}. Wrong account, a token that is not scoped to this repository, or no credentials: "
                 "set GH_TOKEN (a fine-grained token for this repository, docs/REPOSITORY.md) or run `gh auth status`.")
    perms = info.get("permissions")
    if perms is not None and not perms.get("admin"):
        sys.exit(f"github-setup: {who} can read {gh.repo} but is not an admin of it, so GitHub would refuse the settings. Use the owner's account or token.")
    print(f"acting as {who}" + ("" if perms is not None else " (GitHub did not say whether as an admin: failed requests will tell)"))


def parse_remote(url):
    """(host, 'OWNER/NAME') of a git remote URL: https://, ssh://, git:// or scp-style [user@]host:OWNER/NAME; None for anything else (a path, say)."""
    m = (re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]+@)?([^/:]+)(?::\d+)?/+([^/]+)/([^/]+?)(?:\.git)?/?$", url, re.I)
         or re.match(r"^(?:[^@/]+@)?([^/:]+):/*([^/]+)/([^/]+?)(?:\.git)?/?$", url))
    return (m.group(1), f"{m.group(2)}/{m.group(3)}") if m else None


def github_host(host):
    """The GitHub host that `host` stands for, or None. `host` is github.com itself, or an ssh alias (a Host block in ~/.ssh/config, one per account
    or key is common) that `ssh -G` resolves to it: the same resolution git's ssh transport uses, so nothing here guesses from the alias name."""
    allowed = GITHUB_HOSTS | ({os.environ["GH_HOST"].lower()} if os.environ.get("GH_HOST") else set())
    if host.lower() in allowed:
        return host.lower()
    try:
        out = subprocess.run(["ssh", "-G", host], capture_output=True, text=True, check=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        key, _, value = line.partition(" ")
        if key.lower() == "hostname":
            return value.strip().lower() if value.strip().lower() in allowed else None
    return None


def resolve_repo(flag):
    """('OWNER/NAME', where it came from): --repo, then GH_REPO, then the `origin` remote. Explicit beats implied, and the variable is gh's own."""
    for value, source in ((flag, "--repo"), (os.environ.get("GH_REPO"), "GH_REPO")):
        if value:
            if not REPO_RE.match(value):
                sys.exit(f"github-setup: {source} '{value}' is not OWNER/NAME (for GitHub Enterprise give OWNER/NAME and set GH_HOST)")
            return value, source
    try:
        url = subprocess.run(["git", "-C", ROOT, "remote", "get-url", "origin"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        sys.exit("github-setup: cannot read the 'origin' remote; pass --repo OWNER/NAME or set GH_REPO")
    parsed = parse_remote(url)
    host = github_host(parsed[0]) if parsed else None
    if not host:
        sys.exit(f"github-setup: the 'origin' remote '{url}' does not lead to GitHub; pass --repo OWNER/NAME or set GH_REPO")
    via = "" if host == parsed[0].lower() else f" via the ssh host '{parsed[0]}'"
    return parsed[1], f"origin remote{via}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    a = sub.add_parser("apply")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--only")
    a.add_argument("--repo")
    args = ap.parse_args()
    return check() if args.cmd == "check" else apply(args)


if __name__ == "__main__":
    sys.exit(main())
