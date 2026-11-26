<!-- Title: "WP-<id>: what it does" (see docs/ROADMAP.md), or a plain sentence for a fix. The title becomes the commit on master (squash merge). -->

## What and why

## Package and lane

- Package: WP-
- Started from commit:
- [ ] I changed only the files of my lane and the shared files in my own hunks (AGENTS.md, "Lanes and shared files")

## Checklist

- [ ] `make precommit` passes (or the checks it names that need no containers)
- [ ] Generated files are regenerated, not edited (`make k8s-gen`, `bruno-gen`, `seed-build`, `chaos-gen`, `adr-index` as far as they apply)
- [ ] Contracts: unchanged, or additive and `make contracts-breaking BASE=origin/master` passes, or a breaking change with a new version and an ADR
- [ ] Documentation of the area, `docs/STATUS.md` and `docs/HISTORY.md` are updated
- [ ] A decision that is expensive to reverse has an ADR (`make adr-new`)

## Verified

<!-- What ran, how, on what; what did not run. "Not verified" is a normal answer; an unverified "done" is not. -->

## Open questions for the owner
