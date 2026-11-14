#!/usr/bin/env python3
"""infra/host/<svc>.env (the environment of a service run from the IDE, see make host) must not drift from the
environment of the service in infra/docker-compose.yml: same variable names, plus the three port variables."""
import os, re, sys, yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONTAINER_ONLY = {"JAVA_TOOL_OPTIONS"}                       # JVM heap flag sized for the 640 MB container limit
HOST_ONLY = {"HTTP_PORT", "GRPC_PORT", "MGMT_PORT"}          # ports of the process on the host (docs/SERVICE-SPEC.md section 1)
compose = yaml.safe_load(open(os.path.join(ROOT, "infra", "docker-compose.yml"), encoding="utf-8"))
errors = 0

def err(msg):
    global errors; errors += 1; print("ERROR", msg)

for svc in ("account", "media", "catalog", "notification"):
    path = os.path.join(ROOT, "infra", "host", f"{svc}.env")
    if not os.path.isfile(path): err(f"{path} is missing"); continue
    env = {}
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"): continue
        m = re.match(r"([A-Z][A-Z0-9_]*)=(.*)$", line)
        if not m: err(f"{path}:{n}: not NAME=value: {line}"); continue
        if m.group(1) in env: err(f"{path}:{n}: {m.group(1)} defined twice")
        env[m.group(1)] = m.group(2)
    want = set(compose["services"][svc]["environment"]) - CONTAINER_ONLY
    have = set(env)
    for k in sorted(want - have): err(f"{svc}: {k} is in docker-compose.yml but not in infra/host/{svc}.env")
    for k in sorted(have - want - HOST_ONLY): err(f"{svc}: {k} is in infra/host/{svc}.env but not in docker-compose.yml")
    # the host ports must be the ports published for the container
    for var, key in (("HTTP_PORT", "HTTP"), ("MGMT_PORT", "MGMT"), ("GRPC_PORT", "GRPC")):
        pub = [p for p in compose["services"][svc].get("ports", []) if f"PORT_{svc.upper()}_{key}:-" in p]
        if var in env:
            if not pub or f"PORT_{svc.upper()}_{key}:-{env[var]}}}" not in pub[0]: err(f"{svc}: {var}={env[var]} differs from the published port {pub}")
        elif pub: err(f"{svc}: container publishes a {key} port but {var} is missing")
    if env.get("OIDC_CLIENT_ID") != compose["services"][svc]["environment"]["OIDC_CLIENT_ID"]: err(f"{svc}: OIDC_CLIENT_ID differs")
    # host files must not point at in-network names
    for k, v in env.items():
        if re.search(r"(?<![\w.-])(postgres-\w+|redis-notification|redis|kafka|mongo|elasticsearch|keycloak|schema-registry|alloy|mailpit|s3)(?=[:/\s]|$)", v) and "localhost" not in v:
            err(f"{svc}: {k}={v} uses a compose-network name")
print(f"host env files: {errors} errors")
sys.exit(1 if errors else 0)
