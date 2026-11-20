# 0010. Database per service

- Status: Accepted
- Date: 2026-11-20

## Context

Four services own different kinds of data and use different stores ([README, data stores](../../README.md#6-data-stores)). Services written in different languages cannot share
an ORM, a schema migration tool or a connection pool, and a shared database would couple their releases through the table layout.

## Decision

No shared databases. Each service owns its store: account and media have their own PostgreSQL schemas, catalog has MongoDB and Elasticsearch, notification has Redis. Other services get at the data only
through the service's API or its events ([README, principles](../../README.md#1-principles)).

## Consequences

- The shape of each store is still shared as a contract: the canonical schema is in [`contracts/db-schema/`](../../contracts/db-schema/). `make schemas` applies it in the local stack, so a service does not run its own DDL there,
  and in other profiles it runs the same files, never a divergent copy ([SERVICE-SPEC 9](../SERVICE-SPEC.md#9-data-stores-and-migrations)). Which service may touch which store is the rule; what the store looks like is not left to each language.
- Data that another service needs is copied, not joined: catalog keeps a snapshot of each author and updates it from account's `profile-updated` event ([README 4.2](../../README.md#42-avatar-change-and-denormalization)).
- Writing to the database and publishing an event are two operations that can fail between each other; account solves that with the outbox ([0003](0003-outbox-stores-json-and-serializes-avro-at-publish-time.md), [0004](0004-transactional-outbox-only-in-account-service.md)).
- There is no transaction across services; consistency between them is eventual.
