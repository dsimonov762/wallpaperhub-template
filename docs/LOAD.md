# Load tests with k6

Functional tests say the API is right; they say nothing about what happens at 50 users, at 500, or after a night at 20. `loadtest/` is a [k6](https://k6.io)
suite that uses the platform the way the web app does (browse, search, favorite, inbox, GraphQL, upload) and judges it against a latency budget per operation.
It talks HTTP to the gateway only, so it works for every implementation language.

```
make up-load                        # real services, gateway limits raised (see below); WITH_OBS=1 adds Grafana
make load-smoke                     # every journey once, strict: does the harness work? (15 s)
make load-run P=load RATE=20        # 20 journeys/s (about 60 requests/s) for 5 minutes
make load-run P=stress              # double the rate every minute until it breaks
make load-run P=soak DURATION=1h    # the normal rate for an hour: leaks, pools, lag
```

`k6` is used when installed (`winget install k6`, `brew install k6`), otherwise the `grafana/k6` container. Without the real services: `make up-load-mocks`, then
`make load-run P=load SKIP=graphql` (the Prism mocks answer with fixed examples, so this tests the gateway, Keycloak and the harness, not the services).

## The profiles

| Profile | What it does | Passes when |
|---|---|---|
| `smoke` | every journey once with one user | not one failed request, not one 429, no check fails |
| `load` | ramp to `RATE`, hold for `DURATION` (5m), ramp down | error rate under 1%, every operation under its p95 budget, no 429 |
| `stress` | `RATE`, then 2x, 4x ... every `STEP` (1m), up to `MAX_RATE` (80) | under 5% errors all the way. The answer is in the graphs: where latency left the budget, what saturated first |
| `spike` | `RATE`, then `SPIKE`x (10) within 10 s for a minute, then back and two minutes of recovery | under 5% errors, budgets x3 |
| `soak` | `RATE` for `DURATION` (30m) | like `load`. Watch Grafana: memory, pools, outbox lag, disk |
| `uploads` | `UPLOAD_RATE` (0.5/s) uploads for `DURATION` (2m), then waits for the image processing | `upload_to_ready` p95 under 20 s (`UPLOAD_READY_P95`), none rejected or timed out. Needs `make load-data` |
| `ratelimit` | one user searches until the gateway says 429 | 429 after about 60 requests, with `Retry-After` and problem+json, and the user is served again after the wait. Needs the **shipped** limits (`make up-apps`) |

Settings (environment variables, or `make load-run P=load RATE=20 ...`): `RATE`, `DURATION`, `RAMP`, `STEP`, `MAX_RATE`, `SPIKE`, `THINK_TIME` (seconds between steps of a journey, default 0),
`SKIP` (journeys to leave out, e.g. `graphql,collections`), `WITH_UPLOADS=1` (add uploads to the mix), `BUDGET_SCALE` (2 = all budgets twice as wide, for a slow machine), `BASE_URL`, `KEYCLOAK_URL`.
The rest is at the top of `scripts/k6.sh`.

## What is simulated

A **journey** is a few related requests, like one screen of the app ([`loadtest/journeys.js`](../loadtest/journeys.js)); `RATE` counts journeys per second:

| Share | Journey | Requests |
|---|---|---|
| 40% | `browse` | list the catalog (page, category), open three wallpapers, an author |
| 15% | `search` | a word taken from the seed titles and tags, sometimes with facets, sometimes search-as-you-type |
| 10% | `favorites` | favorite a wallpaper of someone else, list favorites, un-favorite it (the state ends where it began) |
| 10% | `inbox` | notifications (all, or unread), notification preferences |
| 10% | `profile` | own profile, own avatar metadata and URL |
| 10% | `graphql` | the catalog page as one GraphQL query (`contracts/graphql/examples/wallpapers-page.graphql`) |
| 5% | `collections` | own collections |
| (3%) | `upload` | with `WITH_UPLOADS=1`: upload, then poll until READY |

The users are the seeded ones that can log in (`make seed-build` writes `seed/out/manifest.json`, `make seed` loads it into the stack); each virtual user logs in once with the password grant
and renews its token before it expires. The arrival-rate executors start journeys at the planned rate whatever the system answers, like real users do: if the system slows down, k6 reports
`dropped_iterations` instead of quietly sending less.

## The latency budget

[`loadtest/lib/routes.js`](../loadtest/lib/routes.js): one p95 per operation, named like the OpenAPI `operationId` (so thresholds, Grafana panels and the contract use the same word).
**The README defines no latency targets; the numbers are a starting point for a laptop.** Measure a baseline with `load`, then tighten them to what you promise.

Every response is also checked the way the contract says: status among the documented ones, JSON body, `application/problem+json` on every 4xx/5xx.

## The gateway's rate limits and `make up-load`

The shipped limits (600 requests per minute per client IP before authentication, 300 per user after it, 60 searches, 30 uploads ...) are right for production and wrong for a load test:
all requests of a test come from one IP, so a test would measure the limiter and nothing else (the `rate_limited` threshold exists to tell you: **any 429 fails the run**).
`make up-load` starts the stack with [`docker-compose.loadtest.yml`](../infra/docker-compose.loadtest.yml): the same `envoy.yaml` with every token bucket multiplied by 100
(`scripts/loadtest-gateway.py`, generated into `infra/loadtest/`, not committed, `LOAD_RL_FACTOR` to change) and 4 worker threads and 768 MB instead of 2 and 384 MB.
The limiter stays in the request path, only its numbers grow. `make up-apps` brings the production limits back. Envoy only: for a hand-written gateway raise its limits yourself.

## Reading a result

1. **The summary** at the end of the run: crosses mark thresholds that failed (exit code 99). `loadtest/.run/summary-<run>.json` keeps it.
2. **Grafana** (`make up-obs`, dashboard *Load test (k6)*; the runner pushes metrics to Prometheus when it answers and tags them with the run id, which the dashboard's *Run* list selects).
   It shows what k6 sent and measured, with the server's own numbers for the same minutes below (gateway, service p95, outbox and Kafka lag). The gap between the client p95 and the service p95 is the gateway, the network and the queue.
3. Is the test itself sound? *Dropped iterations* above zero means k6 or the system could not keep the planned rate; *Blocked/connecting* time growing means the generator or the network is the limit, not the services.
4. A latency that grows without errors is a queue somewhere; errors that start at a certain rate are the knee. Then go to the Service and Gateway dashboards ([OBSERVABILITY.md](OBSERVABILITY.md)) at the same moment.

## Uploads

`make load-data N=200` makes 200 unique pictures in `loadtest/.data/uploads/`: media rejects duplicates by SHA-256 and perceptual hash, so each upload needs a picture of its own, and the pictures of an
earlier run are already in the stack until `make reset`. Each virtual user holds its own slice, so uploads = pictures: `upload_pictures_exhausted` counts the uploads that had none left (raise `N`/`UPLOAD_POOL`).
Uploads create assets and wallpapers, and the image processing is CPU work: run `uploads` on its own, not inside `soak`.

## Limits of this suite

- **Data volume.** The seed has about 30 wallpapers. Caches, indexes and query plans behave very differently with 3 million. A real capacity test needs a bigger dataset; this suite finds regressions, saturation of the services and
  missing timeouts, not production capacity.
- **One machine.** k6, Docker, the services and the databases share one laptop. Absolute numbers are meaningful only as a baseline for the same machine; a regression between two runs on it is meaningful.
- No browser, no CDN, no SSE connections (the notification stream), no Keycloak login flow other than the password grant.

## What is verified, what is not

Verified with real components: k6 1.6.0 running every profile against the real Envoy (the repo's config, and the generated one with raised limits), real Keycloak and the Prism mocks (the REST journeys through the gateway;
smoke, load at 40 journeys/s, stress, uploads, ratelimit: exactly 60 searches served before the first 429, with `Retry-After` and problem+json, and the user served again after the wait); the shipped limits failing a `load` run
through the `rate_limited` threshold as designed; the remote-write output into a real Prometheus 3.16 and every query of the *Load test (k6)* dashboard against the series it produced.

Not verified: any of it against the real services (there are none in the template yet, so the budgets are untested guesses, and the GraphQL journey only ran as far as the mocks go: they serve no GraphQL),
Grafana's rendering of the new dashboard, the `grafana/k6:2.4.0` container and the `host.docker.internal` path of `scripts/k6.sh`, `make up-load` in Docker (the overlay, the 4-thread gateway), and the CI smoke step.
