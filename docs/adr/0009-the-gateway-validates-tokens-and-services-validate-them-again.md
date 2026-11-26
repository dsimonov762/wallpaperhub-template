# 0009. The gateway validates tokens, and every service validates them again

- Status: Accepted
- Date: 2026-11-20

## Context

All client traffic enters through the gateway, which can reject a bad token early and cheaply. But a service reachable only through the gateway today may be reached directly tomorrow
(another network, a misconfigured route, a service called by a job). The README states the principle as zero trust inside the network ([README, principles](../../README.md#1-principles)).

## Decision

The gateway pre-validates the JWT (signature, `iss`, `exp`) and rejects obviously bad tokens; it strips client-supplied `X-User-*` headers and forwards the original `Authorization` header. **Every service validates the
token again**, fully (signature against the cached JWKS, `iss`, `aud`, `exp`/`nbf`, `typ`), and makes the authorization decision ([README 3.1](../../README.md#31-api-gateway), [README 7](../../README.md#7-security)).

## Consequences

- The conformance suite checks this on every service, directly and without the gateway: no token, a garbage token, a token with a damaged signature and a token for another audience must all get `401` ([SERVICE-SPEC 4](../SERVICE-SPEC.md#4-authentication-and-authorization), A1 to A4).
- Every language implements JWT validation with JWKS caching and key rotation, which is part of what the template compares.
- A token is checked twice on each request, a small cost the design accepts.
- Authorization (roles, permissions, ownership) stays in the services; the gateway never decides it. Services must not trust identity headers.
- The gateway can be replaced ([0011](0011-the-gateway-is-an-envoy-configuration.md)) without weakening the services.
