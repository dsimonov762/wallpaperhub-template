#!/usr/bin/env python3
"""Static checks of the Grafana dashboards in infra/grafana/dashboards, and a coverage report against a live Prometheus.

  python3 scripts/validate/validate_dashboards.py                   structure, datasources, PromQL syntax, variables
  python3 scripts/validate/validate_dashboards.py --coverage [URL]  which metrics the dashboards use that Prometheus does
                                                                    not have (default http://localhost:9090): "why is this panel empty?"
  python3 scripts/validate/validate_dashboards.py --metrics         the metric names the dashboards use, per dashboard

Offline on purpose (no Grafana needed): it catches the mistakes that make a panel silently empty or a dashboard fail to load.
Needs PyYAML and promql-parser (scripts/validate/requirements.txt).
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import promql_parser as pq
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
DASH = ROOT / "infra" / "grafana" / "dashboards"
PROV = ROOT / "infra" / "grafana" / "provisioning"
COMPOSE = ROOT / "infra" / "docker-compose.yml"
BUILTIN = {"__rate_interval", "__interval", "__interval_ms", "__range", "__range_s", "__range_ms", "__auto", "__from", "__to",
           "__dashboard", "__name", "__org", "__user", "__all"}
errors = []


def err(where, msg):
    errors.append(f"{where}: {msg}")


def variables_in(text):
    return {m.group(1) or m.group(2) for m in re.finditer(r"\$\{(\w+)[^}]*\}|\$(\w+)", text)} - BUILTIN


def promql_ready(expr):
    """Grafana macros and variables replaced by plain values so the expression can be parsed."""
    expr = re.sub(r"\$__rate_interval|\$__interval|\$__range|\$\{__rate_interval\}", "5m", expr)
    return re.sub(r"\$\{?\w+\}?", "x", expr)


def balanced(text):
    stack, quote = [], None
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch in "({[":
            stack.append(ch)
        elif ch in ")}]":
            if not stack or "({[".index(stack.pop()) != ")}]".index(ch):
                return False
    return not stack and quote is None


def metrics_of(expr):
    names = []

    def visit(node):
        if isinstance(node, pq.VectorSelector) and node.name:
            names.append(node.name)
    pq.walk(pq.parse(promql_ready(expr)), visit)
    return names


def all_panels(d):
    for p in d["panels"]:
        yield p
        yield from p.get("panels", [])


def datasource_uids():
    uids = {}
    for f in sorted((PROV / "datasources").glob("*.y*ml")):
        for ds in yaml.safe_load(f.read_text(encoding="utf-8")).get("datasources", []):
            uids[ds["uid"]] = ds["type"]
    return uids


def check(path, d, ds_uids):
    where = path.name
    for key in ("uid", "title", "panels", "schemaVersion", "tags"):
        if key not in d:
            err(where, f"missing '{key}'")
    if d.get("id") is not None:
        err(where, "'id' must be null (Grafana assigns it; a fixed id breaks provisioning into an existing database)")
    if not re.fullmatch(r"wh-[a-z0-9-]{2,30}", d.get("uid", "")):
        err(where, f"uid '{d.get('uid')}' should look like wh-name")
    if path.stem != d.get("uid", "").removeprefix("wh-"):
        err(where, f"file name should be {d.get('uid', '').removeprefix('wh-')}.json")
    if "wallpaperhub" not in d.get("tags", []):
        err(where, "tag 'wallpaperhub' missing (the dashboard links need it)")
    ids, boxes, used, defined = set(), [], set(), {v["name"]: v for v in d.get("templating", {}).get("list", [])}
    for p in all_panels(d):
        pw = f"{where}: panel {p.get('id')} '{p.get('title', '')}'"
        if p.get("id") in ids or not isinstance(p.get("id"), int):
            err(pw, "id missing or duplicated")
        ids.add(p.get("id"))
        gp = p.get("gridPos") or {}
        if not all(k in gp for k in "hwxy") or gp.get("w", 0) < 1 or gp["x"] + gp["w"] > 24 or gp["x"] < 0:
            err(pw, f"bad gridPos {gp}")
        if p["type"] != "row":
            for (x, y, w, h, other) in boxes:
                if gp["x"] < x + w and x < gp["x"] + gp["w"] and gp["y"] < y + h and y < gp["y"] + gp["h"]:
                    err(pw, f"overlaps panel '{other}'")
            boxes.append((gp["x"], gp["y"], gp["w"], gp["h"], p.get("title")))
        if p["type"] in ("row", "text"):
            continue
        if not p.get("title"):
            err(pw, "no title")
        if not p.get("targets"):
            err(pw, "no targets")
        ds = p.get("datasource") or {}
        if ds.get("uid") not in ds_uids or ds_uids.get(ds.get("uid")) != ds.get("type"):
            err(pw, f"datasource {ds} is not one of the provisioned {ds_uids}")
        refs = set()
        for t in p.get("targets", []):
            if t.get("refId") in refs:
                err(pw, f"duplicate refId {t.get('refId')}")
            refs.add(t.get("refId"))
            if t.get("datasource") != ds:
                err(pw, f"target {t.get('refId')} uses another datasource than the panel")
            text = t.get("expr") or t.get("query") or ""
            if not text.strip():
                err(pw, f"target {t.get('refId')} is empty")
                continue
            used |= variables_in(text)
            kind = ds.get("type")
            if kind == "prometheus":
                try:
                    pq.parse(promql_ready(text))
                except Exception as e:  # noqa: BLE001 - the parser's own message is the useful part
                    err(pw, f"target {t.get('refId')}: PromQL does not parse: {str(e).splitlines()[0]}")
            elif not balanced(text):
                err(pw, f"target {t.get('refId')}: unbalanced brackets or quotes in {kind} query")
            elif kind == "loki" and "{" not in text:
                err(pw, f"target {t.get('refId')}: LogQL without a stream selector")
            elif kind == "tempo" and t.get("queryType") == "traceql" and not text.strip().startswith("{"):
                err(pw, f"target {t.get('refId')}: TraceQL should start with {{")
    for name, v in defined.items():
        q = v.get("query")
        used |= variables_in(json.dumps(q)) if q else set()
        if v["type"] == "query":
            ds = v.get("datasource") or {}
            if ds.get("uid") not in ds_uids:
                err(where, f"variable {name}: unknown datasource {ds}")
            if isinstance(q, str) and "label_values" in q:
                try:
                    inner = re.search(r"label_values\((.*),\s*\w+\)", q)
                    if inner:
                        pq.parse(promql_ready(inner.group(1)))
                except Exception as e:  # noqa: BLE001
                    err(where, f"variable {name}: {str(e).splitlines()[0]}")
    for name in used - set(defined):
        err(where, f"variable ${name} is used but not defined")
    for name in set(defined) - used:
        err(where, f"variable ${name} is defined but never used")


def compose_mounts_dashboards():
    text = COMPOSE.read_text(encoding="utf-8")
    prov = (PROV / "dashboards").glob("*.y*ml")
    paths = [p["options"]["path"] for f in prov for p in yaml.safe_load(f.read_text(encoding="utf-8")).get("providers", [])]
    if not paths:
        err("provisioning/dashboards", "no dashboard provider file")
        return
    if not re.search(r"grafana/dashboards:" + re.escape(paths[0]), text):
        err("docker-compose.yml", f"grafana must mount ./grafana/dashboards at {paths[0]} (the provider path)")


def coverage(base, found):
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/api/v1/label/__name__/values", timeout=10) as r:
            have = set(json.load(r)["data"])
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"cannot read metric names from {base}: {e}\n(make up-obs, or pass the URL of your Prometheus)", file=sys.stderr)
        return 2
    missing = 0
    for dash, names in found.items():
        gone = sorted(n for n in names if n not in have)
        print(f"{dash}: {len(names) - len(gone)}/{len(names)} metrics present")
        for n in gone:
            print(f"    not in Prometheus: {n}")
        missing += len(gone)
    print("\nA panel is empty until some service (or Envoy) emits its metric. docs/OBSERVABILITY.md lists who owns which.")
    return 0 if not missing else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coverage", nargs="?", const="http://localhost:9090", metavar="URL")
    ap.add_argument("--metrics", action="store_true")
    args = ap.parse_args()
    files = sorted(DASH.glob("*.json"))
    if not files:
        print(f"no dashboards in {DASH}", file=sys.stderr)
        return 1
    ds_uids, uids, titles, found = datasource_uids(), {}, {}, {}
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            err(f.name, f"not valid JSON: {e}")
            continue
        if d.get("uid") in uids:
            err(f.name, f"uid {d['uid']} also in {uids[d['uid']]}")
        if d.get("title") in titles:
            err(f.name, f"title also in {titles[d['title']]}")
        uids[d.get("uid")], titles[d.get("title")] = f.name, f.name
        check(f, d, ds_uids)
        names = set()
        for p in all_panels(d):
            for t in p.get("targets", []):
                if (p.get("datasource") or {}).get("type") == "prometheus" and t.get("expr"):
                    try:
                        names |= set(metrics_of(t["expr"]))
                    except Exception:  # noqa: BLE001 - already reported by check()
                        pass
        found[f.name] = names
    compose_mounts_dashboards()
    if errors:
        print("dashboards: %d problem(s)" % len(errors), file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        return 1
    if args.metrics:
        for dash, names in found.items():
            print(f"{dash}: {' '.join(sorted(names))}")
        return 0
    if args.coverage:
        return coverage(args.coverage, found)
    panels = sum(len([p for p in all_panels(json.loads(f.read_text(encoding='utf-8'))) if p["type"] != "row"]) for f in files)
    print(f"dashboards ok: {len(files)} files, {panels} panels, {sum(len(v) for v in found.values())} metric references")
    return 0


if __name__ == "__main__":
    sys.exit(main())
