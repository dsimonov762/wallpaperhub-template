# Working on Wallpaper Hub (for people and AI agents)

Read this first. It is written so that someone who knows nothing about the repository, or a fresh AI dialog, can take **one piece of work**, finish it, and hand it over without reading the code of the other pieces
and without breaking them. Several of these can run at the same time.

## What this is

A polyglot microservice reference project: four domain services (**account, media, catalog, notification**) and an **API gateway** (Envoy), specified in [README.md](README.md) and implemented in as many languages as you like.
The design, the contracts and the complete local development environment exist and are verified; **no domain service is implemented yet**. [docs/STATUS.md](docs/STATUS.md) is the current truth, [docs/ROADMAP.md](docs/ROADMAP.md) cuts the rest into packages.

## Read in this order

1. This file.
2. [docs/STATUS.md](docs/STATUS.md): what exists, what does not, what is open.
3. Your package in [docs/ROADMAP.md](docs/ROADMAP.md): goal, **lane** (what you may change), inputs, definition of done. If you were not given a package, ask for one.
4. Only what that section lists as inputs. Typical ones: [docs/SERVICE-SPEC.md](docs/SERVICE-SPEC.md) (the outside behaviour of a service), the README section it names, the files of `contracts/` it names.
5. The doc of the area you touch (the map is [docs/README.md](docs/README.md)). Decisions and their reasons are in [docs/adr/](docs/adr/README.md): read the ADR before you propose the opposite.

You do **not** need to read the code of other packages. Their behaviour is the **contracts** (`contracts/`), the **service specification** (`docs/SERVICE-SPEC.md`) and the **mocks** (`make up-mocks`). If you find that you must read another package's code to proceed, something is missing from a contract or a doc: say so in your delivery instead.

## The rules

1. **Contracts are the source of truth.** `contracts/` (OpenAPI, protobuf, Avro, GraphQL, i18n, DB schemas) says what the system does; code conforms to it, never the other way round. Do not edit a contract to make your code pass. [Changing a contract](#changing-a-contract) has its own protocol.
2. **A service is its outside behaviour.** Whatever the language, it must pass `make conformance SVC=<name> ARGS="--lifecycle"` ([docs/SERVICE-SPEC.md](docs/SERVICE-SPEC.md)). Internal layout follows README section 12 so that implementations line up side by side.
3. **Database per service; no calls around the contracts.** A service touches only its own stores. Cross-service data comes through the APIs and events of `contracts/` ([ADR 0010](docs/adr/0010-database-per-service.md)). Every service validates tokens itself ([ADR 0009](docs/adr/0009-the-gateway-validates-tokens-and-services-validate-them-again.md)).
4. **Every check is a `make` target; CI is the gate; git hooks are a shortcut** ([ADR 0017](docs/adr/0017-every-check-is-a-make-target-ci-is-the-gate-and-hooks-are-a-shortcut.md)). If you add a check, add the target, the hook if it is cheap, and the CI step. A check only you can run does not count.
5. **Generated files are never edited.** Change the source and regenerate; a check fails when they are stale ([ADR 0016](docs/adr/0016-generated-files-are-committed-and-checked-for-staleness.md)). The generators:

   | Source | Generated | Regenerate | Check |
   |---|---|---|---|
   | `infra/docker-compose.yml` | `deploy/helm/values/**` | `make k8s-gen` | `make k8s-check` |
   | `infra/chaos/edges.yaml` | `infra/chaos/toxiproxy.json`, `infra/docker-compose.chaos.yml` | `make chaos-gen` | `make chaos-check` |
   | `contracts/`, `seed/out/manifest.json` | `bruno/**` (not `bruno/custom/`) | `make bruno-gen` | `make bruno-check` |
   | `seed/dataset.yaml` | `seed/out/**`, `seed/s3/**` | `make seed-build` | `make seed-check` |
   | `contracts/i18n`, `envoy.yaml` | the gateway's error mappers | `python3 scripts/gen-gateway-errors.py` | `make lint` |
   | `services/gateway/envoy/envoy.yaml` | the load-test and HTTPS gateway variants | derived at run time | `make load-check https-check` |
   | `docs/adr/*.md` | the index in `docs/adr/README.md` | `make adr-index` | `make adr-check` |

6. **Pin every version** in a form Renovate can see ([ADR 0018](docs/adr/0018-pin-every-version-and-let-renovate-propose-updates.md)); no `latest`. [docs/RENOVATE.md](docs/RENOVATE.md) says how to mark a pin it cannot find.
7. **No secrets in the repository.** Everything in `infra/.env.example` and the seed data is a local development default. Real credentials never go in a file you commit.
8. **A decision gets an ADR** if it is expensive to reverse, surprising to a newcomer, or has an alternative somebody will propose again: `make adr-new T="Title"`. Never edit an accepted ADR's content; write a new one that supersedes it ([docs/adr/README.md](docs/adr/README.md)).
9. **Documentation is part of the change.** Update the doc of the area, [docs/STATUS.md](docs/STATUS.md) and [docs/HISTORY.md](docs/HISTORY.md) in the same patch. `make docs-check` verifies links, anchors and that every document is in the [map](docs/README.md).
10. **Be honest about verification.** End every delivery with what you verified, **how** (which command, on what), and what you did not. "Not verified" is a normal and useful sentence; an unverified "done" is the only unacceptable one. The levels used in STATUS: *Confirmed* (ran on the owner's machine or in CI), *Sandbox* (ran with the real tool in your environment), *Design only*.
11. **Stay in your lane.** Change only the files of your package. A bug or a gap you find elsewhere goes into your delivery message as a finding; do not fix it in the same patch. This is what lets several packages be merged in any order.

## Lanes and shared files

Each package owns a set of paths (its **lane**) and nobody else edits them; the table is in [docs/ROADMAP.md](docs/ROADMAP.md#lanes-who-may-change-what). A few files are **shared** because every package may need a line in them.
Edit them minimally, in your own hunk, and never reformat or reorder:

| Shared file | Rule |
|---|---|
| `Makefile` | add targets in the section they belong to, with a `## help text` (that is what `make help` prints) and an entry in `.PHONY`; do not rename or reorder existing targets |
| `.github/workflows/ci.yml` | a new job or step; a new job is added to `needs` of the `ok` job (the single required check is `ci / ok`) |
| `infra/docker-compose.yml` | **only the block of your own service**, and only its `environment`, ports and limits; then `make k8s-gen`. New infrastructure is a decision: ADR first |
| `infra/.env.example` | add your variables at the end of the section they belong to |
| `.pre-commit-config.yaml`, `.github/renovate.json5` | add a hook or a rule; keep existing ones as they are |
| `README.md` | the design document. Change it only for a design change, together with an ADR |
| `docs/STATUS.md`, `docs/HISTORY.md` | your own rows and your own line |

**After a merge conflict in a generated file, regenerate it; never resolve it by hand.** If two packages both added an ADR, the later one runs `make adr-new` again to take the next free number (`make adr-check` reports a repeated or skipped number).

## Changing a contract

Contracts are shared by every package, so a contract change is its own small piece of work, merged **before** the code that needs it.

1. Is it additive (a new optional field, endpoint, Avro field with a default, GraphQL field, i18n key)? Then go on. A breaking change needs a new version (`/v2`, `*.v2.avsc`, `account/v2/`) with the old kept until its consumers are gone, and an ADR; there is deliberately no override flag.
2. Make the change, then run `make check-contracts contracts-lint contracts-breaking BASE=origin/master`.
3. Regenerate what derives from it (see the table above: Bruno collection, gateway error mappers, mocks pick it up by themselves) and run `make bruno-check seed-check lint`.
4. List the consumers in the patch description (README 5.6 says who consumes which topic; the OpenAPI files say who calls what). New i18n keys exist in all three languages (`en`, `de`, `es`).
5. If the change shows that a document or a test was wrong, fix that in the same patch; if code in another package must change, say so in the description; do not change it yourself.

## Verification ladder: cheapest first

| Run | What it tells you | Needs |
|---|---|---|
| `make lint check-contracts seed-check bruno-check dashboards-check chaos-check load-check https-check adr-check docs-check k8s-check` | the repository is consistent, generated files are current | no containers, Python 3 |
| `make precommit` | all of the above plus shellcheck, actionlint, hadolint and the file checks, on every file | pre-commit |
| `make contracts-lint`, `make contracts-breaking BASE=origin/master` | the contract style rules and no breaking change | Docker (or `CONTRACT_TOOLS=native` with Node) |
| `make up-mocks && make e2e` | gateway behaviour through real Envoy and Keycloak | Docker, about 2 GB |
| `make host SVC=<name>` then `make conformance SVC=<name> ARGS="--api ... --mgmt ... --log-file service.log"` | your service from the IDE against everything else mocked | Docker |
| `make up-apps && make conformance SVC=<name> ARGS="--lifecycle"` | your container obeys the service specification | Docker, about 8 GB with all services |
| `make up-obs` first, then conformance | also checks that traces, logs and metrics arrive | about 6.5 GB |
| `make up-apps && make e2e-system` | the user flows of README 4.1 | all four services |
| `make up-chaos && make chaos-run S=<scenario>`, `make up-load && make load-run P=load` | resilience promises and latency budgets | real services |
| `make k8s-up-mocks && make k8s-net && make e2e`, `make k8s-lint` | the chart and the local Kubernetes cluster | Docker, kind, kubectl, helm |

**If you cannot run Docker** (a sandbox, a CI-less environment), run the first two rows, say plainly that nothing above them ran, and name the command the owner should run. Do not describe what a container "would" do as if it were a result.
The footprint of each profile is in [docs/GETTING-STARTED.md](docs/GETTING-STARTED.md); the owner's machine has 16 GB, so do not ask for everything at once.

## Environment facts

- The owner develops on **Windows 11 with Docker Desktop (WSL2)** and an Ubuntu WSL distribution; the repository lives in the WSL filesystem (not under `/mnt/c`). Scripts must work with LF line endings and without Windows paths. The default branch is `master`.
- The owner also edits files directly on GitHub, so **the tree you were given may be older than master**. State which commit you started from, deliver a patch (`git diff` against master) with the list of files it touches, and keep it small enough to review. Do not rewrite unrelated files.
- Ports, URLs and logins of the local stack are in [docs/GETTING-STARTED.md](docs/GETTING-STARTED.md#3-what-to-open).
- Tools run pinned, in containers where possible, so that nothing but Docker is required on a laptop. Prefer that to asking for an installation.

## Working in parallel: the protocol

1. The owner (or a coordinating dialog) hands out **one package per dialog**: `WP-<id>` from the [roadmap](docs/ROADMAP.md). A starting prompt is at the end of that file.
2. One branch per package: `wp/<id>-<short-name>`, one pull request titled `WP-<id>: ...`, based on the latest `master`. Merge in any order; the lanes make that safe.
3. Packages talk to each other only through contracts, the specification, mocks and the shared files above. Questions for another package go into your delivery message under **Open questions**, addressed to the owner.
4. When you finish: the [definition of done](docs/ROADMAP.md#definition-of-done-for-every-package) is met, STATUS and HISTORY are updated, and the message says what was verified and what was not.
5. A new decision the owner has to make goes into [STATUS.md](docs/STATUS.md#decisions-that-are-still-open) and your message, not into the code.

## Vocabulary

| Word | Meaning here |
|---|---|
| **WP** | work package of [docs/ROADMAP.md](docs/ROADMAP.md) |
| **lane** | the paths one package may change |
| **persona** | which of the four services a mock or a conformance run stands for (`conformance/services/<name>.env`) |
| **mock** | a Prism container generated from an OpenAPI file that answers with its examples (`make up-mocks`); the stand-in for a service that is not there |
| **host mode** | `make host SVC=<name>`: the container of a service is replaced by a forwarder to the process in your IDE |
| **profile** | a Compose profile (`infra`, `observability`, `apps`, `mocks`, `schemas`, `data`, `tools`, ...) that decides what a `make` target starts |
| **hot file** | a shared file in the table above |

## Where things are

```
README.md          the design (v1.1)                    contracts/     the source of truth
AGENTS.md          this file                            conformance/   does a running service obey the spec
docs/              guides; docs/README.md is the map    e2e/           user-flow and gateway tests (Hurl)
docs/adr/          why things are as they are           infra/         Compose, Keycloak, observability, chaos, data jobs
services/          gateway (Envoy), _mock, your services   deploy/     Helm chart and kind cluster
scripts/           tooling behind the make targets       seed/ bruno/ loadtest/   development data, API collection, k6
```
