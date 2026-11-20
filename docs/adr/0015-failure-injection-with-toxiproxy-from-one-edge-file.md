# 0015. Failure injection with Toxiproxy, from one file of edges

- Status: Accepted
- Date: 2026-11-20

## Context

The README promises behaviour when something fails: a 300 ms deadline towards account, a fallback to the author snapshot, a degraded search without Elasticsearch, a clean 503 when media is unreachable
([README 8](../../README.md#8-resilience)). On a laptop nothing fails, so nobody learns whether the promise is kept until production does it ([CHAOS](../CHAOS.md)).

## Decision

`make up-chaos` puts [Toxiproxy](https://github.com/Shopify/toxiproxy) between every service and what it depends on (databases, Redis, Keycloak, Elasticsearch, S3, other services). The edges are listed once, in
[`infra/chaos/edges.yaml`](../../infra/chaos/edges.yaml); the Toxiproxy configuration and a compose overlay that rewires only the variables naming a dependency are generated from it and committed ([0016](0016-generated-files-are-committed-and-checked-for-staleness.md)).
Scenarios (`make chaos-run S=...`) inject a fault, probe the behaviour the README promises, remove the fault and wait for recovery.

## Consequences

- `make chaos-check` (CI) fails when the generated files are stale, when an upstream is not a service of `docker-compose.yml`, or when an overridden variable does not exist there or names another host or port than the proxy's upstream. Without the overlay nothing changes.
- Some things are not proxied, on purpose: Kafka (a client reconnects to the address the broker advertises, so a proxy at the bootstrap address changes nothing; the scenario pauses the container), the gateway's upstreams (fixed in `envoy.yaml`),
  the token issuer, and real third parties (mail goes to Mailpit).
- Resilience becomes testable and checkable in CI terms, but only for the edges in the file; a new dependency of a service needs a new edge.

## Alternatives considered

Pausing or stopping containers, which is what the scenarios do where a proxy cannot help, but which cannot add latency or accept a connection and never answer, the failure that exposes missing timeouts.
