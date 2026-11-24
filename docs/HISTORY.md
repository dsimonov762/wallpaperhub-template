# History: how the project got here, and why

This is the story, in the order it happened. **What exists now** is in [STATUS.md](STATUS.md); **why a particular choice was made** is in its [ADR](adr/README.md) (linked below); this file connects them and records what we learned by running things.
Append a line when you finish work, never rewrite earlier lines. Dates are given only where they are known: the design (README v1.1) is dated 2026-11-08, ADRs 0001 to 0019 were written on 2026-11-20, Kubernetes and ADRs 0020 and 0021 on 2026-11-23, this documentation pass on 2026-11-24.

## The idea

Wallpaper Hub is an educational, language-agnostic reference: one system (a wallpaper-sharing platform with four domain services and a gateway) that can be implemented in many languages and frameworks, to compare how each solves the same problems and to be reused as a template and a cheat sheet.
The domain is incidental; the point is coverage: REST, gRPC, GraphQL, Kafka with Avro, a transactional outbox, PostgreSQL, MongoDB, Elasticsearch, Redis, S3, SSE and WebSocket, email, OpenTelemetry, resilience patterns.

## How we work

- **Design first, then contracts, then environment, then services.** The README (v1.1, 2026-11-08) is the design. Everything else grew from it in the order below. No service was written before the environment that would test it ([ADR 0001](adr/0001-contract-first-with-a-shared-contracts-folder.md)).
- **The owner works on Windows 11 with Docker Desktop (WSL2).** The AI agent that did most of the building works in a Linux sandbox **without a Docker daemon**. So the agent delivers `git apply` patches, the owner runs them on a real machine and in GitHub Actions, and sends back failures (often as a patch of his own fixes, which are then adopted, not reverted).
- **Honesty about verification** became a rule because of that split: every delivery says what ran for real, what ran against stand-ins, and what did not run at all. The three levels (*Confirmed*, *Sandbox*, *Design only*) are defined in [STATUS.md](STATUS.md#verification-levels-used-in-this-file).
- **Each tool is pinned and each check is a `make` target** so the same command runs on the laptop, in a hook and in CI ([ADR 0017](adr/0017-every-check-is-a-make-target-ci-is-the-gate-and-hooks-are-a-shortcut.md), [0018](adr/0018-pin-every-version-and-let-renovate-propose-updates.md)).

## Phases

Each entry says what was built, why, and where to read more.

### 1. The design

The README: principles, architecture, the four services and the gateway, the key flows (upload, avatar change, outbox, real-time push), the contracts for REST, gRPC, GraphQL and Kafka, data stores, security, resilience matrix, background work, media pipeline, observability, a service's internal layout, repository layout, testing, stacks per language, a requirements matrix and a phase roadmap (0 to 6).
Nine decisions were taken there and later written up as ADRs 0001 to 0010: contracts in one shared folder, four services and a gateway, the outbox in account-service only and its JSON-then-Avro approach, SSE as the primary push with a one-time ticket, Redis as the notification database, OTLP metrics, database per service, tokens checked at the gateway and again in each service.

### 2. Contracts

The machine-readable source of truth in `contracts/`: OpenAPI for the four services (39 operations) plus shared Problem and pagination types, the gRPC `AccountService`, seven Avro events with BACKWARD compatibility, the GraphQL schema, the i18n bundles (en, de, es) and the database schemas.
*Why first:* every later piece (mocks, the gateway tests, the Bruno collection, the conformance suite, the seed data) is derived from them, and different languages can only be compared if they implement the same thing ([ADR 0001](adr/0001-contract-first-with-a-shared-contracts-folder.md)).

### 3. The infrastructure in Compose, and the gateway

All stores, Kafka with Schema Registry, Keycloak with an imported realm, an S3-compatible store and a mail catcher, in Compose profiles so a developer starts only what the task needs (`make up-mocks` about 2 GB, `make up-apps` about 8 GB on a 16 GB machine).
The gateway is an **Envoy configuration, not a program** ([ADR 0011](adr/0011-the-gateway-is-an-envoy-configuration.md)): routing, JWT validation, CORS, rate limiting, problem+json errors in the caller's language, request ids, body limits.
Because the services do not exist yet, Prism mocks generated from the OpenAPI files stand in for them, which lets the gateway be developed and tested first (`make e2e`). The local S3 is PGSTY Silo, a MinIO fork ([ADR 0019](adr/0019-pgsty-silo-as-the-local-s3.md)).

### 4. What a service is: the specification and the conformance suite

[SERVICE-SPEC.md](SERVICE-SPEC.md) states from the outside what any service in any language must do (ports, health, configuration, authentication, error format, logs, telemetry, shutdown, image) with 23 numbered checks;
`conformance/` verifies them against a running service. It was tested against a **reference stub with 13 deliberate violations**, so that each check is known to be able to fail ([ADR 0012](adr/0012-conformance-suite-defines-what-a-service-is.md)).
*Why:* implementations in ten languages must be interchangeable behind the same gateway, Prometheus and Kubernetes probes. "A service is any folder with a Dockerfile that passes the spec."

### 5. The inner loop: host mode, contract tooling

Host mode (`make host SVC=...`) replaces one service's container with a forwarder to the process in the IDE, so the developer debugs one service while everything else runs in Docker.
Contract tooling runs lint (Spectral, buf, Avro and style rules), breaking-change detection (oasdiff against a base branch; no override flag), and code generation, all in pinned containers so that nothing but Docker is needed.

### 6. CI

GitHub Actions: `static` (every check that needs no containers), `seed`, `breaking`, `gateway` (the e2e suite through real Envoy with mocks), `kubernetes`, a detect-and-matrix pair that builds and tests every `services/<name>/<impl>/` that has a Dockerfile, and a single required check `ok`.
`service.yml` is one implementation's pipeline, `system.yml` the nightly full-stack run. Neither has run with a real service yet. Deliberately not included: building and pushing images ([CI.md](CI.md#not-included-on-purpose)).

### 7. Data and daily tools

Seed data (12 users, 30 wallpapers and everything that hangs on them, in every store) with reset and reseed; a tools profile (Kafka UI, Adminer, Mongoku); a token helper and a generated Bruno collection with one environment per seeded user.
Generated outputs are committed and checked for staleness ([ADR 0016](adr/0016-generated-files-are-committed-and-checked-for-staleness.md)): it keeps diffs reviewable and makes "forgot to regenerate" a CI failure instead of a surprise.

### 8. Operating it: dashboards, failure injection, load, HTTPS

Seven provisioned Grafana dashboards and a metric contract ([OBSERVABILITY.md](OBSERVABILITY.md)); Toxiproxy between every service and its dependencies with eleven scenarios generated from one edge file ([ADR 0015](adr/0015-failure-injection-with-toxiproxy-from-one-edge-file.md), [CHAOS.md](CHAOS.md));
k6 journeys in seven profiles with a latency budget per operation, run through a gateway variant with relaxed rate limits ([ADR 0013](adr/0013-local-gateway-variants-are-generated-from-envoy-yaml.md), [LOAD.md](LOAD.md));
opt-in local HTTPS with mkcert, plain HTTP inside the network ([ADR 0014](adr/0014-local-https-with-mkcert-opt-in-and-plain-http-inside.md), [HTTPS.md](HTTPS.md)).
These were built against mocks and the reference stub; the chaos scenarios and the load budgets have **not** met a real service.

### 9. Team hygiene: hooks, Renovate, ADRs

Pre-commit hooks (file checks, shellcheck, actionlint, hadolint and 13 `wh-*` hooks that call the repo's own checks); a hook that needs Docker or Node **skips with a note** when it is missing, so a commit is never blocked by a missing tool, and CI stays the gate ([PRE-COMMIT.md](PRE-COMMIT.md)).
Renovate keeps every pin current, with majors waiting for approval ([RENOVATE.md](RENOVATE.md)). The decision records were written in one pass (0001 to 0019, 2026-11-20) with a checker that enforces form, numbering and links ([adr/README.md](adr/README.md)).

### 10. Kubernetes (2026-11-23)

One generic Helm chart for all five deployables with values **generated from the compose file**, so that Compose stays the single place where a service's configuration is written ([ADR 0020](adr/0020-one-generic-helm-chart-for-every-service-with-values.md));
a local kind cluster with the infrastructure left in Compose and the cluster node attached to its network, so no variable changes between the two ([ADR 0021](adr/0021-the-local-cluster-is-kind-with-the-infrastructure-left-in.md)). See [KUBERNETES.md](KUBERNETES.md).
It was written in a sandbox without Docker or Helm and then run by the owner: the real run found three problems, listed below.

### 11. Documentation for parallel work (2026-11-24)

This pass: [STATUS.md](STATUS.md), [ROADMAP.md](ROADMAP.md) (work packages with exclusive lanes), [../AGENTS.md](../AGENTS.md) (rules), the [map](README.md), this history, and `make docs-check`.
*Why:* the template phase was finished and the next work (four services in perhaps several languages) is parallel by nature. Several people or AI dialogs have to be able to take one package each, understand the project without reading each other's code, and merge in any order.

## Lessons from running it for real

| What happened | Cause | What changed |
|---|---|---|
| Container scripts failed with `\r` / "no such file" on Windows | Git converted line endings to CRLF | `.gitattributes` forces LF; `make doctor` checks it; clone into the WSL filesystem |
| Hurl failed to start on the CI runner (`libxml2.so.2` missing) | Ubuntu 26.04 ships only `libxml2.so.16` | a step installs it and links the old name ([CI.md](CI.md)) |
| Hooks blocked commits on machines without Docker or Node | the hooks assumed their tools | hooks skip with a note when a tool is missing; CI stays the gate |
| The Envoy container in the cluster crashed at start | its entrypoint `chown`s a directory, which fails when every capability is dropped | `ENVOY_UID: "0"`: root, but without capabilities, documented in [STATUS.md](STATUS.md#known-limitations-of-what-exists) |
| Mocks in the cluster were never ready | Kubernetes' startup probe asks `/health/startup`, which the mock did not answer | the mock answers it (the owner's fix, adopted) |
| `scripts/k8s.sh` could not find its Python packages; the `infra` image build was missing a profile | the validation virtualenv was not used; build without `--profile infra` | the script uses `.venv-validate` and builds with `--profile infra` (the owner's fixes, adopted) |
| Renovate's first run | every pin needs to be visible to it | the annotation convention in [RENOVATE.md](RENOVATE.md); a k6 update later went through branch, PR, CI and merge on its own |

**Pattern:** what a sandbox can verify (renderers, schemas, generated files, scripts against stand-ins) is verified there; what depends on the real Docker, kernel, runner image or cluster is found by the owner's first run. Expect the first real service to find a similar handful of problems in `e2e/system/*.hurl`, the latency budgets and the chaos scenarios, and treat them as normal.

## Log

Append one line per finished piece of work, newest last: date, package or topic, one sentence, link to the ADR or the document if there is one.

- 2026-11-08: README design v1.1.
- 2026-11-20: ADRs 0001 to 0019 written; the checker `make adr-check` in CI.
- 2026-11-23: Kubernetes: Helm chart, kind cluster, CI job, ADRs 0020 and 0021. Confirmed on the owner's machine and in CI in mocks mode.
- 2026-11-24: documentation for parallel work: STATUS, ROADMAP, AGENTS, docs map, HISTORY, `make docs-check`.
