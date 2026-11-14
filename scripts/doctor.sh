#!/usr/bin/env bash
# Preflight for the local stack. Prints OK / WARN / FAIL lines; exits 1 only on FAIL.   make doctor
# Catches the usual first-run problems on Windows 11 + Docker Desktop (WSL2) before "docker compose up" does.
cd "$(dirname "$0")/.." || exit 1
fails=0
ok()   { printf '  \033[32mOK\033[0m    %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; fails=$((fails+1)); }

echo "Docker"
if ! command -v docker >/dev/null 2>&1; then
  fail "docker CLI not found. Docker Desktop > Settings > Resources > WSL integration > enable your Ubuntu distro"
elif ! docker info >/dev/null 2>&1; then
  fail "Docker daemon not reachable. Start Docker Desktop and wait until it says 'Engine running'"
else
  ok "daemon reachable ($(docker version --format '{{.Server.Version}}' 2>/dev/null))"
  cv="$(docker compose version --short 2>/dev/null)"
  if [ -z "$cv" ]; then fail "docker compose v2 plugin missing"
  else
    major="${cv%%.*}"; rest="${cv#*.}"; minor="${rest%%.*}"; major="${major#v}"
    if [ "$major" -gt 2 ] || { [ "$major" -eq 2 ] && [ "$minor" -ge 20 ]; }; then ok "compose $cv"
    else fail "compose $cv is too old: 'depends_on ... required: false' needs 2.20+. Update Docker Desktop"; fi
  fi
  # docker info reports the VM's MemTotal in BYTES, a little under what .wslconfig asks for (memory=10GB shows up as
  # ~9.7 GiB), so compare in MiB with slack instead of truncating to whole GiB (that made memory=10GB read as "9").
  # Container memory limits in infra/docker-compose.yml add up to (a ceiling, real use is lower):
  #   up-mocks ~2 GB | up (infra) ~5 GB | up-obs ~6.5 GB | up-apps ~8 GB | infra + observability + apps ~9.3 GB
  mem_b="$(docker info --format '{{.MemTotal}}' 2>/dev/null)"; mem_mb=$(( ${mem_b:-0} / 1048576 )); mem_gb=$(( (mem_mb + 512) / 1024 ))
  if   [ "$mem_mb" -ge 9000 ]; then ok "Docker has ${mem_gb} GB: enough for every profile combination (infra + observability + apps limits add up to ~9.3 GB)"
  elif [ "$mem_mb" -ge 7000 ]; then ok "Docker has ${mem_gb} GB: enough for make up-mocks, make up and make up-obs. make up-apps (~8 GB) is tight and infra + observability + apps (~9.3 GB) will swap: use memory=10GB in %UserProfile%\\.wslconfig ([wsl2]) for those"
  elif [ "$mem_mb" -ge 5500 ]; then warn "Docker has ${mem_gb} GB: fine for make up-mocks (~2 GB) and make up (~5 GB, give it swap=4GB); make up-obs (~6.5 GB) will swap and feel slow. Set memory in %UserProfile%\\.wslconfig ([wsl2]) and run 'wsl --shutdown'"
  else fail "Docker has only ${mem_gb} GB. Set memory=6GB or more (plus swap=4GB) in %UserProfile%\\.wslconfig ([wsl2]) and run 'wsl --shutdown'"; fi
  if docker image inspect alpine:3.24.4 >/dev/null 2>&1; then
    mm="$(docker run --rm --privileged alpine:3.24.4 sysctl -n vm.max_map_count 2>/dev/null)"
    if [ "${mm:-0}" -ge 262144 ]; then ok "vm.max_map_count=$mm (Elasticsearch needs 262144)"
    else fail "vm.max_map_count=${mm:-?} < 262144: Elasticsearch will crash-loop. Fix:  wsl -d docker-desktop sysctl -w vm.max_map_count=262144  (persist it in .wslconfig: kernelCommandLine = \"sysctl.vm.max_map_count=262144\")"; fi
  else warn "alpine:3.24.4 not present, skipped the vm.max_map_count check"; fi
fi

echo "Repository"
case "$(pwd -P)" in
  /mnt/*) warn "repo is on the Windows drive ($(pwd -P)). Bind mounts are slow there and files may get CRLF. Clone into the WSL filesystem: ~/wallpaper-hub" ;;
  *) ok "repo is on a Linux filesystem" ;;
esac
crlf="$(grep -rIl $'\r' --include='*.sh' --include='*.yml' --include='*.yaml' --include='*.alloy' --include='*.hurl' infra services e2e scripts Makefile 2>/dev/null | head -5)"
if [ -n "$crlf" ]; then warn "CRLF line endings in: $(echo $crlf | tr '\n' ' '). Run: git config core.autocrlf input && git rm --cached -r . -q && git reset --hard"
else ok "no CRLF line endings in scripts and configs"; fi
[ -f infra/.env ] && ok "infra/.env present" || warn "infra/.env missing (optional, defaults apply): make env"

echo "Ports (host side, loopback)"
if [ -f infra/.env ]; then set -a; . infra/.env 2>/dev/null; set +a; fi
# Host ports published by running containers, one per line. 'docker ps' prints consecutive ports as a range
# (127.0.0.1:9000-9001->9000-9001/tcp), so expand ranges instead of grepping for ":9000->".
docker_host_ports() {
  docker ps --format '{{.Ports}}' 2>/dev/null | tr ',' '\n' | grep -- '->' \
    | sed -E 's/->.*//; s/.*://' \
    | awk -F- '{ e = ($2 == "" ? $1 : $2); for (p = $1; p <= e; p++) print p }'
}
published="$(docker_host_ports)"
busy=0
for pair in GATEWAY:8080 KEYCLOAK:8180 POSTGRES_ACCOUNT:5432 POSTGRES_MEDIA:5433 MONGO:27017 REDIS:6379 REDIS_NOTIFICATION:6380 \
            KAFKA:9092 SCHEMA_REGISTRY:8081 ELASTICSEARCH:9200 S3_API:9000 S3_CONSOLE:9001 MAILPIT_UI:8025 MAILPIT_SMTP:1025 GRAFANA:3000 PROMETHEUS:9090 \
            LOKI:3100 TEMPO:3200 ALLOY_UI:12345 ALLOY_OTLP_GRPC:4317 ALLOY_OTLP_HTTP:4318; do
  name="PORT_${pair%%:*}"; port="${!name:-${pair##*:}}"
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    exec 3>&- 3<&-
    if grep -qx "$port" <<< "$published"; then :; else fail "port $port ($name) is already in use by something else: set $name in infra/.env"; busy=1; fi
  fi
done
[ "$busy" = 0 ] && ok "no port conflicts with processes outside this stack"
if command -v netsh.exe >/dev/null 2>&1; then
  ex="$(netsh.exe interface ipv4 show excludedportrange protocol=tcp 2>/dev/null | tr -d '\r' | awk '/^ *[0-9]+ +[0-9]+/ {print $1" "$2}')"
  hit=""
  while read -r a b; do [ -z "$a" ] && continue
    for p in 8080 8180 5432 5433 8025 9000 9001 9200 3000 9090 6379 27017; do [ "$p" -ge "$a" ] && [ "$p" -le "$b" ] && hit="$hit $p(in $a-$b)"; done
  done <<< "$ex"
  [ -n "$hit" ] && warn "Windows reserves these ports (Hyper-V/WSL excluded range):$hit. Docker cannot bind them: override PORT_* in infra/.env" \
                || ok "no default port inside a Windows excluded range"
fi

echo "Images (pulled on first start when missing)"
if docker info >/dev/null 2>&1; then
  for img in $(grep -hoE '^\s+image: [^ ]+' infra/docker-compose.yml | awk '{print $2}' | grep -v 'wallpaperhub/' | sort -u); do
    docker image inspect "$img" >/dev/null 2>&1 || warn "missing locally: $img"
  done
  ok "image check done"
fi

echo
[ "$fails" = 0 ] && { echo "doctor: ready for  make up"; exit 0; } || { echo "doctor: $fails problem(s) to fix first"; exit 1; }
