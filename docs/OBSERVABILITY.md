# Observability: dashboards and the metric contract

`make up-obs` (or any profile combination with `observability`) starts Grafana on <http://localhost:3000> (anonymous admin). It opens on
the **Overview** dashboard; the others are in the folder *Wallpaper Hub* and linked from the top bar of every dashboard.

| Dashboard | Question it answers | Data |
|---|---|---|
| **Overview** | Is the platform healthy right now? | gateway + all services, error logs, pipeline state |
| **Service (RED)** | What is wrong with this service? Pick it in the `service` list, narrow with `route`. | the service's OpenTelemetry HTTP metrics, DB and outgoing-call metrics, its logs and failed/slow traces |
| **Gateway (Envoy)** | What reaches us, what do we turn away, are the upstreams healthy? | Envoy stats scraped from `gateway:8081/metrics` |
| **Business and async** | Is the product working: uploads, image processing, emails, outbox, Kafka lag, SSE, circuit breakers, caches? | the business metrics below |
| **Logs** | What did the services say? Filter by service, level, text. | Loki |
| **Observability stack** | Why is a dashboard empty? | Prometheus, Alloy, Loki, Tempo self-metrics |
| **Load test (k6)** | What did a k6 run send and measure, and what did the system say at the same time? | k6 metrics (remote write into Prometheus, only while a run is pushed) next to the gateway and service metrics; [LOAD.md](LOAD.md) |

Correlation works in both directions: a latency percentile has **exemplars** (dots) that open the trace; a log line has a `TraceID`
link; a trace has "logs for this span". So the usual path is Overview → Service (a spike) → an exemplar or a failed trace → the logs of that span.

## A panel is empty: why?

1. Open **Observability stack**. Alloy *accepted* points, but *sent on* zero: Alloy or the backend behind it is down. *Accepted* zero: nothing arrives, the service
   does not export (check `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_METRIC_EXPORT_INTERVAL`) or is not running.
2. `make dashboards-coverage` compares every metric the dashboards use with what Prometheus really has and lists the missing ones. The `k6_*` metrics exist only after a load test (`make load-run`); `make dashboards-coverage` lists them as missing until then. A panel of a business metric stays
   empty until the service that owns it emits it; that is expected in a template with no business code yet.
3. The `service` list of the Service dashboard shows only services that sent `http_server_request_duration_seconds_count`: a service that never took a request is not in it.

## The metric contract

The dashboards are written against these Prometheus names. A service in any language gets them by using the OpenTelemetry SDK; nothing is needed in Prometheus.
What the SDK calls the instrument and what Prometheus stores differ, so both are listed. (Checked against Prometheus 3.16 receiving OTLP from the OpenTelemetry SDK.)

**How OTel names become Prometheus names:** dots become underscores; a unit adds a suffix (`s` → `_seconds`, `By` → `_bytes`); a counter gets `_total`;
the suffix is not added twice (an instrument already called `uploads_total` stays `uploads_total`, and `image_processing_seconds` with unit `s` stays that);
attribute `http.route` becomes label `http_route`. Resource attribute `service.name` becomes the label **`job`**, `service.instance.id` the label `instance`
(set it, otherwise the SDK invents a random UUID). `deployment.environment` and the other resource attributes are only in the `target_info` metric.
The `service.name` MUST equal `OTEL_SERVICE_NAME` of the compose file (`account-service`, `media-service`, `catalog-service`, `notification-service`): the dashboards select services by `job=~".+-service"`.

### Standard (the SDKs and auto-instrumentation emit them; no code)

| OTel instrument | Prometheus | Labels used by the dashboards |
|---|---|---|
| `http.server.request.duration` (histogram, `s`) | `http_server_request_duration_seconds_{bucket,count,sum}` | `http_request_method`, `http_route`, `http_response_status_code` |
| `http.server.active_requests` (up-down counter) | `http_server_active_requests` | |
| `http.client.request.duration` (histogram, `s`) | `http_client_request_duration_seconds_*` | `server_address`, `http_response_status_code` |
| `db.client.operation.duration` (histogram, `s`) | `db_client_operation_duration_seconds_*` | `db_operation_name`, `db_system_name` |

`http.route` MUST be the route template (`/api/v1/wallpapers/{id}`), never the concrete URL: a URL with the id in it makes a new series for every wallpaper and
fills Prometheus. Use explicit histogram buckets (the semantic-convention advice: 5 ms to 10 s) so the percentiles are comparable.

### Business and platform (the service implements them; names are README section 11)

| Owner | Instrument (SDK) | Prometheus | Labels | Meaning |
|---|---|---|---|---|
| media | counter `uploads` | `uploads_total` | `purpose` (WALLPAPER, AVATAR, BANNER), `status` (accepted, rejected) | upload requests and their outcome |
| media | histogram `image_processing`, unit `s` | `image_processing_seconds_*` | `result` | upload event to derivatives ready |
| notification | counter `emails_sent` | `emails_sent_total` | `template`, `status` (sent, failed) | emails handed to the SMTP server |
| notification | up-down counter `sse_connections_active` | `sse_connections_active` | | open SSE streams |
| notification | gauge `circuit_breaker_state` | `circuit_breaker_state` | `name` | 0 closed, 1 half-open, 2 open |
| any with a cache | gauge `cache_hit_ratio` | `cache_hit_ratio` | `cache` | 0..1 |
| any that publishes events | gauge `outbox_pending` | `outbox_pending` | | rows not yet published |
| any that publishes events | gauge `outbox_oldest_age`, unit `s` | `outbox_oldest_age_seconds` | | age of the oldest unpublished row |
| any that consumes Kafka | gauge `kafka_consumer_lag` | `kafka_consumer_lag` | `group`, `topic` | messages behind |

Keep label values to a small fixed set; never a user id, asset id or URL.

### Logs and traces

- **Loki**: the OTLP ingestion makes `service_name` a label (equal to the OTel `service.name`) and keeps `trace_id`, `span_id` and the level as structured metadata:
  the dashboards filter with `| detected_level="error"` and link `trace_id` to Tempo. Log through the OTLP log exporter with the active span's context, then both work.
- **Tempo**: server spans (`kind = server`) with `service.name`; failed requests set the span status to *error* (the "Failed traces" tables select `status = error`).
  The gateway's spans carry the service name `api-gateway`.

### Gateway (Envoy)

Envoy does not push OTLP metrics, so Prometheus scrapes `gateway:8081/metrics` (job `gateway`; the target is down while the `apps`/`mocks` profile is not running).
Envoy reports durations in **milliseconds** (`envoy_http_downstream_rq_time_bucket`), the services in seconds: the dashboards set the unit per panel. The local rate limiters
(`envoy_http_local_rate_limit_*`, one `envoy_local_http_ratelimit_prefix` per limiter) count per gateway instance.

## Changing the dashboards

The JSON files in `infra/grafana/dashboards/` are the source of truth, mounted read-only and re-read by Grafana every 30 seconds.

- **Quick experiment**: edit in the UI. It works until the file changes.
- **To keep it**: *Export > Export as JSON* (leave "export for sharing externally" off), replace the file in the repo, commit. Keep `"id": null` and the `wh-` uid.
- `make dashboards-check` validates the files without Grafana: JSON structure, panel ids and layout (no overlaps, inside 24 columns), datasources exist in
  `provisioning/datasources`, every PromQL expression parses, every `$variable` is defined and used, the compose mount matches the provider. CI runs it.
- `make dashboards-coverage` is the metric check against your running Prometheus (`PROMETHEUS_URL` to point elsewhere).

## What is verified, what is not

Verified with real components (Prometheus 3.16.0, Loki, Tempo, Alloy, Envoy from the repo's config, telemetry produced by the OpenTelemetry Python SDK through Alloy):
the metric names and labels above, exemplars, `service_name`/`detected_level`/`trace_id` in Loki, and **every query of every dashboard** (PromQL, LogQL, TraceQL) executes without error
and returns data where data exists. Not verified: rendering in Grafana itself (no Grafana binary was available): layout, colors, units and the transformations of the two tables
were written from the Grafana 12/13 JSON model but not looked at; the first thing to do after `make up-obs` is to open each dashboard once. Kafka lag and the other business
metrics were produced by a stand-in emitter, not by real services.
