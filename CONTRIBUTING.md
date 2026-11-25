# Contributing

Thank you for helping. The short version: **take one work package, stay in its lane, open one pull request, say what you verified.**

The full rules are in [AGENTS.md](AGENTS.md); they apply to people and to AI agents alike. This page is the part that is about the pull request.

## Before you start

1. Read [docs/STATUS.md](docs/STATUS.md) (what exists) and your package in [docs/ROADMAP.md](docs/ROADMAP.md) (goal, lane, inputs, definition of done). If your idea is not a package, open a *Work package* issue first and say which files you would touch.
2. A change to `contracts/` is its own small pull request, merged before the code that needs it ([AGENTS.md](AGENTS.md#changing-a-contract)).
3. A decision that is expensive to reverse gets a decision record: `make adr-new T="Title"` ([docs/adr/README.md](docs/adr/README.md)).

## Setup

Windows 11 with Docker Desktop (WSL2) and an Ubuntu distribution is the platform this was developed on; clone **into the WSL file system**. [docs/GETTING-STARTED.md](docs/GETTING-STARTED.md) has the steps, and `make doctor` checks them.
Install the git hooks once per clone: `make hooks` ([docs/PRE-COMMIT.md](docs/PRE-COMMIT.md)). They are a shortcut: CI runs the same checks and is the gate.

## The pull request

- **Branch** from the latest `master`: `wp/<id>-<short-name>` (for example `wp/t1-grpc-mock`), or `fix/<short-name>`, `docs/<short-name>`.
- **Title:** `WP-<id>: what it does`. The pull request is squash-merged and the title becomes the commit message on `master`, so write it as one. Renovate's pull requests keep their own titles.
- **One package per pull request**, small enough to review. A bug you find elsewhere is an issue or a line in your description, not a drive-by fix.
- **Checks:** `make precommit` locally; CI must be green (`ok` is the one required check, [docs/CI.md](docs/CI.md)). Run the rung of the [verification ladder](AGENTS.md#verification-ladder-cheapest-first) that your change needs and say which one you ran.
- **Documentation is part of the change:** the guide of the area, [docs/STATUS.md](docs/STATUS.md) and [docs/HISTORY.md](docs/HISTORY.md).
- **Merge:** squash only, linear history; the branch is deleted afterwards. Resolve every conversation. Approvals: the owner decides how many (today: none required, because there is one maintainer, see [docs/REPOSITORY.md](docs/REPOSITORY.md)).

## Reporting problems

Bugs and questions: an issue with the output of `make doctor`. Security problems: **not** an issue, see [SECURITY.md](SECURITY.md).

By contributing you agree that your contribution is licensed as the repository is ([LICENSE](LICENSE)). Be kind: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
