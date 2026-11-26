# 0002. Four domain services and an API gateway

- Status: Accepted
- Date: 2026-11-20

## Context

The domain (a wallpaper-sharing platform) is incidental; the goal is coverage of technologies: several data stores, REST, gRPC, GraphQL, Kafka, caching, search, email, push
([README](../../README.md)). The split into deployables has to give every one of these a place without inventing services that do nothing.

## Decision

Four domain services, each with its own responsibility and store, and one edge service: **account** (PostgreSQL, gRPC server, outbox), **media** (PostgreSQL, S3, image pipeline),
**catalog** (MongoDB, Elasticsearch, GraphQL) and **notification** (Redis, email, SSE/WebSocket), behind an **API gateway** ([README, services](../../README.md#3-services)).
The gateway is edge infrastructure and holds no business logic.

## Consequences

- Every cross-service technology has a real caller and callee: catalog and notification call account over gRPC, catalog calls media over REST, notification calls catalog over REST, and Kafka connects all four.
- Failures between services exist, so resilience (timeouts, circuit breakers, degraded answers) has something to protect ([README, resilience](../../README.md#8-resilience)).
- There are five things to build per language, and a stack of about 5 GB to run locally (`make up`), more with the observability profile.
- Anyone who needs fewer or more services for a real product changes the split with a new record that supersedes this one.

## Alternatives considered

A single application would be simpler to run but would not exercise inter-service calls, events or resilience, which are what the template is for.
More, smaller services would add deployment weight without adding a new technology to demonstrate.
