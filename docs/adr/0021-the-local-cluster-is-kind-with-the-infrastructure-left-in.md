# 0021. The local cluster is kind, with the infrastructure left in Compose

- Status: Accepted
- Date: 2026-11-23

## Context

The chart ([0020](0020-one-generic-helm-chart-for-every-service-with-values.md)) has to run somewhere before it reaches a real cluster, on a laptop that already runs Docker Desktop (WSL2) and the infrastructure of [GETTING-STARTED](../GETTING-STARTED.md):
PostgreSQL x3, MongoDB, Redis x2, Kafka with the schema registry, Elasticsearch, Keycloak, S3 and Mailpit. Their memory limits alone add up to about 5 GB; a typical developer machine has 16 GB.
Databases and brokers are also what a team runs as managed services in production, so putting them into a local cluster would test charts nobody will deploy.

## Decision

1. **The local cluster is [kind](https://kind.sigs.k8s.io)**: one node, created from `deploy/kind/kind-config.yaml`, which publishes the gateway's NodePort 30080 on `127.0.0.1:8080` (what Compose publishes, so `make e2e` and every URL in the documents are the same) and mounts `contracts/` into the node for the mocks.
2. **Only the services and the gateway run in the cluster; the infrastructure stays in Compose.** `scripts/k8s.sh` attaches the node's container to the Compose network (`docker network connect wallpaperhub_default`), so a pod resolves `keycloak`, `redis`, `kafka` ... by the same names a container does, with no change to any variable.
3. **Two modes**: `make k8s-up-mocks` (gateway and the four Prism mocks in the cluster; Keycloak and Redis in Compose, about 2 GB) and `make k8s-up-apps` (the real services; the whole infrastructure in Compose). The Compose gateway must not run at the same time, because both want port 8080; the script says so.
4. **CI runs the mocks mode** in its own job on a GitHub runner: kind creates the cluster, `make e2e` goes through it. The static part (render and schema validation) runs in the `static` job without a cluster.

## Consequences

- The cluster costs about what the gateway and four small Node processes cost, so it fits next to the infrastructure on a 16 GB machine; running the real services in it is bounded by their memory limits as in Compose.
- The services are tested in Kubernetes (probes, restarts, rolling updates, the security context, DNS), but not the infrastructure on Kubernetes. Whether Kafka or Keycloak runs well in a cluster is a different question that this repository does not try to answer.
- Pods reach Compose containers across two Docker networks through the node. This depends on how Docker resolves names for a container attached to two networks and on how kind forwards DNS; `make k8s-net` runs a probe pod that resolves and connects to the infrastructure and says what to check when it cannot.
- `kind load` copies images into the node; with Docker Desktop's containerd image store the direct load can fail, and the script falls back to an image archive.
- Compose recreating its network (`make down` and up) detaches the node; `make k8s-up-...` attaches it again, and `make k8s-net` says when it is detached.
- The Kubernetes version is the one that the pinned kind release ships; the schema version of `make k8s-lint` is set to match and is raised together with kind.

## Alternatives considered

- **Everything in the cluster** (infrastructure charts or operators) is the most faithful to a production cluster of self-hosted databases and the heaviest by far: it needs 5 GB more and the maintenance of charts that are not the subject of this template.
- **minikube or k3d** work as well; kind was chosen because it is widely used to test charts in CI, and it needs only Docker. The scripts would change in a few places, not in the chart.
- **Docker Desktop's built-in Kubernetes** needs no extra tool but cannot be created from a file, cannot be thrown away per branch or per CI run, and its single node is shared with whatever else the developer runs.
- **No cluster, only static checks** would catch a wrong manifest and miss the failure that matters: a service that does not start, or that is never ready, in a pod.
