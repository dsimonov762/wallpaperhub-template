# Getting started (Windows 11 + Docker Desktop + WSL2)

The design lives in [`README.md`](../README.md) (v1.1). This file is the practical side: how to start the stack, what to
open, what was actually tested, and what to do when something breaks.

## 1. One-time setup

1. **Docker Desktop** > Settings > General: *Use the WSL 2 based engine*. Settings > Resources > WSL integration: enable your Ubuntu distro.
2. **Memory.** Create `%UserProfile%\.wslconfig`, then run `wsl --shutdown` and restart Docker Desktop:
   ```ini
   [wsl2]
   memory=8GB
   swap=4GB
   kernelCommandLine = "sysctl.vm.max_map_count=262144"

   [experimental]
   autoMemoryReclaim=gradual
   ```
   `max_map_count` is what Elasticsearch needs; without it the `elasticsearch` container restarts forever.
   `autoMemoryReclaim` hands page cache back to Windows; without it WSL keeps growing towards `memory` and the whole PC slows down.
   Sizes: see the footprint table in section 2. In practice 6 GB plus 4 GB swap was tolerable/bearable for `make up-mocks` and `make up`; 13 GB was not enough
   to run `make up-mocks` and `make up-obs` together comfortably (measured 9.4 GB in use), because `up-obs` already contains everything `up-mocks` needs
   plus Kafka, Elasticsearch, MongoDB and the observability stack.
3. **Clone/copy the repo into the WSL filesystem** (`~/wallpaper-hub`), not under `C:\` (`/mnt/c/...`). Bind mounts from the Windows drive are slow
   and Git may turn scripts into CRLF, which breaks them inside Linux containers. `.gitattributes` forces LF for everything that matters.
4. In the Ubuntu shell: `sudo apt install -y make curl` and install [Hurl](https://hurl.dev) (`winget install hurl` on Windows, or the `.deb` from the releases page for Ubuntu).
   Without Hurl, `e2e/run.sh` falls back to the `ghcr.io/orange-opensource/hurl` container.

## 2. First start - in this order

```bash
make doctor        # preflight: Docker, memory, vm.max_map_count, ports, CRLF, missing images
make up            # infra + DB schemas (about 2-4 minutes the first time, Keycloak and Elasticsearch are the slow ones)
make e2e           # gateway checks   -> only meaningful once a gateway is running, see below
```

Nothing exists behind the gateway until services are implemented. Two ways to get something to talk to:

| You want to | Command | What runs |
|---|---|---|
| Work on gateway, Keycloak, e2e, front-end against the contract | `make up-mocks` then `make e2e` | infra + Envoy + 4 Prism mocks generated from `contracts/openapi` |
| Run your real services | `make up-apps` then `make e2e-system` | infra + your containers built from `services/<name>/<impl>` (`*_DIR` in `infra/.env`) |

**Footprint** (sum of the `mem_limit` values in `infra/docker-compose.yml`; real use is a bit below, the WSL VM and page cache come on top; `make stats` shows the live numbers):

| Command | Starts | Limits add up to |
|---|---|---|
| `make up-mocks` | Keycloak + its Postgres, Redis, gateway, 4 mocks | about 2 GB |
| `make up` | all infra: Postgres x3, Mongo, Redis x2, Kafka, Schema Registry, Keycloak, Elasticsearch, S3, Mailpit | about 5 GB |
| `make up-obs` | `up` + Grafana, Loki, Tempo, Prometheus, Alloy | about 6.5 GB |
| `make up-tools` | the web UIs of section 3 and only the stores they show (Kafka UI needs Kafka and the Schema Registry, Adminer the three Postgres, Mongoku Mongo); `T=adminer` for one | about 0.9 GB for the UIs, plus what they pull in |
| `make up-apps` | `up` + your four services (640 MB each) + gateway (384 MB) | about 8 GB |
| `make up-obs` + `up-apps` together | everything | about 9.3 GB |

`make up-obs` and `make up-mocks` can run side by side (measured by you: about 3.7 GB of RAM in use, about 8 GB counting page cache); `up-obs` and `up-apps` already include the infra, and `up-mocks` is the only light one. Do not run `up-mocks` and `up-apps` together: both answer to the service names.
Elasticsearch (1 GB), Kafka and Keycloak (768 MB each) are the big ones; add the observability stack only when you are looking at traces or metrics.
`make down` stops everything and keeps the data, `make nuke` deletes the volumes too, `make logs S=keycloak` follows one service.

## 3. What to open

| URL | What | Login |
|---|---|---|
| http://localhost:8080/health | gateway (public entry point) | - |
| http://localhost:8180 | Keycloak admin console | `admin` / `admin`; realm users `alice`, `mod`, `admin`: password `password` (after `make seed` also bob, carol, dave, ...) |
| http://localhost:8025 | Mailpit (all outgoing mail) | - |
| http://localhost:9001 | S3 console (Silo) | `silo-admin` / `silo-admin-secret` |
| http://localhost:9200 | Elasticsearch | no auth in dev |
| http://localhost:3000 | Grafana (observability profile) | anonymous admin |
| http://localhost:8081 | Schema Registry | - |
| http://localhost:8082 | Kafka UI (tools profile) | no login |
| http://localhost:8083 | Adminer, Postgres (tools profile) | System PostgreSQL, user = database name, password as in `infra/.env` (default = user name); `make up-tools` prints ready-filled links |
| http://localhost:8084 | Mongoku, MongoDB (tools profile) | no login, connected as root |

Get a token for manual calls (alice by default, `mod`, `admin` and the seeded users work too; `--client catalog-svc` gives a service account, `--decode` shows the claims):

```bash
make token                      # or: scripts/token.sh bob
curl -H "$(scripts/token.sh --header alice)" http://localhost:8080/api/v1/users/me
```

For clicking through the whole API there is a [Bruno collection](../bruno/README.md): one request per operation, one environment per seeded user, the token handled for you. `make bruno-run` runs it from the command line.

## 4. Test ladder

1. `make lint` - compose files for all profile combinations, shell syntax, Hurl formatting. No containers needed.
2. `make check-contracts` - OpenAPI, GraphQL, Avro, proto, i18n and gateway config cross-checked against each other and the README. `make contracts-lint` and `make contracts-breaking` check the contracts on their own, see [contract tooling](#contract-tooling).
3. `make up-mocks && make e2e` - gateway behavior through real Envoy + real Keycloak: problem+json errors, security headers, CORS, JWT routing, rate limit.
4. `make up-apps && make e2e-system` - README 4.1 user flows (register, upload, publish, search, favorite, moderate, notify).
5. `make conformance SVC=account` (or `make conformance-all`) - does one service obey [docs/SERVICE-SPEC.md](SERVICE-SPEC.md) (health endpoints, JWT validation, problem+json and localization, JSON logs, traces/logs/metrics arriving in Tempo/Loki/Prometheus, graceful shutdown, fail-fast config)? Same checks for every language: [conformance/README.md](../conformance/README.md). Run it the first day of a new service, before there is any business logic.
6. CI runs all of the above on every pull request, see [CI.md](CI.md).

### Development data

`make seed` fills every store with a consistent dataset (12 users, 30 wallpapers in every state, favorites, collections, inboxes, images in S3; all users have the password `password`), `make reset` deletes all data again (schemas stay, asks first), `make reseed` does both. What is in it and why: [seed/README.md](../seed/README.md), the ids: [seed/CATALOG.md](../seed/CATALOG.md). `make seed-check` verifies the dataset against the DB contracts without a database. To look at the result: `make up-tools`.

### Web UIs for the stores

`make up-tools` starts **Kafka UI** (topics, Avro messages decoded through the Schema Registry, consumer groups), **Adminer** (the three Postgres databases) and **Mongoku** (MongoDB, database `catalog`), each with the connection already set up; it prints the links. `make up-tools T=kafka-ui` starts one of them. They run with full rights and no login on the loopback address (do not set `BIND_ADDRESS=0.0.0.0` while they run); `TOOLS_READONLY=true` in `infra/.env` makes Kafka UI and Mongoku refuse writes. Mongoku instead of mongo-express because the Docker official mongo-express image is deprecated (no release since April 2024). There is no UI yet for Redis and Elasticsearch: `docker compose exec redis redis-cli` and `curl localhost:9200/_cat/indices` do the job, or add one to the profile.

### Contract tooling

The contracts are the source of truth, so changing them is the risky part. Three commands, all language-agnostic, all run the tools in a pinned container (`wallpaperhub/contract-tools:local`, built on first use from `tools/contract-tools`; set `CONTRACT_TOOLS=native` to use Node 20+ on your machine instead):

| Command | What it does |
|---|---|
| `make contracts-lint` | **OpenAPI** with Spectral and `contracts/.spectral.yaml` (the OpenAPI ruleset plus the project's conventions: every 4xx/5xx is `application/problem+json`, `size` has `maximum: 100`, camelCase properties, kebab-case paths, camelCase operationIds, global `bearerAuth`, `Idempotency-Key` on creating POSTs). **Protobuf** with `buf lint` (`contracts/proto/buf.yaml`, four deliberate exceptions explained there). **Avro**: file/namespace naming, record doc, `eventId` and `occurredAt`, `default: null` on optional fields. **GraphQL**: naming, descriptions. |
| `make contracts-breaking BASE=origin/master` | Compares `contracts/` with the same folder at a git ref (or any folder that contains `contracts/`) and fails on breaking changes: **OpenAPI** with oasdiff, **protobuf** with `buf breaking` (FILE rules), **Avro** with the Avro compatibility rules (BACKWARD, which is what Schema Registry enforces; `AVRO_MODE=FULL` also requires old consumers to read new events), **GraphQL** with graphql-core's breaking-change finder (new enum values and similar are reported as "to review"). |
| `make codegen TARGET=typescript` | `gen/typescript/<service>.d.ts` from the four OpenAPI specs, type-checked with `tsc --strict`. `TARGET=openapi GEN="spring account"` runs any openapi-generator generator for one service into `gen/spring/account/`; `TARGET=proto GEN=buf.gen.yaml` runs `buf generate` with a template you write for your language. `gen/` is not committed. |

Evolving a contract: an additive change passes (new optional response field, new endpoint, new optional Avro field with a default, new GraphQL field). A breaking change needs a new version (`/v2`, `*.v2.avsc`, `account/v2/`) and the old one kept until its consumers are gone; there is no override flag on purpose. In CI run `make contracts-lint contracts-breaking BASE=origin/${GITHUB_BASE_REF}` on pull requests. Database schemas (`contracts/db-schema/`) are not compared: their migrations are forward-only and reviewed by hand.

### Develop one service from your IDE (host mode)

`make up-apps` (or `make up-mocks`), then `make host SVC=account`: the container of that service is stopped and a small forwarder takes over the name `account` in the Docker network, so the gateway and the other services keep calling `account:8080` and reach the process you started in the IDE. Everything else stays in Docker. Load `infra/host/account.env` into your run configuration (it has the same variables as the compose service with `localhost` addresses and the host ports 8101/8191/9101), listen on `0.0.0.0`, debug and hot-reload as usual. `make unhost SVC=account` puts the container back. `make up-apps` leaves hosted services alone while `.host` lists them (`make down` clears it). `make env-matrix` shows the variables of all services side by side.

## 5. What has and has not been verified

Verified with the real binaries in a Linux sandbox (no Docker daemon was available there):

- **Envoy 1.39.1** loads `services/gateway/envoy/envoy.yaml`; a behavior matrix passed (JWT, CORS, rate limit, problem+json, request id, body limits, forged `X-User-*` / `X-Forwarded-For` removal, per-IP and per-user rate-limit buckets, security headers on gateway 404s, de/es/en errors).
- **Keycloak 26.8.2** imports `infra/keycloak/realm-export.json` and issues tokens that Envoy accepts (alice, mod, admin, five service clients).
- **Prometheus 3.16 (`promtool`), Loki 3.7.9, Tempo 3.1.1, Alloy 1.21.3** accept their configs (Tempo was also booted with it).
- **PostgreSQL 16** (the compose image is 18.6): the migrations in `contracts/db-schema/postgres/*` apply cleanly and `infra/db-init/pg-migrate.sh` is idempotent and CRLF-tolerant.
- **Prism 5.16** serves all four OpenAPI specs; the `gateway/*.hurl` suite passes against Envoy + Keycloak + the mocks (`system/*.hurl` requests were checked against the OpenAPI schemas by Prism).
- **docker compose config** is valid for every profile combination.
- **Conformance suite** (`conformance/`): run against a reference stub (Python, in `conformance/reference-stub/`) in all four service personas with the real Keycloak, Hurl, and Loki/Tempo/Prometheus/Alloy: everything passes, and each of 13 deliberate violations (`BREAK=<id>`) makes the intended check fail.
- **Contract tooling:** Spectral, buf and the Avro/GraphQL checks run for real on the contracts (lint is clean after fixing 8 real findings: five missing operation descriptions, a missing Avro record doc and GraphQL type description, one POST without `Idempotency-Key`, which now carries `x-idempotency: not-applicable`). Each Spectral rule fires on a deliberate violation; `buf breaking`, Avro BACKWARD/FULL and GraphQL breaking detection fire on removed/retyped/required-added fields and removed enum values, and pass on additive changes. The TypeScript generation compiles and rejects wrong use.
- **CI:** the three workflows pass a workflow-schema validator (`action-validator`); the commands of the `static` job ran in a fresh copy of the repo without any cached tools; `detect-services.sh` selects the right implementations in a scratch git repo (all, only the changed one, none, FORCE_ALL); `install-hurl.sh` installs from the release tarball layout and degrades to the container when the download fails; `make conformance-selftest` (21 s) passes against the real Keycloak.
- **Host mode:** the forwarder script with real `socat`; real Envoy health-checks and routes through it to a process on the host.
- **Seed data:** the SQL loads twice into PostgreSQL 16 on top of the canonical schema (second load adds nothing); the Redis files into real Redis; the Keycloak partial import and `infra/data/keycloak.sh` (seed, repeat, reset) against Keycloak 26.8.2 incl. fixed user ids and logins; the Elasticsearch loader against a mock; `catalog.js` under Node with a stub driver; `seed-check` catches six deliberate corruptions.

Not verified (needs your Docker): image behavior of Kafka/Schema Registry/Elasticsearch/MongoDB/Silo, `kafka-init`, `schema-registry-init`, `s3-init`, `catalog-db-init`
(mongosh), `catalog-search-init`, the Alloy pipeline at runtime, the mock `Dockerfile`, the Hurl container fallback, `make` targets that call the daemon,
**oasdiff** (`make contracts-breaking` only exercised its call plumbing with a stand-in, the real tool could not be downloaded here, image `tufin/oasdiff:v1.33.0`), the tools image build (`tools/contract-tools/Dockerfile`: buf's binary on Alpine), `TARGET=openapi` (image `openapitools/openapi-generator-cli:v7.10.0`) and `TARGET=proto` (buf plugins need network access), **the workflows on GitHub itself** (never run: action versions, runner memory, the Docker steps, `make up-mocks` and `make e2e` in the runner, artifact upload), the host-mode forwarder image build, `docker compose` `--scale <hosted service>=0`, whether Docker Desktop reaches a host process through `host.docker.internal` on your machine (bind `0.0.0.0`; allow the Windows firewall prompt), the Docker modes of `conformance/checks/lifecycle.sh` (`CONTAINER=`), the container fallback of `conformance/run.sh` when Hurl is not installed, and **all `system/*.hurl` assertions** - they describe the contract and have never run against an implementation. Expect to adjust them with the first real service.

Also not verified: the **`data` jobs and `make seed`/`reset`** against Docker (the scripts were exercised one by one, `scripts/data.sh` with a fake `docker`), the Mongo upserts against a real MongoDB with the validators, `mcli mirror --attr` and `mcli rm` in the Silo image, and the **`tools` profile**: nothing of it was started. The tags `ghcr.io/kafbat/kafka-ui:v1.5.0` (taken from the release list, not confirmed on the registry), `adminer:5.5.1` and `huggingface/mongoku:2.11.5` (seen on Docker Hub), the Kafka UI variable names (`KAFKA_CLUSTERS_0_*`, from its documentation as I remember it) and Adminer's pre-filled `?pgsql=...` links are the likely places for a first-start surprise. A wrong tag shows up as a pull error: set `KAFKA_UI_IMAGE`, `ADMINER_IMAGE` or `MONGO_UI_IMAGE` in `infra/.env`.

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `elasticsearch` exits with code 78 / restarts | `vm.max_map_count` too low. `wsl -d docker-desktop sysctl -w vm.max_map_count=262144`, and persist via `.wslconfig` (section 1) |
| `bind: An attempt was made to access a socket in a way forbidden by its access permissions` | Windows reserves that port (Hyper-V/WSL excluded range). `make doctor` lists them; set `PORT_<NAME>` in `infra/.env` |
| `bind: address already in use` | another program owns the port; same fix. Common: 5432 (local Postgres), 8080, 9090 |
| `exec /scripts/....sh: no such file or directory` or `\r` in logs | CRLF line endings. Re-clone inside WSL; check `git config core.autocrlf` (use `input`) |
| Containers killed (exit 137) / everything crawls | out of memory. Skip `observability`, raise `memory=` in `.wslconfig`, or lower `mem_limit` in services you do not need |
| Keycloak unhealthy for a few minutes | first start imports the realm and builds the DB; give it 2-3 minutes. `make logs S=keycloak` |
| `depends_on ... required` is invalid | Compose older than 2.20. Update Docker Desktop |
| e2e: `429` on `POST /registrations` | the gateway test `99-rate-limit` empties the 10/min bucket of your IP; wait a minute (or use `./e2e/run.sh all`, which runs it last) |
| Kafka UI lists no topics, or says the cluster is offline | `make up-tools` alone starts Kafka but not `kafka-init`: run `make up` once (creates the topics). Offline: `make logs S=kafka-ui`, the broker must be healthy (`make ps`) |
| Adminer: "No driver" / cannot log in | choose System = PostgreSQL (the links from `make up-tools` do), server is the compose name (`postgres-account`), not `localhost` |
| `make up-tools`: pull access denied / manifest unknown | the pinned tag does not exist for you: set `KAFKA_UI_IMAGE`, `ADMINER_IMAGE` or `MONGO_UI_IMAGE` in `infra/.env` (for example `ghcr.io/kafbat/kafka-ui:latest`) |
| System e2e: upload rejected as `DUPLICATE` | media rejects duplicates by SHA-256 and perceptual hash; `run.sh` generates a new random picture per run, which needs `python3` |

## 7. Repository layout

```
README.md                 design document (v1.1)
contracts/                openapi/ proto/ avro/ graphql/ i18n/ db-schema/     the source of truth, language-agnostic
infra/                    docker-compose.yml, .env.example, db-init/, data/ (seed and reset jobs), keycloak/, kafka-init/, observability configs
services/gateway/envoy/   the Envoy gateway (config, Dockerfile, CHEATSHEET.md)
services/_mock/           Prism mock of a service (Dockerfile, mock.js)
conformance/              language-agnostic conformance suite (run.sh, selftest.sh, http/, checks/, reference-stub/); spec: docs/SERVICE-SPEC.md
.github/workflows/        ci.yml, service.yml (one implementation), system.yml (all services, nightly); scripts/ci/ helpers; docs/CI.md
infra/host/, host-proxy/  host mode: env files for the IDE, TCP forwarder
seed/                     development dataset: dataset.yaml, build.py, generated out/ and s3/ (make seed / reset / reseed)
services/<name>/<impl>/   YOUR implementations go here (account, media, catalog, notification)
e2e/                      Hurl tests: gateway/ (any backend) and system/ (real services), fixtures/, run.sh
scripts/                  doctor.sh, wait-healthy.sh, validate/ (contract cross-checks), contracts.sh + contracts/ (lint, breaking), codegen.sh, ct.sh
tools/contract-tools/     pinned Spectral, buf, openapi-typescript (package.json, Dockerfile)
Makefile                  make help
```

## 8. What is still missing for a finished template

- **Service skeletons.** `services/<name>/<impl>/` does not exist yet (`conformance/reference-stub/` is a throwaway Python stand-in that passes the conformance suite, not a template): a service template per language (health endpoints on `:8081`, JWT validation, outbox relay, Avro producer, problem+json mapper, config mapping of the env vars in `infra/docker-compose.yml`).
- **CI** is in `.github/workflows/` (GitHub Actions, see [CI.md](CI.md)); there is no GitLab/Jenkins version, the workflows only call `make` targets.
- **Web client** (the `web-spa` Keycloak client and the CORS origins 5173/4200 are prepared).
- **Decided in the contracts:** avatar/banner assets are verified with media-service before account writes (owner, purpose, not rejected; 403/404/409/503); `size` above 100 is rejected, not clamped; one asset backs at most one wallpaper (`409 wallpaper.asset-already-used`, unique index `asset_uq`). A moderator-removed wallpaper cannot be deleted by its author (`409 wallpaper.removed-by-moderation`), so its asset cannot be reposted.
- **Known gateway gap:** rate-limit buckets are per client (IP, or user id after sign-in) but live in each gateway instance's memory, so they multiply with the number of instances and reset on restart; shared counters (README: Redis) need Envoy's global rate limit service (`envoyproxy/ratelimit`), worth adding when you run more than one gateway. Behind a load balancer set `xff_num_trusted_hops`. Only 401, 404, 413, 429 and 502-504 are localized (de/es/en); other gateway errors are generic English.
