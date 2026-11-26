# Security policy

Wallpaper Hub is a **reference and template**: everything in `infra/`, `seed/` and `deploy/` is a local development default (known passwords, a realm with test users, plain HTTP inside the network). Nothing here is meant to be exposed to the internet as it is; [docs/KUBERNETES.md](docs/KUBERNETES.md#beyond-the-laptop) lists what changes for a real deployment.
That said, a mistake in the template (a pattern that is unsafe once copied, a vulnerable pinned dependency, a leaked real secret) is worth reporting.

## Reporting

**Do not open a public issue.** Use GitHub's private reporting: *Security* tab, *Report a vulnerability* ([direct link](https://github.com/dsimonov762/wallpaperhub-template/security/advisories/new)). Say what you found, where, and how to reproduce it.
You will get an answer as soon as the maintainer can give one; this is a one-person project, so please allow a few days.

## Supported versions

Only the latest release and `master`. There are no maintenance branches.

## What the repository does about it

- Secret scanning with push protection, Dependabot alerts (Renovate raises the updates), and CodeQL on every pull request and on `master`; see [docs/REPOSITORY.md](docs/REPOSITORY.md).
- Every version is pinned and updated by Renovate ([docs/RENOVATE.md](docs/RENOVATE.md)).
- The design of authentication and authorization is README section 7 and [ADR 0009](docs/adr/0009-the-gateway-validates-tokens-and-services-validate-them-again.md).
