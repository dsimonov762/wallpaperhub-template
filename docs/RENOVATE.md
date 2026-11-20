# Keeping versions current (Renovate)

This repository pins everything: container images, GitHub Actions, npm and pip packages, pre-commit hooks, the Hurl and k6 versions CI installs. Pinned means reproducible, and it also means that nobody
notices the Keycloak security release, the Postgres patch, or the action that stopped working on the new runner image, until something breaks. [Renovate](https://docs.renovatebot.com) reads the pins, looks for
newer versions and opens a pull request per update; CI is the test. The configuration is [`.github/renovate.json5`](../.github/renovate.json5), with a comment on every rule.

## Install (once)

1. Install the hosted **Renovate** GitHub App (github.com/apps/renovate, free for GitHub.com) on this repository. It reads `.github/renovate.json5`; there is no onboarding pull request because the file exists.
2. It opens an issue, the **Dependency Dashboard**: every dependency it found, every update it knows about, and what waits for a decision. Updates are created on Monday before 08:00 UTC; the dashboard
   has a checkbox per waiting update if you do not want to wait (the first run will find pins that are already behind).
3. Settings > Branches: require `ci / ok` ([CI.md](CI.md)), so that a Renovate pull request can only be merged green. Renovate's pushes trigger CI like any other.
4. Optional: Settings > Code security > enable Dependabot alerts. Renovate then opens a pull request for a vulnerable dependency at once, ignoring the schedule.

Self-hosted instead (a company that does not want an external app): run the [`renovatebot/github-action`](https://github.com/renovatebot/github-action) on a schedule with a token of a GitHub App or a
fine-grained token (contents, pull requests, issues, workflows: write). The configuration file is the same. Not set up here, because it needs a secret that only you can create.

## What it watches

| Where | Read by |
|---|---|
| `infra/docker-compose*.yml` (including `${VAR:-image:tag}` defaults), every `Dockerfile` | the built-in `docker-compose` and `dockerfile` managers |
| `.github/workflows/*.yml`: actions, `python-version`, `node-version`, `runs-on`, service images | `github-actions` |
| `tools/contract-tools/package.json` and its lock file, `scripts/validate/`, `seed/`, `conformance/reference-stub/` requirements | `npm`, `pip_requirements` |
| `.pre-commit-config.yaml` (`rev:` of every hook) | `pre-commit`, switched on in the config |
| Images in shell scripts, Python generators, the Makefile, `.env.example` and these documents (`grafana/k6:2.4.0`, `tufin/oasdiff:v1.33.0`, `python:3.13-slim` ...) | a regex manager: any `registry.host/path:tag` or `owner/name:tag` whose tag has a dot, and `alpine`, `python`, `postgres`, `mongo`, `redis`, `elasticsearch`, `adminer`, `node` |
| Hurl in `scripts/ci/install-hurl.sh`, k6 in `ci.yml`, Prism in `services/_mock/Dockerfile`, `shellcheck-py` in the actionlint hook, the Renovate version of `make renovate-check` | one small regex manager each |
| Anything else | a comment on the line before the pin, see below |

An image that is written in a script and in a compose file is **one dependency**: one pull request changes both, so the documentation cannot drift from the code (it had: Adminer 5.5.1 and openapi-generator-cli 7.10.0
in a document, 6.3.0 and 7.27.0 in the code, found while testing this configuration).

### A pin Renovate cannot see

Put a comment on the line before it:

```
# renovate: datasource=docker depName=nginx
NGINX_IMAGE="1.29.1-alpine"

# renovate: datasource=github-releases depName=grafana/k6 extractVersion=^v(?<version>.+)$
k6: "1.6.0"
```

`datasource` is `docker`, `npm`, `pypi`, `github-releases`, `github-tags` ... (see the Renovate documentation), `depName` the package or `owner/repo`; `versioning=` and `extractVersion=` are optional.
It works in shell, Python, YAML, `.env`, `Makefile` and `Dockerfile`. Official one-word images that the image pattern does not know (`nginx`, `busybox`) need it; compose files and Dockerfiles never do.

## What becomes one pull request, and why

One batch a week (Monday before 08:00 UTC, at most 10 open at a time) instead of a stream; things that must move together do:

| Pull request | Contains | Why together |
|---|---|---|
| observability images | Grafana, Loki, Tempo, Alloy, Prometheus (minor, patch) | Alloy writes to the other three |
| Confluent Platform | `cp-kafka` and `cp-schema-registry`, **also the major** | released under one version number |
| data store images | Postgres, MongoDB, Redis, Elasticsearch, Silo (minor, patch) | nothing depends on their order; one test run |
| dev tool images | Kafka UI, Adminer, Mongoku, Mailpit (minor, patch) | nothing depends on them |
| k6 | the image of `scripts/k6.sh` and the version CI installs | `ci.yml` says to keep them in step |
| Hurl | the CI binary and the container image | the same |
| npm contract tools, pip validation tooling | their packages (minor, patch) | one test run |
| pre-commit hooks, shellcheck | hook revs; shellcheck and its copy inside the actionlint hook | the same version twice |
| GitHub Actions | every action, major versions included | CI is the test; an action major is usually a Node runtime bump |
| CI runtimes | `python-version`, `node-version` (minor, patch) | |
| everything else (Envoy, Keycloak, Alpine, openapi-generator, oasdiff, Prism ...) | one pull request each | |

**Major versions are not pull requests until you ask.** A new Postgres, Elasticsearch, Keycloak, Kafka or Grafana major changes data formats or configuration, and Python or Node majors change the toolchain.
They are listed on the Dependency Dashboard and Renovate opens the pull request (labelled `major`) when you tick its box. Exceptions: GitHub Actions (above), and PGSTY Silo, whose version is a date
(`RELEASE.2026-10-26T00-00-00Z`): its configuration tells Renovate to read year, month, day as major, minor, patch and not to treat the next year as a breaking change.

Also set: an npm or PyPI release younger than 3 days waits (the dashboard lists it under *Pending Status Checks* until it is old enough; a compromised release is usually pulled within days); the lock file of `tools/contract-tools` is refreshed monthly; no automatic merge; commit
messages are plain ("Update dependency x to vY"), because nothing here has chosen Conventional Commits.

## What a pull request has to pass

The same CI as yours. Look at what a bump touches: `make chaos-check` and `make https-check` compare generated files with their generators, so a Toxiproxy bump changes
`docker-compose.chaos.yml`, `scripts/chaos.py`, `infra/.env.example` and `CHAOS.md` together, and stays consistent. The stack itself is started by the `gateway` job (Keycloak, Envoy, Redis, mocks, the
conformance suite), so a Keycloak, Envoy or Redis bump is tested against the real thing, and the `seed` job loads the seed data into Postgres; Mongo, Elasticsearch, Kafka and Silo are only started by `make up-apps` on your machine, so read
the release notes of those and try the branch: `git fetch && git switch renovate/data-store-images && make reset up-apps`.

When an update is wrong for you: close the pull request (Renovate does not re-open it for that version), or pin the dependency in `packageRules` (`allowedVersions`, `enabled: false`).

## Policies you may want to change

- **Automatic merge** for the boring ones, once `ci / ok` is required. In `packageRules`: `{ matchManagers: ["github-actions"], matchUpdateTypes: ["minor", "patch"], automerge: true }`.
- **Pin actions to a digest** (supply chain): `extends: [..., "helpers:pinGitHubActionDigestsToSemver"]`. Today actions use a major tag, except `setup-k6-action`, which is pinned to a digest with the version in a comment; Renovate keeps both forms current.
- **Conventional Commits**: `semanticCommits: "enabled"`, and in `.pre-commit-config.yaml` a `commit-msg` hook ([PRE-COMMIT.md](PRE-COMMIT.md)).
- **Another schedule or time zone**: `schedule` and `timezone` at the top of the file.

## Checking the configuration

```
make renovate-check          # strict validation with the Renovate release pinned in scripts/renovate-check.sh
```

It needs Node 24.11+ (runs it with `npx`) or a running Docker (the official image). CI runs it, and so does a hook when you touch `.github/renovate.json5`; the hook does not fail a commit when neither is available (it says so and passes, CI is the gate), while `make renovate-check` itself exits with an error then. It catches an unknown key, a wrong option, a regular
expression Renovate cannot compile. Renovate uses the RE2 engine: **no lookahead and no lookbehind** in `matchStrings`; this has already caught one mistake while writing the file. The hosted app runs its own Renovate release (the Mend page of the repository shows it: 44.249.1 on 20 November), a few days behind the one pinned here, so an option that only the newer release knows would be reported by the app as a configuration warning.

To see what Renovate finds without opening any pull request (the way this configuration was tested): `npx renovate --platform=local --dry-run=lookup` in the repository, with `LOG_LEVEL=debug` for the details
and `GITHUB_COM_TOKEN` set so that it can read GitHub releases.

## What is verified, what is not

Verified in the sandbox with Renovate 44.253.0 itself (Node 24):

- The configuration passes the strict validator; a misspelled option and an invalid regular expression are both caught by `make renovate-check`.
- **Extraction** on a copy of this repository: 37 compose images, 9 Dockerfile entries, 28 workflow entries, 4 npm and 14 pip packages, 4 pre-commit hooks and 34 pins found by the regex managers, across 19 files (scripts, generators, `.env.example`, the documents).
  An inverse scan for anything image-shaped that was *not* found came back empty after the image pattern was generalised (it had missed `adminer`, `mongoku` and `tufin/oasdiff`). After the two stale document pins were fixed
  no image has two different versions anywhere in the repository.
- **Rules**, against a stand-in Docker registry serving made-up newer tags (the sandbox cannot reach Docker Hub or GitHub): every grouping in the table above, the Confluent group including its major, the
  `-trixie` and `-alpine` suffixes of Postgres and Redis (no cross-variant updates), the date version of Silo (parsed; its next year is not a major to approve), Keycloak's `-0` suffix, and, with real npm and PyPI data,
  the npm and pip groups. The approval gate for majors was tested **by proxy** (a visible marker on the same rule shows it lands on every major and not on Silo's year change), not by watching a Dependency Dashboard.
- The annotation comment manager on shell, YAML and Dockerfile samples, with `versioning=` and `extractVersion=`.
- The Hurl package matcher (container image and GitHub release both match; look-alikes do not), with Renovate's own matcher code.

Confirmed on the first real run against the repository (the Dependency Dashboard of 19 November 2026, with real registries): the major updates wait under *Pending Approval* (k6 v2, Node 26, Pillow 13, TypeScript 7),
the rest under *Awaiting Schedule* in the groups above (Confluent Platform, data store images with Postgres, Mongo and the Silo date tags, observability images), the k6 updates are found in all four places the version
appears (the image in the script and the documents, and the version CI installs, two different datasources), lock file maintenance is scheduled, and `make renovate-check` passes through the container.
A group with a single update that week is titled by that dependency ("Update axllent/mailpit Docker tag to v1.34.0" and not "dev tool images").

The second look (20 November, after the hook change): a Postgres 19 major waits under *Pending Approval* (one entry for all nine places it is pinned) while the 18.x updates are in the data store group;
`renovate 44.256.1`, published that morning, is under *Pending Status Checks* and `numpy 2.5.5`, published five days earlier, under *Awaiting Schedule*: the 3-day wait works (publication dates checked on npm and PyPI).
Hurl 8.1.0, Toxiproxy 2.13.0, Kafka UI 1.5.0, `actions/*` v7 and `setup-k6-action` 1.3.0 are listed under Detected Dependencies with no update, and the release tags on GitHub show they are the latest, so there was nothing to find.
The Dockerfile `apk add` packages (`socat`, `nodejs`, `npm`) are listed with the version `undefined`: they are not pinned (hadolint's DL3018 is ignored on purpose), so there is nothing to update.

Not verified: that the app turns these into pull requests (the schedule is Monday before 08:00 UTC, so none existed yet) and that CI passes on them.
