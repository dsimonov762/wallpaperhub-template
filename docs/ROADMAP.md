# Roadmap: what is left, cut into independent work packages

The design (README, section 17) has seven phases. Phase 0 and the tooling around it are finished ([STATUS.md](STATUS.md), [HISTORY.md](HISTORY.md)). What is left is cut here into **work packages** (WP) so that
one person, or one AI agent in a fresh dialog, can take a package, work in its own folders, and finish it without reading or touching the code of another package. The rules for doing that are in [../AGENTS.md](../AGENTS.md).

Status of every package: **open** unless a line in [STATUS.md](STATUS.md) says otherwise. Sizes are rough: S = a day or less, M = a few days, L = about a week or more.

## Map

| WP | Package | Size | Needs first | Can run in parallel with |
|---|---|---|---|---|
| [S0](#wp-s0-first-language-and-the-service-scaffold) | First language and the service scaffold | M | decision D-1 | T1, T2, D1, R1, X1, O1 (gateway part), G1 |
| [S1](#wp-s1-account-service) | account-service | L | S0 | T1, T2, D1, R1, X1, G1 |
| [S2](#wp-s2-media-service) | media-service | L | S0 | S1, S3, S4 |
| [S3](#wp-s3-catalog-service) | catalog-service | L | S0, T1, T2 (or a running S1) | S1, S2, S4 |
| [S4](#wp-s4-notification-service) | notification-service | L | S0, T1, T2 (or a running S1) | S1, S2, S3 |
| [T1](#wp-t1-grpc-mock-for-accountservice) | gRPC mock for `AccountService` | S | nothing | everything |
| [T2](#wp-t2-event-emitter) | Event emitter for the Kafka topics | S-M | nothing | everything |
| [E1](#wp-e1-system-tests-and-the-phase-6-exercises) | System tests and the phase 6 exercises | M | S1 (grows with S2-S4) | |
| [D1](#wp-d1-developer-inner-loop) | Developer inner loop | S-M | nothing (better after S0) | everything |
| [R1](#wp-r1-repository-basics) | Repository basics | S | owner decisions (license, owners) | everything |
| [X1](#wp-x1-security-scanning) | Security scanning in CI | M | nothing | everything |
| [C1](#wp-c1-release-and-deployment) | Release and deployment | L | decision D-4, a service with a Dockerfile | |
| [O1](#wp-o1-alerts-slos-runbooks) | Alerts, SLOs, runbooks | M | gateway part: nothing; per service: S-packages | |
| [O2](#wp-o2-secrets-for-real-environments) | Secrets for real environments | S-M | C1 helps | |
| [G1](#wp-g1-gateway-follow-ups) | Gateway follow-ups | M | nothing | everything |
| [W1](#wp-w1-web-client-optional) | Web client (optional) | L | decision D-3, ideally S1 | |
| [L1](#wp-l1-more-languages) | More languages (README phase 6) | L each | S0 and the first implementation of that service | |

**Suggested order.** Now, in parallel: S0 (after D-1), T1, T2, R1, X1, D1, G1. Then S1 on its own until it is a walking skeleton through the whole pipeline (conformance, system flows for account, `make k8s-up-apps`), because it settles the patterns the others copy.
Then S2, S3 and S4 in parallel, E1 growing with each. C1, O1, O2 once a service image exists. W1 and L1 when wanted. The README's phase table (section 17) is the same sequence at a coarser grain.

## Lanes: who may change what

A package changes the files of its **lane**. Everything else is read-only for it. Files that every package may need are *shared*; the rule for them is in [AGENTS.md](../AGENTS.md#lanes-and-shared-files).

| WP | Lane (exclusive) | Shared files it touches, and how |
|---|---|---|
| S0 | `services/_template/**`, `scripts/new-service.sh` | `Makefile` (one target), `docs/` (a guide) |
| S1-S4 | `services/<name>/<impl>/**` | its own service block in `infra/docker-compose.yml` (environment only), then `make k8s-gen`; `conformance/services/<name>.env`; `infra/host/<name>.env`; `docs/STATUS.md` row |
| T1 | `services/_mock/**` | `infra/docker-compose.yml` (the `account-mock` block), `.github/workflows/ci.yml` (one step in `gateway`) |
| T2 | `tools/event-emitter/**` or `scripts/emit*` | `Makefile` (one target) |
| E1 | `e2e/system/**`, `e2e/run.sh`, `e2e/fixtures/**` | |
| D1 | `.devcontainer/**`, `.editorconfig`, `docs/ide/**` | `.gitignore` (un-ignore the shared IDE files; `.vscode/` and `.idea/` are ignored today) |
| R1 | `LICENSE`, `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/**`, `.github/CODEOWNERS` | `docs/CI.md` (branch protection) |
| X1 | `.gitleaks.toml` or similar, `scripts/security*`, `.trivyignore` | `.github/workflows/ci.yml` (new job), `.pre-commit-config.yaml` (hooks), `Makefile` |
| C1 | `.github/workflows/release.yml`, `deploy/helm/environments/**`, `docs/RELEASE.md` | `deploy/helm/service/**` (only for what environments need) |
| O1 | `infra/prometheus/rules/**`, `infra/grafana/**` (alert provisioning), `docs/runbooks/**`, `docs/SLO.md` | `infra/docker-compose.yml` (Alertmanager block, if chosen), `infra/prometheus/prometheus.yml` |
| O2 | `docs/SECRETS.md`, `deploy/helm/environments/**` (with C1) | |
| G1 | `services/gateway/**`, `scripts/gen-gateway-errors.py` | `contracts/i18n/**` (new keys, see the contract protocol), `e2e/gateway/**` |
| W1 | `web/**` | `infra/keycloak/realm-export.json` (only if the client needs a change: coordinate) |
| L1 | `services/<name>/<impl>/**` for the new `<impl>` | as S1-S4 |

Not in any package's lane, changed only through the **contract protocol** of [AGENTS.md](../AGENTS.md#changing-a-contract): `contracts/**`, `docs/SERVICE-SPEC.md`, `infra/keycloak/realm-export.json`, `conformance/http/**` and `conformance/checks/**`.

## Definition of done for every package

1. Everything the package adds is reachable from a `make` target, documented in the doc it belongs to (or a new one linked from [docs/README.md](README.md)), and covered by `make precommit` and CI. A check that only the author can run does not count.
2. `make lint check-contracts contracts-lint adr-check k8s-check` pass; generated files are regenerated, not edited.
3. A decision that has a plausible alternative has an ADR (`make adr-new`).
4. [STATUS.md](STATUS.md) has the new state with a verification level, and [HISTORY.md](HISTORY.md) one line.
5. The delivery message says **what was verified, how, and what was not** (the convention of the whole repository).

## Services

Common to S1-S4 and L1. A service is a folder `services/<name>/<impl>/` with a `Dockerfile`; CI finds it by that path ([CI.md](CI.md)).

**Develop against everything else mocked.** `make up-mocks` starts Keycloak, Redis, the gateway and the four mocks; `make host SVC=<name>` then stops the mock of your service and forwards its name to the process in your IDE ([GETTING-STARTED](GETTING-STARTED.md#develop-one-service-from-your-ide-host-mode)).
Add `make up` (the whole infrastructure) when the service needs its database, Kafka or S3. Nobody else's service has to exist.

**A service is done when:**
- `make conformance SVC=<name> ARGS="--lifecycle"` passes against the container built from the Dockerfile (health, authentication, errors, i18n, logs, telemetry, fail-fast, graceful shutdown: [SERVICE-SPEC.md](SERVICE-SPEC.md), checks `M1` to `S1`);
- the endpoints of its OpenAPI file behave as specified (unit and integration tests with Testcontainers, README section 14), and the `e2e/system` flows that involve it pass as far as the other services allow;
- the image listens on 0.0.0.0, runs as a non-root user, fits `mem_limit` (640 MB) and is built by `make up-apps`; its environment variables are the ones in its compose block (`make env-matrix`), and `make k8s-gen` and `make k8s-check` are clean;
- it has a `CHEATSHEET.md` mapping concept to file (README section 13), a formatter/linter/type check wired into its own CI step or Makefile target, and the internal layout of README section 12.

### WP-S0: first language and the service scaffold

- **Goal.** A scaffold so that a new service starts at "passes conformance" instead of at an empty folder. **Needs decision D-1** (the language): ask the owner; the default in `infra/.env.example` is `java-spring`.
- **Lane.** `services/_template/<impl>/` (the underscore keeps it out of CI's service detection) and `scripts/new-service.sh`; `make new-service SVC=account IMPL=java-spring` copies it to `services/account/java-spring/` with the names, ports and variables substituted.
- **Contains.** Bootstrap in the order of README section 12; typed config from environment variables that fails fast naming the variable (C1); the three management endpoints on 8081 (M1-M4); JWT validation against the JWKS with `iss`, `aud`, `exp`, `nbf`, `typ` (A1-A4); the problem+json mapper and localization from `contracts/i18n` (E1-E6); JSON logging with trace ids and no secrets (L1-L3); OpenTelemetry through OTLP (T1-T3); graceful shutdown (S1); a Dockerfile (non-root, honours the memory limit); formatter, linter and type check; unit-test layout; a `CHEATSHEET.md` skeleton.
- **Inputs.** [SERVICE-SPEC.md](SERVICE-SPEC.md), README sections 5.2, 5.3 and 12, `contracts/i18n`, `infra/docker-compose.yml` (environment), `conformance/`.
- **Done when.** Four scaffolded services (one per persona) pass `make conformance-all ARGS="--lifecycle"` with no domain code, in CI (`service.yml` runs them) and in `make k8s-up-apps`.
- **Note.** The reference stub in `conformance/reference-stub/` is a throwaway Python program that satisfies the spec; read it for the details of the checks, do not copy it.

### WP-S1: account-service

- **Goal.** README phase 1, "the template service": finish it completely before the others copy its patterns.
- **Lane.** `services/account/<impl>/**`.
- **Contains.** Config, HTTP, DTOs, mappers, validation, errors, i18n; PostgreSQL with ORM (the schema is `contracts/db-schema/postgres/account`, applied by `make schemas`; the service never owns local DDL, SERVICE-SPEC section 9); Redis cache-aside; the **gRPC server** of `contracts/proto/account/v1`; **transactional outbox and relay** (README 4.3, [ADR 0003](adr/0003-outbox-stores-json-and-serializes-avro-at-publish-time.md), [0004](adr/0004-transactional-outbox-only-in-account-service.md)), Avro producer with `acks=all`; registration through the Keycloak admin API; avatar/banner verification against media over REST with the caller's token; security in three layers; application-level audit (`audit_log`); soft delete and purge job; the metrics of README section 11.
- **Inputs.** `contracts/openapi/account.yaml`, `contracts/proto`, `contracts/avro/account.*`, `contracts/db-schema/postgres/account`, README 4.1-4.3, 5, 6.1, 7, 9; seed users in [../seed/CATALOG.md](../seed/CATALOG.md).
- **Needs of other services.** Media only (REST, mockable). Nothing else.
- **Done when.** The common definition above, plus: `e2e/system/10-account.hurl` and `40-avatar-ownership.hurl` pass; the outbox test (broker stopped, changes made, broker started: no event lost, none duplicated to business logic) passes; `make chaos-run S=postgres-down` and `S=redis-down` end in recovery without a restart; `make load-run P=load` keeps the account operations inside their budgets.

### WP-S2: media-service

- **Lane.** `services/media/<impl>/**`.
- **Contains.** Upload validation (magic bytes, pixel cap, never trust the extension), the image pipeline of README section 10 (EXIF strip, sRGB, SHA-256 and perceptual hash, blurhash, palette, variants), S3 (PGSTY Silo locally, [ADR 0019](adr/0019-pgsty-silo-as-the-local-s3.md)), Redis job queue with retries and dead letter, presigned URLs, orphan cleanup job (hourly, Redis lock), **database triggers** for the audit (the deliberate contrast with account), direct Kafka publish after commit (`media.asset.processed`, `.rejected`), consumer of `account.user.deleted`.
- **Inputs.** `contracts/openapi/media.yaml`, `contracts/avro/media.*`, `contracts/db-schema/postgres/media`, README 4.1 steps 4-5, 6.2, 9, 10.
- **Needs of other services.** None at runtime (it produces events and answers REST).
- **Done when.** The common definition, plus `e2e/system/30-media-rejection.hurl` and the upload steps of `20-wallpaper-lifecycle.hurl` pass; the upload profile of the load test (`make load-run P=uploads`) holds; `make chaos-run S=s3-down`.

### WP-S3: catalog-service

- **Lane.** `services/catalog/<impl>/**`.
- **Contains.** MongoDB (collections with `$jsonSchema` validators from `contracts/db-schema/mongo`), Elasticsearch search, autocomplete and facets with the degraded Mongo fallback, REST and **GraphQL** (`contracts/graphql`) with the DataLoader on `Wallpaper.author`, **gRPC client** to account (300 ms deadline, 2 retries, circuit breaker, fallback to the denormalized author snapshot), REST client to media (1 s, bulkhead of 20), Kafka consumers (`media.asset.processed`, `account.user.profile-updated`, `account.user.deleted`) with retry topics and DLQ, producer (`catalog.wallpaper.published`, `.moderated`), Redis cache and counters, trending job, counter flush, Mongo `bulkWrite` for author denormalization.
- **Inputs.** `contracts/openapi/catalog.yaml`, `contracts/graphql`, `contracts/proto`, `contracts/avro`, README 4.1 steps 6-9, 4.2, 5.5, 6.3-6.5, 8, 9.
- **Needs of other services.** Account over gRPC and the events of media and account: **WP-T1 and WP-T2** make them available without those services; a running S1 does the same.
- **Done when.** The common definition, plus the wallpaper lifecycle in `20-wallpaper-lifecycle.hurl` and the favorite/moderation flows; `make chaos-run S=account-down` (author snapshot fallback) and `S=elasticsearch-down` (degraded search) behave as README section 8 promises; the search journey stays in budget.

### WP-S4: notification-service

- **Lane.** `services/notification/<impl>/**`.
- **Contains.** **Redis as the primary database** ([ADR 0007](adr/0007-redis-as-the-primary-database-of-notification-service.md)): inbox, preferences, dedup; Kafka consumers with retry and DLQ; localized e-mail templates; two mail adapters (SMTP into Mailpit and an HTTP-API one) with failover; Redis-backed task queue; weekly digest job; **SSE** as the primary transport and WebSocket as the alternative ([ADR 0005](adr/0005-sse-as-the-primary-push-transport.md)), one-time stream ticket ([0006](adr/0006-one-time-ticket-authenticates-sse-and-websocket.md)), Redis Pub/Sub fan-out across instances, `Last-Event-ID` replay, heartbeat every 15 s, three connections per user; gRPC client to account; REST client to catalog.
- **Inputs.** `contracts/openapi/notification.yaml`, `contracts/avro`, `contracts/db-schema/redis`, README 4.4, 6.5, 8, 9.
- **Needs of other services.** The same as S3 (T1, T2).
- **Done when.** The common definition, plus: an event produced by T2 ends as an inbox entry, a Mailpit e-mail and a live SSE message; the stream-ticket flow works through the gateway (no buffering, no idle timeout); `make chaos-run S=redis-down`.

## Tooling that unblocks the services

### WP-T1: gRPC mock for AccountService

- **Goal.** Catalog and notification call account over gRPC; today no mock speaks it, so they cannot start before S1 is finished.
- **Lane.** `services/_mock/**`. Extend the existing account mock (a second process in the same container, port 9090) rather than adding a container: two containers with the alias `account` would split the traffic.
- **Contains.** `GetUser`, `GetUsersByIds` (batch) and the server-streaming `ListUsersUpdatedSince` of `contracts/proto/account/v1/account.proto`, answering from the seeded users ([../seed/CATALOG.md](../seed/CATALOG.md)) so authors match the seed data; unknown ids behave as the proto comments say; a way to make it fail or slow down on request (for the resilience tests).
- **Done when.** `make up-mocks` serves gRPC on `account:9090` (a `grpcurl` check in the `gateway` job of CI proves it); Compose and Helm values need the extra port (`make k8s-gen`); [GETTING-STARTED](GETTING-STARTED.md) says so.

### WP-T2: event emitter

- **Goal.** Consumers (catalog, notification) develop without the producers: a command that publishes valid events.
- **Lane.** `tools/event-emitter/**` or `scripts/emit*`.
- **Contains.** `make emit EVENT=media.asset.processed [ID=...]` builds a payload from the Avro schema of `contracts/avro` (values from the seed data), registers or finds the schema in the Schema Registry, publishes with the key and headers of README 5.6 (`event-id`, `traceparent`, `correlation-id`). Also `make emit-list`.
- **Done when.** Every one of the 7 schemas can be emitted and read back through Kafka UI (`make up-tools`); a test generates a payload for each schema and validates it; the Avro compatibility rules of `make contracts-breaking` are untouched.

### WP-E1: system tests and the phase 6 exercises

- **Lane.** `e2e/system/**`, `e2e/run.sh`, `e2e/fixtures/**`.
- **Contains.** Making the `system/*.hurl` flows pass against real services, adjusting them where the contract assertions were wrong (they have never run against an implementation); the README 4.1 scenario end to end (register, upload, publish, search, e-mail in Mailpit, SSE event received); the outbox failure test; the rate-limit test; the Avro v2 evolution exercise (add `marketingConsent` with a default, watch the registry accept it, then a breaking change and watch it rejected).
- **Rule.** A test that disagrees with a contract is a bug in one of them: fix it through the contract protocol if the contract is wrong, never by loosening the test silently.
- **Done when.** `make up-apps && make e2e-all` is green locally and in `system.yml`.

## Developer experience and the team

### WP-D1: developer inner loop

- **Lane.** `.devcontainer/**`, `.editorconfig`, `docs/ide/**`.
- **Contains.** `.editorconfig` (LF everywhere that matters, matching `.gitattributes`); a devcontainer with Docker-outside-of-Docker and the tools the repo uses (make, Hurl, kind, kubectl, helm, kubeconform, pre-commit, Python, Node); IDE run configurations for host mode (`infra/host/<name>.env`) and debugging a service in Compose, kept in `docs/ide/` because `.vscode/` and `.idea/` are git-ignored; hot-reload guidance per language (added by each scaffold).
- **Done when.** A fresh clone opens in the devcontainer and `make doctor && make up-mocks && make e2e` pass inside it.

### WP-R1: repository basics

- **Lane.** `LICENSE`, `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/**`, `.github/CODEOWNERS`.
- **Needs owner decisions.** The license; who the code owners are (CODEOWNERS needs real handles).
- **Contains.** CONTRIBUTING: branch and PR flow, `make precommit` before pushing, when to write an ADR, the contract protocol, commit message convention; a PR template whose checklist asks about contracts changed, generated files regenerated, STATUS updated, what was verified; branch protection written down in [CI.md](CI.md) (require `ci / ok`, linear history, who may merge).
- **Done when.** The files exist, are linked from the README and from [docs/README.md](README.md), and `make adr-check`'s link check and `make docs-check` are clean.

### WP-X1: security scanning

- **Lane.** Scan configuration and scripts; shared files: `ci.yml` (new job), `.pre-commit-config.yaml`, `Makefile`.
- **Contains.** Secret scanning (gitleaks) as a hook and a CI step, with an allow-list for the development defaults of `infra/.env.example` and the seed passwords; image scanning (Trivy) of the images the repository builds and of the pinned third-party images; dependency review on pull requests; a license check; later an SBOM per published image (with C1). A `make security` target that runs what CI runs.
- **Rules.** Every tool is pinned and watched by Renovate like everything else ([ADR 0018](adr/0018-pin-every-version-and-let-renovate-propose-updates.md)); decide and write down (ADR) which severity fails the build. The check must not fail on third-party images the template cannot change without an exception file that explains each entry.
- **Done when.** A planted secret and a planted vulnerable pin each fail CI; both are removed afterwards.

## Operating it

### WP-C1: release and deployment

- **Needs decision D-4** (registry, environments, push or pull deployment) and a service that has a Dockerfile.
- **Lane.** `.github/workflows/release.yml`, `deploy/helm/environments/<env>/values.yaml`, `docs/RELEASE.md`.
- **Contains.** Build and publish images (tags: git sha and semantic version), SBOM and optional signature, per-environment values overlays on top of the generic chart (replicas, resources, ingress, `existingSecret`, endpoints of managed databases), a promotion flow (dev, staging, production), and either a deploy job (`helm upgrade`) or a GitOps repository layout; rollback procedure.
- **Rules.** The generated values stay local-cluster values; environments are separate files that are never generated ([ADR 0020](adr/0020-one-generic-helm-chart-for-every-service-with-values.md)). The first run needs a real cluster: say so in the delivery.

### WP-O1: alerts, SLOs, runbooks

- **Lane.** `infra/prometheus/rules/**`, alert provisioning in `infra/grafana/**`, `docs/runbooks/**`, `docs/SLO.md`.
- **Contains.** SLOs per service (availability and latency, taken from README section 8 and the load-test budgets in [LOAD.md](LOAD.md)); Prometheus alert rules (gateway and stack now, per-service rules with the services: outbox lag, Kafka consumer lag, circuit breaker open, queue depth, error budget burn); an alert destination (Alertmanager or Grafana alerting: a decision, write an ADR; Mailpit receives the mail locally); one runbook per alert.
- **Done when.** Each chaos scenario of [CHAOS.md](CHAOS.md) fires its alert and the runbook says what to do; `make dashboards-check` and a rules check (`promtool`) are CI gates.

### WP-O2: secrets for real environments

- **Lane.** `docs/SECRETS.md`; environment overlays together with C1.
- **Contains.** What the development defaults are and why they are fine locally; how a real cluster gets secrets (`existingSecret` plus an external store: External Secrets, Sealed Secrets or SOPS: a decision, ADR); how Keycloak client secrets are rotated; what must never be in the repository (and the scan that enforces it, X1).

### WP-G1: gateway follow-ups

- **Lane.** `services/gateway/**`, `scripts/gen-gateway-errors.py`.
- **Contains, independent items.** (a) Shared rate-limit counters with Envoy's global rate limit service (`envoyproxy/ratelimit` with Redis), replacing the per-instance buckets; (b) localized messages for the gateway errors that are generic English today (new keys in `contracts/i18n`: contract protocol); (c) the README's second gateway mode: a **hand-written thin gateway** in `services/gateway/<impl>/` that passes the same `make e2e` suite as Envoy.
- **Rules.** `envoy.yaml` is the single source: the load-test, HTTPS and chaos gateway variants are generated from it ([ADR 0013](adr/0013-local-gateway-variants-are-generated-from-envoy-yaml.md)); after a change run `make load-check https-check chaos-check` and regenerate. Keep `ENVOY_UID: "0"` unless the entrypoint problem described in [KUBERNETES.md](KUBERNETES.md) is solved.
- **Done when.** `make up-mocks && make e2e` and `make k8s-up-mocks && make e2e` both pass; for (a) a two-replica gateway shares one bucket.

### WP-W1: web client (optional)

- **Needs decision D-3.** **Lane.** `web/**` (a new top-level folder; not under `services/`).
- **Contains.** An SPA using the `web-spa` Keycloak client (authorization code with PKCE, origins 5173 and 4200 are already allowed in CORS), the TypeScript types of `make codegen TARGET=typescript`, the SSE stream with the one-time ticket, the GraphQL endpoint. Runs against `make up-mocks` first.

### WP-L1: more languages

README phase 6: after one implementation of a service is finished, port it to the next language. One package per service and language (`services/<name>/<impl>/`), same definition of done, same pipeline ([CI.md](CI.md) builds and tests every implementation of a service against its own copy of the stack).
The comparison between implementations is the point of the project: keep the internal layout of README section 12 and the same `CHEATSHEET.md` structure so that implementations line up side by side.

## Starting a package

Paste this at the start of a new dialog, with the package filled in:

```text
You are working on package WP-<id> of the Wallpaper Hub template repository.
1. Read AGENTS.md, then docs/STATUS.md, then the section of docs/ROADMAP.md for WP-<id>, then only the documents and contracts that section lists as inputs.
2. Work only inside the lane of that section. Do not read or edit other packages' code: their behaviour is the contracts, docs/SERVICE-SPEC.md and the mocks.
3. Every check you add is a make target. Run the checks of "definition of done"; say what you could not run.
4. Finish by updating docs/STATUS.md and docs/HISTORY.md, and deliver a patch against the current master with the list of files it touches.
```
