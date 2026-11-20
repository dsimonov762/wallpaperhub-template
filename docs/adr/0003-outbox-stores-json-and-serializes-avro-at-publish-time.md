# 0003. The outbox stores JSON and serializes Avro at publish time

- Status: Accepted
- Date: 2026-11-20

## Context

account-service writes a domain change and an event in one database transaction, and a relay publishes the stored events to Kafka ([README 4.3](../../README.md#43-transactional-outbox-account-service)).
The event values are Avro, with schemas in Schema Registry whose compatibility rules the contracts depend on ([README 5.6](../../README.md#56-kafka-topics-and-avro)).
The row in `outbox_event` can hold either the final Avro bytes or something readable.

## Decision

The outbox row holds the payload as **JSON**. The relay serializes it to **Avro** when it publishes, through Schema Registry.

## Consequences

- Schema Registry compatibility is enforced where events leave the system: a payload that does not fit the registered schema is rejected when the relay publishes (and counted in `outbox_publish_failures_total`), not when the row is written.
- The table stays readable: an operator can look at pending events with plain SQL.
- The relay needs the serializer and a reachable Schema Registry, and the transaction that writes the row cannot tell that the payload will fail later. A contract test and the outbox failure scenario of the e2e suite have to cover that gap.

## Alternatives considered

Storing Avro bytes in the row would validate at write time, but the table would be opaque, and a schema change would leave old rows in a format the new code has to know how to read.
