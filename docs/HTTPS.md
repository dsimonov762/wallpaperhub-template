# HTTPS on your laptop (mkcert)

By default everything is `http://localhost`. That is fine for the services and for `curl`, and wrong for a front end: a browser treats an `https` page differently from an `http` one
(`Secure` cookies, mixed-content blocking, HTTP/2, OAuth providers that refuse `http` callbacks, service workers on a name other than `localhost`), and the first time a real HTTPS gateway
meets your code should not be production. [mkcert](https://github.com/FiloSottile/mkcert) makes a private certificate authority (CA) that **your** machine trusts and a certificate
from it, so the browser shows a normal padlock and no tool needs `-k`.

```
make certs ARGS=--install   # once per machine: create the CA, trust it (browsers, OS, Java), make the certificate
make certs                  # later: nothing to do while the certificate is current (it renews itself when under 30 days are left)

make up-apps                # as before
make up-https               # the same stack + the gateway also on  https://localhost:8443   (http://localhost:8080 keeps working)
make up-https HTTPS_ISSUER=1  # + Keycloak on https://localhost:8543, and every token's issuer moves there (see "Keycloak over https")
make up-https-mocks         # the same without the services, to try the TLS setup (also HTTPS_ISSUER=1)
make https-check            # the generator still fits services/gateway/envoy/envoy.yaml (CI runs it)
```

`make doctor` has an "HTTPS (optional)" section that tells you whether a current certificate exists.

## What you get

| | |
|---|---|
| `https://localhost:8443` | the gateway: the same routes, CORS, rate limits and error format as `:8080`. TLS 1.2 and 1.3, HTTP/2 (negotiated with ALPN; clients without it fall back to HTTP/1.1) |
| `https://localhost:8543` | Keycloak, only with `HTTPS_ISSUER=1` |
| the certificate | valid for `localhost`, `127.0.0.1`, `::1`, `host.docker.internal`, `gateway`, `keycloak`, `wallpaperhub.localhost` and `*.wallpaperhub.localhost` (`CERT_NAMES="..." make certs` replaces the list and makes a new one) |
| `infra/certs/` | `wallpaperhub.pem` + `wallpaperhub-key.pem` (the certificate, git-ignored) and `rootCA.pem`, the **public** certificate of your CA, which tools need (below). The CA's private key stays in mkcert's own folder (`mkcert -CAROOT`) and never enters the repo or a container |

`*.wallpaperhub.localhost` is there for front ends that want their own origin (`app.wallpaperhub.localhost`): browsers resolve every `*.localhost` name to your machine without a hosts file,
and the gateway's CORS list accepts `https://<name>.wallpaperhub.localhost` (with any port) as well as `https://localhost:5173`, `:4200` and `:8443`.

## Windows 11 + WSL

The browser lives in Windows, so the CA that matters is the one in the **Windows** trust store.

1. PowerShell: `winget install FiloSottile.mkcert`, then `mkcert -install` (Windows asks once to trust the CA).
2. Ubuntu (WSL): `sudo apt install mkcert`, then `make certs ARGS=--install`.

`scripts/certs.sh` sees that it runs in WSL, asks `mkcert.exe -CAROOT` where the Windows CA is, converts the path with `wslpath` and tells the Linux mkcert to use that same CA folder, instead of
creating a second CA that no browser trusts. If only `mkcert.exe` is installed, it uses that one. Firefox keeps its own store: mkcert adds the CA to it only when `certutil` is available, which on Windows it usually is not. Either import `rootCA.pem` (Settings > Privacy & Security > Certificates > View Certificates > Authorities > Import), or set `security.enterprise_roots.enabled` to `true` in `about:config` so that Firefox uses the Windows store.
Git Bash works with `mkcert.exe` alone.

## Who trusts the CA

Browsers and the OS do after `mkcert -install`. Command line tools and runtimes use their own lists, so give them `infra/certs/rootCA.pem`:

| Tool | How | In this repo |
|---|---|---|
| curl | `curl --cacert infra/certs/rootCA.pem https://localhost:8443/...` | `make token` and `scripts/token.sh` add it by themselves for an `https` Keycloak URL; without the file they print "make certs" |
| Hurl | `--cacert infra/certs/rootCA.pem` | `make e2e` adds it when `BASE_URL`/`KEYCLOAK_URL` is https, also for the container (the file is mounted) |
| k6 | `SSL_CERT_FILE=infra/certs/rootCA.pem` (Go reads it on Linux/macOS) | `make load-run` sets it for an https `BASE_URL`; native k6 on Windows uses the Windows store, which `mkcert -install` has already extended |
| Node | `NODE_EXTRA_CA_CERTS=infra/certs/rootCA.pem` | |
| Java | `mkcert -install` adds it to the JDK's `cacerts` it finds through `JAVA_HOME`. Otherwise a private store, which touches nothing global: `keytool -importcert -noprompt -alias wallpaperhub-mkcert -file infra/certs/rootCA.pem -keystore wallpaperhub-ts.p12 -storetype PKCS12 -storepass changeit`, then run with `-Djavax.net.ssl.trustStore=wallpaperhub-ts.p12 -Djavax.net.ssl.trustStorePassword=changeit -Djavax.net.ssl.trustStoreType=PKCS12` (this replaces the default store for that JVM, which is fine for a call to the local gateway) | |
| Python `requests` | `REQUESTS_CA_BUNDLE=infra/certs/rootCA.pem` | |
| Go | `SSL_CERT_FILE=infra/certs/rootCA.pem` | |
| Bruno | Settings > Preferences > Custom CA certificate: `infra/certs/rootCA.pem`; then set `baseUrl` (and, with `HTTPS_ISSUER=1`, `keycloakUrl`) of the environment you use to `https://localhost:8443` (`https://localhost:8543`) | |
| Postman, Insomnia | add `rootCA.pem` as a CA certificate in the settings | |

`make doctor` and `scripts/certs.sh --check` report the state without changing anything.

## Why the gateway does not send HSTS here

The shipped gateway config sends `Strict-Transport-Security: max-age=31536000; includeSubDomains` (README section 7), as production should. On `localhost` that header is a trap: browsers
remember it for the **host**, and a host is not a port. One visit to `https://localhost:8443` and from then on **every** `http://localhost:...` (the Vite dev server, Grafana, Keycloak on
`:8180`, anything) is silently rewritten to https for a year and fails with a certificate or "connection refused" error. The generated config therefore sends `max-age=0`, which also *deletes* an
HSTS entry that an earlier visit may have left. Everything else (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) is untouched. To see the real header, use the plain `http://localhost:8080` stack, where it is sent as shipped.

## How it is wired (and what is deliberately not)

`scripts/https-gateway.py` reads `services/gateway/envoy/envoy.yaml` and writes `infra/https/envoy.generated.yaml` (git-ignored): a copy of the `public` listener on port 8443 with the TLS settings
(`DownstreamTlsContext`, TLS 1.2 minimum, ALPN `h2` and `http/1.1`, the mkcert certificate), HSTS neutralised, and the `https://` twins of the CORS origins. `docker-compose.https.yml`
mounts it over `/etc/envoy/envoy.yaml` and publishes the port. The shipped `envoy.yaml` is not changed, so without `make up-https` nothing differs. When someone edits the places the
generator replaces text in (the HSTS value, the `http://localhost:8080` CORS entry, the JWT issuer line), `make https-check` fails and says which one (it does not silently produce a gateway without the header or the origin).

The same listener means the same everything: JWT validation, the rate limits, the problem+json error mapping, the access log. One difference follows from the copy: each listener has its own rate-limit buckets (measured: 10 registrations per minute on `:8080` **and** 10 on `:8443`), so a client that alternates ports gets both. Irrelevant on a laptop; it is one more reason why this overlay is for development only.

Not done, on purpose:

- **TLS between the gateway and the services, or between services.** The README's trust boundary is the gateway; inside the Docker network traffic is plain. mTLS between services is a platform decision (service mesh, SPIFFE), not something to fake with a development CA.
- **A different certificate for production.** `infra/certs` is for development only; production certificates come from your ingress or load balancer. The key is `chmod 644` so the non-root containers can read it: it is the key of a development CA that only your machine trusts, so treat `rootCA-key.pem` (in `mkcert -CAROOT`) as a secret, and do not install your mkcert CA on machines you do not own.
- **A hand-written gateway.** The overlay assumes the Envoy of this repo. If you replace it, terminate TLS in your gateway and skip `docker-compose.https.yml`.

## Keycloak over https (`HTTPS_ISSUER=1`)

Why you would want it: a front end served over https that logs in against an `http` Keycloak is blocked by the browser's mixed-content rules, and the secure-cookie behaviour of the real flow
(`SameSite`, `Secure`) differs. Why it is **not** the default: the issuer (the `iss` claim) is part of every token, and changing it changes tokens for everyone.

| | default | `HTTPS_ISSUER=1` |
|---|---|---|
| `iss` of a token | `http://localhost:8180/realms/wallpaperhub` | `https://localhost:8543/realms/wallpaperhub` |
| JWKS and token endpoints for the services | `http://keycloak:8080/...` | unchanged (back-channel inside the network stays plain) |
| gateway JWT issuer | as in `envoy.yaml` | the generated config says the new one |
| `OIDC_ISSUER_URI` of the four services | `http://localhost:8180/...` | `https://localhost:8543/realms/wallpaperhub` |
| Keycloak health check (port 9000) | plain | plain (`KC_HTTP_MANAGEMENT_SCHEME=http`; otherwise the management port would inherit https and the compose health check would fail) |
| `http://localhost:8180` | works | still works, but tokens from it are issued with the https `iss`, because the public URL is fixed by `KC_HOSTNAME` |

Consequences to know:

- **A service you run from the IDE (host mode)** must be given `OIDC_ISSUER_URI=https://localhost:8543/realms/wallpaperhub`, and its runtime must trust the CA **only if it fetches from that URL**.
  With the default `OIDC_JWKS_URI` (the back-channel on `localhost:8180`, see `infra/host/*.env`) it never does, and only compares the `iss` string. If your framework runs OIDC discovery from the issuer URL instead of using a configured JWKS URI, give it the CA (table above) or configure the JWKS URI explicitly.
- **Tokens for your own scripts**: `KEYCLOAK_URL=https://localhost:8543 make token`, `make e2e` and `make conformance` accept an https `KEYCLOAK_URL` and trust `infra/certs/rootCA.pem` by themselves (`BASE_URL=https://localhost:8443` for e2e). A service under conformance test is told its own issuer through `OIDC_ISSUER_URI`, as above; if the service fetches its keys from an https URL it needs the CA, the table above.
- The realm accepts the SPA client `web-spa` from `https://localhost:5173`, `:4200` and `:8443` in addition to the http origins (redirect URIs; its web origins are derived from them).

## Environment

| Variable (`infra/.env`) | Default | |
|---|---|---|
| `PORT_GATEWAY_TLS` | 8443 | published https port of the gateway |
| `PORT_KEYCLOAK_TLS` | 8543 | published https port of Keycloak (`HTTPS_ISSUER=1`) |
| `BIND_ADDRESS` | 127.0.0.1 | as for every other port: set `0.0.0.0` only knowingly, the certificate would then be presented to your network |
| `CERT_NAMES` | see above | names in the certificate (environment of `make certs`, not `.env`) |

When you change a port after the certificate was made, nothing needs regenerating: the certificate has no port. When you change `PORT_KEYCLOAK_TLS`, run `make up-https HTTPS_ISSUER=1` again (the issuer string changes).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Browser: "Your connection is not private" | the CA is not in that browser's store. `mkcert -install` (the Windows side in WSL), restart the browser. Firefox: see the note under Windows 11 + WSL (on Linux install `libnss3-tools` and run `mkcert -install` again) |
| `curl: (60) SSL certificate problem` | `--cacert infra/certs/rootCA.pem`, see the table. Do not use `-k`: it hides exactly the mistakes this setup exists to find |
| `make up-https`: "no current certificate" | `make certs` (the names or the CA changed, or less than 30 days are left) |
| The gateway (or Keycloak) container exits at start with a certificate or key error in `make logs S=gateway` | `infra/certs/*.pem` missing or unreadable: `make certs`, then `make up-https` again. A Docker bind mount of a file that did not exist creates an empty **directory** of that name: delete `infra/certs` and run `make certs` |
| Every `http://localhost:...` becomes https and fails | an old HSTS entry for `localhost` from another project. Chrome: `chrome://net-internals/#hsts`, "Delete domain security policies": `localhost`. This stack sends `max-age=0` and heals it itself on the first visit to `https://localhost:8443` |
| 401 from the gateway with a token that worked before | the stack was switched between `HTTPS_ISSUER=1` and the default: the issuer of old tokens no longer matches. Get a new one (`make token`) |
| Windows: `mkcert.exe` works, WSL says "no local CA" | run `make certs ARGS=--install` once from WSL, it maps the Windows CA; `mkcert.exe -CAROOT` must print a folder that contains `rootCA.pem` |
| Preflight from an origin that is not in the CORS list still gets an answer | the gateway only answers listed origins itself and passes the rest to the service, which decides (the Prism mocks echo any origin; Keycloak answers any preflight and enforces its web origins on the real request). A real service must not allow-list on its own: check it with `make conformance` |

## What is verified, what is not

Verified with real components (Envoy and Keycloak 26.8.2 binaries, mkcert, curl, Hurl, k6, Node, a JDK 21; no Docker daemon was available):

- `certs.sh` with a real mkcert on Linux: creation, idempotence, regeneration after a change of names and of CA, the expiry threshold.
- The generated Envoy config is accepted by `envoy --mode validate` and serves traffic: TLS handshake with the CA, HTTP/2 through ALPN and HTTP/1.1 fallback, a name that is not in the certificate is rejected, TLS 1.1 is refused, `max-age=0` on both listeners, the https CORS origins (including `*.wallpaperhub.localhost`).
- `make e2e` (the gateway suite, 29 requests) passes over https against the plain-http Keycloak **and** against Keycloak over https; `token.sh` fetches a token over https and trusts the CA by itself; a token with a damaged signature or payload gets 401, a token with the https issuer gets through on both listeners. The conformance self-test (reference stub in all four roles, five deliberately broken stubs caught) passes with Keycloak over https and the https issuer.
- Keycloak with `KC_HOSTNAME=https://localhost:8543`: the issuer in discovery and in the token, the back-channel discovery on `keycloak:8080` still answering, the management port staying plain.
- k6, Node and Java trust the CA through the variables above and fail with the expected error without them.

Not verified: the Docker side (the two compose overlays are validated by `docker compose config` in CI's `make lint`, but the containers, the bind mounts of `infra/certs` and their file permissions, and Keycloak's container image were not started: the sandbox ran Keycloak and Envoy as plain processes with the same settings), the WSL branch of `certs.sh` and `mkcert.exe` (no Windows host), any browser (the redirect flow of `web-spa` over https, Firefox's store), and the services in `HTTPS_ISSUER=1` mode (there are none yet in the template: `OIDC_ISSUER_URI` is a variable they must honour).
