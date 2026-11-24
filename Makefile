# Wallpaper Hub - developer tasks.  Run from the repo root in WSL (Ubuntu), Git Bash or Linux/macOS:  make help
# Windows: keep the repo inside the WSL filesystem (~/wallpaper-hub), NOT under /mnt/c - bind mounts from there are slow
# and CRLF-prone.  Docker Desktop must have WSL integration enabled for your distro.
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

COMPOSE := docker compose --project-directory infra -f infra/docker-compose.yml
JOBS    := account-db-migrate media-db-migrate catalog-db-init catalog-search-init
# per-target profile sets
INFRA   := --profile infra
OBS     := --profile observability
TOOLS   := kafka-ui adminer mongo-ui
APPS    := --profile apps
ALLP    := --profile infra --profile schemas --profile data --profile tools --profile observability --profile apps --profile mocks \
           --profile host-account --profile host-media --profile host-catalog --profile host-notification
SERVICES := account media catalog notification

help: ## this list
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

doctor: ## check Docker, memory, ports, line endings and images before the first start
	@bash scripts/doctor.sh

env: ## create infra/.env from the example (never overwrites)
	@[ -f infra/.env ] && echo "infra/.env exists" || { cp infra/.env.example infra/.env && echo "created infra/.env"; }

# ---- start / stop ----------------------------------------------------------------------------------------------------
up: env ## infra (databases, Kafka, Keycloak, ES, S3, Mailpit) + create the DB schemas - ~5 GB
	$(COMPOSE) $(INFRA) up -d
	@bash scripts/wait-healthy.sh 600
	@$(MAKE) --no-print-directory schemas

up-obs: env ## infra + observability (Grafana, Loki, Tempo, Prometheus, Alloy) - memory limits add up to ~6.5 GB
	$(COMPOSE) $(INFRA) $(OBS) up -d
	@bash scripts/wait-healthy.sh 600
	@$(MAKE) --no-print-directory schemas

schemas: ## (re)apply the canonical DB schema: Postgres migrations, Mongo collections/indexes, ES index (idempotent)
	$(COMPOSE) $(INFRA) --profile schemas up -d --force-recreate --no-deps $(JOBS)
	@for j in $(JOBS); do \
	  c=$$($(COMPOSE) $(INFRA) --profile schemas ps -aq $$j); code=$$(docker wait $$c); \
	  if [ "$$code" = 0 ]; then echo "  ok      $$j"; else echo "  FAILED  $$j (exit $$code)"; docker logs $$c 2>&1 | tail -20; exit 1; fi; \
	done

up-apps: env ## infra + schemas + the real services and gateway (needs services/<name>/<impl> to exist)
	$(COMPOSE) $(INFRA) $(APPS) --profile schemas up -d --build $$(for s in $$(cat .host 2>/dev/null); do printf -- '--scale %s=0 ' $$s; done)

renovate-check: ## .github/renovate.json5 is a valid Renovate configuration (strict; needs Node 24.11+ or Docker; CI runs it)
	@bash scripts/renovate-check.sh

hooks: ## install the git hooks of this clone (pre-commit: hygiene and quick checks on commit, Docker-based ones on push); needs: pipx install pre-commit
	@command -v pre-commit >/dev/null 2>&1 || { echo "pre-commit is not installed: pipx install pre-commit  (or: pip install --user pre-commit)   details: docs/PRE-COMMIT.md"; exit 1; }
	pre-commit install

precommit: ## run every pre-commit hook on every file, as CI does (ARGS="--hook-stage pre-push" adds the slow ones; make precommit ARGS="shellcheck" runs one hook)
	@command -v pre-commit >/dev/null 2>&1 || { echo "pre-commit is not installed: pipx install pre-commit  (or: pip install --user pre-commit)   details: docs/PRE-COMMIT.md"; exit 1; }
	pre-commit run --all-files $(ARGS)

certs: ## local HTTPS certificates with mkcert (once per machine and every ~2 years); ARGS=--install also trusts the CA, ARGS=--check only reports
	@bash scripts/certs.sh $(ARGS)

up-https: env ## like up-apps + the gateway on https://localhost:8443 (mkcert certificate: make certs); HTTPS_ISSUER=1 also serves Keycloak over https and moves the token issuer there (+0 MB)
	@bash scripts/certs.sh --check >/dev/null || { echo "no current certificate: make certs"; exit 1; }
	$(VENV)
	.venv-validate/bin/python scripts/https-gateway.py $(if $(HTTPS_ISSUER),--keycloak-https)
	$(COMPOSE) -f infra/docker-compose.https.yml $(if $(HTTPS_ISSUER),-f infra/docker-compose.https-issuer.yml) $(INFRA) $(APPS) --profile schemas up -d --build $$(for s in $$(cat .host 2>/dev/null); do printf -- '--scale %s=0 ' $$s; done)
	@echo "gateway: https://localhost:$${PORT_GATEWAY_TLS:-8443}  (http://localhost:$${PORT_GATEWAY:-8080} still works)$(if $(HTTPS_ISSUER),; Keycloak: https://localhost:$${PORT_KEYCLOAK_TLS:-8543})   details: docs/HTTPS.md"

up-https-mocks: env ## up-mocks with the https gateway: tries the TLS setup without the services (also HTTPS_ISSUER=1)
	@bash scripts/certs.sh --check >/dev/null || { echo "no current certificate: make certs"; exit 1; }
	$(VENV)
	.venv-validate/bin/python scripts/https-gateway.py $(if $(HTTPS_ISSUER),--keycloak-https)
	$(COMPOSE) -f infra/docker-compose.https.yml $(if $(HTTPS_ISSUER),-f infra/docker-compose.https-issuer.yml) $(INFRA) --profile mocks up -d --build gateway
	@bash scripts/wait-healthy.sh 600

https-check: ## the TLS listener can still be derived from envoy.yaml, with and without the https issuer (CI runs it; make lint checks the overlays)
	$(VENV)
	.venv-validate/bin/python scripts/https-gateway.py --check
	.venv-validate/bin/python scripts/https-gateway.py --keycloak-https --check

up-load: env ## like up-apps, with the gateway's rate limits raised x100 and more threads, for load tests (make load-run P=load); WITH_OBS=1 adds Grafana & co (+6 GB)
	$(VENV)
	.venv-validate/bin/python scripts/loadtest-gateway.py --factor $(or $(LOAD_RL_FACTOR),100)
	$(COMPOSE) -f infra/docker-compose.loadtest.yml $(INFRA) $(if $(WITH_OBS),$(OBS)) $(APPS) --profile schemas up -d --build $$(for s in $$(cat .host 2>/dev/null); do printf -- '--scale %s=0 ' $$s; done)
	@echo "gateway with raised rate limits: make load-run P=smoke | load | stress ...   (production limits again: make up-apps)"

up-load-mocks: env ## up-mocks with the raised gateway limits: tries the load-test harness itself without the services (make load-run P=load SKIP=graphql)
	$(VENV)
	.venv-validate/bin/python scripts/loadtest-gateway.py --factor $(or $(LOAD_RL_FACTOR),100)
	$(COMPOSE) -f infra/docker-compose.loadtest.yml $(INFRA) $(if $(WITH_OBS),$(OBS)) --profile mocks up -d --build gateway
	@bash scripts/wait-healthy.sh 600

up-chaos: env ## like up-apps, with every service's connections to its databases/Redis/Keycloak/ES/S3/other services going through Toxiproxy (failure injection: make chaos-run) - +64 MB
	$(MAKE) --no-print-directory chaos-gen
	$(COMPOSE) -f infra/docker-compose.chaos.yml $(INFRA) $(APPS) --profile schemas up -d --build $$(for s in $$(cat .host 2>/dev/null); do printf -- '--scale %s=0 ' $$s; done)
	@echo "Toxiproxy API: http://localhost:$${PORT_TOXIPROXY:-8474}   try: make chaos-run S=media-down   (back to direct connections: make up-apps)"

up-tools: env ## web UIs: Kafka UI, Adminer (Postgres), Mongoku (MongoDB); starts only the stores they show; one UI: make up-tools T=adminer - ~0.9 GB
	$(COMPOSE) $(INFRA) --profile tools up -d $(or $(T),$(TOOLS))
	@bash scripts/wait-healthy.sh 600
	@bash scripts/tools-info.sh $(or $(T),$(TOOLS))

up-mocks: env ## only what the gateway needs (Keycloak, Redis) + gateway + 4 Prism mocks - ~2 GB, the light way to work
	$(COMPOSE) $(INFRA) --profile mocks up -d --build gateway
	@bash scripts/wait-healthy.sh 600
	@echo "gateway: http://localhost:$${PORT_GATEWAY:-8080}/health   (mocks answer with the examples of contracts/openapi)"

down: ## stop everything, keep the data
	$(COMPOSE) $(ALLP) down --remove-orphans
	@rm -f .host

nuke: ## stop everything AND delete all data volumes
	$(COMPOSE) $(ALLP) down --remove-orphans --volumes
	@rm -f .host

stats: ## memory and CPU of the running containers
	docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}'

ps: ## containers and their health
	$(COMPOSE) $(ALLP) ps -a

logs: ## follow logs:  make logs S=keycloak
	$(COMPOSE) $(ALLP) logs -f --tail=100 $(S)

# ---- develop one service from the IDE -----------------------------------------------------------------------------------
host: ## run ONE service from your IDE, the rest stays in Docker:  make host SVC=account|media|catalog|notification
	@case "$(SVC)" in account|media|catalog|notification) ;; *) echo "usage: make host SVC=account|media|catalog|notification"; exit 2;; esac
	-$(COMPOSE) $(INFRA) $(APPS) stop $(SVC)
	$(COMPOSE) --profile host-$(SVC) up -d --no-deps --build $(SVC)-host
	@touch .host; grep -qx $(SVC) .host || echo $(SVC) >> .host
	@bash scripts/host-info.sh $(SVC)

unhost: ## put the container of a hosted service back:  make unhost SVC=account
	@case "$(SVC)" in account|media|catalog|notification) ;; *) echo "usage: make unhost SVC=account|media|catalog|notification"; exit 2;; esac
	$(COMPOSE) --profile host-$(SVC) rm -sf $(SVC)-host
	@[ -f .host ] && { grep -vx $(SVC) .host > .host.tmp; mv .host.tmp .host; [ -s .host ] || rm -f .host; } || true
	@$(COMPOSE) $(INFRA) $(APPS) start $(SVC) 2>/dev/null && echo "$(SVC) container started" || echo "no $(SVC) container to start: make up-apps creates it"

env-matrix: ## the environment variables of the four services side by side (secrets masked)
	@python3 scripts/env-matrix.py

# ---- contracts -------------------------------------------------------------------------------------------------------
contracts-lint: ## lint OpenAPI (Spectral), protobuf (buf), Avro and GraphQL conventions; tools run in a container (CONTRACT_TOOLS=native: local Node)
	@scripts/contracts.sh lint

contracts-breaking: ## fail on breaking contract changes against a git ref:  make contracts-breaking [BASE=origin/master]
	@scripts/contracts.sh breaking $(BASE)

codegen: ## generate code from contracts/ into gen/:  make codegen TARGET=typescript | TARGET=openapi GEN="spring account" | TARGET=proto GEN=buf.gen.yaml
	@scripts/codegen.sh $(TARGET) $(GEN)

# ---- tests -----------------------------------------------------------------------------------------------------------
conformance: ## does a service obey docs/SERVICE-SPEC.md?  make conformance SVC=account [ARGS="--lifecycle --no-telemetry ..."]
	@./conformance/run.sh $(SVC) $(ARGS)

conformance-selftest: ## test the conformance suite itself with the reference stub (needs Keycloak: make up-mocks)
	@./conformance/selftest.sh

conformance-all: ## conformance of all four running services (the real ones, make up-apps + make up-obs)
	@rc=0; for s in $(SERVICES); do ./conformance/run.sh $$s $(ARGS) || rc=1; echo; done; exit $$rc

e2e: ## gateway-level checks (work against real services and mocks)
	./e2e/run.sh gateway

e2e-system: ## README 4.1 user flows through all services (needs the real implementations)
	./e2e/run.sh system

e2e-all: ## system flows, then gateway checks
	./e2e/run.sh all

# ---- development data -------------------------------------------------------------------------------------------------
seed: ## fill every store with the development dataset (12 users, 30 wallpapers, favorites, inboxes ...; see seed/CATALOG.md); safe to repeat
	@bash scripts/data.sh seed

reset: ## DELETE all data in every store (schemas stay; asks first, YES=1 skips the question)
	@bash scripts/data.sh reset

reseed: ## reset, then seed: the same known state every time
	@bash scripts/data.sh reseed

seed-build: ## regenerate seed/out and the images from seed/dataset.yaml (python3 + seed/requirements.txt, or Docker)
	@bash scripts/seed-build.sh

seed-check: ## fail when seed/out or the images are out of date, and validate the seed data against the DB schemas of contracts/
	@[ -d .venv-validate ] || python3 -m venv .venv-validate
	@.venv-validate/bin/pip install -q -r scripts/validate/requirements.txt
	.venv-validate/bin/python seed/build.py --check
	.venv-validate/bin/python scripts/validate/validate_seed.py

# ---- Grafana dashboards (infra/grafana/dashboards) ----------------------------------------------------------------------
PROMETHEUS_URL ?= http://localhost:9090
dashboards-check: ## validate the dashboard JSON without Grafana (structure, datasources, PromQL syntax, variables)
	@[ -d .venv-validate ] || python3 -m venv .venv-validate
	@.venv-validate/bin/pip install -q -r scripts/validate/requirements.txt
	.venv-validate/bin/python scripts/validate/validate_dashboards.py

dashboards-coverage: ## which metrics the dashboards use that your running Prometheus does not have (why is a panel empty?)
	@[ -d .venv-validate ] || python3 -m venv .venv-validate
	@.venv-validate/bin/pip install -q -r scripts/validate/requirements.txt
	.venv-validate/bin/python scripts/validate/validate_dashboards.py --coverage $(PROMETHEUS_URL)

# ---- calling the API by hand -------------------------------------------------------------------------------------------
token: ## access token of a user for curl & co:  make token [U=alice|mod|admin|bob ...] [ARGS=--decode|--header|--json] ; a service account: ARGS="--client catalog-svc"
	@bash scripts/token.sh $(ARGS) $(U)

bruno-run: ## run the Bruno collection (bruno/) against the running stack as a seeded user:  make bruno-run [U=alice] [ARGS="--tags read"]
	@bash scripts/bruno.sh --env $(or $(U),alice) $(ARGS)

bruno-gen: ## regenerate bruno/ from contracts/ and the seed manifest (your own requests in bruno/custom/ stay)
	@[ -d .venv-validate ] || python3 -m venv .venv-validate
	@.venv-validate/bin/pip install -q -r scripts/validate/requirements.txt
	.venv-validate/bin/python scripts/bruno-gen.py

bruno-check: ## fail when bruno/ is out of date with contracts/ or seed/out
	@[ -d .venv-validate ] || python3 -m venv .venv-validate
	@.venv-validate/bin/pip install -q -r scripts/validate/requirements.txt
	.venv-validate/bin/python scripts/bruno-gen.py --check

seed-test-sql: ## load the seed SQL twice into a throw-away Postgres (docker) on top of the canonical schema: proves constraints and idempotency
	@bash scripts/ci/seed-sql-test.sh

# ---- load tests with k6 (docs/LOAD.md) ---------------------------------------------------------------------------------
load-run: ## run a k6 profile: make load-run P=smoke|load|stress|spike|soak|uploads|ratelimit [RATE=20 DURATION=10m SKIP=graphql ...]
	@bash scripts/k6.sh $(or $(P),smoke)

load-smoke: ## every journey once with one user: do the harness, the data and the API work? (about 15 s)
	@bash scripts/k6.sh smoke

load-data: ## the unique pictures for the uploads profile: make load-data N=200
	python3 scripts/loadtest-data.py $(or $(N),200) --fresh

load-check: ## the gateway rate-limit transformation still fits envoy.yaml (CI runs it)
	$(VENV)
	.venv-validate/bin/python scripts/loadtest-gateway.py --check

# ---- failure injection (docs/CHAOS.md) -------------------------------------------------------------------------------
VENV = @[ -d .venv-validate ] || python3 -m venv .venv-validate; .venv-validate/bin/pip install -q -r scripts/validate/requirements.txt

chaos: ## break a connection: make chaos C="down catalog-elasticsearch" | "latency 'catalog-*' 800" | "timeout media-s3" | reset | status (default)
	$(VENV)
	.venv-validate/bin/python scripts/chaos.py $(or $(C),status)

chaos-run: ## run a failure scenario and check the README-8 behaviour: make chaos-run S=media-down (S=all for every one; make chaos-list)
	$(VENV)
	.venv-validate/bin/python scripts/chaos.py run $(or $(S),$(error give a scenario: make chaos-run S=media-down  (make chaos-list)))

chaos-list: ## the failure scenarios
	$(VENV)
	@.venv-validate/bin/python scripts/chaos.py list

chaos-gen: ## regenerate infra/chaos/toxiproxy.json and infra/docker-compose.chaos.yml from infra/chaos/edges.yaml
	$(VENV)
	.venv-validate/bin/python scripts/chaos.py gen

chaos-check: ## chaos config is up to date and fits docker-compose.yml and the scenarios (CI runs it)
	$(VENV)
	.venv-validate/bin/python scripts/chaos.py gen --check

# ---- Kubernetes (Helm chart + a local kind cluster; the infrastructure stays in Compose) - docs/KUBERNETES.md --------------------------
k8s-gen: ## regenerate deploy/helm/values/ (the Helm values of every service) from infra/docker-compose.yml
	$(VENV)
	.venv-validate/bin/python scripts/k8s-gen.py

k8s-check: ## deploy/helm/values is up to date, the Service names fit envoy.yaml and Compose, kind publishes the gateway (CI runs it)
	$(VENV)
	.venv-validate/bin/python scripts/k8s-gen.py --check

k8s-lint: ## helm lint --strict + helm template + kubeconform for every values file (needs helm and kubeconform; CI runs it)
	@bash scripts/k8s-lint.sh

k8s-up-mocks: env ## kind cluster with the gateway and the 4 Prism mocks; Keycloak and Redis stay in Compose (needs docker, kind, kubectl, helm) - ~2 GB
	$(COMPOSE) $(INFRA) up -d keycloak redis
	@bash scripts/wait-healthy.sh 600
	@bash scripts/k8s.sh up mocks
	@echo "make e2e runs against the cluster now; make k8s-net proves the pods reach Compose by name"

k8s-up-apps: up ## kind cluster with the real services and the gateway; the whole infrastructure stays in Compose (like make up-apps, but the services run in kind)
	@bash scripts/k8s.sh up apps

k8s-down: ## delete the kind cluster (Compose keeps running)
	@bash scripts/k8s.sh down

k8s-status: ## deployments, pods and services of the cluster
	@bash scripts/k8s.sh status

k8s-net: ## can the pods reach Keycloak, Redis (and with k8s-up-apps the databases, Kafka) by name? A probe pod tries
	@bash scripts/k8s.sh check

k8s-logs: ## logs of one service in the cluster:  make k8s-logs S=gateway
	@bash scripts/k8s.sh logs $(or $(S),gateway)

# ---- static checks (no containers needed) ----------------------------------------------------------------------------
lint: ## compose config for every profile combination, shell syntax, Hurl formatting
	@for p in "$(INFRA)" "$(INFRA) --profile schemas" "$(INFRA) --profile data" "$(INFRA) --profile tools" "$(INFRA) $(OBS) $(APPS) --profile schemas" "$(INFRA) --profile mocks" "--profile host-account --profile host-media --profile host-catalog --profile host-notification"; do \
	  $(COMPOSE) $$p config -q && echo "  ok  compose $$p" || exit 1; done
	@$(COMPOSE) -f infra/docker-compose.chaos.yml $(INFRA) $(APPS) --profile schemas config -q && echo "  ok  compose with the chaos overlay"
	@$(COMPOSE) -f infra/docker-compose.loadtest.yml $(INFRA) $(APPS) --profile schemas config -q && echo "  ok  compose with the load-test overlay"
	@$(COMPOSE) -f infra/docker-compose.https.yml -f infra/docker-compose.https-issuer.yml $(INFRA) $(APPS) --profile schemas config -q && echo "  ok  compose with the https overlays"
	@for f in infra/db-init/*.sh infra/data/*.sh; do bash -n $$f && echo "  ok  sh -n $$f" || exit 1; done
	@for f in e2e/run.sh scripts/*.sh scripts/ci/*.sh conformance/run.sh conformance/selftest.sh conformance/checks/*.sh infra/host-proxy/forward.sh; do bash -n $$f && echo "  ok  bash -n $$f" || exit 1; done
	@python3 scripts/gen-gateway-errors.py --check
	@command -v hurlfmt >/dev/null && hurlfmt --check e2e/gateway/*.hurl e2e/system/*.hurl conformance/http/*.hurl && echo "  ok  hurlfmt" || echo "  skip hurlfmt (not installed)"

check-contracts: ## cross-check OpenAPI, GraphQL, Avro, proto, i18n and the gateway config against each other and the README
	@[ -d .venv-validate ] || python3 -m venv .venv-validate
	@.venv-validate/bin/pip install -q -r scripts/validate/requirements.txt
	.venv-validate/bin/python scripts/validate/validate_openapi.py
	.venv-validate/bin/python scripts/validate/validate_contracts2.py
	.venv-validate/bin/python scripts/validate/validate_host_env.py

adr-check: ## architecture decision records (docs/adr): form, numbering, links, supersessions, index (CI runs it)
	@python3 scripts/adr.py check

adr-selftest: ## test scripts/adr.py itself on a fixture (what it catches; new and --supersedes keep the records consistent)
	@bash scripts/ci/adr-selftest.sh

docs-check: ## Markdown documentation: relative links and anchors, `make` targets named in the text, the documentation map (CI runs it)
	@python3 scripts/docs-check.py

docs-selftest: ## test scripts/docs-check.py itself on a fixture (what it catches)
	@bash scripts/ci/docs-selftest.sh

adr-index: ## rewrite the table in docs/adr/README.md from the records
	@python3 scripts/adr.py index

adr-new: ## a new decision record:  make adr-new T="Use gRPC between catalog and account" [SUPERSEDES=0007]
	@[ -n "$(T)" ] || { echo 'usage: make adr-new T="Title of the decision" [SUPERSEDES=0007]'; exit 1; }
	@python3 scripts/adr.py new "$(T)" $(if $(SUPERSEDES),--supersedes $(SUPERSEDES))

.PHONY: help doctor env up up-tools up-obs schemas seed reset reseed seed-build seed-check seed-test-sql token bruno-run bruno-gen bruno-check dashboards-check dashboards-coverage up-apps up-chaos certs up-https up-https-mocks https-check up-load up-load-mocks load-run load-smoke load-data load-check chaos chaos-run chaos-list chaos-gen chaos-check up-mocks down nuke stats ps logs host unhost env-matrix conformance conformance-selftest conformance-all e2e e2e-system e2e-all lint check-contracts contracts-lint contracts-breaking codegen hooks precommit renovate-check adr-check adr-selftest adr-index adr-new docs-check docs-selftest k8s-gen k8s-check k8s-lint k8s-up-mocks k8s-up-apps k8s-down k8s-status k8s-net k8s-logs
