# Project status

**As of 2026-11-24.** Update this file in the same change as the work it describes (see [How to keep this file true](#how-to-keep-this-file-true)).
For the story of how it got here see [HISTORY.md](HISTORY.md); for what is left and how to cut it into independent pieces see [ROADMAP.md](ROADMAP.md);
for the rules of working on it (also with several AI agents at once) see [../AGENTS.md](../AGENTS.md).

## In one paragraph

Wallpaper Hub is a polyglot microservice reference project: four domain services (account, media, catalog, notification) and an API gateway, specified by
[README.md](../README.md) (design v1.1, 2026-11-08). **The design, the contracts and the whole local development environment are done and run on the owner's machine
(Windows 11, Docker Desktop with WSL2) and in GitHub Actions. No domain service is implemented yet:** `services/` holds the Envoy gateway and a Prism mock, nothing else.
Everything a service needs in order to be developed, tested, observed, load-tested, broken on purpose and deployed to a local Kubernetes cluster exists and
is exercised by CI with mocks and a throwaway reference stub. The next step is the first real service ([ROADMAP.md](ROADMAP.md), WP-S1).

## Verification levels used in this file

| Level | Meaning |
|---|---|
| **Confirmed** | the owner ran it on his machine and/or it runs green in GitHub Actions |
| **Sandbox** | run for real with the real tool by an AI agent in a Linux sandbox without a Docker daemon, never confirmed on the owner's machine |
| **Design only** | specified in a document or a contract, no code runs it yet |

Nothing is marked "done" in this file without one of the first two.

## What exists

### Design and contracts (the source of truth)

| Area | State | Where |
|---|---|---|
| Architecture, scenarios, resilience matrix, data model, security, observability design | **Done** (v1.1) | [README.md](../README.md) |
| 22 decision records (9 from the README's decision log, 13 about principles, tooling and the repository) | **Done**, [index](adr/README.md); `make adr-check` is a CI gate | [adr/](adr/README.md) |
| OpenAPI for the four services (39 operations), shared `common.yaml` (Problem, pagination) | **Confirmed**: linted (Spectral), breaking-change checked (oasdiff), served by Prism, TypeScript generation compiles | `contracts/openapi/` |
| gRPC `AccountService`, 7 Avro events (BACKWARD compatible), GraphQL SDL, i18n bundles en/de/es, DB schemas (Postgres, Mongo, Elasticsearch, Redis) | **Confirmed**: `make check-contracts contracts-lint`, schemas applied by `make schemas` | `contracts/` |
| What a service must do from the outside (ports, health, config, auth, errors, logs, telemetry, shutdown, image) | **Done**, 23 checks have IDs | [SERVICE-SPEC.md](SERVICE-SPEC.md) |

### Local environment

| Capability | State | Entry point | Doc |
|---|---|---|---|
| Whole infrastructure in Compose profiles: PostgreSQL x3, MongoDB, Redis x2, Kafka + Schema Registry, Elasticsearch, Keycloak (realm imported), S3 (PGSTY Silo), Mailpit | **Confirmed** | `make up` | [GETTING-STARTED](GETTING-STARTED.md) |
| Gateway: Envoy configuration (routing, JWT, CORS, rate limit, problem+json, request ids, body limits) and four contract-generated Prism mocks | **Confirmed** | `make up-mocks`, `make e2e` | [Envoy cheatsheet](../services/gateway/envoy/CHEATSHEET.md) |
| Observability: Alloy, Loki, Tempo, Prometheus, Grafana with 7 provisioned dashboards | **Confirmed** | `make up-obs` | [OBSERVABILITY](OBSERVABILITY.md) |
| Conformance suite: checks any running service against the spec (health, auth, errors, i18n, logs, traces/logs/metrics arriving, fail-fast, graceful shutdown); tested against a reference stub with 13 deliberate violations | **Confirmed** (against the stub; **never against a real service**) | `make conformance SVC=account` | [conformance/README](../conformance/README.md) |
| Host mode: run one service from the IDE, the rest in Docker | **Confirmed** | `make host SVC=account` | [GETTING-STARTED](GETTING-STARTED.md) |
| Contract tooling: lint, breaking-change detection, code generation | **Confirmed** | `make contracts-lint contracts-breaking codegen` | [GETTING-STARTED](GETTING-STARTED.md#contract-tooling) |
| Seed data (12 users, 30 wallpapers, ... in every store), reset, reseed | **Confirmed** | `make seed reset reseed` | [seed/README](../seed/README.md) |
| Tools profile: Kafka UI, Adminer, Mongoku | **Confirmed** | `make up-tools` | [GETTING-STARTED](GETTING-STARTED.md#web-uis-for-the-stores) |
| Token helper and Bruno collection (one request per operation, one environment per seeded user) | **Confirmed** | `make token`, `make bruno-run` | [bruno/README](../bruno/README.md) |
| Failure injection: Toxiproxy between every service and its dependencies, 11 scenarios | **Confirmed** (against mocks; **no real service has been broken yet**) | `make up-chaos`, `make chaos-run` | [CHAOS](CHAOS.md) |
| Load tests: k6 journeys, 7 profiles, latency budget per operation | **Confirmed** (smoke in CI); the **budgets are untested guesses** | `make up-load`, `make load-run` | [LOAD](LOAD.md) |
| Local HTTPS with mkcert (opt-in) | **Confirmed** | `make certs`, `make up-https` | [HTTPS](HTTPS.md) |
| Kubernetes: one generic Helm chart, generated values per service, local kind cluster, CI job | **Confirmed in mocks mode** (cluster, pods, DNS to Compose, e2e through the cluster); real-services mode **never run** | `make k8s-up-mocks`, `make k8s-up-apps` | [KUBERNETES](KUBERNETES.md) |

### Automation and hygiene

| Capability | State | Doc |
|---|---|---|
| GitHub repository as code: About text and topics, ruleset on `master` (pull request, check `ok`, squash only), tag protection, secret scanning + push protection, Dependabot alerts, CodeQL, read-only Actions token, environments `staging`/`production`, labels, issue forms, PR template, CODEOWNERS, LICENSE (MIT), CONTRIBUTING, SECURITY; applied by `make github-apply` | **Sandbox**: the files are checked (`make github-check`) and the 68 requests of a full run validate against GitHub's published API description; **no request has been sent to GitHub yet**. Becomes Confirmed after the owner's first `make github-apply` | [REPOSITORY](REPOSITORY.md) |

The rest of this section is confirmed:

| Capability | State | Doc |
|---|---|---|
| CI on GitHub Actions: `static`, `seed`, `breaking`, `gateway`, `kubernetes`, `detect` + `services`, `ok` (the one required check); `service.yml` (one implementation), `system.yml` (nightly, all services) | **Confirmed green**; `service.yml` and `system.yml` have **never run with a real service** (no Dockerfile, so they skip) | [CI](CI.md) |
| Pre-commit hooks: file checks, shellcheck, actionlint, hadolint and 15 `wh-*` hooks that run the repo's own checks; skip gracefully without Docker or Node | **Confirmed** | [PRE-COMMIT](PRE-COMMIT.md) |
| Renovate: every pin of the repository (images, actions, npm, pip, hooks, tool versions), grouped updates, majors wait for approval | **Confirmed**: dashboard seen, a k6 update went through branch, PR, CI and merge | [RENOVATE](RENOVATE.md) |
| 78 `make` targets; every check is one, CI calls the same ones | **Confirmed** | `make help` |
| Generated files are committed and checked for staleness (gateway error mappers, Bruno collection, chaos config, load-test and HTTPS gateway variants, seed output, Grafana dashboards, Helm values, ADR index) and the documentation itself (`make docs-check`: links, anchors, `make` targets named in the text, the documentation map) | **Confirmed** for all but `docs-check`, which is **Sandbox** until its first CI run | [ADR 0016](adr/0016-generated-files-are-committed-and-checked-for-staleness.md) |

## What does not exist yet

| Gap | Why it matters | Planned as |
|---|---|---|
| **The four domain services** (`services/<name>/<impl>/`), in any language | Nothing behind the gateway but mocks. `make up-apps`, `make e2e-system`, `make k8s-up-apps`, `service.yml`, `system.yml`, the chaos scenarios against real services and the load test against real services have **never run** | [WP-S1 to S4](ROADMAP.md#services) |
| A service scaffold / golden path per language | The conformance suite says what a service must do; nothing generates a service that does it | [WP-S0](ROADMAP.md#wp-s0-first-language-and-the-service-scaffold) |
| A gRPC mock of `AccountService` and an event emitter for the Kafka topics | Catalog and notification depend on account (gRPC) and on events; today they cannot be developed without a running account service | [WP-T1](ROADMAP.md#wp-t1-grpc-mock-for-accountservice), [WP-T2](ROADMAP.md#wp-t2-event-emitter) |
| Inner-loop tooling: `.editorconfig`, devcontainer, IDE run configurations, hot-reload guidance | Every developer builds this alone otherwise | [WP-D1](ROADMAP.md#wp-d1-developer-inner-loop) |
| Security scanning in CI beyond what GitHub's settings give (secret scanning, CodeQL, alerts): images, dependency review, licenses, SBOM | | [WP-X1](ROADMAP.md#wp-x1-security-scanning) |
| Build and publish images, versioning, environments, promotion, deployment pipeline | The chart is proven locally only; CI deliberately does not build or push ([CI](CI.md#not-included-on-purpose)) | [WP-C1](ROADMAP.md#wp-c1-release-and-deployment) |
| Alert rules, SLOs, runbooks; a secrets story for real environments | Dashboards exist, nobody is paged | [WP-O1](ROADMAP.md#wp-o1-alerts-slos-runbooks), [WP-O2](ROADMAP.md#wp-o2-secrets-for-real-environments) |
| Web client | The `web-spa` Keycloak client and the CORS origins 5173 and 4200 are prepared | [WP-W1](ROADMAP.md#wp-w1-web-client-optional) |
| Hand-written gateway (the README's second gateway mode); shared rate-limit counters | README 3.1; see known limitations | [WP-G1](ROADMAP.md#wp-g1-gateway-follow-ups) |

## Decisions that are still open

| # | Question | Today |
|---|---|---|
| D-1 | **Which language implements the first service (account)?** | `infra/.env.example` defaults to `services/<name>/java-spring`, but the owner has not chosen. It decides which scaffold WP-S0 produces |
| D-2 | **How does a service repository use this template?** The owner is going to create a separate repository for the first service (one per language and framework). The template stays the source of the contracts, the service specification, the conformance suite, the infrastructure and the tools | Not designed. Options: the service repository pins a template tag (`v0.1.0`, [REPOSITORY](REPOSITORY.md#tags-and-releases)) in a file and a script checks it out into an ignored folder, so `make` targets and contracts are read from there; a git submodule; or copying the needed folders. It decides what [WP-S0](ROADMAP.md#wp-s0-first-language-and-the-service-scaffold) builds and whether `service.yml` lives here or there |
| D-3 | Is a web client part of this template? | Optional, not started |
| D-4 | Which registry and environments for publishing images? | Not decided; blocks WP-C1 |

A decision that is made becomes an [ADR](adr/README.md) (`make adr-new`) and its row here is removed.

## Known limitations of what exists

- **Nothing has run against a real service.** Every assertion in `e2e/system/*.hurl` describes the contract and has never run against an implementation: expect to adjust them with the first service. The k6 latency budgets are guesses.
- **Gateway rate limits** are per client but live in each gateway instance's memory, so they multiply with the number of instances and reset on restart. Shared counters need Envoy's global rate limit service. Only 401, 404, 413, 429 and 502-504 are localized by the gateway.
- **Gateway readiness follows its upstreams** (`/health` is 200 only while every upstream is healthy): when one service is down the gateway leaves a Kubernetes Service and all routes answer 503. Same behaviour in Compose.
- **Envoy runs as root without capabilities** in the container (`ENVOY_UID: "0"`: its entrypoint otherwise tries to `chown`, which fails when every capability is dropped). A cluster that forbids root needs another setup ([KUBERNETES](KUBERNETES.md#what-is-verified-what-is-not)).
- **Kubernetes:** the infrastructure stays in Compose and the kind node is attached to its network; Compose recreating that network detaches the node (`make k8s-up-...` attaches it again, `make k8s-net` tells). The chart is a template, not a production deployment: development secrets are the defaults.
- **Memory:** the full stack does not fit a 16 GB machine comfortably. Profiles exist for that reason: `make up-mocks` about 2 GB, `make up` about 5 GB, `make up-obs` about 6.5 GB, `make up-apps` about 8 GB ([GETTING-STARTED](GETTING-STARTED.md#2-first-start---in-this-order)).
- **Windows and WSL2** are the developed-on platform. Clone into the WSL filesystem; CRLF breaks container scripts (`.gitattributes` forces LF). macOS and native Linux are expected to work and have not been tried.

## How to keep this file true

- Whoever finishes a work package of [ROADMAP.md](ROADMAP.md) edits **this file in the same change**: move its row from *What does not exist yet* to *What exists* with a verification level, change the date at the top, and add one line to [HISTORY.md](HISTORY.md).
- Never write "done" for something nobody ran. Use **Sandbox** or **Design only** and say what is missing. The project's convention is to end every delivery with *what was verified and what was not*.
- A decision goes to an ADR; an open question goes to *Decisions that are still open*; a limitation goes to *Known limitations*.
