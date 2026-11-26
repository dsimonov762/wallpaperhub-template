# Service conformance suite

Checks that a running service behaves like a Wallpaper Hub service, whatever language it is written in. The rules are
in [docs/SERVICE-SPEC.md](../docs/SERVICE-SPEC.md); this folder only tests them, over the network, the log output and
the observability stack.

```
make conformance SVC=account            # the container started by make up-apps
make wait-ready SVC=account             # first, if the container has just been started: waits for /health/ready (default 180 s)
make conformance-all                    # all four
make conformance SVC=catalog ARGS="--lifecycle"        # also C1 and S1 (this stops the service)
```

| Check | What | How |
|---|---|---|
| M1-M4 | health endpoints on 8081, none on 8080 | `http/10-management.hurl` |
| A0-A4 | no token, garbage, tampered signature, wrong audience are 401; a good token is not | `http/20-authentication.hurl` |
| E1-E6 | problem+json, de/es/en texts from `contracts/i18n`, `traceId`, `X-Request-Id`, page size > 100 refused | `http/30-errors.hurl` |
| E3, L3 | validation errors with field list (JSON or multipart create) | `http/31-validation-*.hurl` |
| L1-L3 | stdout is JSON with the required fields, carries the request's trace id, contains no secrets | `checks/logs.py` |
| T1-T3 | the request shows up in Tempo, Loki and Prometheus | `checks/telemetry.py` (needs `make up-obs`) |
| C1, S1 | fail fast on missing config, clean exit within 30 s of SIGTERM | `checks/lifecycle.sh` (opt-in) |

Needs Keycloak (realm imported) and Hurl (or Docker: the Hurl container is used then). Per-service parameters
(paths, which user, which foreign client for the audience check) are in `services/<name>.env`.

## While the service runs from the IDE (host mode)

```
make host SVC=account
# start the service with infra/host/account.env, logging to stdout:   my-service 2>&1 | tee service.log
make conformance SVC=account ARGS="--api http://localhost:8101 --mgmt http://localhost:8191 --log-file service.log"
```

Without `--log-file` and without a container the log checks are skipped (and listed as skipped). For C1/S1 on a
process: `SERVICE_CMD="./run-my-service" ./conformance/run.sh account --lifecycle`; the command runs with your
environment, C1 unsets one variable (`--require VAR`, default `OIDC_ISSUER_URI`).

Exit code: 0 all executed checks passed, 1 a check failed, 2 the suite could not run (no token, no Hurl).

## The reference stub

`reference-stub/stub.py` is a ~260 line Python program that satisfies the spec for any of the four services
(`OTEL_SERVICE_NAME`, `OIDC_*`, `HTTP_PORT`, `MGMT_PORT`). It is how the suite itself is tested: `BREAK=<ids>` makes
it violate chosen checks (`M4 A3 A4 E2 E4 E5 E6 L1 L2 L3 T C1 S1`) and the matching check must fail. It is not a
template for your service: it implements none of the domain.

```
pip install -r conformance/reference-stub/requirements.txt
OTEL_SERVICE_NAME=account-service OIDC_CLIENT_ID=account-svc OIDC_ISSUER_URI=http://localhost:8180/realms/wallpaperhub \
OIDC_JWKS_URI=http://localhost:8180/realms/wallpaperhub/protocol/openid-connect/certs HTTP_PORT=8101 MGMT_PORT=8191 \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 python conformance/reference-stub/stub.py
```
