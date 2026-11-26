# 0018. Pin every version, and let Renovate propose the updates

- Status: Accepted
- Date: 2026-11-20

## Context

The repository pins everything: container images, GitHub Actions, npm and pip packages, pre-commit hooks, the Hurl and k6 versions that CI installs. Pinned means reproducible; it also means that nobody notices
the Keycloak security release, the Postgres patch or the action that stopped working on a new runner image until something breaks ([RENOVATE](../RENOVATE.md)). Updates have to come without a person remembering to look.

## Decision

The hosted **Renovate** GitHub App reads the pins and opens pull requests; CI is the test. The configuration is [`.github/renovate.json5`](../../.github/renovate.json5), with a comment on every rule. Its policy:

- One batch a week (Monday before 08:00 UTC, at most 10 open pull requests), and things that must move together are one pull request: the observability images, Confluent Platform, the data store images, k6 (the image and the CI binary), Hurl, the npm and pip tooling, the hooks.
- **Major versions wait** on the Dependency Dashboard until someone ticks them (a new Postgres, Elasticsearch, Keycloak, Kafka or Grafana major changes data formats or configuration). Exceptions: GitHub Actions, and Silo, whose date version is not a major. The Python image of the seed build also waits for a minor, because CI does not build it.
- npm and PyPI releases younger than 3 days are not taken; the lock file is refreshed monthly; nothing is merged automatically; commit messages are plain.
- Pins that no built-in manager can read (images in shell scripts, Python generators, documents, versions in workflow inputs) are found by regular-expression managers or by a `# renovate:` annotation, so the same image in a script and in a compose file is one dependency.

## Consequences

- `make renovate-check` validates the configuration strictly (Node 24.11+ or Docker) and CI runs it. Renovate's regular expressions use the RE2 engine, which has no lookahead or lookbehind.
- A weekly batch needs a reviewer; with `ci / ok` required, a pull request can only be merged green. Updates of Mongo, Elasticsearch, Kafka and Silo are not started by CI (only by `make up-apps` on a developer machine), so those pull requests need a manual try.
- A pin written in a new place must look like one of the patterns or carry an annotation, or Renovate cannot see it.
- Self-hosting Renovate instead of the hosted app is possible with the same file and a token; it is not set up here because it needs a secret that only the owner can create.

## Alternatives considered

Dependabot is not used for version updates; its security alerts can be switched on next to Renovate. Updating by hand, which is how the stale pins described in the document accumulated.
