# 0007. Redis as the primary database of notification-service

- Status: Accepted
- Date: 2026-11-20

## Context

Redis appears in the stack as a cache (account, catalog), a queue (media) and counters (catalog). The template also wants to show Redis as a **database**, with data that must survive a restart ([README, services](../../README.md#3-services)).
notification-service's data is small, keyed by user and naturally fits Redis structures: the inbox, the preferences and the deduplication of events.

## Decision

notification-service uses Redis as its primary store (inbox, preferences, dedup), with no relational or document database behind it.

## Consequences

- It gets its own Redis instance with persistence: `redis-notification` runs with AOF (`appendonly yes`, `appendfsync everysec`) and a volume. The other Redis instance is ephemeral on purpose, because losing it only costs cache warmth ([`docker-compose.yml`](../../infra/docker-compose.yml)).
- With `everysec`, a crash can lose up to about a second of writes; that is acceptable for an inbox and would not be for money.
- Both instances run with a memory limit and `noeviction`, so a full instance refuses writes instead of dropping data silently.
- Queries are by key; anything that needs a search or a join across users has to be built by hand or does not exist.

## Alternatives considered

A relational or document store would be the conventional choice for an inbox, but it would add nothing to the coverage the template wants (Redis beyond caching).
