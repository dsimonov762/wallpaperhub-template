#!/usr/bin/env python3
"""Prints the environment of the four services side by side, from `docker compose config --format json`.
   make env-matrix            secrets are masked. Standard library only."""
import json, re, subprocess, sys

cmd = ["docker", "compose", "--project-directory", "infra", "-f", "infra/docker-compose.yml", "--profile", "infra", "--profile", "apps", "config", "--format", "json"]
try:
    cfg = json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)
except Exception as e:
    sys.exit(f"cannot read the compose configuration: {e}")
svcs = ["account", "media", "catalog", "notification"]
env = {s: cfg["services"][s].get("environment", {}) for s in svcs}
keys = sorted(set().union(*[e.keys() for e in env.values()]))
mask = re.compile(r"SECRET|PASSWORD|_KEY$")
def cell(s, k):
    v = env[s].get(k)
    if v is None: return "-"
    if mask.search(k): return "***"
    return str(v) if len(str(v)) <= 38 else str(v)[:35] + "..."
w = [max(len(k) for k in keys)] + [max(len(s), *(len(cell(s, k)) for k in keys)) for s in svcs]
row = lambda cols: "  ".join(c.ljust(w[i]) for i, c in enumerate(cols))
print(row(["variable"] + svcs)); print(row(["-" * x for x in w]))
shared = [k for k in keys if all(env[s].get(k) == env[svcs[0]].get(k) for s in svcs)]
for k in keys: print(row([k] + [cell(s, k) for s in svcs]))
print(f"\n{len(shared)} of {len(keys)} variables have the same value in all four services")
