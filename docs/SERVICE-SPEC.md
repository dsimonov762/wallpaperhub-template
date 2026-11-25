# Service specification

What every Wallpaper Hub service must do, whatever language or framework it is written in. The README (section 12)
describes the internal layout of a service; this file is the **outside view**: the behavior another team, the gateway,
Prometheus or a test can rely on. `conformance/` checks the items marked with an ID (`M1`, `A3`, ...) against any running
service, so "does the Go account-service behave like the Java one" is answered by a command, not by reading code.

Words: **MUST** = checked by `conformance/` or required for the stack to work; **SHOULD** = expected, not checked.

Applies to `account`, `media`, `catalog` and `notification`. The gateway is an Envoy config, not a service.

## 1. Ports

| Port | Protocol | What | Published on the host as |
|---|---|---|---|
| 8080 | HTTP | the API (`/api/v1/...`, `/graphql` for catalog, SSE for notification) | 8101 account, 8102 media, 8103 catalog, 8104 notification |
| 9090 | gRPC | account only: the `AccountService` of `contracts/proto` | 9101 |
| 8081 | HTTP | management: health and optional `/metrics`. Never exposed by the gateway | 8191 .. 8194 |

The three ports are fixed. Ports are *not* configurable by environment variable in the container (the host side is
`PORT_*` in `infra/.env`). A service that runs on the developer's host instead of in Docker (see `make host`) takes
its ports from `HTTP_PORT`, `GRPC_PORT` and `MGMT_PORT`, defaulting to the values above, and listens on all interfaces
(0.0.0.0): the container that forwards `<name>:8080` to it reaches it through `host.docker.internal`.

## 2. Management endpoints (port 8081)

| Path | 200 when | Body |
|---|---|---|
| `GET /health/live` | the process is running and not deadlocked. Never checks dependencies | `{"status":"UP"}` |
| `GET /health/ready` | the service can serve traffic: database, Redis, Kafka producer, and the Keycloak JWKS were reachable at least once | `{"status":"UP"}` |
| `GET /health/startup` | initialization (config, migrations check, warm-up) is finished | `{"status":"UP"}` |

- **M1-M3** All three exist, answer `200` with `Content-Type: application/json` and `status` `UP` once the service is up.
- When not ready they answer `503` with `{"status":"DOWN"}`. The gateway health-checks `/health/ready` every few
  seconds and takes the service out of rotation, so `ready` must turn `DOWN` while a dependency is gone and recover
  by itself.
- **M4** The management port is separate: `/health/*` is not served on 8080.
- `GET /metrics` (Prometheus text format) is optional and only on 8081. Metrics are pushed by OTLP (section 8).

## 3. Configuration

Twelve-factor: everything comes from environment variables, validated at startup. A missing or malformed required
variable MUST stop the process with a non-zero exit within 30 seconds and a log line that names the variable
(**C1**, `conformance/checks/lifecycle.sh`, run with `--lifecycle`). Defaults are only allowed for non-secret tuning values.

Names are the contract; the typed config object inside the service is yours. The authoritative list per service is the
`environment` of the service in `infra/docker-compose.yml`; `make env-matrix` prints it. Shared by all four services:

| Variable | Meaning |
|---|---|
| `APP_PROFILE` | `local`, `test` or `prod`. With `local` a service MUST NOT create or alter database schema: `make schemas` owns it (see section 9) |
| `LOG_LEVEL` | `trace`, `debug`, `info` (default), `warn`, `error` |
| `OIDC_ISSUER_URI` | the exact `iss` of accepted tokens: `http://localhost:8180/realms/wallpaperhub` (the address a browser sees, not the in-network one) |
| `OIDC_JWKS_URI` | where to fetch signing keys: `http://keycloak:8080/realms/wallpaperhub/protocol/openid-connect/certs` |
| `OIDC_TOKEN_URI`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | the service's own client-credentials identity for calls to other services; `OIDC_CLIENT_ID` is also its token **audience** (`account-svc`, `media-svc`, `catalog-svc`, `notification-svc`) |
| `KAFKA_BOOTSTRAP_SERVERS`, `SCHEMA_REGISTRY_URL` | event bus and Avro registry |
| `REDIS_HOST`, `REDIS_PORT` | Redis (idempotency keys, caches) |
| `OTEL_SERVICE_NAME` | `account-service`, `media-service`, `catalog-service`, `notification-service` |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`, `OTEL_METRIC_EXPORT_INTERVAL`, `OTEL_RESOURCE_ATTRIBUTES` | standard OpenTelemetry settings, passed to the SDK unchanged |

Service-specific variables (database coordinates, `S3_*`, `MONGO_*`, `ELASTICSEARCH_URL`, `MEDIA_BASE_URL`,
`ACCOUNT_GRPC_ADDR`, `OUTBOX_RELAY_ENABLED`, ...) are listed in the compose file with their local values.

## 4. Authentication and authorization

Every `/api/v1` operation that the OpenAPI file marks with `security` MUST validate the bearer token itself, even
though the gateway already did a coarse check. A service reachable only through the gateway today must stay safe when
reached directly (**A1-A4**):

| Check | Required answer |
|---|---|
| no `Authorization` header (**A1**) | `401`, problem `unauthorized`, `WWW-Authenticate: Bearer` |
| `Bearer` with garbage, not a JWT (**A2**) | `401` |
| a valid token with one character of the signature changed (**A3**) | `401` |
| a valid token whose `aud` does not contain the service's own `OIDC_CLIENT_ID` (**A4**) | `401` |

Full validation: signature against the cached JWKS (refetch on an unknown `kid`, with a minimum interval so a flood
of bad `kid`s cannot hammer Keycloak), `iss` equal to `OIDC_ISSUER_URI`, `aud`, `exp` and `nbf` with 30 s clock skew,
and `typ` `Bearer`. Claims used: `sub`, `email`, `locale`, `realm_access.roles`, `scope`.
Roles `USER`, `MODERATOR`, `ADMIN` for people, `internal` for service accounts. Ownership checks belong to the service.
Never trust `X-User-*` style headers: the gateway removes them, and a service must not read them.

## 5. Errors

All error responses on the API port are `application/problem+json` (RFC 9457), also for failures that happen before
routing (unknown path, unsupported method, malformed JSON, oversize body). Shape: `contracts/openapi/common.yaml`
(`Problem`). Mapping of exceptions to status, gRPC and GraphQL codes: README 5.3.

- `type` is `https://wallpaperhub.dev/problems/<slug>`; the slug MUST be one with `problem.<slug>.title` and
  `.detail` in `contracts/i18n`.
- `status` equals the HTTP status. `instance` is the request path. `code` carries the domain error code from the
  OpenAPI `x-error-codes` (`user.username-taken`, ...) when there is one.
- **E1** unknown path with a valid token: `404`, slug `not-found`, with `traceId`.
- **E2** `traceId` is the 32-hex trace id of the request: the one in the incoming `traceparent` header, or a new one
  when there is none. Logs and traces of that request carry the same id, so a user can quote it.
- **E3** a request with an invalid body: `400`, slug `validation-failed`, `errors[]` with `field`, `code`, `message`.
- **E4** localization: `Accept-Language` picks `en` (default), `de` or `es` by its first tag. `title`, `detail` and
  `errors[].message` come from the bundle `contracts/i18n/messages.<lang>.json`; the response has `Content-Language`.
- **E5** pagination: `size` above 100 is rejected with `400` and code `pagination.size-too-large`, never clamped.
- **E6** `X-Request-Id`: when the request has one it is echoed unchanged in the response, otherwise one is generated.
  (The gateway replaces client-supplied values; a service reached directly keeps them.) **Only a plain id is echoed:** 1 to 128 characters
  of `A-Z a-z 0-9 . _ : -`. Anything else (a space, a control character, a folded header line) is ignored and a new id is generated, because
  a value that a client chose must never reach a response header unchecked (HTTP response splitting; CodeQL flags exactly this). The same
  holds for every other request value that you copy into a header. The suite checks the echo; it does not yet send a malformed id.
- Never leak internals: no stack traces, SQL, hostnames or class names in `detail`.

## 6. Logs

Structured JSON, one object per line on **stdout** (what `docker logs` shows) and, through the OpenTelemetry SDK, as
OTLP logs to Alloy (what Loki and Grafana show). Stderr only for crashes before logging is initialized. Required fields:

| Field | Value |
|---|---|
| `timestamp` | RFC 3339, UTC, millisecond precision |
| `level` | `trace` `debug` `info` `warn` `error` (lower case) |
| `message` | human readable text |
| `service` | the `OTEL_SERVICE_NAME` |
| `trace_id`, `span_id` | present on every line written while a request or message is being handled |
| `request_id` | the `X-Request-Id` of the request, when there is one |
| `user_id` | the token `sub`, when the caller is authenticated |

- **L1** every stdout line parses as JSON and has `timestamp`, `level`, `message`, `service`.
- **L2** the line that logs a request carries the `trace_id` of the incoming `traceparent`.
- **L3** secrets stay out: the bearer token, passwords, client secrets and raw e-mail addresses are never logged
  (mask like `a***@example.test`). Request and response bodies are not logged.
- One access-log line per request at `info` (method, path without query string values, status, duration in ms).
  Health checks on 8081 are logged at `debug` only.

## 7. Correlation and headers

- W3C Trace Context in and out: `traceparent` and `tracestate` are read from requests and propagated to every HTTP,
  gRPC and Kafka call the request causes (Kafka: message headers).
- `X-Request-Id` as described in E6.
- `Idempotency-Key` on POST, `ETag` / `If-Match` on PUT and PATCH: README 5.2. Behavior is per endpoint and covered by
  the `e2e/system` tests, not by `conformance/`.
- CORS and security headers are the gateway's job. A service SHOULD still send `X-Content-Type-Options: nosniff`.

## 8. Telemetry

OpenTelemetry SDK with the standard `OTEL_*` variables; OTLP to `OTEL_EXPORTER_OTLP_ENDPOINT` (Alloy, gRPC 4317).
Alloy forwards logs to Loki, traces to Tempo, metrics to Prometheus. With the `observability` profile running, after
a few requests (the conformance run makes them; skip with `--no-telemetry`):

- **T1** Tempo has traces whose resource `service.name` is the `OTEL_SERVICE_NAME`.
- **T2** Loki has log lines with `service_name` equal to it (Loki's OTLP ingestion derives that label).
- **T3** Prometheus has the standard HTTP server duration histogram for it
  (`http_server_request_duration_seconds_count{job="<OTEL_SERVICE_NAME>"}`).

Also: server spans for HTTP and gRPC, client spans for outgoing calls, Kafka produce/consume spans, database spans with
sanitized statements. Business metrics named in README section 11; their exact names, units and labels are the contract the
Grafana dashboards are written against: `docs/OBSERVABILITY.md`. The service itself never talks to Loki, Tempo
or Prometheus.

## 9. Data stores and migrations

The canonical schema is in `contracts/db-schema/`. In the local stack the jobs behind `make schemas` apply it
(Postgres migrations with the `contract_schema_migrations` version table, Mongo collections and indexes, the
Elasticsearch index). Therefore:

- With `APP_PROFILE=local` a service does not run Flyway/Liquibase/ORM auto-DDL. It SHOULD check at startup that the
  schema version it needs is applied and fail fast with a clear message if not ("run `make schemas`").
- In other profiles it may run the same `contracts/db-schema` files through a `migrate` command (README section 12),
  never its own divergent copy.
- A service only touches its own stores. Cross-service data comes through APIs and events.

## 10. Events and outbox

Avro schemas in `contracts/avro`, topics and keys in README 5.6, registered in Schema Registry by
`schema-registry-init`. Events are published through the transactional outbox (README 4.3) with the `traceparent` of
the originating request in the message headers. Consumers are idempotent and classify errors as retryable (retry
topic) or non-retryable (dead-letter topic). Verified by the `e2e/system` flows, not by `conformance/`.

## 11. Shutdown

On `SIGTERM` the service stops accepting new requests, lets in-flight ones finish, stops consumers, flushes telemetry
and exits with code 0 within 30 seconds (**S1**, `conformance/checks/lifecycle.sh`, run with `--lifecycle`; exit code 143 is
accepted for runtimes that cannot map SIGTERM to a clean exit). `/health/ready` turns `DOWN` as soon as shutdown starts.

## 12. Container image

- Listens on 0.0.0.0, runs as a non-root user, has a `HEALTHCHECK` or relies on the compose one against 8081.
- JVM images honor the container memory limit (`JAVA_TOOL_OPTIONS` is set by compose); other runtimes MUST fit in
  `mem_limit` of the compose file (640 MB per service) while idle and under the e2e load.
- Build context is `services/<name>/<impl>/`, selected by `*_DIR` in `infra/.env`; the image is tagged
  `wallpaperhub/<name>:local`.

## 13. What `conformance/` does not check

The business behavior of the endpoints (that is `e2e/system` and your own unit and integration tests), resilience
policies (README section 8; those are checked by the failure scenarios of `docs/CHAOS.md`), security of authorization rules beyond A1-A4, performance. A service that passes the
conformance suite is a good citizen of the platform, not a correct implementation of its domain.
