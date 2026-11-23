# Kubernetes (Helm chart and a local kind cluster)

The services and the gateway can run in a Kubernetes cluster. The repository ships **one generic Helm chart** for all of them and a **local kind cluster** to try it on; the infrastructure (databases, Kafka, Keycloak ...)
stays in Docker Compose. The decisions behind this: [0020](adr/0020-one-generic-helm-chart-for-every-service-with-values.md) and [0021](adr/0021-the-local-cluster-is-kind-with-the-infrastructure-left-in.md).

```
deploy/
├── helm/service/          the chart: Deployment, Service, ServiceAccount, Secret, optional PDB / HPA / Ingress; values.schema.json; ci/ (cases for lint)
├── helm/values/apps/      generated: account, media, catalog, notification, gateway      (make k8s-gen)
├── helm/values/mocks/     generated: the four Prism mocks, named as the services they stand for
└── kind/kind-config.yaml  the local cluster: the gateway on localhost:8080, contracts/ mounted for the mocks
scripts/k8s.sh             up / down / status / check / logs / dump        scripts/k8s-gen.py   compose -> values        scripts/k8s-lint.sh   helm lint + template + kubeconform
```

## Try it

You need `kind`, `kubectl` and `helm` (4, or 3.18+) next to Docker Desktop; `make doctor` says what is missing. `scripts/k8s.sh` creates `.venv-validate` itself when it is missing. Nothing else changes: Compose still runs the infrastructure.

```
make k8s-up-mocks      # Keycloak and Redis in Compose (started for you), the gateway and the four Prism mocks in kind   ~2 GB
make k8s-net           # a probe pod resolves and connects to Keycloak and Redis by name
make e2e               # the gateway suite, unchanged: http://localhost:8080 is the gateway in the cluster now
make k8s-status        # deployments, pods, services
make k8s-logs S=gateway
make k8s-down          # delete the cluster; Compose keeps running
```

`make k8s-up-apps` does the same with the real services (`services/<name>/<impl>` must exist): `make up` (the whole infrastructure and the schemas) and the five deployments in kind.

- The **Compose gateway must not run** at the same time (both publish port 8080). `make k8s-up-...` refuses and prints the command that stops it.
- The first `make k8s-up-...` builds the images with Compose, creates the cluster and loads the images into it; the next ones reuse the cluster and only reinstall the releases (`helm upgrade --install`), so a code change is: rebuild, `make k8s-up-apps` again (`scripts/k8s.sh up apps --no-build` skips the build).
- Switching between mocks and apps is the same command with the other target; the releases are replaced in place.
- `make k8s-down` deletes the cluster and with it everything in it. Pointing `kubectl` at it by hand: `kubectl --context kind-wallpaperhub -n wallpaperhub get pods`.

## How the cluster reaches the infrastructure

The services read `keycloak:8080`, `kafka:29092`, `postgres-account:5432` ... from their environment, as in Compose. `scripts/k8s.sh` attaches the cluster's node container to the Compose network (`wallpaperhub_default`),
and kind forwards the cluster's DNS to Docker's, which knows those names, so the pods resolve and reach them without any variable changing. The services in the cluster have the Compose names too (`fullnameOverride`: `account`, `media`, `catalog`, `notification`, `gateway`),
which is what `envoy.yaml` and the services' own URLs expect.

The token issuer stays `http://localhost:8180/realms/wallpaperhub` (what a browser or `make token` sees); the pods fetch the signing keys from `keycloak:8080`, exactly as the containers do.

## The chart

One chart, `deploy/helm/service`; what differs per service is a values file. The defaults follow [SERVICE-SPEC](SERVICE-SPEC.md):

| | default |
|---|---|
| ports | `http` 8080, `management` 8081, `grpc` off (account sets 9090). The Service exposes all of them: Envoy health-checks `<service>:8081/health/ready` |
| probes | startup `/health/startup` (up to 3 minutes), liveness `/health/live`, readiness `/health/ready`, all on the management port |
| termination | `terminationGracePeriodSeconds: 40` (the spec asks for an exit within 30 s of SIGTERM) |
| rollout | RollingUpdate, `maxUnavailable: 0`, `maxSurge: 1` |
| resources | request 100m CPU and half of the memory limit, limit = the Compose `mem_limit`; no CPU limit |
| security | seccomp `RuntimeDefault`, no privilege escalation, all capabilities dropped, no ServiceAccount token mounted. `runAsNonRoot` is off until your images use a numeric `USER` |
| secrets | `secretEnv` (development defaults) become a Secret; for a real cluster set `existingSecret` and leave `secretEnv` out. A change of `secretEnv` restarts the pods |
| optional | `podDisruptionBudget`, `autoscaling` (HPA v2), `ingress`, `extraEnv`, `extraVolumes`, `nodeSelector`, `affinity`, `tolerations` |

`values.schema.json` refuses keys the chart does not know, so a typo fails `helm template` instead of being ignored. The complete list of values is `deploy/helm/service/values.yaml`; `ci/full.yaml` switches every option on.

### Generated values

`deploy/helm/values/{apps,mocks}/*.yaml` are generated from `infra/docker-compose.yml` by `scripts/k8s-gen.py` and committed ([0016](adr/0016-generated-files-are-committed-and-checked-for-staleness.md)):
the image, the memory limit, the ports, and every environment variable (credentials, meaning names ending in `SECRET`, `PASSWORD`, `TOKEN`, `_KEY` or URLs with a password, go to `secretEnv`; `${VAR:-default}` becomes the default).

```
make k8s-gen      # after changing a service's environment, port or memory limit in infra/docker-compose.yml
make k8s-check    # CI and a hook: the files are current, and
                  #   - every host that a variable names is a Compose service or a service of the chart
                  #   - every upstream host of envoy.yaml is a service of the chart
                  #   - kind-config.yaml publishes the gateway where Compose does (NodePort 30080 -> PORT_GATEWAY) and mounts contracts/
```

A Compose feature the generator cannot translate (a bind mount other than `contracts/`) stops it with a message. Edit the values by hand only for what Kubernetes adds (replicas, ingress ...), in a separate file passed with a second `-f`.

## Checks

`make k8s-lint` (needs `helm` and `kubeconform`) runs, for every values file and for each case of `deploy/helm/service/ci/`: `helm lint --strict`, `helm template`, and kubeconform with the schemas of the Kubernetes version that the pinned kind ships.
It also checks that the schema refuses an unknown key. `make k8s-check` needs neither tool. Both run in the `static` job of CI and as pre-commit hooks (`wh-k8s`; `wh-k8s-lint` skips with a note when a tool is missing).
The `kubernetes` job of CI starts the mocks mode in a kind cluster on the runner and runs `make e2e` through it, then `make k8s-net`.
`kubeconform` is installed by `scripts/ci/install-kubeconform.sh ~/.local/bin` if you want the same locally.

## Beyond the laptop

The chart is a template for your own deployment, not a production setup. What changes there: the image repository and tag (`image.repository`, `image.tag`, `imagePullSecrets`), `existingSecret` with credentials from your secret store,
the infrastructure endpoints in `env` (managed databases instead of the Compose names), `ingress` instead of the NodePort (`service.type: ClusterIP`), `replicaCount` or `autoscaling`, `podDisruptionBudget`, and a numeric non-root `USER` with `runAsNonRoot: true`.
Remember what [the decision](adr/0020-one-generic-helm-chart-for-every-service-with-values.md) says about the gateway's readiness (it follows its upstreams) and about the rate-limit counters, which live in each gateway replica (the known gap in [GETTING-STARTED](GETTING-STARTED.md)).

## When something does not work

| Symptom | Cause / fix |
|---|---|
| `the Compose gateway runs and holds port 8080` | `make k8s-up-...` found a running Compose gateway; stop it with the command it prints |
| `kind could not create the cluster` | port 8080 is taken (`docker ps` shows by whom), or Docker Desktop has too little memory (`make doctor`) |
| `could not load the images into the cluster` | Docker Desktop > Settings > General > *Use containerd for pulling and storing images*: switch it off and build again. The script already tries an image archive after the direct load fails |
| a pod is `ImagePullBackOff` for `wallpaperhub/...:local` | the image was not loaded: run `make k8s-up-...` again without `--no-build` |
| deployments do not become available | `make k8s-up-...` prints the pods, the last events and logs of the ones that are not ready. Afterwards: `make k8s-logs S=<service>`, `kubectl --context kind-wallpaperhub -n wallpaperhub describe pod <pod>` |
| a Spring service restarts during start-up | the startup probe allows 3 minutes; a service that needs longer raises `probes.startup.failureThreshold` |
| `make k8s-net` fails | the infrastructure is down (`make ps`), or Compose recreated its network after the cluster was built (`make k8s-down`, then up again), or DNS: see below |
| `make e2e` cannot connect | `make k8s-status`: is the `gateway` pod ready? The gateway is ready only when its upstreams are (their `/health/ready`) |

### When a pod cannot reach the infrastructure

First find out which step fails:

```
docker network inspect wallpaperhub_default --format '{{range .Containers}}{{.Name}} {{end}}'    # does it list wallpaperhub-control-plane?
docker exec wallpaperhub-control-plane getent hosts keycloak                                       # does the node resolve the Compose names?
kubectl --context kind-wallpaperhub -n kube-system logs -l k8s-app=kube-dns --tail=20             # CoreDNS: timeouts to the upstream?
```

The node missing from the network: `make k8s-up-...` attaches it. The node resolves, the pods do not: CoreDNS cannot reach Docker's resolver from the pod network (it works on Docker Desktop with WSL2 and on GitHub runners, so a failure points at your Docker or kind version; keep the output of the three commands above). The alternative is to run the infrastructure in the cluster too ([0021](adr/0021-the-local-cluster-is-kind-with-the-infrastructure-left-in.md) says why that is not what the repository does); the charts for that are yours to choose.

## What is verified, what is not

Run for real (on Docker Desktop with WSL2, and in the `kubernetes` job of CI on a GitHub runner): `make k8s-check`, `make k8s-lint`, `make k8s-up-mocks` (the cluster, the image load, the five deployments becoming ready), `make k8s-net`
(the pods resolve and reach Keycloak and Redis in Compose through the node's second network) and `make e2e` through the gateway in the cluster. CI needed three fixes that came from those runs and are in the repository now:
the Envoy image is told to run as the user it is given (`ENVOY_UID: "0"` in the compose file and the gateway's values: its entrypoint otherwise tries to `chown` and drop privileges, which fails when every capability is dropped),
the Prism mocks answer `/health/startup` as the chart's startup probe asks, and `scripts/k8s.sh` uses the same virtual environment as the generators because a bare `python3` has no PyYAML.

Also checked while the chart was written, without a cluster: the templates were rendered by a Go `text/template` stand-in for Helm and every object passes kubeconform (strict); selectors, probe ports, Service target ports and Secret keys were cross-checked;
`values.schema.json` rejects an unknown key, a NodePort outside 30000-32767 and a bad name; `scripts/k8s-gen.py --check` catches a stale file, a host that does not exist and a kind configuration that no longer matches.

**Not verified:** `make k8s-up-apps` (the template ships no real services yet, so only the mocks mode has run), the image-archive fallback of `kind load` (the direct load worked), and any real cluster other than kind. `ENVOY_UID: "0"` means Envoy runs as root without capabilities in the container;
a cluster that forbids root needs an Envoy image or a security context that runs it as a numeric non-root user.
