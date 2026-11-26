# 0017. Every check is a make target; CI is the gate and git hooks are a shortcut

- Status: Accepted
- Date: 2026-11-20

## Context

The repository has many checks: contract consistency, linting, generated files, seed data, dashboards, gateway overlays, workflows, shell scripts, Dockerfiles, the Renovate configuration. They have to run on a developer's machine,
in a pull request and for every implementation in every language. Two things go wrong with checks: nobody can reproduce a red pipeline locally, and a check that is only in a git hook is skipped as soon as someone commits from another tool.

## Decision

1. **Every check is a `make` target** (`make check-contracts`, `make seed-check`, `make lint`, ...). The GitHub Actions workflows are thin wrappers that call these targets, so a red job is reproduced with one command, and another CI system calls the same targets ([CI](../CI.md)).
2. **CI is the gate.** The one check to require is `ci / ok`.
3. **Git hooks ([pre-commit](https://pre-commit.com)) are a faster way to hear about a failure, never the gate.** They run the same checks on the files of a commit (and the slow Docker-based ones before a push), the repo's own checks only when files of their area changed ([PRE-COMMIT](../PRE-COMMIT.md)).

## Consequences

- `git commit --no-verify` is allowed. A branch that skipped a hook and breaks a check fails in CI with the same message.
- A hook whose tool is missing (no Docker Desktop running, Node older than 24 for the Renovate validator) says so and passes, because a hook must not fail a commit over a missing tool. The `make` target run by hand fails in that case, as it should.
- The pre-commit step of CI skips the repo's own hooks (`wh-*`), because CI's own steps already run those targets and show their output separately; the list is read from the config, so a new hook needs no change to the workflow.
- Nothing in the repository depends on pre-commit being installed.
- Deliberately not included: a secret scanner (the repository holds development secrets on purpose, so a scanner needs an allow-list that fits your services) and a commit-message convention (a team decision); the documents say how to add them.
- A new check starts as a make target; a hook entry and a CI step then call it, and the documents say what it catches.

## Alternatives considered

Checks that live in the workflow files only, which cannot be run locally. Hooks as the gate, which a different git client or `--no-verify` bypasses silently.
