#!/usr/bin/env python3
"""L1-L3 of docs/SERVICE-SPEC.md: reads the stdout log of the service under test and checks it.
    logs.py (--file PATH | --docker CONTAINER) --trace-id HEX --secret TEXT [--secret TEXT ...]
Prints PASS/FAIL lines, exits 1 when one fails. Standard library only."""
import argparse, json, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument("--file"); ap.add_argument("--docker")
ap.add_argument("--trace-id", required=True)
ap.add_argument("--secret", action="append", default=[])
a = ap.parse_args()

if a.file:
    text = open(a.file, encoding="utf-8", errors="replace").read()
else:
    p = subprocess.run(["docker", "logs", "--since", "15m", a.docker], capture_output=True, text=True)
    if p.returncode != 0:
        print(f"FAIL L1: cannot read logs of {a.docker}: {p.stderr.strip()}"); sys.exit(1)
    text = p.stdout + p.stderr   # a service writes JSON to stdout; stderr is included to catch stray output

lines = [l for l in text.splitlines() if l.strip()]
failed = False
def result(ok, id_, msg):
    global failed
    print(("PASS " if ok else "FAIL ") + id_ + (": " + msg if msg else "")); failed |= not ok

if not lines:
    result(False, "L1", "no log lines found (did the service log to stdout?)"); sys.exit(1)

# L1 every line is a JSON object with the required fields
bad, objs = [], []
for l in lines:
    try:
        o = json.loads(l)
        if not isinstance(o, dict): raise ValueError
        objs.append(o)
        miss = [k for k in ("timestamp", "level", "message", "service") if k not in o]
        if miss: bad.append(f"missing {miss}: {l[:120]}")
        elif o["level"] not in ("trace", "debug", "info", "warn", "error"): bad.append(f"level {o['level']!r}: {l[:120]}")
    except ValueError:
        bad.append(f"not JSON: {l[:120]}")
result(not bad, "L1", f"{len(bad)} of {len(lines)} lines bad, first: {bad[0]}" if bad else f"{len(lines)} lines")

# L2 the request line carries the trace id of the incoming traceparent
hit = [o for o in objs if o.get("trace_id") == a.trace_id]
result(bool(hit), "L2", "" if hit else f"no line with trace_id {a.trace_id}; a line needs trace_id (and span_id) while a request is handled")

# L3 no secrets
leaks = [s for s in a.secret if s and s in text]
result(not leaks, "L3", "" if not leaks else "found in the log: " + ", ".join(repr(s[:12] + "...") for s in leaks))
sys.exit(1 if failed else 0)
