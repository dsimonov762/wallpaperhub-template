# 0022. master is protected by a ruleset, and the repository settings are files applied by a script

- Status: Accepted
- Date: 2026-11-24

## Context

The template is finished and the work that follows is done by several people or AI agents in parallel ([AGENTS.md](../../AGENTS.md)), each in a branch of its own, for months. What keeps `master` working is CI ([0017](0017-every-check-is-a-make-target-ci-is-the-gate-and-hooks-are-a-shortcut.md)), but only if nothing can reach `master` without passing it.
The settings that make that true (what may be pushed, what is required, how a pull request is merged, who is told about a vulnerability) live in the GitHub web interface: nobody reviews them, they cannot be copied to the next repository, and a change leaves no trace. The repository is public and belongs to a personal account, with one maintainer for now and a team expected later.

## Decision

1. **`master` is protected by a repository ruleset**, not by a classic branch protection rule: no direct push, no deletion, no force push; changes arrive by pull request; the check **`ok`** (the last job of `ci.yml`, shown as `ci / ok`) must pass on a branch that is up to date; conversations must be resolved; **squash merge only** (so history is linear and the pull request title, `WP-<id>: ...`, is the commit message); head branches are deleted after the merge.
2. **No approving review is required while there is one maintainer**, because a rule that the only maintainer cannot satisfy is worked around instead of followed. It becomes one required approval, with code-owner review, when a second maintainer joins ([REPOSITORY.md](../REPOSITORY.md#when-the-team-grows)). Repository admins may bypass the ruleset only through a pull request, as an emergency hatch.
3. **Release tags `v*` cannot be moved or deleted**, so that a version that another repository pins stays what it was.
4. **The settings are files, applied by a script:** `.github/repository.json` (About text, topics, features, merge settings, security, Actions token, environments), `.github/rulesets/*.json`, `.github/labels.json`, and `scripts/github-setup.py` (`make github-apply`; `make github-plan` shows what it would send). The script only sets what the files say and is safe to run again.
   `make github-check` verifies the files offline in CI; in particular that the required check is a job that `ci.yml` has: a ruleset that waits for a check nobody produces blocks every merge, and the name that GitHub registers is the job name, not the one shown in the interface.
5. **Security features on:** secret scanning with push protection, Dependabot alerts (Renovate reads them and raises the update at once, [0018](0018-pin-every-version-and-let-renovate-propose-updates.md)), private vulnerability reporting, CodeQL default setup. **Dependabot security updates are off**, so that a vulnerable pin does not produce two pull requests, one from each tool.
6. **The workflow token is read-only by default** and Actions cannot approve pull requests; a workflow that needs more asks for it in its own `permissions:`.
7. **Environments `staging` and `production` exist** with their rules (deployment only from `master` and `v*` tags for staging, from `v*` tags with a required reviewer for production) so that the first deployment pipeline ([ROADMAP](../ROADMAP.md), WP-C1) finds them; they hold no secrets and nothing deploys to them yet.

## Consequences

- A pull request cannot be merged red or stale, and nobody (including the maintainer) can push to `master` by accident. The price is that every change, also a typo in a document, goes through a pull request and a CI run, and that a branch that is behind must be updated before it merges (the *Update branch* button, or auto-merge, which is enabled).
- Required "up to date" means that with many parallel pull requests each merge makes the others stale and CI runs again. With the packages in separate lanes this is tolerable; if it hurts, `strict_required_status_checks_policy` is one line in `master.json` (or a merge queue).
- The settings can be reviewed in a pull request, repeated for a second repository, and re-applied when somebody changes them in the interface. What the script does not manage, because the API cannot: the social preview image, the repository's visibility, Discussions, who has which role. [REPOSITORY.md](../REPOSITORY.md) lists them.
- The script needs `gh` logged in as an admin of the repository and was not run against GitHub when it was written; its requests were checked against GitHub's published REST description. Its first run is the owner's.
- A fork or a copy of this repository starts without any of these settings; running `make github-apply` there sets them (the repository is also a GitHub template repository).

## Alternatives considered

- **Classic branch protection** is older, cannot protect tags, cannot be layered, and has no bypass mode that works only through a pull request. Rulesets are what GitHub develops now.
- **Settings by hand** is quick and is what most repositories do; it was rejected for the reasons in the context (no review, no history, not repeatable).
- **A settings app (Probot settings, Terraform provider)** adds a service or a toolchain for what a 300-line standard-library script with a dry run does; the files are plain JSON in GitHub's own format, so moving to one of them later costs little.
- **Requiring signed commits** on `master`: squash merges made in the web interface are signed by GitHub, so the rule would mostly protect against direct pushes that are already blocked, and it forbids rebase merges. Not taken; it is one more rule in `master.json` if wanted.
- **One required approval from the start** with the maintainer's own pull requests: impossible to satisfy alone (GitHub does not count the author), so it would have meant permanent bypass.
