#!/usr/bin/env bash
# The local Kubernetes cluster (kind) for the Wallpaper Hub services.   docs/KUBERNETES.md
#
#   scripts/k8s.sh up mocks|apps [--no-build]   build the images, create the cluster, install the charts, wait until they are ready
#   scripts/k8s.sh down                         delete the cluster (Compose is not touched)
#   scripts/k8s.sh status                       what runs in the cluster
#   scripts/k8s.sh check                        can the pods reach the Compose infrastructure by name? (a probe pod resolves and connects)
#   scripts/k8s.sh logs <service> [kubectl-logs args]
#   scripts/k8s.sh dump [DIR]                   objects, events and the logs of every pod in a folder (CI uploads it when a run fails)
#
# The infrastructure (Keycloak, Redis, the databases, Kafka ...) stays in Compose, see ADR 0020: this script attaches the cluster's node to
# the Compose network, so a pod resolves keycloak, redis, kafka ... exactly as a container does. The gateway is published on
# http://localhost:8080 as in Compose (kind-config.yaml), so run it instead of the Compose gateway, not next to it.
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd -P)"

CLUSTER="${K8S_CLUSTER:-wallpaperhub}"
CONTEXT="kind-$CLUSTER"
NS="${K8S_NAMESPACE:-wallpaperhub}"
NETWORK="${COMPOSE_NETWORK:-wallpaperhub_default}"
NODE="$CLUSTER-control-plane"
TIMEOUT="${K8S_TIMEOUT:-420s}"
CHART=deploy/helm/service
COMPOSE=(docker compose --project-directory infra -f infra/docker-compose.yml)
# renovate: datasource=docker depName=busybox
busybox_version=1.37.0

say()  { printf '%s\n' "$*"; }
die()  { printf 'k8s: %s\n' "$*" >&2; exit 1; }

# The same virtual environment as make k8s-gen and the other generators (the Makefile's VENV): created once, requirements kept current.
venv_python() {
  [ -d .venv-validate ] || python3 -m venv .venv-validate || die "cannot create .venv-validate (python3 -m venv failed)"
  .venv-validate/bin/pip install -q -r scripts/validate/requirements.txt || die "cannot install scripts/validate/requirements.txt into .venv-validate"
}
kc()   { kubectl --context "$CONTEXT" -n "$NS" "$@"; }

need() {
  local missing=0 t
  for t in "$@"; do
    command -v "$t" >/dev/null 2>&1 && continue
    missing=1
    case "$t" in
      docker)  say "  missing docker:  Docker Desktop with WSL integration for this distro" ;;
      kind)    say "  missing kind:    https://kind.sigs.k8s.io/docs/user/quick-start/#installation  (a single binary; Windows: winget install Kubernetes.kind)" ;;
      kubectl) say "  missing kubectl: https://kubernetes.io/docs/tasks/tools/  (a single binary)" ;;
      helm)    say "  missing helm:    https://helm.sh/docs/intro/install/  (version 4 or 3.18+; Windows: winget install Helm.Helm)" ;;
    esac
  done
  [ "$missing" -eq 0 ] || die "install the tools above (make doctor lists what is present)"
  docker info >/dev/null 2>&1 || die "the Docker daemon is not reachable (start Docker Desktop)"
}

cluster_exists() { kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; }

compose_running() { "${COMPOSE[@]}" --profile infra --profile apps --profile mocks ps --status running --services 2>/dev/null; }

# ---- up -------------------------------------------------------------------------------------------------------------------
images_for() {   # the compose services whose images the mode needs
  case "$1" in
    mocks) say "gateway account-mock" ;;   # the four mocks are one image
    apps)  say "gateway account media catalog notification" ;;
  esac
}

cmd_up() {
  local mode="${1:-}" build=1
  case "$mode" in mocks|apps) ;; *) die "usage: k8s.sh up mocks|apps [--no-build]" ;; esac
  [ "${2:-}" = "--no-build" ] && build=0
  need docker kind kubectl helm

  venv_python   # k8s-gen.py needs PyYAML, which a bare python3 (a CI runner, a fresh laptop) does not have
  .venv-validate/bin/python scripts/k8s-gen.py --check >/dev/null || { .venv-validate/bin/python scripts/k8s-gen.py --check; die "the values files do not match the compose file: make k8s-gen"; }

  local running; running="$(compose_running)"
  printf '%s\n' "$running" | grep -qx gateway && die "the Compose gateway runs and holds port 8080. Stop it first:  ${COMPOSE[*]} stop gateway account-mock media-mock catalog-mock notification-mock account media catalog notification"
  for s in keycloak redis; do
    printf '%s\n' "$running" | grep -qx "$s" || die "$s is not running in Compose. make k8s-up-$mode starts the infrastructure it needs itself (use it instead of calling this script)"
  done
  docker network inspect "$NETWORK" >/dev/null 2>&1 || die "the Compose network $NETWORK does not exist: start the infrastructure first (make up or make up-mocks)"

  # shellcheck disable=SC2046
  if [ "$build" -eq 1 ]; then
    say "building the images ($(images_for "$mode"))"
    "${COMPOSE[@]}" --profile "$mode" build $(images_for "$mode") || die "the image build failed"
  fi

  if cluster_exists; then say "cluster $CLUSTER exists, reusing it"
  else
    say "creating the kind cluster $CLUSTER"
    local cfg; cfg="$(mktemp)"
    sed "s|@CONTRACTS@|$ROOT/contracts|" deploy/kind/kind-config.yaml > "$cfg"
    kind create cluster --config "$cfg" --wait 120s || { rm -f "$cfg"; die "kind could not create the cluster (port 8080 taken? docker ps shows who holds it)"; }
    rm -f "$cfg"
  fi
  kubectl config use-context "$CONTEXT" >/dev/null

  # The node joins the Compose network: pods then resolve and reach keycloak, redis, kafka ... by name (kind forwards DNS to Docker's).
  if docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$NODE" | grep -qw "$NETWORK"; then say "node already on $NETWORK"
  else docker network connect "$NETWORK" "$NODE" || die "could not attach $NODE to $NETWORK"; say "attached $NODE to $NETWORK"; fi

  load_images "$mode"

  kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create ns "$NS" >/dev/null
  local svc f failed=0
  for svc in account media catalog notification gateway; do
    if [ "$mode" = mocks ] && [ "$svc" != gateway ]; then f="deploy/helm/values/mocks/$svc.yaml"; else f="deploy/helm/values/apps/$svc.yaml"; fi
    helm upgrade --install "$svc" "$CHART" --kube-context "$CONTEXT" -n "$NS" -f "$f" >/dev/null || failed=1
  done
  [ "$failed" -eq 0 ] || die "helm could not install a release (helm lint: make k8s-lint)"
  say "waiting for the deployments (up to $TIMEOUT; a Spring service needs about a minute to start)"
  if ! kc wait --for=condition=Available deployment --all --timeout="$TIMEOUT" >/dev/null; then
    diagnose; die "not every deployment became available"
  fi
  # pods of a replaced ReplicaSet that are still terminating do not count; the gateway answers when the readiness probes passed
  say "ready:"
  kc get deploy
  say ""
  say "gateway: http://localhost:8080/health   (make e2e runs against it)"
  say "next:    make k8s-net   (pods reach the infrastructure by name),  make k8s-down  (delete the cluster)"
}

load_images() {   # kind has its own image store: copy the images from Docker into the node
  local imgs=() i
  case "$1" in
    mocks) imgs=(wallpaperhub/gateway:local wallpaperhub/mock:local) ;;
    apps)  imgs=(wallpaperhub/gateway:local wallpaperhub/account:local wallpaperhub/media:local wallpaperhub/catalog:local wallpaperhub/notification:local) ;;
  esac
  for i in "${imgs[@]}"; do docker image inspect "$i" >/dev/null 2>&1 || die "image $i is not built (run without --no-build)"; done
  say "loading ${imgs[*]} into the node"
  if kind load docker-image --name "$CLUSTER" "${imgs[@]}" >/dev/null 2>&1; then return 0; fi
  # Docker Desktop with the containerd image store can fail the direct load; an archive works there.
  say "  kind load docker-image failed, trying an image archive"
  local tar; tar="$(mktemp --suffix=.tar)"
  docker save -o "$tar" "${imgs[@]}" && kind load image-archive --name "$CLUSTER" "$tar" >/dev/null
  local rc=$?; rm -f "$tar"
  [ "$rc" -eq 0 ] || die "could not load the images into the cluster (Docker Desktop > Settings > General > 'Use containerd for pulling and storing images': try switching it off)"
}

diagnose() {
  say ""; say "---- pods"; kc get pods -o wide
  local p
  for p in $(kc get pods --no-headers 2>/dev/null | awk '{split($2, a, "/"); if (a[1] != a[2] || $3 != "Running") print $1}'); do
    say ""; say "---- $p"
    kc describe pod "$p" | sed -n '/^Events:/,$p' | tail -15
    kc logs "$p" --tail=25 2>&1 | tail -25
  done
}

# ---- the others -----------------------------------------------------------------------------------------------------------
cmd_down() {
  need kind
  if cluster_exists; then kind delete cluster --name "$CLUSTER"; else say "no cluster $CLUSTER"; fi
}

cmd_status() {
  need kubectl
  cluster_exists || die "no cluster $CLUSTER: make k8s-up-mocks  or  make k8s-up-apps"
  kc get deploy,pods,svc -o wide
}

cmd_check() {
  need docker kind kubectl
  cluster_exists || die "no cluster $CLUSTER"
  docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$NODE" | grep -qw "$NETWORK" \
    || die "the node is not on $NETWORK (Compose recreated the network?): make k8s-up-mocks / make k8s-up-apps attaches it again"
  local targets=(keycloak:8080 redis:6379) rc=0 t
  # the real services (not the mocks) also use the databases and Kafka
  kc get deploy account -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null | grep -q '^wallpaperhub/account:' && targets+=(postgres-account:5432 kafka:29092 mongo:27017)
  say "a probe pod (busybox $busybox_version) resolves and connects to: ${targets[*]}"
  local script='rc=0; for t in "$@"; do h=${t%:*}; p=${t#*:}; if nc -z -w 3 "$h" "$p" 2>/dev/null; then echo "  ok    $t"; else echo "  FAIL  $t ($(nslookup "$h" 2>&1 | grep -c Address) addresses)"; rc=1; fi; done; exit $rc'
  kubectl --context "$CONTEXT" -n "$NS" run k8s-probe --rm -i --quiet --restart=Never --image-pull-policy=IfNotPresent \
    --image="busybox:$busybox_version" --command -- sh -c "$script" sh "${targets[@]}" || rc=1
  if [ "$rc" -ne 0 ]; then
    say ""
    say "A pod cannot reach the Compose infrastructure. Usual causes:"
    say "  - the service is not running in Compose (make ps)"
    say "  - Compose recreated its network after the cluster was built: make k8s-down, then make k8s-up-... again"
    say "  - DNS: kind forwards to Docker's resolver through the node; see docs/KUBERNETES.md, 'When a pod cannot reach the infrastructure'"
  fi
  return "$rc"
}

cmd_dump() {   # everything a failed CI run needs: objects, events, the logs of every pod (also the previous container)
  need kubectl
  local dir="${1:-k8s-logs}" p; mkdir -p "$dir"
  kc get all -o wide > "$dir/get-all.txt" 2>&1
  kc get events --sort-by=.lastTimestamp > "$dir/events.txt" 2>&1
  kc describe pods > "$dir/describe-pods.txt" 2>&1
  for p in $(kc get pods -o name 2>/dev/null); do
    kc logs "$p" --all-containers --tail=500 > "$dir/${p#pod/}.log" 2>&1
    kc logs "$p" --all-containers --previous --tail=200 > "$dir/${p#pod/}.previous.log" 2>&1 || rm -f "$dir/${p#pod/}.previous.log"
  done
  say "cluster state in $dir ($(find "$dir" -type f | wc -l) files)"
}

cmd_logs() {
  need kubectl
  [ -n "${1:-}" ] || die "usage: k8s.sh logs <account|media|catalog|notification|gateway> [kubectl logs args]"
  local s="$1"; shift
  kc logs "deploy/$s" --tail=200 "$@"
}

case "${1:-}" in
  up)     shift; cmd_up "$@" ;;
  down)   cmd_down ;;
  status) cmd_status ;;
  check)  cmd_check ;;
  logs)   shift; cmd_logs "$@" ;;
  dump)   shift; cmd_dump "$@" ;;
  *)      sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
