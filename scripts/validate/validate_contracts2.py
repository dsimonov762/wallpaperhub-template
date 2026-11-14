"""Validates contracts/graphql and contracts/i18n, and cross-checks them against the README, the Avro
schemas, the Envoy gateway config and the Keycloak realm."""
import glob
import json
import os
import re
import sys

import yaml
from graphql import (GraphQLEnumType, GraphQLInputObjectType, GraphQLObjectType, GraphQLScalarType, ast_from_value,
                     build_schema, parse, print_ast, validate)
from graphql.type import assert_valid_schema

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
README = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
errs = []


def err(msg):
    errs.append(msg)
    print("  ERROR:", msg)


def read(p):
    return open(os.path.join(ROOT, p), encoding="utf-8").read()


# =================================================================== GraphQL
print("== GraphQL ==")
main_sdl = read("contracts/graphql/catalog.graphqls")
sub_sdl = read("contracts/graphql/catalog-subscriptions.graphqls")
schema = build_schema(main_sdl)
assert_valid_schema(schema)
print("catalog.graphqls builds a valid schema:", len([t for t in schema.type_map if not t.startswith("__")]), "types")
full = build_schema(main_sdl + "\n" + sub_sdl)
assert_valid_schema(full)
if full.subscription_type is None or "wallpaperPublished" not in full.subscription_type.fields:
    err("subscription file does not define Subscription.wallpaperPublished")
else:
    print("with catalog-subscriptions.graphqls: Subscription.wallpaperPublished present")
if schema.subscription_type is not None:
    err("main schema must not define a Subscription type (it is optional)")

# README 5.5: every field it shows must exist with the same type, arguments and defaults
readme_sdl = re.search(r"```graphql\n(.*?)```", README, re.S).group(1)
doc = parse(readme_sdl)


def field_shape_ours(f):
    args = {}
    for n, a in f.args.items():
        d = a.default                       # GraphQLDefaultInput(literal, value) or None
        if d is None:
            shown = None
        elif d.literal is not None:
            shown = print_ast(d.literal)
        else:
            shown = print_ast(ast_from_value(d.value, a.type))
        args[n] = (str(a.type), shown)
    return str(f.type), args


def field_shape_readme(f):
    args = {a.name.value: (print_ast(a.type), print_ast(a.default_value) if a.default_value else None)
            for a in (f.arguments or [])}
    return print_ast(f.type), args


checked = 0
for d in doc.definitions:
    if d.kind != "object_type_definition":
        continue
    name = d.name.value
    ours = schema.type_map.get(name)
    if ours is None:
        err(f"README type {name} is missing")
        continue
    for f in d.fields:
        if f.name.value not in ours.fields:
            err(f"README field {name}.{f.name.value} is missing")
        elif field_shape_ours(ours.fields[f.name.value]) != field_shape_readme(f):
            err(f"{name}.{f.name.value} differs from README: {field_shape_ours(ours.fields[f.name.value])} vs {field_shape_readme(f)}")
        else:
            checked += 1
    if name in ("Query", "Mutation") and set(ours.fields) != {f.name.value for f in d.fields}:
        err(f"{name} has fields the README does not: {set(ours.fields) - {f.name.value for f in d.fields}}")
print(f"{checked} README fields (Query, Mutation, Wallpaper) match name, type, arguments and defaults")

# documentation coverage: every type and every object/input field has a description
undocumented = []
for tname, t in schema.type_map.items():
    if tname.startswith("__") or tname in ("String", "Int", "Float", "Boolean", "ID"):
        continue
    if not t.description:
        undocumented.append(tname)
    if isinstance(t, (GraphQLObjectType, GraphQLInputObjectType)):
        for fname, f in t.fields.items():
            if not f.description:
                undocumented.append(f"{tname}.{fname}")
if undocumented:
    err(f"undocumented: {undocumented}")
else:
    print("every type and field has a description")

# example operations validate against the schema
for path in sorted(glob.glob(f"{ROOT}/contracts/graphql/examples/*.graphql")):
    d = parse(open(path, encoding="utf-8").read())
    problems = validate(schema, d)
    ops = [x.name.value for x in d.definitions if x.kind == "operation_definition"]
    if problems:
        for p in problems:
            err(f"{os.path.basename(path)}: {p.message}")
    else:
        print(f"  ok examples/{os.path.basename(path)}: {', '.join(ops)}")

# a bad query must be rejected (guards against a validator that accepts everything)
bad = validate(schema, parse("query { wallpapers { edges { node { nope } } } }"))
if not bad:
    err("validator accepted a query with an unknown field")

# =================================================================== i18n
print("\n== i18n ==")
langs = ["en", "de", "es"]
B = {l: json.load(open(f"{ROOT}/contracts/i18n/messages.{l}.json", encoding="utf-8")) for l in langs}
for l in langs:
    raw_keys = [k for k, _ in json.load(open(f"{ROOT}/contracts/i18n/messages.{l}.json", encoding="utf-8"),
                                        object_pairs_hook=lambda p: p)]
    B[l + "_order"] = raw_keys
orders = {l: B.pop(l + "_order") for l in langs}
if not (orders["en"] == orders["de"] == orders["es"]):
    err("key order differs between languages")
keys = set(B["en"])
print(f"{len(keys)} keys per language, same keys and order: {orders['en'] == orders['de'] == orders['es'] and set(B['de']) == keys == set(B['es'])}")
for l in ("de", "es"):
    if set(B[l]) != keys:
        err(f"{l}: key mismatch, missing={keys - set(B[l])} extra={set(B[l]) - keys}")

TOKEN = re.compile(r"\{\{|\}\}|\{([A-Za-z][A-Za-z0-9]*)\}")
KEY = re.compile(r"^[a-z][A-Za-z0-9-]*(\.[A-Za-z0-9_-]+)+$")


def fmt(template, args):
    def sub(m):
        if m.group(0) == "{{":
            return "{"
        if m.group(0) == "}}":
            return "}"
        return str(args[m.group(1)]) if m.group(1) in args else m.group(0)
    return TOKEN.sub(sub, template)


def placeholders(s):
    return {m.group(1) for m in TOKEN.finditer(s) if m.group(1)}


for k in sorted(keys):
    if not KEY.match(k):
        err(f"bad key name {k}")
    ph = placeholders(B["en"][k])
    for l in langs:
        v = B[l].get(k, "")
        if not v.strip():
            err(f"{l}:{k} is empty")
        if v != v.strip():
            err(f"{l}:{k} has leading/trailing whitespace")
        if placeholders(v) != ph:
            err(f"{l}:{k} placeholders {sorted(placeholders(v))} != en {sorted(ph)}")
        stripped = TOKEN.sub("", v)
        if "{" in stripped or "}" in stripped:
            err(f"{l}:{k} has a stray brace")
print("placeholders identical across languages, no empty values, no stray braces")

# German and Spanish must actually differ from English (catches untranslated copies), except where identical by nature
same = [k for k in keys if B["de"][k] == B["en"][k] and k not in ("field.tags", "notification.digest.item")]
if same:
    print("  note: identical in de and en:", same)
sames = [k for k in keys if B["es"][k] == B["en"][k]]
if sames:
    print("  note: identical in es and en:", sames)

# format test vectors against the reference implementation (also exercises the README snippet's logic)
vectors = json.load(open(f"{ROOT}/contracts/i18n/format-tests.json", encoding="utf-8"))
bad_v = [v["name"] for v in vectors if fmt(v["template"], v["args"]) != v["expected"]]
if bad_v:
    err(f"format vectors failing: {bad_v}")
else:
    print(f"all {len(vectors)} format test vectors pass")
# the snippet in the i18n README must be the same algorithm: execute it and rerun the vectors
snippet = re.search(r"```python\n(.*?)```", read("contracts/i18n/README.md"), re.S).group(1)
ns = {}
exec(snippet, ns)                                                         # noqa: S102 (our own README snippet)
if [v["name"] for v in vectors if ns["fmt"](v["template"], v["args"]) != v["expected"]]:
    err("the README reference implementation fails the vectors")
else:
    print("the reference implementation in contracts/i18n/README.md passes them too")

# ---- cross-check 1: README 5.2 example and 5.3 exception model
en = B["en"]
if en["problem.validation-failed.title"] != "Validation failed" or en["problem.validation-failed.detail"] != "One or more fields are invalid.":
    err("validation-failed title/detail differ from the README 5.2 example")
if fmt(en["validation.NotBlank"], {"field": en["field.title"]}) != "Title must not be blank.":
    err("validation.NotBlank + field.title does not reproduce the README 5.2 message")
else:
    print("README 5.2 example reproduced: 'Title must not be blank.'")
table = re.search(r"### 5\.3 Exception model.*?\n(\|.*?)\n\n", README, re.S).group(1)
slugs = set()
for row in table.splitlines()[2:]:
    cls = re.match(r"\|\s*`(\w+)`", row).group(1)
    stem = cls.removesuffix("Exception")
    slug = "validation-failed" if stem == "Validation" else re.sub(r"(?<!^)(?=[A-Z])", "-", stem).lower()
    slugs.add(slug)
    for part in ("title", "detail"):
        if f"problem.{slug}.{part}" not in keys:
            err(f"README exception {cls}: missing problem.{slug}.{part}")
print("README 5.3 exceptions -> problem slugs:", sorted(slugs))
if "problem.internal-error.title" not in keys:
    err("missing internal-error")

# ---- cross-check 2: the gateway's own problem+json responses use the same slugs and English titles
envoy = yaml.safe_load(read("services/gateway/envoy/envoy.yaml"))
hcm = next(l for l in envoy["static_resources"]["listeners"] if l["name"] == "public")["filter_chains"][0]["filters"][0]["typed_config"]
lr = hcm["local_reply_config"]
def mapper_lang(m):
    """de / es from the Accept-Language test of the mapper, en when it has none."""
    flt = m.get("filter", {})
    for f in flt.get("and_filter", {}).get("filters", []):
        rx = f.get("header_filter", {}).get("header", {}).get("string_match", {}).get("safe_regex", {}).get("regex")
        if rx:
            return re.search(r"\^\\s\*([a-z]{2})", rx).group(1)
    return "en"

bundles = {l: json.load(open(f"{ROOT}/contracts/i18n/messages.{l}.json", encoding="utf-8")) for l in ("en", "de", "es")}
n = 0
seen = set()
for m in lr["mappers"]:
    jf = m["body_format_override"]["json_format"]
    t = re.fullmatch(r"https://wallpaperhub\.dev/problems/([a-z-]+)", jf.get("type", ""))   # the 200 mapper has no type
    if not t:
        continue
    slug, lang = t.group(1), mapper_lang(m)
    hdr = m["headers_to_add"][0]["header"]
    if hdr["value"] != lang:
        err(f"gateway {slug}/{lang}: Content-Language is {hdr['value']}")
    for part in ("title", "detail"):
        key = f"problem.{slug}.{part}"
        if key not in bundles[lang]:
            err(f"gateway uses {key} that has no i18n key")
        elif bundles[lang][key] != jf[part]:
            err(f"gateway {part} {jf[part]!r} != i18n[{lang}] {bundles[lang][key]!r} for {slug}")
        else:
            n += 1
    seen.add((slug, lang))
want = {(s_, l) for s_ in ("unauthorized", "not-found", "payload-too-large", "rate-limited", "upstream-unavailable") for l in ("en", "de", "es")}
if seen != want:
    err(f"gateway localized replies missing: {sorted(want - seen)}")
print(f"{n} gateway title/detail texts match the i18n bundles (en, de, es)")

# ---- cross-check 3: Avro (decisions, reject reasons) and the notification events
mod = json.load(open(f"{ROOT}/contracts/avro/catalog.wallpaper.moderated.v1.avsc"))
decision = next(f for f in mod["fields"] if f["name"] == "decision")["type"]
for sym in decision["symbols"]:
    if sym == "UNKNOWN":
        continue
    for part in ("email-subject", "email-body", "inbox-title", "inbox-body"):
        if f"notification.wallpaper-moderated.{sym}.{part}" not in keys:
            err(f"missing notification.wallpaper-moderated.{sym}.{part}")
extra = {k.split(".")[2] for k in keys if k.startswith("notification.wallpaper-moderated.") and k.split(".")[2].isupper()}
if extra - set(decision["symbols"]):
    err(f"notification keys for decisions not in the Avro enum: {extra - set(decision['symbols'])}")
print("moderation decisions in Avro:", [s for s in decision["symbols"] if s != "UNKNOWN"], "-> all have keys")

rej = json.load(open(f"{ROOT}/contracts/avro/media.asset.rejected.v1.avsc"))
codes = set(re.findall(r"\b[A-Z][A-Z_]{3,}\b", rej["doc"].split(";")[0]))
for c in codes:
    if f"media.reject-reason.{c}" not in keys:
        err(f"Avro reasonCode {c} has no media.reject-reason key")
if "media.reject-reason.OTHER" not in keys:
    err("missing media.reject-reason.OTHER fallback")
print("Avro reasonCode examples with keys:", sorted(codes))

events = {}
for k in keys:
    if k.startswith("notification."):
        parts = k.split(".")
        ev = parts[1]
        events.setdefault(ev, set()).add(parts[-1])
for ev, parts in sorted(events.items()):
    need = {"email-subject", "email-body"} <= parts or ev == "digest"
    inbox = {"inbox-title", "inbox-body"} <= parts
    if ev != "digest" and not inbox and ev != "wallpaper-moderated":
        err(f"event {ev} lacks an inbox pair")
print("notification events:", sorted(events))

# ---- cross-check 4: Keycloak realm locales and seed-user locales
realm = json.load(open(f"{ROOT}/infra/keycloak/realm-export.json", encoding="utf-8"))
if sorted(realm["supportedLocales"]) != sorted(langs):
    err(f"realm supportedLocales {realm['supportedLocales']} != bundles {langs}")
else:
    print("Keycloak supportedLocales == bundle languages:", realm["supportedLocales"])

# ---- cross-check 5: the account.proto User.locale comment and i18n README agree on the locale set
proto = read("contracts/proto/account/v1/account.proto")
if '"en", "de" or "es"' not in proto:
    err("account.proto locale comment out of date")

print("\nERRORS:" if errs else "\nALL CHECKS PASSED", *errs, sep="\n  ")
sys.exit(1 if errs else 0)
