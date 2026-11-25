# The GitHub repository: settings, protection, releases

How `dsimonov762/wallpaperhub-template` is configured on GitHub, why, and how to apply or change it. The settings are **files in `.github/` applied by `scripts/github-setup.py`**, so they can be reviewed in a pull request and repeated for another repository ([ADR 0022](adr/0022-master-is-protected-by-a-ruleset-and-the-repository.md)).

| What | File |
|---|---|
| About text, topics, features, merge settings, security, Actions token, environments | [`.github/repository.json`](../.github/repository.json) |
| Protection of `master` and of release tags | [`.github/rulesets/master.json`](../.github/rulesets/master.json), [`tags.json`](../.github/rulesets/tags.json) |
| Labels | [`.github/labels.json`](../.github/labels.json) |
| Who reviews what | [`.github/CODEOWNERS`](../.github/CODEOWNERS) |
| Issue forms, pull request template, release-note categories | `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/release.yml` |
| License, how to contribute, security policy, code of conduct | [`LICENSE`](../LICENSE), [`CONTRIBUTING.md`](../CONTRIBUTING.md), [`SECURITY.md`](../SECURITY.md), [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) |

## Applying it

```
export GH_TOKEN=...            # a fine-grained token for this one repository (see Credentials below); needs the GitHub CLI binary, no `gh auth login`
make github-plan               # prints every request that would be sent; sends nothing
make github-apply              # sets everything; safe to run again. ONLY=rulesets,labels sets a part
make github-check              # offline: the files are consistent with ci.yml and the templates (CI runs it)
```

`apply` configures the repository that `origin` points to: an https, ssh or scp-style URL, also through an ssh host alias from `~/.ssh/config` (one alias per account is common; `ssh -G` resolves it, so any alias name works). To name it instead: `GH_REPO=OWNER/NAME make github-apply` (the variable `gh` itself reads) or `--repo OWNER/NAME` on `scripts/github-setup.py apply`; the first line of the output says which repository it is and where the name came from. Which account acts is decided by the credential, **not** by the ssh key or the remote (see [Credentials](#credentials)); the second line of the output says who it is, and the run stops before sending anything unless that account is an admin of the repository. The name is not stored in the files, so a copy of the repository needs no edit.
`apply` sets only what the files say. It prints one line per request and, at the end, the requests that failed and the usual reasons (not an admin, a feature the plan does not have, code scanning already configured by a workflow); the rest is applied, and a second run is harmless.
Steps: `about`, `settings`, `security`, `actions`, `rulesets`, `environments`, `labels`.

**First time, in this order:** merge the pull request that added these files; `make github-plan` and read it; `make github-apply`; then the checklist [*Not set by the script*](#not-set-by-the-script); then [the first release](#tags-and-releases).
After the ruleset is on, every change to `master` goes through a pull request, including the next change to these files.

## Credentials

`make github-apply` talks to the GitHub API through the `gh` command. An **ssh key does not authenticate `gh`**: ssh is only how `git push` reaches GitHub, so with several accounts and several keys the remote URL can name one account while `gh` is logged in as another. Three ways to give `gh` an identity, best first for a repository that is meant to look like a real one:

1. **A fine-grained personal access token for this repository only, given per command** (recommended). GitHub > Settings > Developer settings > Personal access tokens > Fine-grained tokens, created **by the owner account**: *Repository access: only* `wallpaperhub-template`, expiration 7 to 30 days, repository permissions **Administration: read and write**, **Issues: read and write** (labels), **Environments: read and write**; *Metadata: read* is added automatically. Then, in the Ubuntu shell:

   ```
   read -rsp "token: " GH_TOKEN; export GH_TOKEN; echo     # typed, not stored in the shell history or in a file
   make github-plan && make github-apply
   unset GH_TOKEN
   ```

   Why this one: the token can touch one repository and nothing else, it expires, nothing is stored on disk (`gh` needs no `auth login`, only to be installed), it does not matter which account `gh` or the ssh agent would have picked, and **Administration: write** (the dangerous permission) exists only for the minutes the command runs. Revoke the token afterwards; create a new one for the next change of settings.
   The list of permissions is what the requests need according to GitHub's documentation as far as it could be checked (the page is long and was read in parts); if a request fails with `403 Resource not accessible by personal access token`, the message names what is missing: add it to the token and run again, the run is repeatable.
2. **A separate `gh` login per account**, when you would rather not paste a token: `GH_CONFIG_DIR=~/.config/gh-dsimonov762 gh auth login` once (the folder keeps this account's login apart from every other), then `GH_CONFIG_DIR=~/.config/gh-dsimonov762 make github-apply`. The login is stored on the machine and is as powerful as the scopes you gave it (the default is `repo`, which reaches every repository of the account): the price of convenience.
3. **`gh auth login` once and `gh auth switch`** between accounts: the least safe, because the active account is a global state that the next command inherits. The check before every run (the second line, "acting as ...") exists for this case.

An organization later: use a fine-grained token of an owner of the organization, or run the apply from a workflow with a GitHub App token; the script does not change.

## About

- **Description** (350 characters at most): *Language-agnostic microservice reference: OpenAPI, gRPC, Avro and GraphQL contracts, a complete local dev environment (Compose, Envoy gateway, Keycloak, Kafka, observability, kind and Helm), a conformance suite and CI. Implement the same four services in any language.*
- **Topics:** `microservices polyglot reference-architecture template contract-first openapi grpc graphql avro kafka envoy docker-compose kubernetes helm opentelemetry keycloak conformance-testing developer-experience platform-engineering github-actions` (the limit is 20).
- **Website:** none. **Template repository:** on (*Use this template* creates a copy; a copy runs `make github-apply` to get the same settings).
- **Social preview:** upload [`docs/assets/social-preview.png`](assets/social-preview.png) (1280 x 640; the source is `social-preview.html` next to it), Settings > General > Social preview. The API has no endpoint for it.
- **Features:** Issues on (forms only, blank issues off); Wiki and Projects off, because the documentation is in the repository ([README](README.md)) and the work is in [ROADMAP](ROADMAP.md).

## Protection of `master` (ruleset `master`)

| Rule | Setting | Why |
|---|---|---|
| Deletion, force push | blocked | `master` is the history everybody builds on |
| Changes only by pull request | required; **0 approvals** today; stale approvals dismissed on a new push; conversations must be resolved | one maintainer cannot approve their own pull request; see [When the team grows](#when-the-team-grows) |
| Required status check | **`ok`**, from the GitHub Actions app, on a branch that is up to date | `ok` is the last job of [`ci.yml`](../.github/workflows/ci.yml) and fails when any job it needs fails ([CI.md](CI.md)); GitHub shows it as `ci / ok`, but registers the job name |
| Merge method | **squash only**; linear history | one commit per pull request, whose message is the title `WP-<id>: ...`; the branch is deleted afterwards |
| Bypass | repository admins, **only through a pull request** | the emergency hatch when CI itself is broken; a direct push is still refused |

Two details worth knowing. The rule *requires the check to be green* but does not make CI run: `ci.yml` runs on every pull request, so it always reports. And a check that no job produces would block every merge; `make github-check` compares the name with `ci.yml` for exactly that reason.
**Renovate** opens ordinary pull requests, so it meets the same rules. Auto-merge is allowed in the settings; Renovate's own auto-merge is not switched on ([RENOVATE.md](RENOVATE.md)).

## Release tags (ruleset `release tags`)

Tags `v*` cannot be deleted, moved or updated, so a version that another repository pins stays what it was. Admins can bypass it, for the day a tag is pushed by mistake.

## Tags and releases

The tag is the **version of the template**: contracts, service specification, conformance suite, infrastructure and the tools a service repository builds on. Semantic versioning, read this way:

- **major**: a breaking change of a contract, of the service specification or of a documented `make` target;
- **minor**: a new capability or an additive contract change;
- **patch**: a fix, a documentation change, a version update.

It stays `0.x` until the first real service passes the conformance suite and the system flows; that is the moment to call it `1.0.0`. The first release is the template as it is now: `v0.1.0`.

```
git switch master && git pull
git tag -a v0.1.0 -m "Template v0.1.0: contracts, local environment, CI, Kubernetes, documentation"
git push origin v0.1.0
gh release create v0.1.0 --verify-tag --title "v0.1.0: the template" --generate-notes
```

`--generate-notes` sorts merged pull requests by label with [`.github/release.yml`](../.github/release.yml), which is why pull requests carry labels (`breaking`, `contract`, `area:*`, ...). Write one paragraph by hand at the top of the notes for a release that matters.

## Security

| Feature | State | Notes |
|---|---|---|
| Secret scanning and push protection | on | a push with a recognised secret is refused. The development defaults in `infra/.env.example` and `seed/` are not patterns that it knows |
| Dependabot alerts | on | read by Renovate, which then raises the update at once, outside its Monday schedule ([RENOVATE.md](RENOVATE.md)) |
| Dependabot security updates | **off** | Renovate does this; two tools would open two pull requests for one vulnerability |
| Dependabot version updates | none (no `dependabot.yml`) | Renovate |
| Private vulnerability reporting | on | [SECURITY.md](../SECURITY.md) links to it |
| CodeQL (default setup) | on for `actions`, `javascript-typescript`, `python` | on pull requests, on `master` and weekly; results under *Security > Code scanning*. Not a required check yet: make it one (a `code_scanning` rule in `master.json`) after the first clean run |
| Actions token | read-only by default; Actions cannot approve pull requests | a workflow that writes asks for it in its own `permissions:` |

What is **not** covered, and is planned: secret scanning of the repository history with an allow-list, image and dependency scanning, license checks ([WP-X1](ROADMAP.md#wp-x1-security-scanning)).

## Environments

| Environment | Can be deployed from | Reviewer | Today |
|---|---|---|---|
| `staging` | `master`, tags `v*` | none | empty |
| `production` | tags `v*` only | the owner (may approve their own deployment: one maintainer) | empty |

They exist so that the first deployment pipeline ([WP-C1](ROADMAP.md#wp-c1-release-and-deployment)) finds the rules in place; nothing deploys to them and they hold no secrets. Which registry and which targets is still an open decision ([STATUS.md](STATUS.md#decisions-that-are-still-open), D-4).
Secrets for a real environment belong to an environment, not to the repository ([WP-O2](ROADMAP.md#wp-o2-secrets-for-real-environments)).

## Labels

`type`: `bug`, `enhancement`, `documentation`, `security`, `dependencies`. `process`: `work-package`, `contract`, `breaking`, `adr`, `needs-decision`, `blocked`, `good first issue`, `help wanted`, `question`, `duplicate`, `wontfix`. `area:`: `gateway`, `account`, `media`, `catalog`, `notification`, `infra`, `ci`, `k8s`.
Issue forms add `bug`, `work-package` or `contract` by themselves; Renovate adds `dependencies`. The labels the forms and `release.yml` use are checked to exist.

## When the team grows

Edit `.github/rulesets/master.json` in a pull request and run `make github-apply ONLY=rulesets`:

1. `required_approving_review_count: 1`, `require_code_owner_review: true`, and `require_last_push_approval: true` if the author may push after an approval.
2. Replace `.github/CODEOWNERS` by team handles per area (the file says how); the owner of `contracts/` should be the people who answer for the architecture.
3. Remove the admin bypass, or keep it for one named person.
4. If every merge makes the other pull requests stale and CI runs again and again, set `strict_required_status_checks_policy` to `false` or add a merge queue.
5. Moving the repository to an organization: transfer it, then add `OrganizationAdmin` to the bypass actors if wanted and set the environment reviewers to a team.

## Not set by the script

The API has no endpoint for these, or they are decisions about people:

- [ ] Upload the social preview image (above).
- [ ] Settings > Actions > General > *Fork pull request workflows*: require approval for all outside collaborators (this repository is public, forks can run workflows).
- [ ] Install the Renovate GitHub App if it is not installed ([RENOVATE.md](RENOVATE.md)).
- [ ] Two-factor authentication on the owner account, and a passkey or a security key if possible: the ruleset protects `master` from everyone but the person who can change the ruleset.
- [ ] Settings > Code security: check that *Code scanning* shows CodeQL as configured, and look at the first results.
- [ ] Optional: Discussions (the REST API cannot switch them on), a pinned issue that links to [ROADMAP.md](ROADMAP.md), sponsors, a project board.

## Service repositories

The first real service is going to live in a repository of its own (the open decision D-2 in [STATUS.md](STATUS.md#decisions-that-are-still-open)). The files here are written to be reused: copy `.github/` (change the names in `CODEOWNERS`, the issue-form links and the topics), `scripts/github-setup.py`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, run `make github-apply`, and the new repository protects itself the same way. The required check there is the job that ends that repository's workflow, again named `ok`.

## What is verified, what is not

The files are consistent (`make github-check`, with a self-test that proves it can fail: `make github-selftest`), and `apply` was run against a stand-in for `gh` that answers like a fresh repository and like one that already has everything: the first run creates, the second updates, a failed request is reported at the end and gives a non-zero exit.
All 68 requests of a full run were validated against **GitHub's own REST API description** (the OpenAPI document that GitHub publishes): the operations exist, every body validates against the request schema, and no key is undocumented; the same validator rejects deliberately wrong requests.
**Not verified: any request against the real GitHub**, because the sandbox has no credentials for the repository. The likely surprises, in order: the admin bypass actor id (`5` is the *Admin* repository role), the order in which code scanning and Actions settings are accepted, a feature that a personal account lacks. `make github-apply` prints each failed request with GitHub's message; send it.
