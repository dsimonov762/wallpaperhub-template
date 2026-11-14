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
APPS    := --profile apps
ALLP    := --profile infra --profile schemas --profile observability --profile apps --profile mocks \
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

# ---- static checks (no containers needed) ----------------------------------------------------------------------------
lint: ## compose config for every profile combination, shell syntax, Hurl formatting
	@for p in "$(INFRA)" "$(INFRA) --profile schemas" "$(INFRA) $(OBS) $(APPS) --profile schemas" "$(INFRA) --profile mocks" "--profile host-account --profile host-media --profile host-catalog --profile host-notification"; do \
	  $(COMPOSE) $$p config -q && echo "  ok  compose $$p" || exit 1; done
	@for f in infra/db-init/*.sh; do sh -n $$f && echo "  ok  sh -n $$f" || exit 1; done
	@for f in e2e/run.sh scripts/*.sh scripts/ci/*.sh conformance/run.sh conformance/selftest.sh conformance/checks/*.sh infra/host-proxy/forward.sh; do bash -n $$f && echo "  ok  bash -n $$f" || exit 1; done
	@python3 scripts/gen-gateway-errors.py --check
	@command -v hurlfmt >/dev/null && hurlfmt --check e2e/gateway/*.hurl e2e/system/*.hurl conformance/http/*.hurl && echo "  ok  hurlfmt" || echo "  skip hurlfmt (not installed)"

check-contracts: ## cross-check OpenAPI, GraphQL, Avro, proto, i18n and the gateway config against each other and the README
	@[ -d .venv-validate ] || python3 -m venv .venv-validate
	@.venv-validate/bin/pip install -q -r scripts/validate/requirements.txt
	.venv-validate/bin/python scripts/validate/validate_openapi.py
	.venv-validate/bin/python scripts/validate/validate_contracts2.py
	.venv-validate/bin/python scripts/validate/validate_host_env.py

.PHONY: help doctor env up up-obs schemas up-apps up-mocks down nuke stats ps logs host unhost env-matrix conformance conformance-selftest conformance-all e2e e2e-system e2e-all lint check-contracts contracts-lint contracts-breaking codegen
