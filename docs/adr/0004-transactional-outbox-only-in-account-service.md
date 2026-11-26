# 0004. The transactional outbox only in account-service

- Status: Accepted
- Date: 2026-11-20

## Context

Writing to a database and publishing to Kafka is a dual write: a crash between the two loses or invents events. The outbox pattern closes that gap at the cost of a table, a relay and a cleanup job
([README 4.3](../../README.md#43-transactional-outbox-account-service)). The project is a teaching and comparison tool, and the failure mode is easier to understand when both behaviours can be seen.

## Decision

Only **account-service** uses the outbox. media-service and catalog-service publish directly after the commit, on a best-effort basis.

## Consequences

- The two approaches can be compared in one system: stop the broker, make changes, restart it, and see which service loses events. The design's e2e suite includes an outbox failure test for account ([README 14](../../README.md#14-testing)).
- An event published by media or catalog can be lost when the process dies between the commit and the publish. Consumers must be idempotent in any case (delivery is at least once).
- This is a deliberate gap, not an oversight. A system built from this template should decide per event whether best effort is acceptable; moving the outbox to another service is a new record that supersedes this one.

## Alternatives considered

An outbox in every service would be the safer production choice and is described in the README as the pattern, but it would remove the contrast the template is meant to show.
Debezium reading the outbox table instead of a polling relay is documented as an alternative and not required ([README 4.3](../../README.md#43-transactional-outbox-account-service)).
