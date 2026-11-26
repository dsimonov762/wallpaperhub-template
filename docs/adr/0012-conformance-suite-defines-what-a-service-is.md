# 0012. A conformance suite defines what a service is

- Status: Accepted
- Date: 2026-11-20

## Context

Services in any language are supposed to be interchangeable ([0001](0001-contract-first-with-a-shared-contracts-folder.md)). OpenAPI says what the endpoints look like, but not how a service behaves as a part of the platform:
its ports, health endpoints, configuration variables, token validation, error format, log format, correlation headers, telemetry, shutdown and container image.

## Decision

The behaviour that the gateway, Prometheus, Kubernetes-style probes and other teams rely on is written down in [SERVICE-SPEC.md](../SERVICE-SPEC.md), with an ID for each checkable item (`M1`, `A3`, `T2` ...),
and **`conformance/` checks those items against any running service**: `make conformance SVC=account`. A service is "any folder with a Dockerfile that passes the spec" ([CI](../CI.md)).

## Consequences

- "Does the Go account-service behave like the Java one" is answered by a command, not by reading code. CI runs it for every implementation under `services/<service>/<implementation>/` (`service.yml`).
- The suite is itself tested: `make conformance-selftest` runs it against a throw-away Python stand-in (`conformance/reference-stub/`), which must pass as each of the four services, and against deliberately broken variants, which must be caught.
- The spec and the suite change together, and the reference stub has to keep passing; that is work whenever a requirement is added.
- Passing is not correctness. The suite does not test business behaviour (that is the e2e suite and a service's own tests), resilience policies (the failure scenarios) or authorization rules beyond A1 to A4 ([SERVICE-SPEC 13](../SERVICE-SPEC.md#13-what-conformance-does-not-check)).
- MUST items are checked or required for the stack to work; SHOULD items are expected and not checked.

## Alternatives considered

A written specification alone would drift from the implementations, and checking only through the e2e suite would test the whole system rather than one service in isolation.
