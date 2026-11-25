#!/usr/bin/env python3
"""Reference stub: the smallest program that satisfies docs/SERVICE-SPEC.md. It is NOT a template for a service and it
has no business logic. It exists to prove that `conformance/` can pass (and, with BREAK=..., that every check can
fail), and to let you try the suite and `make host` before your own service exists.

    pip install -r requirements.txt
    OTEL_SERVICE_NAME=account-service OIDC_CLIENT_ID=account-svc \
    OIDC_ISSUER_URI=http://localhost:8180/realms/wallpaperhub \
    OIDC_JWKS_URI=http://localhost:8180/realms/wallpaperhub/protocol/openid-connect/certs  python3 stub.py

Environment: HTTP_PORT (8080), MGMT_PORT (8081), BIND_HOST (0.0.0.0), I18N_DIR (../../contracts/i18n), LOG_LEVEL, the
variables of the spec, and BREAK=<ids> (comma separated) to violate checks on purpose: M4 A3 A4 E2 E4 E5 E6 L1 L2 L3
C1 S1 T."""
import json, logging, os, re, signal, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

BREAK = {b.strip() for b in os.environ.get("BREAK", "").split(",") if b.strip()}
HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- configuration, validated at startup (spec 3, C1)
REQUIRED = ["OTEL_SERVICE_NAME", "OIDC_ISSUER_URI", "OIDC_JWKS_URI", "OIDC_CLIENT_ID"]
missing = [v for v in REQUIRED if not os.environ.get(v)]
if missing and "C1" not in BREAK:
    print(json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "level": "error",
                      "message": f"missing required environment variable {missing[0]}", "service": "stub"}), flush=True)
    sys.exit(2)
SERVICE = os.environ.get("OTEL_SERVICE_NAME", "stub-service")
ISSUER = os.environ.get("OIDC_ISSUER_URI", "")
JWKS = os.environ.get("OIDC_JWKS_URI", "http://localhost:0/none")
AUDIENCE = os.environ.get("OIDC_CLIENT_ID", "")
HTTP_PORT, MGMT_PORT = int(os.environ.get("HTTP_PORT", 8080)), int(os.environ.get("MGMT_PORT", 8081))
BIND = os.environ.get("BIND_HOST", "0.0.0.0")
I18N = os.environ.get("I18N_DIR", os.path.join(HERE, "..", "..", "contracts", "i18n"))
BUNDLES = {l: json.load(open(os.path.join(I18N, f"messages.{l}.json"), encoding="utf-8")) for l in ("en", "de", "es")}

# What this stub pretends to be, per service: (public POST, list GET, create POST and its kind, required fields)
PERSONA = {
    "account-service": dict(me="/api/v1/users/me", list="/api/v1/users", create=("/api/v1/registrations", "json", ["username", "email", "password"], True)),
    "media-service": dict(list="/api/v1/media", create=("/api/v1/media", "multipart", ["file", "purpose"], False)),
    "catalog-service": dict(list="/api/v1/wallpapers", create=("/api/v1/wallpapers", "json", ["assetId", "title"], False)),
    "notification-service": dict(list="/api/v1/notifications", create=("/api/v1/admin/notifications/test", "json", ["userId"], False)),
}.get(SERVICE, {})

# ---------------------------------------------------------------- telemetry (spec 8)
tracer = meter = None
providers = []
if "T" not in BREAK:
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    from opentelemetry.propagate import extract
    res = Resource.create({"service.name": SERVICE})
    tp = TracerProvider(resource=res); tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(), schedule_delay_millis=1000))
    mp = MeterProvider(resource=res, metric_readers=[PeriodicExportingMetricReader(
        OTLPMetricExporter(), export_interval_millis=int(os.environ.get("OTEL_METRIC_EXPORT_INTERVAL", 15000)))])
    lp = LoggerProvider(resource=res); lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(), schedule_delay_millis=1000))
    tracer = tp.get_tracer("stub"); meter = mp.get_meter("stub")
    duration = meter.create_histogram("http.server.request.duration", unit="s", description="Duration of HTTP server requests")
    providers = [tp, mp, lp]

# ---------------------------------------------------------------- logs (spec 6)
class JsonFormatter(logging.Formatter):
    def format(self, r):
        if "L1" in BREAK:
            return f"{r.levelname} {r.getMessage()}"
        d = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r.created)) + f".{int(r.msecs):03d}Z",
             "level": r.levelname.lower(), "message": r.getMessage(), "service": SERVICE}
        for k in ("trace_id", "span_id", "request_id", "user_id", "method", "path", "status", "duration_ms"):
            if hasattr(r, k) and getattr(r, k) is not None:
                d[k] = getattr(r, k)
        return json.dumps(d, ensure_ascii=False)

log = logging.getLogger("stub"); log.setLevel(os.environ.get("LOG_LEVEL", "info").upper()); log.propagate = False
h = logging.StreamHandler(sys.stdout); h.setFormatter(JsonFormatter()); log.addHandler(h)
if providers:
    log.addHandler(LoggingHandler(logger_provider=providers[2]))

# ---------------------------------------------------------------- i18n and problems (spec 5)
def lang_of(header):
    # the first two letters of the first tag; slicing instead of a regular expression, which a header of many spaces could make slow (polynomial ReDoS)
    l = (header or "").lstrip()[:2].lower()
    return l if l in BUNDLES else "en"

def tr(lang, key, **args):
    s = BUNDLES[lang].get(key) or BUNDLES["en"].get(key, key)
    for k, v in args.items():
        s = s.replace("{" + k + "}", str(v))
    return s

TP = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")
# E6: a request id from the client goes into a response header, so it is accepted only in this plain form (no space, no control character,
# no folded line): anything else would let a client add lines to our response (HTTP response splitting). Spec E6.
REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")

def no_line_breaks(value):
    """The last line of defence for any response header: no CR and no LF. (E6 above already refuses a request id that is not plain.)"""
    return str(value).replace("\r", "").replace("\n", "")

# ---------------------------------------------------------------- authentication (spec 4)
import jwt
from jwt import PyJWKClient
jwks = PyJWKClient(JWKS, cache_keys=True, lifespan=300)

def authenticate(auth_header):
    """returns (claims, None) or (None, reason). Never logs the token."""
    if not auth_header or not auth_header.startswith("Bearer "):
        return None, "missing bearer token"
    token = auth_header[7:].strip()
    try:
        opts = {"require": ["exp"], "verify_aud": "A4" not in BREAK}
        if "A3" in BREAK:
            claims = jwt.decode(token, options={**opts, "verify_signature": False}, audience=AUDIENCE if "A4" not in BREAK else None,
                                issuer=ISSUER, leeway=30)
        else:
            key = jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=AUDIENCE if "A4" not in BREAK else None,
                                issuer=ISSUER, leeway=30, options=opts)
        if claims.get("typ") not in ("Bearer", None):
            return None, "wrong token type"
        return claims, None
    except Exception as e:  # any validation failure is a 401
        return None, type(e).__name__

# ---------------------------------------------------------------- state
state = {"shutting_down": False}

class Api(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "stub"

    def log_message(self, *a):  # silence the default access log
        pass

    def send(self, status, body=None, ctype="application/json", extra=None):
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():       # every header that is not fixed passes here: no line break can get through (response splitting)
            self.send_header(no_line_breaks(k), no_line_breaks(v))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def problem(self, status, slug, lang, trace_id, code=None, errors=None, detail=None, extra=None):
        body = {"type": f"https://wallpaperhub.dev/problems/{slug}", "title": tr(lang, f"problem.{slug}.title"), "status": status,
                "detail": detail or tr(lang, f"problem.{slug}.detail"), "instance": urlsplit(self.path).path, "traceId": trace_id}
        if code:
            body["code"] = code
        if errors:
            body["errors"] = errors
        self.send(status, body, "application/problem+json", {"Content-Language": lang, **(extra or {})})

    def handle_any(self):
        started = time.perf_counter()
        u = urlsplit(self.path); q = parse_qs(u.query)
        lang = lang_of(self.headers.get("Accept-Language")) if "E4" not in BREAK else "en"
        # request id (E6): echo what came in, otherwise make one
        rid = self.headers.get("X-Request-Id")
        rid = rid if rid and REQUEST_ID.fullmatch(rid) else None            # an implausible id is ignored: a new one is made
        rid_out = (str(uuid.uuid4()) if "E6" in BREAK else rid) or str(uuid.uuid4())
        carrier = {k.lower(): v for k, v in self.headers.items()}
        span_cm = tracer.start_as_current_span(f"{self.command} {u.path}", context=extract(carrier), kind=trace.SpanKind.SERVER) if tracer else None
        span = span_cm.__enter__() if span_cm else None
        if span:
            ctx = span.get_span_context(); trace_id, span_id = format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
        else:
            m = TP.match(self.headers.get("traceparent", "")); trace_id = m.group(1) if m else uuid.uuid4().hex; span_id = uuid.uuid4().hex[:16]
        problem_trace = uuid.uuid4().hex if "E2" in BREAK else trace_id
        status, user = 500, None
        try:
            status, user = self.route(u, q, lang, rid_out, problem_trace)
        except Exception as e:  # last resort: a problem document, no internals
            self.problem(500, "internal-error", lang, trace_id, extra={"X-Request-Id": rid_out}); status = 500
            log.error("unhandled error: " + type(e).__name__, extra={"trace_id": trace_id, "span_id": span_id})
        elapsed = time.perf_counter() - started
        extra = {"trace_id": trace_id, "span_id": span_id, "request_id": rid, "user_id": user, "method": self.command,
                 "path": u.path, "status": status, "duration_ms": round(elapsed * 1000, 1)}
        if "L2" in BREAK:
            extra.pop("trace_id")
        log.info("request", extra=extra)
        if "L3" in BREAK:
            log.info("auth header was " + (self.headers.get("Authorization") or ""), extra=extra)
        if span_cm:
            span.set_attribute("http.response.status_code", status)
            span_cm.__exit__(None, None, None)
            duration.record(elapsed, {"http.request.method": self.command, "http.response.status_code": status, "http.route": u.path})

    def route(self, u, q, lang, rid, trace_id):
        p = PERSONA
        rh = {"X-Request-Id": rid}
        self.rid = rid
        if "M4" in BREAK and u.path.startswith("/health/"):
            self.send(200, {"status": "UP"}, extra=rh); return 200, None
        public = bool(p.get("create") and p["create"][3] and u.path == p["create"][0] and self.command == "POST")
        claims = None
        if not public:
            claims, why = authenticate(self.headers.get("Authorization"))
            if claims is None:
                self.problem(401, "unauthorized", lang, trace_id, extra={"WWW-Authenticate": "Bearer", **rh}); return 401, None
        user = claims.get("sub") if claims else None
        # pagination (E5)
        if self.command == "GET" and u.path == p.get("list"):
            size = int((q.get("size") or ["20"])[0])
            if size > 100 and "E5" not in BREAK:
                self.problem(400, "validation-failed", lang, trace_id, code="pagination.size-too-large",
                             detail=tr(lang, "error.pagination.size-too-large", max=100), extra=rh); return 400, user
            self.send(200, {"items": [], "page": 0, "size": min(size, 100), "totalItems": 0, "totalPages": 0}, extra=rh); return 200, user
        if self.command == "GET" and u.path == p.get("me"):
            self.send(200, {"id": claims.get("sub"), "username": claims.get("preferred_username", "")}, extra=rh); return 200, user
        if self.command == "POST" and p.get("create") and u.path == p["create"][0]:
            kind, required = p["create"][1], p["create"][2]
            n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(n) if n else b""
            errors = []
            if kind == "json":
                try:
                    body = json.loads(raw or b"{}"); body = body if isinstance(body, dict) else {}
                except ValueError:
                    body = {}
                missing = [f for f in required if not str(body.get(f, "")).strip()]
            else:  # multipart: only look for the part names
                missing = [f for f in required if f'name="{f}"'.encode() not in raw]
            for f in missing:
                errors.append({"field": f, "code": "NotBlank", "message": tr(lang, "validation.NotBlank", field=f)})
            if errors:
                self.problem(400, "validation-failed", lang, trace_id, errors=errors, extra=rh); return 400, user
            self.send(201, {"id": str(uuid.uuid4())}, extra=rh); return 201, user
        self.problem(404, "not-found", lang, trace_id, extra=rh); return 404, user

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = handle_any


class Mgmt(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_GET(self):
        ok = self.path in ("/health/live", "/health/startup") or (self.path == "/health/ready" and not state["shutting_down"])
        known = self.path in ("/health/live", "/health/ready", "/health/startup")
        body = json.dumps({"status": "UP" if ok else "DOWN"} if known else {"status": 404}).encode()
        self.send_response(200 if ok else (503 if known else 404))
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

api = ThreadingHTTPServer((BIND, HTTP_PORT), Api); api.daemon_threads = True
mgmt = ThreadingHTTPServer((BIND, MGMT_PORT), Mgmt); mgmt.daemon_threads = True

def shutdown(*_):  # spec 11: ready DOWN, stop accepting, finish in-flight, flush telemetry, exit 0
    state["shutting_down"] = True
    log.info("shutting down")
    def stop():
        api.shutdown(); mgmt.shutdown()
        for pr in providers:
            try: pr.shutdown()
            except Exception: pass
        os._exit(0)
    threading.Thread(target=stop, daemon=True).start()

signal.signal(signal.SIGTERM, signal.SIG_IGN if "S1" in BREAK else shutdown)
signal.signal(signal.SIGINT, shutdown)
threading.Thread(target=mgmt.serve_forever, daemon=True).start()
log.info(f"{SERVICE} listening on {HTTP_PORT} (api) and {MGMT_PORT} (management)")
api.serve_forever()
