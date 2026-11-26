# 0011. The gateway is an Envoy configuration

- Status: Accepted
- Date: 2026-11-20

## Context

The README allows two kinds of gateway: an off-the-shelf one (Envoy, Traefik, Kong or Spring Cloud Gateway) or a thin hand-written one per language as an exercise. The roadmap says "off-the-shelf first,
then a hand-written version" ([README 3.1](../../README.md#31-api-gateway), [roadmap](../../README.md#17-roadmap)). The gateway must route, pre-validate JWTs, strip identity headers, rate-limit,
pass SSE and WebSocket through unbuffered, and map its own errors to the problem+json format.

## Decision

The default gateway is **Envoy**, as a configuration file ([`services/gateway/envoy/envoy.yaml`](../../services/gateway/envoy/envoy.yaml)) and a small Dockerfile, not a service with code.
The [service specification](../SERVICE-SPEC.md) applies to the four domain services and says so: the gateway is an Envoy config, not a service.

## Consequences

- There is nothing to port to another language, and the same gateway fronts every combination of implementations. The gateway checks of the e2e suite run against it, with mocks or real services.
- The route order matters (first match wins, `/users/me/favorites` before `/users/**`) and lives in one file, which scripts read: [0013](0013-local-gateway-variants-are-generated-from-envoy-yaml.md) builds on that.
- The shipped configuration keeps one in-memory rate-limit bucket per client in each gateway instance, not the shared Redis counters the README describes. They multiply with the number of instances and reset on a restart;
  Envoy's global rate-limit service would fix that and is not added ([GETTING-STARTED, what is missing](../GETTING-STARTED.md#8-what-is-still-missing-for-a-finished-template)).
- Its upstream hosts are fixed in the configuration, which is why failure injection cannot sit in front of them ([0015](0015-failure-injection-with-toxiproxy-from-one-edge-file.md)).
- The localized error mappers of the gateway are generated from the i18n bundles and checked against them (`scripts/gen-gateway-errors.py`).
- The hand-written gateway exercise is still open: `services/gateway/<implementation>/` would have to pass the same e2e gateway suite.

## Alternatives considered

Traefik, Kong and Spring Cloud Gateway are named in the README as equally valid. This template did not evaluate them against Envoy; a team that prefers one of them writes a record that supersedes this one.
