#!/usr/bin/env python3
"""T1-T3 of docs/SERVICE-SPEC.md: the telemetry of the service arrived in Tempo, Loki and Prometheus.
    telemetry.py --service NAME --trace-id HEX [--tempo URL] [--loki URL] [--prom URL] [--wait SECONDS]
Needs the observability profile (or equivalent) running. Standard library only."""
import argparse, json, sys, time, urllib.parse, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--service", required=True); ap.add_argument("--trace-id", required=True)
ap.add_argument("--tempo", default="http://localhost:3200"); ap.add_argument("--loki", default="http://localhost:3100")
ap.add_argument("--prom", default="http://localhost:9090"); ap.add_argument("--wait", type=int, default=90)
a = ap.parse_args()

def get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:
        return 0, str(e).encode()

def poll(fn):
    end = time.time() + a.wait
    while True:
        ok, why = fn()
        if ok or time.time() > end:
            return ok, why
        time.sleep(3)

def t1():
    s, b = get(f"{a.tempo}/api/traces/{a.trace_id}")
    if s == 200 and a.service.encode() in b: return True, ""
    return False, f"trace {a.trace_id} with service.name {a.service} not found in Tempo (HTTP {s})"
def t2():
    q = urllib.parse.urlencode({"query": '{service_name="%s"}' % a.service, "limit": 5})
    s, b = get(f"{a.loki}/loki/api/v1/query_range?{q}")
    try: n = len(json.loads(b)["data"]["result"])
    except Exception: n = 0
    return (n > 0, "" if n else f"no log stream with service_name={a.service} in Loki (HTTP {s})")
def t3():
    q = urllib.parse.urlencode({"query": '{__name__=~"http_server_(request_)?duration.*_count",job="%s"}' % a.service})
    s, b = get(f"{a.prom}/api/v1/query?{q}")
    try: n = len(json.loads(b)["data"]["result"])
    except Exception: n = 0
    return (n > 0, "" if n else f"no http_server duration histogram with job={a.service} in Prometheus (HTTP {s}); metrics export every OTEL_METRIC_EXPORT_INTERVAL")

failed = False
for id_, fn in (("T1", t1), ("T2", t2), ("T3", t3)):
    ok, why = poll(fn)
    print(("PASS " if ok else "FAIL ") + id_ + ("" if ok else ": " + why)); failed |= not ok
sys.exit(1 if failed else 0)
