# Documentation map

Where to find what. `make docs-check` verifies that every document in `docs/` is listed here and that every relative link and anchor in the repository's Markdown files resolves.

## Start here

| You are... | Read |
|---|---|
| a new human or AI dialog that was given **one piece of work** | [../AGENTS.md](../AGENTS.md), then your package in [ROADMAP.md](ROADMAP.md) |
| the owner, wanting to know where the project stands | [STATUS.md](STATUS.md) |
| wondering **why** something is the way it is | [adr/](adr/README.md) for a decision, [HISTORY.md](HISTORY.md) for the story |
| going to start the stack for the first time | [GETTING-STARTED.md](GETTING-STARTED.md) |
| going to implement a service | [SERVICE-SPEC.md](SERVICE-SPEC.md), the README sections it names, then [../conformance/README.md](../conformance/README.md) |

## By question

| Question | Document |
|---|---|
| What is this system, how is it built, what does each service do? | [../README.md](../README.md) (the design, v1.1) |
| What exists, what does not, what is open, what is untested? | [STATUS.md](STATUS.md) |
| What is left to build and who can build it in parallel? | [ROADMAP.md](ROADMAP.md) |
| How did we get here, and what went wrong on the way? | [HISTORY.md](HISTORY.md) |
| What are the working rules (also for AI agents)? | [../AGENTS.md](../AGENTS.md) |
| Why was X decided? | [adr/README.md](adr/README.md) (23 records, indexed) |
| What must a service do from the outside? | [SERVICE-SPEC.md](SERVICE-SPEC.md) (23 numbered checks) |
| How do I start, stop, reset the stack; what do I open; how much memory? | [GETTING-STARTED.md](GETTING-STARTED.md) |
| How do I check a running service against the spec? | [../conformance/README.md](../conformance/README.md) |
| What do the dashboards show; what metrics must a service emit? | [OBSERVABILITY.md](OBSERVABILITY.md) |
| How do I break a dependency on purpose? | [CHAOS.md](CHAOS.md) |
| How do I load-test; what are the latency budgets? | [LOAD.md](LOAD.md) |
| How do I use HTTPS locally? | [HTTPS.md](HTTPS.md) |
| How do I run on Kubernetes (local kind cluster, Helm chart)? | [KUBERNETES.md](KUBERNETES.md) |
| What does CI check, and what is deliberately not in it? | [CI.md](CI.md) |
| How is the GitHub repository configured (protection, security, releases, labels)? | [REPOSITORY.md](REPOSITORY.md) |
| What do the git hooks do? | [PRE-COMMIT.md](PRE-COMMIT.md) |
| How are versions kept current? | [RENOVATE.md](RENOVATE.md) |
| What test data exists, and who are the seeded users? | [../seed/README.md](../seed/README.md), [../seed/CATALOG.md](../seed/CATALOG.md) |
| How do I call the API by hand? | [../bruno/README.md](../bruno/README.md) |
| How is the gateway configured? | [../services/gateway/envoy/CHEATSHEET.md](../services/gateway/envoy/CHEATSHEET.md) |
| What are the contract conventions (OpenAPI, i18n, database schemas)? | [../contracts/openapi/README.md](../contracts/openapi/README.md), [../contracts/i18n/README.md](../contracts/i18n/README.md), [../contracts/db-schema/README.md](../contracts/db-schema/README.md) |

## Every document of `docs/`

| Document | Kind | Purpose |
|---|---|---|
| [README.md](README.md) | map | this file |
| [STATUS.md](STATUS.md) | state | what exists and what does not, with a verification level for each; open decisions; limitations |
| [ROADMAP.md](ROADMAP.md) | plan | work packages with lanes, inputs, definition of done and a prompt to start one |
| [HISTORY.md](HISTORY.md) | story | what was built in which order and why; lessons from running it |
| [SERVICE-SPEC.md](SERVICE-SPEC.md) | specification | the outside behaviour of any service in any language |
| [GETTING-STARTED.md](GETTING-STARTED.md) | guide | first start, daily commands, URLs and logins, profiles and their memory, contract tooling |
| [OBSERVABILITY.md](OBSERVABILITY.md) | guide | the metric contract and the seven dashboards |
| [CHAOS.md](CHAOS.md) | guide | Toxiproxy edges and the eleven scenarios |
| [LOAD.md](LOAD.md) | guide | k6 journeys, profiles, latency budgets |
| [HTTPS.md](HTTPS.md) | guide | mkcert, the HTTPS stack |
| [KUBERNETES.md](KUBERNETES.md) | guide | the Helm chart, the kind cluster, what is verified |
| [REPOSITORY.md](REPOSITORY.md) | guide | the GitHub settings as files: About text, protection of `master`, security features, environments, labels, releases and tags |
| [CI.md](CI.md) | guide | the workflows, jobs, branch protection |
| [PRE-COMMIT.md](PRE-COMMIT.md) | guide | the hooks and how they skip |
| [RENOVATE.md](RENOVATE.md) | guide | what Renovate manages and how to mark a pin |
| [adr/README.md](adr/README.md) | decisions | the index of decision records; how to write one |

## Which document gets which kind of information

A fact lives in exactly one place; the others link to it.

| Information | Goes to | Not to |
|---|---|---|
| A design or behaviour of the system | the README section it belongs to, or a contract | a guide |
| A decision and its reasons | a new [ADR](adr/README.md) (`make adr-new`) | STATUS or HISTORY (they link to the ADR) |
| How to use a feature | the guide of that feature | the README |
| What is finished, what is open, how well it is verified | [STATUS.md](STATUS.md) | anywhere else |
| What happened and what we learned | [HISTORY.md](HISTORY.md) (append a line, never rewrite) | STATUS |
| Work still to do | [ROADMAP.md](ROADMAP.md) | the README (section 17 only gives the coarse phases) |
| How to behave in this repository | [../AGENTS.md](../AGENTS.md) | the guides |

Conventions: a document starts with a one-line title and says in its first paragraph what it is for; claims about how well something was verified use the levels of [STATUS.md](STATUS.md#verification-levels-used-in-this-file);
relative links only; commands are the `make` targets (`make help` lists them), never a long invocation that a target already wraps. A new document in `docs/` is added to the table above in the same change.
