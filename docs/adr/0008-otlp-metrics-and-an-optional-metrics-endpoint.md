# 0008. OTLP metrics and an optional /metrics endpoint

- Status: Accepted
- Date: 2026-11-20

## Context

Logs, traces and metrics flow through OTLP to Alloy and on to Loki, Tempo and Prometheus ([README 11](../../README.md#11-observability)). Prometheus's own model is pull: it scrapes a `/metrics` endpoint.
The template wants both ways visible.

## Decision

Metrics are **pushed by OTLP** by default. An **optional** `GET /metrics` in Prometheus text format is allowed on the management port (8081) only, for contrast.

## Consequences

- The conformance suite requires the OTLP path (a Prometheus series for the service's HTTP server duration, [SERVICE-SPEC 8](../SERVICE-SPEC.md#8-telemetry)) and does not require `/metrics` ([SERVICE-SPEC 2](../SERVICE-SPEC.md#2-management-endpoints-port-8081)).
- Services never talk to Loki, Tempo or Prometheus; they know only the OTLP endpoint (`OTEL_EXPORTER_OTLP_ENDPOINT`).
- The names, units and labels of the business metrics are a contract: the Grafana dashboards are written against them ([OBSERVABILITY](../OBSERVABILITY.md)).
