# Git hooks (pre-commit)

CI tells you about a broken contract or a stale generated file five minutes after the push. A git hook tells you before the commit exists. [pre-commit](https://pre-commit.com) runs
the same checks from [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) on your machine, in any language, without anything in the repo depending on it: CI runs every check anyway, so a hook is a
faster way to hear about a failure, never the gate.

```
pipx install pre-commit      # once per machine (or: pip install --user pre-commit)
make hooks                   # once per clone: installs the commit and push hooks
make precommit               # every hook on every file: what CI runs. ARGS=shellcheck runs one hook; ARGS="--hook-stage pre-push" runs the push hooks
```

The first run clones the hook repositories and builds their environments (needs GitHub and PyPI); later runs reuse them. `make doctor` says whether the hooks are installed in your clone.

## What runs

**On every commit**, on the files you changed:

| Hook | Catches |
|---|---|
| `trailing-whitespace`, `end-of-file-fixer` | fixes the file and stops the commit, so you look at the change and commit again. Generated folders (`seed/out`, `bruno`, `infra/grafana/dashboards`, ...) are left alone: their generators decide the bytes |
| `check-yaml`, `check-json` | a file that does not parse |
| `check-merge-conflict`, `check-case-conflict` | conflict markers; two files that differ only by case (fine on Linux, a broken checkout on Windows) |
| `check-added-large-files` | more than 1 MB (`--maxkb` in the config) |
| `detect-private-key` | a private key in a commit. Development certificates are generated into git-ignored `infra/certs/` (`make certs`) |
| `shellcheck` | warnings and errors in every shell script (`--severity=warning`; style hints are not enforced) |
| `actionlint` | workflow mistakes (wrong expression, unknown input), plus shellcheck on the `run:` scripts of the workflows. Knows the `ubuntu-26.04` runner through `.github/actionlint.yaml` |
| `hadolint` | Dockerfile rules (`:latest`, missing `--no-cache`, ...). `.hadolint.yaml` ignores pinning of `apk add` packages, with the reason |

**The repo's own checks** (ids `wh-*`), only when files of their area changed, so a change to a document runs none of them. Each is the `make` target CI runs:

| Hook | Runs | When these paths change |
|---|---|---|
| `wh-contracts` | `make check-contracts` | `contracts/`, the gateway config, `scripts/validate/`, host and conformance env files, `README.md` |
| `wh-gateway-errors` | `scripts/gen-gateway-errors.py --check` | `contracts/i18n/`, the gateway config |
| `wh-seed` | `make seed-check` | `seed/`, `contracts/db-schema/` |
| `wh-bruno` | `make bruno-check` | `bruno/`, `contracts/openapi/`, `seed/` |
| `wh-dashboards` | `make dashboards-check` | `infra/grafana/` |
| `wh-chaos` | `make chaos-check` | `infra/chaos/`, `infra/docker-compose.yml` and the chaos overlay |
| `wh-gateway-overlays` | `make load-check https-check` | `envoy.yaml`, the two generators |
| `wh-renovate` | `make renovate-check` | `.github/renovate.json5` (needs Node 24.11+ or Docker, see [RENOVATE.md](RENOVATE.md)) |

They need `make` and Python 3, so they run in WSL, Linux and macOS; they create `.venv-validate` on first use. Each takes a few seconds once that exists.

**Before a push** (they need Docker or build the tool image, too slow for every commit): `wh-lint` (`make lint`: the compose files of every profile, shell syntax, Hurl formatting) when `infra/`, `e2e/`,
`conformance/`, `scripts/`, the gateway or the Makefile changed, and `wh-contracts-lint` (`make contracts-lint`: Spectral, buf, Avro, GraphQL conventions) when `contracts/` changed.

When a generated-file hook fails, its message says what to run (`make bruno-gen`, `make chaos-gen`, `make seed-build`), and you commit the result.

## Skipping, bypassing, updating

```
SKIP=wh-seed git commit ...        # skip one hook (several: SKIP=wh-seed,shellcheck)
git commit --no-verify             # skip all commit hooks      git push --no-verify   skip the push hooks
pre-commit run --files path/to/file             # try the hooks on one file without committing
pre-commit autoupdate              # move the pinned hook versions (rev:) to the latest releases; review the diff, then make precommit
                                   # (Renovate does this as a weekly pull request once installed: RENOVATE.md)
```

`--no-verify` is allowed: CI is the gate. A branch that skipped a hook and breaks the check fails there, with the same message.

## Windows 11 + WSL

Install pre-commit and run `make hooks` **in Ubuntu (WSL)**, with the clone on the WSL file system, and commit from there (a terminal in WSL, or VS Code with the WSL extension). The installed hook points
at the Python of the machine that installed it: a commit made by *Windows* git (GitHub Desktop, Git Bash outside WSL) on a clone whose hooks were installed in WSL cannot find it and the hook fails
with "pre-commit not found". Either commit from WSL, or install pre-commit for Windows too and run `pre-commit install` from there instead, and not both. (Not tested on Windows; this follows from how pre-commit writes the hook.)

## What is deliberately not in it

- **A secret scanner such as gitleaks.** This repository contains development secrets on purpose (the realm export and compose defaults: `account-svc-dev-secret`, `password`), so a scanner needs an allow-list that fits *your* services, and it needs a Go toolchain on every machine. `detect-private-key` catches the case that matters here. Add a scanner when real credentials start to appear in your configuration, with a baseline.
- **A commit message convention** (Conventional Commits and similar). It is a team decision; if you take it, pre-commit has `commit-msg` hooks for it (add `commit-msg` to `default_install_hook_types` and run `make hooks` again).
- **`make contracts-breaking`.** It compares with another git ref and has no override by design; the `breaking` job of CI runs it on pull requests with the right base.
- **Markdown or YAML style linters, formatters of your code.** Language-specific tools belong to the implementation under `services/<name>/<impl>/`, which can have its own hooks (a second `.pre-commit-config.yaml` there is not read; add its hooks to the root file with `files: ^services/account/go/`).

## CI

The `static` job runs `pre-commit run --all-files` first, with the `wh-*` hooks skipped (its own steps run those `make` targets one by one and show the output separately). The skip list is read from the
config, so a new `wh-*` hook needs no change to `ci.yml`.

## What is verified, what is not

Verified with pre-commit 4.7.0, shellcheck 0.11 and the pinned hook versions, on a git copy of this repo: every hook on all files passes (after fixing six shellcheck warnings in scripts and five findings in the
workflows); real `git commit` calls with the hooks installed are stopped for trailing whitespace, a private key, a hand-edited Bruno file, a shell script with an
unchecked `cd`, a workflow expression typo, a Dockerfile with `:latest`, invalid YAML, an i18n key removed, a stale chaos config, an edited HSTS value, a broken dashboard query, a hand-edited seed file and a renamed
operationId; a documentation-only commit runs none of the `wh-*` hooks; the pre-push hooks trigger on the right paths, and `make lint` passes through them.

Not verified: the hooks on Windows, `make contracts-lint` through the hook (it needs the Docker daemon, which the sandbox did not have; the hook ran and failed there for exactly that reason), and the new step in GitHub Actions
(the workflow passes actionlint and the same commands run locally, but it has not run on a runner).
