# Failure injection with Toxiproxy

README section 8 promises behaviour: a 300 ms deadline towards account, a fallback to the author snapshot, a degraded search when Elasticsearch is
gone, a clean 503 when media is unreachable. On a laptop nothing ever fails, so nobody finds out whether the promise is kept until production does it for you.
`make up-chaos` puts [Toxiproxy](https://github.com/Shopify/toxiproxy) between every service and what it depends on, so you can break one connection on purpose
and see what the service does.

```
make up-apps          # normal: the services talk to their dependencies directly
make up-chaos         # same stack + Toxiproxy; the services talk to their dependencies through it (back: make up-apps)

make chaos-list                         # the scenarios
make chaos-run S=media-down             # baseline -> inject -> probe -> remove -> wait for recovery -> report
make chaos-run S=all                    # every scenario, with a summary (a few minutes)

make chaos                              # state of every proxy and its toxics
make chaos C="down catalog-elasticsearch"          # refuse connections
make chaos C="latency 'catalog-*' 800 --jitter 200"
make chaos C="timeout media-s3"                    # accept the connection, never answer: the nasty one
make chaos C=reset                                 # everything back to normal
```

Then look at what you broke: Grafana (`make up-obs`, [OBSERVABILITY.md](OBSERVABILITY.md)): error rate and latency of the service, the circuit breaker state, the logs.

## What can be broken

Proxies are named `<service>-<dependency>` and are listed in [`infra/chaos/edges.yaml`](../infra/chaos/edges.yaml) (`make chaos C=status` or `python3 scripts/chaos.py edges`):

| Service | Dependencies behind a proxy |
|---|---|
| account | `postgres`, `redis`, `keycloak`, `media` |
| media | `postgres`, `redis`, `s3`, `keycloak` |
| catalog | `mongo`, `elasticsearch`, `redis`, `account` (gRPC), `media`, `keycloak` |
| notification | `redis`, `smtp`, `account` (gRPC), `catalog`, `keycloak` |

A glob selects several: `'catalog-*'` (everything catalog depends on), `'*-redis'`, `'*-keycloak'`, `account-*`.

| Fault | Command | Models |
|---|---|---|
| `down` / `up` | `chaos C="down GLOB"` | the dependency is stopped: connection refused, immediately |
| `timeout` | `timeout GLOB [--ms N]` | a hung dependency or a black-holing firewall: connected, no answer (N ms, 0 = forever). Finds every missing timeout. |
| `latency` | `latency GLOB MS [--jitter MS]` | a slow network or an overloaded dependency |
| `reset-peer` | `reset-peer GLOB` | a connection killed in the middle (TCP RST) |
| `bandwidth` | `bandwidth GLOB KBPS` | a throttled link (uploads, big result sets) |
| `limit-data` | `limit-data GLOB BYTES` | the connection is cut after N bytes: truncated responses |
| `slow-close` | `slow-close GLOB MS` | connections that linger: pool exhaustion |

Several faults can sit on one proxy; `reset` removes them all (it also unpauses containers paused by a scenario).

## The scenarios

[`infra/chaos/scenarios/*.yaml`](../infra/chaos/scenarios): each one names a fault, a few requests through the gateway, and what the answer must be.
A scenario runs the requests first **without** the fault (a baseline that is already broken proves nothing), then repeats them during the fault,
then removes the fault and waits until the answers are normal again (recovery without a restart is part of the promise).

| Scenario | Fault | What must hold (source) |
|---|---|---|
| `media-down` | account to media down | avatar change answers a fast `503`, nothing changed; the rest of account works (account.yaml `setAvatar`) |
| `account-down` | catalog and notification to account down | wallpaper and search still `200` with the author snapshot (README section 8) |
| `account-slow` | account answers in 1.5 s | the 300 ms deadline fires; catalog answers in about a second, not 1.5 s per call (README section 8) |
| `elasticsearch-down` | Elasticsearch down | search `200` from the degraded Mongo query (README section 8, catalog.yaml `searchWallpapers`) |
| `elasticsearch-slow` | Elasticsearch hangs | the 2 s timeout ends the wait: `200` in under 6.5 s (README section 8) |
| `postgres-down` | account's database down | a fast `503`, never a `500` or a hang; catalog unaffected; the pool reconnects without a restart |
| `mongo-down` | catalog's database down | same, the other way round |
| `redis-down` | every Redis down | reads keep working, slower (this repo's rule; the README does not specify the policy of the rate limiter) |
| `keycloak-down` | Keycloak unreachable from the services | already valid tokens keep working: the signing keys are cached |
| `s3-down` | object storage down | an upload fails cleanly (`503`/`504`), asset metadata still readable |
| `kafka-paused` | Kafka container paused | writes still succeed (outbox), the lag shows on the dashboard and drains afterwards |

They are the acceptance tests of section 8 for a real implementation, in any language. A scenario that fails tells you which promise the service does not keep.
Add your own: copy a file, the keys are checked by `make chaos-check` (unknown proxy names, variables or keys are errors). Request paths may use `{wallpaper_id}`, `{wallpaper_word}`,
`{collection_id}`, `{<user>_id}`, `{<user>_avatar}` (from the seed data, `make seed-build`), `{rand}` and `{sample_image}`; `as:` picks the user (default `alice`, password `password`).

Environment: `CHAOS_BASE_URL` (the gateway, default `http://localhost:$PORT_GATEWAY`), `KEYCLOAK_URL`, `TOXIPROXY_URL`.

## A service you run from the IDE

A service in host mode ([GETTING-STARTED.md](GETTING-STARTED.md)) reaches its dependencies on `localhost` ports. To put it behind the proxies:

```
python3 scripts/chaos.py env catalog        # the variables of catalog, pointing at localhost:150xx
```

Paste them over your normal ones. The proxy ports (15000-15099) and the API (8474) are published on `BIND_ADDRESS` by `make up-chaos`.

## How it is wired (and what is deliberately not)

`infra/chaos/edges.yaml` is the single source. `make chaos-gen` writes from it `infra/chaos/toxiproxy.json` (the proxies) and `infra/docker-compose.chaos.yml`
(an overlay that adds the `toxiproxy` service and overrides, per service, only the variables that name a dependency: `DB_HOST`/`DB_PORT`, `MONGO_URI`, `ACCOUNT_GRPC_ADDR` ...).
Both are committed and `make chaos-check` (CI) fails when they are stale, when an upstream is not a service of `docker-compose.yml`, or when an overridden variable
does not exist there or names another host or port than the proxy's upstream. Without the overlay nothing changes.

Not proxied, on purpose:

- **Kafka.** A Kafka client reconnects to the broker address the broker advertises, so a proxy in front of the bootstrap address changes nothing. The scenario pauses the container instead.
- **The gateway's upstreams.** Envoy's upstream hosts are fixed in its config. To see the gateway with a dead upstream: `docker compose -p wallpaperhub pause account`, and `unpause` afterwards.
- **The `iss` claim.** Keycloak keeps issuing tokens for `http://localhost:8180`; only the back-channel calls (JWKS, token) of the services go through the proxy (`KC_HOSTNAME_BACKCHANNEL_DYNAMIC`).
- **Real third parties.** Outbound e-mail goes to Mailpit; the failover to a second provider of README section 8 is not testable with one SMTP sink.

## What is verified, what is not

Verified with real components: `toxiproxy-server` 2.12.0 (all seven faults through the CLI and `reset`, the proxy configuration file; the effect on real traffic was observed for `down`, `latency` and `timeout`, the other four were applied and listed but no traffic ran through them), the generator and its validation (mutation-tested:
wrong port, unknown host, port clash, unknown variable, unknown proxy in a scenario), and the scenario runner end to end: nine scenarios against stand-in services that call their
dependencies through the proxies with the README policy (timeouts, retries, fallback). A fault that changes nothing, a failing expectation, an exit code of 1 and the cleanup after a failed run were all exercised.

Not verified: the Docker side. There was no Docker daemon, so the `ghcr.io/shopify/toxiproxy:2.13.0` image, `compose config` with the overlay (CI runs it in `make lint`), the
overlay merge with the real compose file, and `docker compose pause` (the `kafka-paused` scenario) were not run. And no scenario ran against real services: there are none in the template yet,
which is the point: these are the checks they must pass. Expect to adjust the numbers (`max_ms_during`) to your implementation's retry policy.
