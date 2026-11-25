# Continuous integration

GitHub Actions workflows in `.github/workflows/`. They run the same `make` targets you run on your machine, so a red pipeline
can be reproduced locally with one command. Nothing in them depends on a programming language: a service is "any folder with a
Dockerfile that passes [SERVICE-SPEC.md](SERVICE-SPEC.md)".

| Workflow | When | What |
|---|---|---|
| `ci.yml` | every pull request, push to `master` | the jobs below; the single check to require is the job **`ok`** (shown as `ci / ok`); the ruleset that requires it is applied from `.github/rulesets/master.json`, see [REPOSITORY.md](REPOSITORY.md) |
| `service.yml` | called by `ci.yml` once per implementation (also callable from your own workflow) | build one implementation, start it with the infrastructure, `make conformance` |
| `system.yml` | push to `master`, nightly 03:17 UTC, manually | all four real services and the gateway: `make e2e-all` (README 4.1 flows, then gateway checks) |

## Jobs of `ci.yml`

| Job | Runs | Local equivalent |
|---|---|---|
| `static` | the pre-commit hooks on every file (whitespace, YAML/JSON syntax, private keys, shellcheck, actionlint, hadolint; the `wh-*` hooks are skipped because the checks below are the same commands, see [PRE-COMMIT.md](PRE-COMMIT.md)); compose files for every profile, shell syntax, Hurl formatting, generated gateway error mappers; cross-checks of OpenAPI/GraphQL/Avro/proto/i18n/gateway against each other and the README; Spectral, buf lint, Avro and GraphQL conventions; the seed data is up to date and valid against the Mongo/Elasticsearch/Redis schemas; the Bruno collection is up to date with the contracts and the seed data; the Grafana dashboards are valid (structure, datasources, PromQL syntax); the failure-injection config (Toxiproxy proxies and compose overlay) is up to date and fits the compose file and the scenarios, and the overlay merges with the compose file; the load-test overlay too, and the raised gateway limits can still be derived from `envoy.yaml`; the same for the HTTPS gateway config (both variants, with and without the https issuer), and both HTTPS compose overlays merge with the compose file; the Renovate configuration is valid (`make renovate-check`, [RENOVATE.md](RENOVATE.md)); the architecture decision records are well formed, linked and indexed, and the checker still catches what it should (`make adr-check adr-selftest`, [adr/README.md](adr/README.md)); the Markdown links, anchors, `make` targets named in the text and the documentation map are consistent (`make docs-check docs-selftest`, [README.md](README.md)); the files that configure the GitHub repository agree with `ci.yml` and the issue templates (`make github-check github-selftest`, [REPOSITORY.md](REPOSITORY.md)); the Helm values are generated from the compose file and the cluster names fit `envoy.yaml` (`make k8s-check`), and the chart passes `helm lint --strict`, `helm template` and kubeconform for every values file (`make k8s-lint`, [KUBERNETES.md](KUBERNETES.md)) | `make lint check-contracts contracts-lint seed-check bruno-check dashboards-check chaos-check load-check https-check renovate-check adr-check adr-selftest docs-check docs-selftest github-check github-selftest k8s-check k8s-lint` and `make precommit` |
| `seed` | a Postgres service container: the canonical schema, then `seed/out/account.sql` and `media.sql` twice (CHECK constraints hold, the second load adds nothing) | `make seed-test-sql` |
| `breaking` (pull requests) | `contracts/` against the point where the branch left its base branch: oasdiff, `buf breaking`, Avro BACKWARD compatibility, GraphQL breaking changes | `make contracts-breaking BASE=$(git merge-base origin/master HEAD)` |
| `gateway` | `make up-mocks` (Envoy, Keycloak, Redis, Prism mocks, about 2 GB), `make e2e`, a k6 smoke test (`make load-run P=smoke SKIP=graphql`, every user journey once through the gateway), then `make conformance-selftest`: the conformance suite must pass the reference stub as all four services and catch five deliberately broken ones | `make up-mocks e2e conformance-selftest` and `make load-run P=smoke SKIP=graphql` |
| `kubernetes` | Keycloak and Redis in Compose, the gateway and the four Prism mocks in a kind cluster on the runner (`make k8s-up-mocks`, about 2 GB), `make k8s-net` (a probe pod reaches Compose by name), then `make e2e` through the cluster; the cluster's logs are uploaded when it fails | `make k8s-up-mocks k8s-net e2e k8s-down` (needs kind, kubectl, helm) |
| `detect` + `services` | one `service.yml` run per `services/<service>/<impl>/Dockerfile` (account, media, catalog, notification). On a pull request only the implementations whose folder changed run, unless `contracts/`, `infra/`, `conformance/`, `scripts/`, `tools/`, the `Makefile` or `.github/` changed: then all of them | `make conformance SVC=<service>` against `make up-obs` and the service started from your implementation |
| `ok` | fails if any job failed or was cancelled; skipped jobs are fine (no implementation yet, not a pull request) | |

Two implementations of the same service (for example `services/account/java-spring` and `services/account/go`) are both built and tested,
each against its own copy of the stack. That is the point of the polyglot template: the same pipeline holds every language to the same spec.

## What `service.yml` does for one implementation

1. `<SERVICE>_DIR` is pointed at the implementation (the compose file builds from it).
2. `make up-obs` (infrastructure, schemas, Grafana/Loki/Tempo/Prometheus/Alloy), then the service alone with `docker compose up -d --build --no-deps <service>`.
3. `make conformance SVC=<service> ARGS="--lifecycle"`: health endpoints, authentication, errors and localization, JSON logs, traces/logs/metrics arriving in Tempo, Loki and Prometheus, fail-fast configuration, graceful shutdown.
4. On failure the logs of every container are uploaded as the artifact `logs-<folder>`.

Inputs: `lifecycle` (default true), `telemetry` (default true: with `false` the observability stack is not started and T1-T3 are skipped), `runner` (default `ubuntu-latest`).
To call it from a workflow of your own: `uses: ./.github/workflows/service.yml` with `service:` and `dir:`.

## Set-up

1. Push the repository to GitHub, enable Actions.
2. Protect `master`: `make github-apply` applies the ruleset that requires the status check `ok` (shown as `ci / ok`), squash merges and linear history, and the rest of the repository settings ([REPOSITORY.md](REPOSITORY.md)). By hand: Settings > Rules > Rulesets.
3. For `system.yml`, set repository variables (Settings > Secrets and variables > Actions > Variables) when your implementations are not in `services/<service>/java-spring`: `ACCOUNT_DIR`, `MEDIA_DIR`, `CATALOG_DIR`, `NOTIFICATION_DIR` (for example `services/account/go`). While a service has no Dockerfile the job ends with a notice instead of failing.
4. No secrets are needed: every credential in the stack is a local default from `infra/.env.example`.

## Runner size

GitHub's standard Linux runner has 4 CPU and 16 GB for public repositories and 2 CPU and 7 GB for private ones (check the current figures for your plan).

| Stack | Memory | Fits 7 GB | Fits 16 GB |
|---|---|---|---|
| `gateway` job (mocks) | about 2 GB | yes | yes |
| `service.yml` with `telemetry: false` | about 5 GB plus the service | yes, tight | yes |
| `service.yml` with telemetry | about 6.5 GB plus the service | no | yes |
| `system.yml` (all services) | about 8 GB | no | yes |

On a private repository use a larger runner for those: set `runner:` in the `services` job of `ci.yml` and the repository variable `CI_RUNNER_APPS` for `system.yml`, or pass `telemetry: false`.

## Not included, on purpose

- Building and pushing images to a registry, deployments: they depend on where you run the services. Add them as further jobs that `needs` the jobs above.
- Another CI system: the workflows are thin wrappers around `make`; a GitLab or Jenkins pipeline calls the same targets (`make lint check-contracts contracts-lint`, `make contracts-breaking BASE=...`, `make up-mocks e2e conformance-selftest`, `make conformance SVC=...`).
- Caching of Docker layers and images: the first run of a job pulls about 3 GB of images. Add a registry mirror or `docker/setup-buildx-action` with the GitHub cache when pull time hurts.

## Runner image and Hurl

The workflows run on `ubuntu-26.04` and Python 3.15.2 / Node 24. The Hurl binary needs `libxml2.so.2`, which Ubuntu 26.04 no longer ships (only `libxml2.so.16`),
so every job that installs Hurl has a step that installs `libxml2-16` and links it under the old name when it is missing. The default branch is `master`.
