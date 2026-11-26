# 0020. One generic Helm chart for every service, with values generated from the compose file

- Status: Accepted
- Date: 2026-11-23

## Context

The four services and the gateway have the same shape on purpose ([SERVICE-SPEC](../SERVICE-SPEC.md)): HTTP on 8080, a management port 8081 with `/health/startup`, `/health/live` and `/health/ready`, gRPC on 9090 for account only,
configuration from environment variables. A team that adopts this template will run it on Kubernetes sooner or later, and a chart per service would be five copies of one Deployment that drift apart.
Compose is where the environment of each service is already defined and exercised by the e2e suite and the conformance suite ([0012](0012-conformance-suite-defines-what-a-service-is.md)): variables, memory limits, the names of the other services.
A second hand-written copy of that environment for Kubernetes would be wrong the first time somebody changes one and not the other.

## Decision

1. **One chart, `deploy/helm/service`, deploys any service of the template** (the four services, the gateway and the Prism mocks): a Deployment, a Service that also exposes the management port (Envoy health-checks its upstreams at `<service>:8081/health/ready`),
   a ServiceAccount, a Secret for the credentials in `secretEnv` (or `existingSecret` for a real cluster), and optional PodDisruptionBudget, HorizontalPodAutoscaler and Ingress. Probes use the three management endpoints.
   Pods get a restricted security context (seccomp `RuntimeDefault`, no privilege escalation, all capabilities dropped, no ServiceAccount token).
2. **What differs per service is a values file**, `deploy/helm/values/{apps,mocks}/<service>.yaml`, and `fullnameOverride` is the DNS name of the service (`account`, `media`, `catalog`, `notification`, `gateway`),
   so the fixed upstream hosts of `envoy.yaml` and the URLs in every service's environment work in the cluster unchanged.
3. **The values files are generated from `infra/docker-compose.yml`** by `scripts/k8s-gen.py`, committed, and checked for staleness ([0016](0016-generated-files-are-committed-and-checked-for-staleness.md)): `make k8s-gen`, `make k8s-check`.
   The same check fails when a host named in a variable is neither a Compose service nor a service of the chart, when a host of `envoy.yaml` has no values file, and when the kind configuration no longer publishes the gateway where Compose does.
4. **The chart validates its own values**: `values.schema.json` refuses unknown keys, so a typo is an error and not a setting that is silently ignored. `make k8s-lint` runs `helm lint --strict`, `helm template` and kubeconform on every values file and on the cases in `deploy/helm/service/ci/`.

## Consequences

- A new service needs a block in the compose file and nothing else: `make k8s-gen` produces its values, `make k8s-check` tells when that was forgotten.
- The cluster runs the environment that Compose runs. The cost is that the values files are a generated artefact to review as a diff, and that Compose features the generator does not translate (bind mounts other than `contracts/`, healthchecks, `depends_on`) stop it with a message instead of being dropped.
- The development defaults of `infra/.env.example` (database passwords, client secrets) are what the values files contain. They are meant for a local cluster. A real cluster supplies `existingSecret` and its own values, and the chart refuses nothing about that: it is a template, not a production deployment.
- Kubernetes-specific things that Compose never had (replicas, autoscaling, disruption budgets, ingress, resource requests) are chart options with conservative defaults and are not generated. Memory requests are half of the Compose limit and CPU requests are a flat 100m: a starting point to tune.
- `runAsNonRoot` is off by default because the kubelet cannot verify a non-numeric user in an image; a team that sets `USER 10001` in its Dockerfiles turns it on in `podSecurityContext`.
- The gateway's readiness is the aggregated health of its upstreams (`envoy.yaml`). When one service is down, the gateway leaves the Service endpoints and every route answers 503 instead of only that service's routes. That is the behaviour of the gateway in Compose too; change `envoy.yaml` if the cluster should behave differently.

## Alternatives considered

- **A chart per service** would let each team shape its own, at the price of five copies of the same template and no way to tell when they diverge.
- **Kustomize** needs a base and an overlay per service and has no schema for its inputs; the generic template plus a validated values file is shorter for services this alike.
- **Hand-written values files** are what most teams do and what drifts: the compose file is the one that the tests exercise.
- **Generating the manifests themselves** (a tool such as Kompose) hides the template behind an output nobody wants to maintain; a chart is the thing a team would write next.
