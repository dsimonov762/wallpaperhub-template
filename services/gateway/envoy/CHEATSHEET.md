# Gateway (Envoy) cheat sheet

README concept -> where it lives in `envoy.yaml`. The same table, filled in for other gateways, makes the
implementations comparable side by side.

| README 3.1 concept | Envoy feature | Where in `envoy.yaml` |
|---|---|---|
| Route table, first match wins | `route_config.virtual_hosts[].routes` (order matters) | `routes:` under listener `public` |
| `/users/me/favorites` before `/users/**` | route order | `path: /api/v1/users/me/favorites`, declared before `/api/v1/users` |
| Coarse JWT check (signature, `iss`, `exp`) | `jwt_authn` HTTP filter, JWKS from Keycloak | filter `envoy.filters.http.jwt_authn`, cluster `keycloak` |
| Public endpoints | per-route `jwt_authn` `disabled: true` | registrations, `/api/v1/auth`, `/docs` |
| SSE/WebSocket with one-time ticket | per-route requirement `valid_if_present` | route `/api/v1/notifications/(stream\|ws)` |
| Forward original `Authorization` | `provider.forward: true` | `providers.keycloak` |
| Strip client `X-User-*` | Lua filter | filter `envoy.filters.http.lua` |
| `X-Request-Id`, root `traceparent`, root span | `generate_request_id`, OpenTelemetry tracer (OTLP to Alloy) | HCM `tracing`, cluster `alloy_otlp` |
| Global + per-route rate limit | `local_ratelimit` token bucket, per-route override | filter `local_ratelimit`, `typed_per_filter_config` on routes |
| Per-route timeout | `route.timeout` | every route (media 60 s, SSE/WS 0 = off) |
| Body limit | `buffer` filter, per-route override | default 1 MiB, media 35 MiB, SSE/WS disabled |
| Retries for idempotent methods only | `retry_policy.retriable_request_headers` on `:method` | anchor `&idempotent_retry` |
| Circuit breaker per upstream | cluster `circuit_breakers` + `outlier_detection` | each cluster (shared anchors) |
| CORS | `cors` filter + `CorsPolicy` | virtual host `typed_per_filter_config` |
| Security headers | `response_headers_to_add` | virtual host |
| Compression | `compressor` (gzip), JSON/HTML only | filter `compressor` (SSE is not compressed) |
| No buffering / no idle timeout for SSE | `timeout: 0s`, `idle_timeout: 0s`, buffer disabled | route `/api/v1/notifications/(stream\|ws)` |
| WebSocket `Upgrade` | HCM `upgrade_configs` | HCM of `public` |
| GraphQL subscriptions (optional) | route on `Upgrade: websocket` before plain `/graphql`: no timeouts, token optional at the edge | second `/graphql` route |
| Structured access log | `access_log` with `json_format` | HCM of `public` |
| Errors as problem+json | `local_reply_config` mappers | HCM of `public` |
| Aggregated `/health` | `health_check` filter + active HTTP health checks | `cluster_min_healthy_percentages`, cluster `health_checks` |
| Management port, `/metrics` | second listener, route to the admin interface | listener `management` |
| Aggregated `/docs` | `direct_response` Swagger UI + per-service spec routes | routes under `/docs` |

## Contract the services must honour

- `GET :8081/health/ready` answers 200 only when the service can serve traffic (Envoy polls it every 5 s).
- `GET :8080/openapi.json` returns the service's OpenAPI document (used by `/docs`).
- Services keep validating the JWT themselves (zero trust). The gateway checks signature, issuer and expiry only,
  not audience or roles.

## Known differences from the README

- **Rate limits are per client but per gateway instance, and not in Redis.** Every client gets its own token bucket
  (client IP before authentication, user id after it), so one client cannot use up the budget of the others.
  The buckets live in the memory of one Envoy process: with N gateway instances the limits are N times higher
  and a restart resets them. The README's Redis-backed shared counters need Envoy's global rate limit service
  (`envoyproxy/ratelimit` plus Redis) or the hand-written gateway. Behind a load balancer set
  `xff_num_trusted_hops` on the connection manager, otherwise the client IP is the balancer's.
- **`/health` returns a status code only.** Which upstream is unhealthy shows in
  `http://localhost:8190/metrics`, for example `envoy_cluster_membership_healthy{envoy_cluster_name="account"}`.
- **Gateway-generated errors are localized from the i18n bundles** (`de`, `es`, English otherwise, decided by the first
  tag of `Accept-Language`; `Content-Language` says which). The mappers in `envoy.yaml` are generated:
  `python3 scripts/gen-gateway-errors.py` after changing a `problem.*` text. Only 401, 404, 413, 429 and 502-504 are
  localized; any other gateway error stays the generic English `about:blank` problem.
- **TLS termination is not configured.** Add a `transport_socket` (DownstreamTlsContext) to the `public` listener
  when you want HTTPS locally.
- **The README route table has no entry for `POST /admin/notifications/test`**; it is routed to
  notification-service here.

## Rate limits as shipped

Two `local_ratelimit` filters: the first runs before the JWT check and keys on the client IP, the second runs after it
and keys on the user id (`sub`), or on the IP for requests without a token.

| Route | Limit per client and minute | Keyed by |
|---|---|---|
| any request (before authentication) | 600 | IP |
| default (after authentication) | 300 | user, else IP |
| `/api/v1/registrations` | 10 | IP |
| `/api/v1/auth/**` | 30 | IP |
| `/api/v1/media/**` | 30 | user |
| `/api/v1/wallpapers/search` | 60 | user |

Each filter also has one shared bucket of 6000 per minute as an emergency valve, far above normal load.
Tune the `descriptors[].token_bucket` values in `envoy.yaml` (rebuild the image afterwards). For load tests raise
them. Requests without a valid token are answered 401 before the per-user limiter, so the per-IP limiter is what bounds them.
Behind Docker Desktop every local request comes from the same address, so per-IP limits cannot be tried with
several clients locally.
