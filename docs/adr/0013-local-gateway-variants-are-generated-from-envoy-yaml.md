# 0013. Local gateway variants are generated from envoy.yaml, never forked

- Status: Accepted
- Date: 2026-11-20

## Context

Two development modes need a gateway that differs from the shipped one: load tests need the rate limits raised ([LOAD](../LOAD.md)), and local HTTPS needs a TLS listener ([0014](0014-local-https-with-mkcert-opt-in-and-plain-http-inside.md)).
A copy of `envoy.yaml` edited by hand for each mode would drift from the original: a new route or a changed policy would exist in one gateway and not in the other, and nobody would notice.

## Decision

The variants are **generated from [`envoy.yaml`](../../services/gateway/envoy/envoy.yaml) by a script** (`scripts/loadtest-gateway.py`, `scripts/https-gateway.py`) and mounted over it by a compose overlay
(`docker-compose.loadtest.yml`, `docker-compose.https.yml`). The shipped file is not changed, so without the overlay nothing differs. The generated files are git-ignored.

## Consequences

- A variant has the same routes, JWT validation, rate limits and error mapping as the shipped gateway, because it is the same text with a few replacements.
- The generators replace exact text (the HSTS value, a CORS origin, the issuer line, the rate-limit numbers). When someone edits those places, `make load-check` and `make https-check` fail and say which one, instead of producing a gateway without the header or the origin. CI and a git hook run them.
- Editing those places in `envoy.yaml` means updating the generator in the same change.
- Differences that follow from the copy exist and are documented: each listener has its own rate-limit buckets, so a client that alternates ports gets both. These overlays are for development only.
- The overlays assume the Envoy of this repository. A team that replaces the gateway ([0011](0011-the-gateway-is-an-envoy-configuration.md)) drops them.

## Alternatives considered

A hand-maintained second configuration file per mode, which is the drift described above.
