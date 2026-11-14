"""Validates contracts/openapi and cross-checks it against the README, i18n, GraphQL, Avro, proto and Envoy."""
import copy
import glob
import json
import os
import re
import sys

import yaml
from graphql import GraphQLEnumType, GraphQLObjectType, build_schema
from openapi_schema_validator import OAS30Validator
from openapi_spec_validator import validate as validate_spec
from openapi_spec_validator.validation import OpenAPIV30SpecValidator

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OA = f"{ROOT}/contracts/openapi"
README = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
errs, warns = [], []


def err(m):
    errs.append(m)
    print("  ERROR:", m)


def warn(m):
    warns.append(m)
    print("  WARN:", m)


DOCS = {}
for f in ("common", "account", "media", "catalog", "notification"):
    DOCS[f] = yaml.safe_load(open(f"{OA}/{f}.yaml", encoding="utf-8"))
SERVICES = ["account", "media", "catalog", "notification"]
METHODS = ["get", "put", "post", "delete", "patch", "options", "head"]

# ------------------------------------------------------------------ strict spec validation
print("== OpenAPI spec validation ==")
for f, d in DOCS.items():
    try:
        validate_spec(d, base_uri=f"file://{OA}/{f}.yaml", cls=OpenAPIV30SpecValidator)
        print(f"{f}.yaml: valid OpenAPI 3.0.3")
    except Exception as e:  # noqa
        err(f"{f}.yaml: {type(e).__name__}: {str(e)[:400]}")


# ------------------------------------------------------------------ $ref resolution
def resolve_ref(ref, cur):
    file_part, _, ptr = ref.partition("#")
    doc_name = cur if not file_part else os.path.basename(file_part)[:-5]
    node = DOCS[doc_name]
    for p in [x for x in ptr.split("/") if x]:
        node = node[p.replace("~1", "/").replace("~0", "~")]
    return node, doc_name


def deref(node, cur, depth=0):
    if depth > 30:
        raise RuntimeError("ref depth")
    if isinstance(node, dict):
        if "$ref" in node:
            target, doc = resolve_ref(node["$ref"], cur)
            return deref(target, doc, depth + 1)
        return {k: deref(v, cur, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [deref(v, cur, depth + 1) for v in node]
    return node


def obj(node, cur):
    """Resolve only the top-level ref chain."""
    while isinstance(node, dict) and "$ref" in node:
        node, cur = resolve_ref(node["$ref"], cur)
    return node, cur


# ------------------------------------------------------------------ gather operations
ops = []  # (service, path, method, op, pathitem)
for s in SERVICES:
    for path, item in DOCS[s]["paths"].items():
        for m in METHODS:
            if m in item:
                ops.append((s, path, m, item[m], item))


def op_params(s, op, item):
    out = []
    for p in item.get("parameters", []) + op.get("parameters", []):
        pp, _ = obj(p, s)
        out.append(deref(pp, s))
    return out


# ------------------------------------------------------------------ README parity
print("== README 5.1 parity ==")
sec = re.search(r"### 5\.1 REST.*?(?=### 5\.2)", README, re.S).group(0)
expected = {}
cur_svc = None
for line in sec.splitlines():
    m = re.match(r"\*\*(\w+)-service\*\*", line)
    if m:
        cur_svc = m.group(1)
        continue
    if not line.startswith("|") or line.startswith("|---") or "Method" in line:
        continue
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    methods_s, paths_s = cells[0], cells[1]
    paths = re.findall(r"`([^`]+)`", paths_s)
    if methods_s.upper() == "CRUD":
        for p in paths:
            expected.setdefault(cur_svc, set()).update(
                {("get", p), ("post", p), ("get", p + "/{id}"), ("put", p + "/{id}"), ("delete", p + "/{id}")})
        continue
    for mm in [x.strip().lower() for x in methods_s.split(",")]:
        for p in paths:
            expected.setdefault(cur_svc, set()).add((mm, p.split("?")[0]))
for s in SERVICES:
    have = {(m, p) for (sv, p, m, _, _) in ops if sv == s}
    exp = expected.get(s, set())
    for x in sorted(exp - have):
        err(f"{s}: README lists {x[0].upper()} {x[1]} but the spec has no such operation")
    for x in sorted(have - exp):
        err(f"{s}: spec has {x[0].upper()} {x[1]} which README 5.1 does not list")
    print(f"{s}: {len(have)} operations, README expects {len(exp)}")

# ------------------------------------------------------------------ per-operation rules
print("== Operation rules ==")
ACCESS = {"public", "authenticated", "owner", "owner-or-moderator", "owner-or-admin", "owner-or-internal",
          "moderator", "admin"}
seen_ids = {}
I18N = {l: json.load(open(f"{ROOT}/contracts/i18n/messages.{l}.json", encoding="utf-8")) for l in ("en", "de", "es")}
EN = I18N["en"]
IDEMPOTENT_EXEMPT = {"createStreamTicket"}
all_codes = {}
for (s, path, m, op, item) in ops:
    tag = f"{s} {m.upper()} {path}"
    oid = op.get("operationId")
    if not oid or not re.fullmatch(r"[a-z][A-Za-z0-9]*", oid):
        err(f"{tag}: operationId missing or not camelCase: {oid}")
    elif oid in seen_ids:
        err(f"{tag}: duplicate operationId {oid} (also {seen_ids[oid]})")
    seen_ids[oid] = tag
    if not op.get("tags"):
        err(f"{tag}: no tags")
    if not op.get("summary"):
        err(f"{tag}: no summary")
    acc = op.get("x-access")
    if acc not in ACCESS:
        err(f"{tag}: x-access missing/invalid: {acc}")
    params = op_params(s, op, item)
    names = {(p["in"], p["name"]) for p in params}
    if ("header", "Accept-Language") not in names:
        err(f"{tag}: no Accept-Language parameter")
    sec_eff = op.get("security", DOCS[s].get("security"))
    if (acc == "public") != (sec_eff == []):
        err(f"{tag}: x-access={acc} but security={sec_eff}")
    codes = {str(c) for c in op["responses"]}
    if acc != "public" and "401" not in codes:
        err(f"{tag}: non-public operation has no 401")
    if re.search(r"\{\w+\}", path) and "404" not in codes:
        err(f"{tag}: path parameter but no 404")
    if acc in ("owner", "owner-or-moderator", "owner-or-admin", "moderator", "admin", "owner-or-internal") \
            and "403" not in codes and "404" not in codes:
        err(f"{tag}: role/ownership restricted but neither 403 nor 404 is documented")
    if "500" not in codes:
        err(f"{tag}: no 500")
    if "x-error-codes" not in op:
        err(f"{tag}: x-error-codes missing (use [] when none)")
    for c in op.get("x-error-codes", []):
        all_codes.setdefault(c, []).append(tag)
    for c, r in op["responses"].items():
        r2, rc = obj(r, s)
        if int(c) >= 400:
            ct = set(r2.get("content", {}))
            if ct != {"application/problem+json"}:
                err(f"{tag}: {c} response content types {ct}, expected only application/problem+json")
    succ = [c for c in codes if c.startswith("2")]
    if m == "post" and any(c in ("201", "202") for c in succ) and oid not in IDEMPOTENT_EXEMPT:
        if ("header", "Idempotency-Key") not in names:
            err(f"{tag}: creating POST without Idempotency-Key")
    if m == "post" and ("header", "Idempotency-Key") in names and "409" not in codes:
        err(f"{tag}: Idempotency-Key declared but no 409")
    if m in ("put", "patch"):
        if ("header", "If-Match") not in names:
            err(f"{tag}: no If-Match")
        if "409" not in codes:
            err(f"{tag}: If-Match but no 409")
        r200, rc = obj(op["responses"].get("200", {}), s)
        if "ETag" not in r200.get("headers", {}):
            err(f"{tag}: 200 does not expose ETag")
    if m == "post" and "201" in codes:
        r201, _ = obj(op["responses"]["201"], s)
        if "Location" not in r201.get("headers", {}) and oid not in {"createStreamTicket", "sendTestNotification"}:
            err(f"{tag}: 201 without Location")
    # list endpoints
    for c, r in op["responses"].items():
        r2, rc = obj(r, s)
        sch = r2.get("content", {}).get("application/json", {}).get("schema")
        if not sch:
            continue
        d = deref(sch, s)
        is_page = any("totalPages" in (x.get("properties") or {}) for x in d.get("allOf", [])) or \
            "totalPages" in (d.get("properties") or {})
        if is_page:
            for need in ("page", "size") + (() if oid == "searchWallpapers" else ("sort",)):
                if ("query", need) not in names:
                    err(f"{tag}: offset-paged response but no '{need}' query parameter")
            for p in params:
                if p["name"] == "sort":
                    en = p["schema"].get("enum", [])
                    if not en or not all(re.fullmatch(r"[a-zA-Z]+,(asc|desc)", x) for x in en):
                        err(f"{tag}: sort enum invalid: {en}")
                    if p["schema"].get("default") not in en:
                        err(f"{tag}: sort default not in enum")
        if "nextCursor" in (d.get("properties") or {}):
            for need in ("cursor", "size"):
                if ("query", need) not in names:
                    err(f"{tag}: keyset response but no '{need}' query parameter")
        break
print(f"{len(ops)} operations checked")

# ------------------------------------------------------------------ examples validate against schemas
print("== Examples ==")
n_ex = 0


def check(schema_node, example, cur, where):
    global n_ex
    try:
        d = deref(schema_node, cur)
    except Exception as e:  # noqa
        err(f"{where}: cannot dereference schema: {e}")
        return
    v = OAS30Validator(d)
    es = sorted(v.iter_errors(example), key=lambda e: list(e.path))
    n_ex += 1
    for e in es[:3]:
        err(f"{where}: example invalid at /{'/'.join(map(str, e.path))}: {e.message[:200]}")


def walk(node, cur, path):
    if isinstance(node, dict):
        if "schema" in node and isinstance(node.get("schema"), dict) and ("example" in node or "examples" in node):
            if "example" in node:
                check(node["schema"], node["example"], cur, path)
            for k, ex in (node.get("examples") or {}).items():
                if "value" in ex:
                    check(node["schema"], ex["value"], cur, f"{path}/examples/{k}")
        elif "example" in node and any(k in node for k in ("type", "allOf", "enum", "oneOf", "$ref")) \
                and "properties" not in node.get("example", {}) if isinstance(node.get("example"), dict) else \
                ("example" in node and any(k in node for k in ("type", "allOf", "enum", "oneOf", "$ref"))):
            check({k: v for k, v in node.items() if k != "example"}, node["example"], cur, path)
        for k, v in node.items():
            walk(v, cur, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, cur, f"{path}/{i}")


for f, d in DOCS.items():
    walk(d, f, f)
print(f"{n_ex} examples validated against their schemas")

# ------------------------------------------------------------------ i18n cross-checks
print("== i18n ==")
used_codes = set(all_codes)
for r, rv in DOCS["common"]["components"]["responses"].items():
    ex = rv["content"]["application/problem+json"].get("example", {})
    if "code" in ex:
        used_codes.add(ex["code"])
for c in sorted(used_codes):
    if f"error.{c}" not in EN:
        err(f"error code {c} has no i18n key error.{c} (used by {all_codes.get(c, ['common examples'])[:2]})")
    if not re.fullmatch(r"[a-z]+(\.[a-z0-9-]+)+", c):
        err(f"error code {c} does not match the Problem.code pattern")
fe = set(DOCS["common"]["components"]["schemas"]["FieldError"]["properties"]["code"]["enum"])
vk = {k.split(".", 1)[1] for k in EN if k.startswith("validation.")}
if fe != vk:
    err(f"FieldError.code enum {sorted(fe)} != i18n validation.* {sorted(vk)}")
loc = set(DOCS["common"]["components"]["schemas"]["Locale"]["enum"])
if loc != set(I18N):
    err(f"Locale enum {loc} != i18n languages {set(I18N)}")
# problem slugs: Problem.type examples
slugs = {k.split(".")[1] for k in EN if k.startswith("problem.")}
for r, rv in DOCS["common"]["components"]["responses"].items():
    ex = rv["content"]["application/problem+json"].get("example", {})
    slug = ex.get("type", "").rsplit("/", 1)[-1]
    if slug not in slugs:
        err(f"common response {r}: problem slug '{slug}' not in i18n problem.<slug>.*")
    if ex.get("title") != EN.get(f"problem.{slug}.title"):
        warn(f"common response {r}: example title '{ex.get('title')}' != i18n '{EN.get(f'problem.{slug}.title')}'")

# field labels
need = {}
for (s, path, m, op, item) in ops:
    for p in op_params(s, op, item):
        if p["in"] == "query":
            need.setdefault(p["name"], []).append(f"{s} {path}")
    rb = op.get("requestBody")
    if rb:
        rb2, _ = obj(rb, s)
        for ct, mt in rb2.get("content", {}).items():
            d = deref(mt.get("schema", {}), s)
            for pn in (d.get("properties") or {}):
                need.setdefault(pn, []).append(f"{s} {path} body")
for n in sorted(need):
    if f"field.{n}" not in EN:
        err(f"i18n has no field.{n} label (used by {need[n][0]}{' +' + str(len(need[n]) - 1) if len(need[n]) > 1 else ''})")

# notification types vs i18n events
types = DOCS["notification"]["components"]["schemas"]["NotificationType"]["enum"]
events = {k.split(".")[1] for k in EN if k.startswith("notification.") and k.endswith(".inbox-title")}
for t in types:
    ev = t.lower().replace("_", "-")
    if t != "TEST" and ev not in events:
        err(f"NotificationType {t} has no i18n notification.{ev}.*")
for ev in events:
    if ev.upper().replace("-", "_") not in types:
        err(f"i18n notification.{ev}.* has no NotificationType")

# ------------------------------------------------------------------ GraphQL / Avro / proto parity
print("== GraphQL / Avro / proto ==")
gql = build_schema(open(f"{ROOT}/contracts/graphql/catalog.graphqls", encoding="utf-8").read())
CS = DOCS["catalog"]["components"]["schemas"]


def gql_enum(n):
    return list(gql.type_map[n].values.keys())


for oa, g in (("WallpaperStatus", "WallpaperStatus"), ("WallpaperCategory", "WallpaperCategory"),
              ("VariantKind", "VariantKind"), ("FacetKey", "FacetKey")):
    if CS[oa]["enum"] != gql_enum(g):
        err(f"enum {oa}: OpenAPI {CS[oa]['enum']} != GraphQL {gql_enum(g)}")
avro = json.load(open(f"{ROOT}/contracts/avro/catalog.wallpaper.moderated.v1.avsc"))
dec = [f for f in avro["fields"] if f["name"] == "decision"][0]["type"]
syms = [x for x in dec.get("symbols", [])] if isinstance(dec, dict) else None
if syms is None:
    syms = [t for t in (dec if isinstance(dec, list) else []) if isinstance(t, dict)][0]["symbols"]
want = [x for x in syms if x != "UNKNOWN"]
for nm, en in (("ModerationDecision", CS["ModerationDecision"]["enum"]),
               ("Notification.data.decision",
                DOCS["notification"]["components"]["schemas"]["Notification"]["properties"]["data"]["properties"]["decision"]["enum"])):
    if en != want:
        err(f"{nm} {en} != Avro decisions without UNKNOWN {want}")


def gql_fields(n):
    t = gql.type_map[n]
    return {k: v for k, v in t.fields.items()}


def gtype_required(f):
    return str(f.type).endswith("!")


for gname, oname in (("Wallpaper", "Wallpaper"), ("Author", "Author"), ("Variant", "Variant"),
                     ("Dimensions", None)):
    gf = gql_fields(gname)
    if gname == "Dimensions":
        osch = CS["Wallpaper"]["properties"]["dimensions"]
    else:
        osch = CS[oname]
    props = osch.get("properties", {})
    for fname, f in gf.items():
        if fname not in props:
            err(f"GraphQL {gname}.{fname} missing in OpenAPI {oname or 'Wallpaper.dimensions'}")
            continue
        ps, _ = obj(props[fname], "catalog")
        nullable_oa = ps.get("nullable", False) if "$ref" not in props[fname] else \
            obj(props[fname], "catalog")[0].get("nullable", False)
        if gtype_required(f) == nullable_oa:
            err(f"{gname}.{fname}: GraphQL nullability ({'!' if gtype_required(f) else 'nullable'}) != OpenAPI nullable={nullable_oa}")
        if gtype_required(f) and fname not in osch.get("required", []):
            err(f"{gname}.{fname} is non-null in GraphQL but not 'required' in OpenAPI")
proto = open(f"{ROOT}/contracts/proto/account/v1/account.proto", encoding="utf-8").read()
um = re.search(r"message User \{(.*?)\n\}", proto, re.S).group(1)
pf = re.findall(r"^\s*(?:optional\s+|repeated\s+)?[\w.]+\s+(\w+)\s*=\s*\d+", um, re.M)
camel = lambda s: re.sub(r"_(\w)", lambda m: m.group(1).upper(), s)  # noqa
AU = DOCS["account"]["components"]["schemas"]
pub = set(AU["PublicUser"]["properties"])
full_ = set(AU["User"]["properties"])
print("proto User fields:", [camel(x) for x in pf])
for f in pf:
    c = camel(f)
    if c not in full_ and c not in pub:
        warn(f"proto User.{f} has no counterpart in OpenAPI User/PublicUser (may be intentional)")

# ------------------------------------------------------------------ Envoy routing
print("== Envoy ==")
env = yaml.safe_load(open(f"{ROOT}/services/gateway/envoy/envoy.yaml", encoding="utf-8"))
vh = None
for l in env["static_resources"]["listeners"]:
    for fc in l["filter_chains"]:
        for fl in fc["filters"]:
            rc = fl["typed_config"].get("route_config")
            if rc and rc["name"] == "public":
                vh = rc["virtual_hosts"][0]
routes = vh["routes"]


def match_route(path, method="GET", headers=None):
    headers = headers or {}
    for r in routes:
        m = r["match"]
        ok = True
        if "prefix" in m:
            ok = path.startswith(m["prefix"])
        elif "path" in m:
            ok = path == m["path"]
        elif "path_separated_prefix" in m:
            p = m["path_separated_prefix"]
            ok = path == p or path.startswith(p + "/")
        elif "safe_regex" in m:
            ok = re.fullmatch(m["safe_regex"]["regex"], path) is not None
        if ok:
            for h in m.get("headers", []):
                nm = h["name"]
                val = method if nm == ":method" else headers.get(nm)
                sm = h.get("string_match", {})
                if "safe_regex" in sm:
                    ok = ok and val is not None and re.fullmatch(sm["safe_regex"]["regex"], val) is not None
                elif "exact" in sm:
                    ok = ok and val is not None and val.lower() == sm["exact"].lower()
        if ok:
            return r
    return None


def jwt_mode(r):
    c = (r.get("typed_per_filter_config") or {}).get("envoy.filters.http.jwt_authn")
    if not c:
        return "required"
    if c.get("disabled"):
        return "disabled"
    return c.get("requirement_name", "required")


for (s, path, m, op, item) in ops:
    full = "/api/v1" + re.sub(r"\{\w+\}", "x", path)
    r = match_route(full, m.upper())
    tag = f"{s} {m.upper()} {path}"
    if r is None:
        err(f"{tag}: gateway has no route for {full}")
        continue
    cl = r.get("route", {}).get("cluster")
    if cl != s:
        err(f"{tag}: gateway routes {full} to cluster '{cl}', expected '{s}'")
    mode = jwt_mode(r)
    acc = op["x-access"]
    stream = op["operationId"] in ("streamNotifications", "connectNotificationSocket")
    exp = "disabled" if acc == "public" else ("valid_if_present" if stream else "required")
    if mode != exp:
        err(f"{tag}: gateway JWT mode '{mode}' but spec implies '{exp}'")
    if stream and r["route"].get("timeout") != "0s":
        err(f"{tag}: streaming route must have timeout 0s")
    if m == "post" and path == "/media":
        pass

# Envoy-facing hints
print("== Done ==")
print(f"errors: {len(errs)}, warnings: {len(warns)}")
sys.exit(1 if errs else 0)
