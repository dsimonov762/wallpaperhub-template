# 0001. Contract-first with a shared contracts folder

- Status: Accepted
- Date: 2026-11-20

## Context

The point of the project is to implement the same system in several languages and compare them ([README, principles](../../README.md#1-principles)). That only works if every
implementation is held to the same interfaces, and if one test suite can judge all of them. Interfaces that exist only as the output of one implementation cannot do that.

## Decision

The interfaces live in [`contracts/`](../../contracts/) and are the source of truth: OpenAPI per service, protobuf for gRPC, Avro for Kafka values, GraphQL SDL, the i18n message keys and bundles,
and a canonical database schema. Implementations satisfy the contracts; a contract is never derived from an implementation.

## Consequences

- Services in different languages can be mixed, and one e2e and conformance suite ([0012](0012-conformance-suite-defines-what-a-service-is.md)) applies to all of them.
- The contracts are checked against each other, the gateway configuration and the README (`make check-contracts`), linted (`make contracts-lint`), and compared with the branch point of a pull
  request (`make contracts-breaking`: oasdiff, `buf breaking`, Avro BACKWARD compatibility, GraphQL).
- Evolving a contract has a rule: an additive change passes; a breaking one needs a new version (`/v2`, `*.v2.avsc`, `account/v2/`) next to the old one ([GETTING-STARTED](../GETTING-STARTED.md#contract-tooling)).
- Code can be generated from the contracts (`make codegen`), and the Bruno collection and the mocks are derived from them.
- The cost is that a change to an API starts in `contracts/`, not in the controller, and that a team must be willing to review a contract before any code exists.

## Alternatives considered

Letting each implementation generate its own OpenAPI document would give as many versions of the truth as there are implementations, and nothing to hold a new implementation to.
