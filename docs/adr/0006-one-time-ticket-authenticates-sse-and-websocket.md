# 0006. A one-time ticket authenticates SSE and WebSocket connections

- Status: Accepted
- Date: 2026-11-20

## Context

Browsers cannot set an `Authorization` header on an `EventSource` or a `WebSocket`, and the notification stream must belong to one user ([README 4.4](../../README.md#44-real-time-inbox-push-notification-service)).
Putting the access token in the URL would write it into access logs and proxies for as long as it is valid.

## Decision

The client first calls `POST /api/v1/notifications/stream-tickets` (protected by the JWT) and receives a **one-time ticket** with a 30 second lifetime, stored in Redis. It then connects with `?ticket=...`.
Clients that can set headers (non-browser ones) may use the `Authorization` header directly.

## Consequences

- What ends up in a URL, and so in logs, is useless after the first use and after 30 seconds.
- One more request before every connection, and a ticket store with expiry, in the service that already has Redis as its database ([0007](0007-redis-as-the-primary-database-of-notification-service.md)).
- The gateway has to let the query string through and the service has to consume the ticket atomically, or the "one-time" is not true.

## Alternatives considered

The access token itself in the query string would put a credential that stays valid into logs and proxies, which is what the ticket avoids.
