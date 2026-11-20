# 0014. Local HTTPS with mkcert: opt-in, and plain HTTP inside the network

- Status: Accepted
- Date: 2026-11-20

## Context

By default the stack is `http://localhost`, which suits services and `curl` and is wrong for a front end: browsers treat https pages differently (`Secure` cookies, mixed content, HTTP/2, OAuth providers that refuse `http` callbacks),
and the first time a real HTTPS gateway meets the code should not be production ([HTTPS](../HTTPS.md)). The developers work on Windows with WSL, where the browser and the shell live on different sides.

## Decision

HTTPS is **opt-in**: `make up-https` adds a listener on `https://localhost:8443` next to `http://localhost:8080`, with a certificate from [mkcert](https://github.com/FiloSottile/mkcert), a private CA that the developer's own machine trusts.
Keycloak can move to https as well (`HTTPS_ISSUER=1`). Inside the Docker network, traffic stays plain HTTP: the trust boundary is the gateway ([0009](0009-the-gateway-validates-tokens-and-services-validate-them-again.md)).
The generated gateway sends `Strict-Transport-Security: max-age=0`.

## Consequences

- No tool needs `-k`. `scripts/certs.sh` sets up the CA, trusts it for browsers, the OS and Java, and under WSL it reuses the CA of the Windows side, so one CA serves both. The CA's private key never enters the repo or a container.
- HSTS is neutralised on purpose: browsers remember it for the **host**, not the port, so one visit to `https://localhost:8443` would turn every `http://localhost:...` (the dev server, Grafana, Keycloak) into https for a year. `max-age=0` also deletes an entry left by an earlier visit.
  To see the real header, use the plain http stack ([HTTPS, why no HSTS](../HTTPS.md#why-the-gateway-does-not-send-hsts-here)).
- Not done, on purpose: TLS between the gateway and the services or between services (mTLS is a platform decision, such as a service mesh, and a development CA would only fake it); a production certificate (`infra/certs` is for development, and the key of the CA is a secret on the machine that made it);
  a hand-written gateway ([HTTPS, what is not wired](../HTTPS.md#how-it-is-wired-and-what-is-deliberately-not)).
- With Keycloak on https the token issuer changes, so every service that checks `iss` must be configured accordingly; the document says how.
- The generator is one of the variants of [0013](0013-local-gateway-variants-are-generated-from-envoy-yaml.md).

## Alternatives considered

Plain http everywhere stays the default and still works. A separate self-signed certificate for every tool would need `-k` or a trust setting in each of them.
