# 0005. SSE as the primary push transport, WebSocket as the alternative

- Status: Accepted
- Date: 2026-11-20

## Context

notification-service pushes new inbox items to the browser ([README 4.4](../../README.md#44-real-time-inbox-push-notification-service)). The traffic is one-way: the server tells the client that something happened.

## Decision

**Server-Sent Events** is the primary transport (`GET /api/v1/notifications/stream`). **WebSocket** is offered as an alternative with the same payloads (`GET /api/v1/notifications/ws`).

## Consequences

- SSE is plain HTTP, so it passes through the gateway like any other route with two settings (no response buffering, no idle timeout), and the browser reconnects by itself. SSE `id:` is the notification id, so `Last-Event-ID` replays what was missed from the inbox.
- Both transports need a heartbeat every 15 seconds and a limit of three concurrent connections per user, and both appear in the gateway's route table.
- Two transports to implement and test per language; the second exists for comparison.
- Authentication of both is described in [0006](0006-one-time-ticket-authenticates-sse-and-websocket.md).

## Alternatives considered

WebSocket as the only transport: it is bidirectional, which this feature does not need. The README keeps it as the second transport so that the two can be compared.
