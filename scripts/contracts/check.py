#!/usr/bin/env python3
"""Contract rules that need no Docker: Avro and GraphQL lint, and breaking-change detection for Avro and GraphQL.
(OpenAPI and protobuf are checked by Spectral, oasdiff and buf: see scripts/contracts.sh.)

  check.py lint                      Avro event conventions, GraphQL naming and documentation
  check.py breaking BASE_DIR         compare contracts/ with the contracts folder of another revision (BASE_DIR/avro, BASE_DIR/graphql)
      --avro-mode BACKWARD|FULL      BACKWARD (default) is what Schema Registry enforces: consumers on the new schema read old events.
                                     FULL also requires old consumers to read new events (needed when consumers upgrade later than producers).
Exit code 1 when a rule marked ERROR is violated. Needs: pip install -r scripts/validate/requirements.txt"""
import argparse, glob, json, os, re, sys
import avro.schema
from avro.compatibility import ReaderWriterCompatibilityChecker, SchemaCompatibilityType
from graphql import GraphQLError, build_schema, GraphQLEnumType, GraphQLInputObjectType, GraphQLInterfaceType, GraphQLObjectType, GraphQLScalarType, GraphQLUnionType
from graphql.utilities import find_breaking_changes, find_dangerous_changes

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
errors = warnings = 0


def err(msg):
    global errors; errors += 1; print("ERROR", msg)


def warn(msg):
    global warnings; warnings += 1; print("WARN ", msg)


# ----------------------------------------------------------------------------------------------------- Avro
def avro_files(d):
    return sorted(glob.glob(os.path.join(d, "avro", "*.avsc")))


def lint_avro(d):
    names = set()
    for path in avro_files(d):
        fn = os.path.basename(path); tag = f"avro/{fn}"
        m = re.match(r"^([a-z]+)\.([a-z]+)\.([a-z]+(?:-[a-z]+)*)\.v([1-9][0-9]*)\.avsc$", fn)
        if not m: err(f"{tag}: file name must be <service>.<entity>.<event>.v<N>.avsc (it is also the topic name)"); continue
        raw = json.load(open(path, encoding="utf-8"))
        try: avro.schema.parse(json.dumps(raw))
        except Exception as e: err(f"{tag}: not a valid Avro schema: {e}"); continue
        if raw.get("type") != "record": err(f"{tag}: top-level type must be a record"); continue
        if raw.get("namespace") != f"dev.wallpaperhub.{m.group(1)}.v{m.group(4)}": err(f"{tag}: namespace must be dev.wallpaperhub.{m.group(1)}.v{m.group(4)}, is {raw.get('namespace')}")
        if raw["name"] in names: err(f"{tag}: record name {raw['name']} used twice")
        names.add(raw["name"])
        if not raw.get("doc"): err(f"{tag}: record has no doc")
        fields = {f["name"]: f for f in raw["fields"]}
        if fields.get("eventId", {}).get("type") != "string": err(f"{tag}: needs field eventId of type string (the dedup key of consumers)")
        oa = fields.get("occurredAt", {}).get("type")
        if not (isinstance(oa, dict) and oa.get("type") == "long" and oa.get("logicalType") == "timestamp-millis"): err(f"{tag}: needs field occurredAt as long/timestamp-millis")
        for f in raw["fields"]:
            if not re.match(r"^[a-z][a-zA-Z0-9]*$", f["name"]): err(f"{tag}: field {f['name']} is not camelCase")
            t = f["type"]
            if isinstance(t, list) and "null" in t:
                if t[0] != "null": err(f"{tag}: field {f['name']}: null must be the first branch of the union")
                if f.get("default", "missing") is not None: err(f"{tag}: field {f['name']}: optional field needs \"default\": null (otherwise adding or removing it breaks compatibility)")
            if isinstance(t, dict) and t.get("type") == "enum" and "default" not in t:
                warn(f"{tag}: enum {t.get('name')} has no \"default\" symbol, so adding a symbol later breaks old consumers")
            if isinstance(t, (str, dict)) and (t if isinstance(t, str) else t.get("type")) in ("float", "double") and "amount" in f["name"].lower():
                warn(f"{tag}: field {f['name']}: use a decimal logical type for money, not floating point")


def avro_breaking(base, head, mode):
    old = {os.path.basename(p): p for p in avro_files(base)}
    new = {os.path.basename(p): p for p in avro_files(head)}
    for fn in sorted(set(old) - set(new)): err(f"avro/{fn}: removed (topic and subject disappear; consumers of it break)")
    for fn in sorted(set(new) - set(old)): print(f"  new   avro/{fn}")
    for fn in sorted(set(old) & set(new)):
        w, r = avro.schema.parse(open(old[fn], encoding="utf-8").read()), avro.schema.parse(open(new[fn], encoding="utf-8").read())
        checks = [("BACKWARD", r, w)] + ([("FORWARD", w, r)] if mode == "FULL" else [])
        for name, reader, writer in checks:
            res = ReaderWriterCompatibilityChecker().get_compatibility(reader, writer)
            if res.compatibility != SchemaCompatibilityType.compatible:
                kinds = ", ".join(sorted({i.name for i in res.incompatibilities}))
                for loc, msg in zip(sorted(res.locations), sorted(res.messages)) if len(res.locations) == len(res.messages) else [("/", "; ".join(sorted(res.messages)))]:
                    err(f"avro/{fn}: {name} incompatible ({kinds}) at {loc}: {msg}")
        # a changed name or namespace is a new type even if the fields match
        if w.fullname != r.fullname: err(f"avro/{fn}: record renamed {w.fullname} -> {r.fullname}")


# -------------------------------------------------------------------------------------------------- GraphQL
def load_graphql(d):
    parts = [open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(d, "graphql", "*.graphqls")))]
    if not parts: return None
    try: return build_schema("\n".join(parts))
    except GraphQLError as e:
        err(f"graphql: the schema in {d} does not parse: {str(e).splitlines()[0]}"); raise SystemExit(1)


def lint_graphql(d):
    schema = load_graphql(d)
    if schema is None: return
    for name, t in schema.type_map.items():
        if name.startswith("__") or isinstance(t, GraphQLScalarType) and name in ("String", "Int", "Float", "Boolean", "ID"): continue
        if not re.match(r"^[A-Z][a-zA-Z0-9]*$", name): err(f"graphql {name}: type names are PascalCase")
        if not t.description: err(f"graphql {name}: type has no description")
        if isinstance(t, GraphQLEnumType):
            for v, ev in t.values.items():
                if not re.match(r"^[A-Z][A-Z0-9_]*$", v): err(f"graphql {name}.{v}: enum values are UPPER_SNAKE_CASE")
                if ev.deprecation_reason is not None and not ev.deprecation_reason.strip(): err(f"graphql {name}.{v}: @deprecated needs a reason")
        if isinstance(t, (GraphQLObjectType, GraphQLInterfaceType, GraphQLInputObjectType)):
            for f, fd in t.fields.items():
                if not re.match(r"^[a-z][a-zA-Z0-9]*$", f): err(f"graphql {name}.{f}: field names are camelCase")
                if not fd.description and name not in ("Query", "Mutation", "Subscription"):
                    warn(f"graphql {name}.{f}: field has no description")
                if not fd.description and name in ("Query", "Mutation", "Subscription"):
                    err(f"graphql {name}.{f}: root field has no description")
                if getattr(fd, "deprecation_reason", None) is not None and not fd.deprecation_reason.strip(): err(f"graphql {name}.{f}: @deprecated needs a reason")
                for a, ad in (getattr(fd, "args", None) or {}).items():
                    if not re.match(r"^[a-z][a-zA-Z0-9]*$", a): err(f"graphql {name}.{f}({a}): argument names are camelCase")


def graphql_breaking(base, head):
    old, new = load_graphql(base), load_graphql(head)
    if old is None: print("  (no graphql schema in the base revision)"); return
    if new is None: err("graphql: the schema was removed"); return
    for c in find_breaking_changes(old, new): err(f"graphql: {c.type.name}: {c.description}")
    for c in find_dangerous_changes(old, new): warn(f"graphql: {c.type.name}: {c.description}")


# ------------------------------------------------------------------------------------------------------ main
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("lint")
b = sub.add_parser("breaking"); b.add_argument("base"); b.add_argument("--head", default=os.path.join(ROOT, "contracts")); b.add_argument("--avro-mode", default="BACKWARD", choices=["BACKWARD", "FULL"])
a = ap.parse_args()
head = os.path.join(ROOT, "contracts") if a.cmd == "lint" else a.head
if a.cmd == "lint":
    lint_avro(head); lint_graphql(head)
    print(f"avro + graphql lint: {errors} errors, {warnings} warnings")
else:
    avro_breaking(a.base, head, a.avro_mode); graphql_breaking(a.base, head)
    print(f"avro + graphql breaking changes vs {a.base}: {errors} breaking, {warnings} to review")
sys.exit(1 if errors else 0)
