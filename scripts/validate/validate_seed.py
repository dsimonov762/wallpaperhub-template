#!/usr/bin/env python3
"""The generated seed data (seed/out) against the canonical schemas of contracts/db-schema, without any database:

  * catalog.js documents against the $jsonSchema validators and the $expr rule of contracts/db-schema/mongo/catalog.json
    (a small BSON-aware checker: dates, int/long vs double, patterns, enums, additionalProperties ...)
  * catalog.es.ndjson against the strict mapping of wallpapers-v1.json (no unknown field, right scalar types)
  * redis files against contracts/db-schema/redis/keys.yaml (every key matches a documented pattern, notif hash fields)
  * cross-store consistency: same ids everywhere, favoriteCount == number of favorites, Elasticsearch holds exactly the
    PUBLISHED wallpapers, every asset referenced by a wallpaper exists with a matching status, image files exist and their
    sha256 matches the media.sql row
The Postgres files are exercised by `make seed-test-sql` / CI against a real server because the CHECK constraints live there.
"""
import hashlib, json, os, re, sys
import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SEED = os.path.join(ROOT, "seed")
errors = 0


def err(msg):
    global errors
    errors += 1
    print("ERROR", msg)


# ---------------------------------------------------------------------------------------------------------------------
# JavaScript literal -> JSON with type markers
def js_to_json(text, name):
    m = re.search(r"const %s = (.*?);\n(?:const|\nfunction|function)" % name, text, re.S)
    if not m:
        err(f"catalog.js: no `const {name}`")
        return []
    src = m.group(1)
    src = re.sub(r'new Date\(("[^"]*")\)', r'{"$date": \1}', src)
    src = re.sub(r"NumberInt\((-?\d+)\)", r'{"$int": \1}', src)
    src = re.sub(r'ObjectId\(("[0-9a-f]{24}")\)', r'{"$oid": \1}', src)
    src = re.sub(r'U\(("[^"]*")\)', r'{"$url": \1}', src)
    return json.loads(src)


def bson_type(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, str):
        return "string"
    if isinstance(v, float) or isinstance(v, int):
        return "double"  # a bare number in the file would be stored as a double
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        if "$date" in v:
            return "date"
        if "$int" in v:
            return "int"
        if "$oid" in v:
            return "objectId"
        if "$url" in v:
            return "string"
        return "object"
    return "?"


def value_of(v):
    if isinstance(v, dict):
        for k in ("$date", "$int", "$oid", "$url"):
            if k in v:
                return v[k]
    return v


def check(schema, v, path, out):
    t = bson_type(v)
    want = schema.get("bsonType")
    if want is not None:
        want = [want] if isinstance(want, str) else want
        if t not in want:
            out.append(f"{path}: type {t}, schema wants {want}")
            return
    val = value_of(v)
    if "enum" in schema and val not in schema["enum"]:
        out.append(f"{path}: {val!r} not in enum")
    if isinstance(val, str) and t == "string":
        if "pattern" in schema and not re.search(schema["pattern"], val):
            out.append(f"{path}: {val!r} does not match {schema['pattern']}")
        if "minLength" in schema and len(val) < schema["minLength"]:
            out.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(val) > schema["maxLength"]:
            out.append(f"{path}: longer than {schema['maxLength']}")
    if t == "int" and "minimum" in schema and val < schema["minimum"]:
        out.append(f"{path}: {val} < minimum")
    if t == "object":
        for r in schema.get("required", []):
            if r not in v:
                out.append(f"{path}: missing required {r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in v:
                if k not in props:
                    out.append(f"{path}: unexpected field {k}")
        for k, sub in props.items():
            if k in v:
                check(sub, v[k], f"{path}.{k}", out)
    if t == "array":
        if "maxItems" in schema and len(v) > schema["maxItems"]:
            out.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in v}) != len(v):
            out.append(f"{path}: items are not unique")
        for i, x in enumerate(v):
            if "items" in schema:
                check(schema["items"], x, f"{path}[{i}]", out)


# ---------------------------------------------------------------------------------------------------------------------
def main():
    out_dir = os.path.join(SEED, "out")
    man = json.load(open(os.path.join(out_dir, "manifest.json"), encoding="utf-8"))
    catalog_js = open(os.path.join(out_dir, "catalog.js"), encoding="utf-8").read()
    schema = json.load(open(os.path.join(ROOT, "contracts/db-schema/mongo/catalog.json"), encoding="utf-8"))["collections"]
    docs = {n: js_to_json(catalog_js, n) for n in ("wallpapers", "favorites", "collections", "audit")}
    cmap = {"wallpapers": "wallpapers", "favorites": "favorites", "collections": "collections", "audit": "audit"}

    # 1. mongo validators
    for coll, items in docs.items():
        sch = schema[cmap[coll]]["validator"]["$jsonSchema"]
        for d in items:
            problems = []
            check(sch, d if "_id" in d else {**d, "_id": {"$oid": "0" * 24}}, "$", problems)  # the server adds a missing _id
            if coll == "wallpapers" and d.get("status") == "PUBLISHED":
                if not d["variants"] or bson_type(d.get("dimensions")) != "object":
                    problems.append("$expr: PUBLISHED needs variants and dimensions")
            for p in problems:
                err(f"catalog.{coll} {value_of(d.get('_id', d.get('entityId', '?')))}: {p}")
    for coll, key in (("wallpapers", lambda d: d["_id"]), ("collections", lambda d: d["_id"]), ("favorites", lambda d: (d["userId"], d["wallpaperId"])),
                      ("audit", lambda d: (d["entityType"], d["entityId"], d["action"]))):
        ks = [json.dumps(value_of(key(d))) for d in docs[coll]]
        if len(set(ks)) != len(ks):
            err(f"catalog.{coll}: duplicate keys (unique index / upsert filter)")

    # 2. elasticsearch
    mapping = json.load(open(os.path.join(ROOT, "contracts/db-schema/elasticsearch/wallpapers-v1.json"), encoding="utf-8"))["mappings"]["properties"]
    lines = [l for l in open(os.path.join(out_dir, "catalog.es.ndjson"), encoding="utf-8").read().split("\n") if l]
    if len(lines) % 2:
        err("catalog.es.ndjson: odd number of lines")
    es = {}
    for i in range(0, len(lines) - 1, 2):
        op, doc = json.loads(lines[i]), json.loads(lines[i + 1])
        if list(op) != ["create"] or op["create"].get("_index") != "wallpapers":
            err(f"catalog.es.ndjson line {i + 1}: expected a create op on the alias wallpapers")
        es[op["create"]["_id"]] = doc
        for k, v in doc.items():
            if k not in mapping:
                err(f"es {op['create']['_id']}: field {k} is not in the strict mapping")
                continue
            t = mapping[k].get("type")
            ok = {"keyword": lambda x: isinstance(x, (str, list)), "text": lambda x: x is None or isinstance(x, str), "integer": lambda x: isinstance(x, int) and abs(x) < 2 ** 31,
                  "date": lambda x: isinstance(x, str) and re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", x)}.get(t)
            if t is None and "properties" in mapping[k]:
                for kk, vv in v.items():
                    if kk not in mapping[k]["properties"]:
                        err(f"es {op['create']['_id']}: {k}.{kk} not in mapping")
                    elif not isinstance(vv, int):
                        err(f"es {op['create']['_id']}: {k}.{kk} must be an integer")
            elif ok and not ok(v):
                err(f"es {op['create']['_id']}: {k}={v!r} is not a valid {t}")

    # 3. redis
    keys = yaml.safe_load(open(os.path.join(ROOT, "contracts/db-schema/redis/keys.yaml"), encoding="utf-8"))["keys"]
    pats = {}
    for k in keys:
        rx = re.escape(k["pattern"]).replace(r"\{", "{").replace(r"\}", "}")
        rx = re.sub(r"\{[^}]+\}", r"[^:\\s]+", rx).replace(r"\*", ".*")
        pats[k["pattern"]] = (re.compile("^" + rx + "$"), k)
    notif_fields = set(next(k for k in keys if k["pattern"] == "notif:{id}")["fields"])
    prefs_fields = set(next(k for k in keys if k["pattern"] == "prefs:{userId}")["fields"])
    inbox, unread, notif_hashes = {}, {}, {}
    for fname, instance in (("notification.redis", "notification"), ("shared.redis", "shared")):
        for n, line in enumerate(open(os.path.join(out_dir, fname), encoding="utf-8"), 1):
            if not line.strip() or line.startswith("#"):
                continue
            toks = re.findall(r'"(?:[^"\\]|\\.)*"|\S+', line.rstrip("\n"))
            cmd, key = toks[0], toks[1].strip('"')
            hit = [(p, k) for p, (rx, k) in pats.items() if rx.match(key)]
            if not hit:
                err(f"{fname}:{n}: key {key} matches no pattern of keys.yaml")
                continue
            if hit[0][1]["instance"] != instance:
                err(f"{fname}:{n}: {key} belongs to the {hit[0][1]['instance']} instance")
            if cmd == "HSET":
                fields = dict(zip(toks[2::2], toks[3::2]))
                if key.startswith("notif:"):
                    if set(fields) != notif_fields:
                        err(f"{fname}:{n}: notif hash fields {sorted(fields)} != {sorted(notif_fields)}")
                    notif_hashes[key[6:]] = {k: v.strip('"') for k, v in fields.items()}
                if key.startswith("prefs:") and not set(fields) <= prefs_fields:
                    err(f"{fname}:{n}: unknown prefs fields {sorted(set(fields) - prefs_fields)}")
            if cmd == "ZADD" and key.startswith("inbox:unread:"):
                unread.setdefault(key[13:], set()).add(toks[3].strip('"'))
            elif cmd == "ZADD" and key.startswith("inbox:"):
                inbox.setdefault(key[6:], set()).add(toks[3].strip('"'))
    for uid, ids in unread.items():
        if not ids <= inbox.get(uid, set()):
            err(f"inbox:unread:{uid} has members that are not in inbox:{uid}")
    for nid, f in notif_hashes.items():
        if nid not in inbox.get(f["userId"], set()):
            err(f"{nid} is not in inbox:{f['userId']}")
        if (f["read"] == "1") == (nid in unread.get(f["userId"], set())):
            err(f"{nid}: read flag and inbox:unread disagree")

    # 4. cross-store consistency (manifest is the neutral form of the same model)
    users = {u["id"]: u for u in man["users"]}
    assets = {a["id"]: a for a in man["assets"]}
    wps = {w["id"]: w for w in man["wallpapers"]}
    if set(d["_id"] for d in docs["wallpapers"]) != set(wps):
        err("catalog.js wallpapers differ from the manifest")
    pub = {i for i, w in wps.items() if w["status"] == "PUBLISHED"}
    if set(es) != pub:
        err(f"Elasticsearch holds {len(es)} documents, the catalog has {len(pub)} PUBLISHED wallpapers")
    fav = {}
    for f in docs["favorites"]:
        fav[f["wallpaperId"]] = fav.get(f["wallpaperId"], 0) + 1
        if f["userId"] not in users:
            err(f"favorite of unknown user {f['userId']}")
        if f["wallpaperId"] not in pub:
            err(f"favorite of {f['wallpaperId']}, which is not PUBLISHED")
    for d in docs["wallpapers"]:
        wid = d["_id"]
        if value_of(d["favoriteCount"]) != fav.get(wid, 0):
            err(f"{wid}: favoriteCount {value_of(d['favoriteCount'])} != {fav.get(wid, 0)} favorites")
        a = assets.get(d["assetId"])
        if not a:
            err(f"{wid}: asset {d['assetId']} is not in media.sql")
            continue
        if d["author"]["id"] != a["owner"] or a["purpose"] != "WALLPAPER":
            err(f"{wid}: asset owner or purpose does not match")
        if d["status"] == "PUBLISHED" and a["status"] != "READY":
            err(f"{wid}: PUBLISHED but its asset is {a['status']}")
        if d["status"] == "PENDING_MEDIA" and a["status"] != "PROCESSING":
            err(f"{wid}: PENDING_MEDIA but its asset is {a['status']}")
        if a["status"] == "READY" and {x["kind"] for x in a["variants"]} != {v["kind"] for v in d["variants"]}:
            err(f"{wid}: variants differ from media_variant")
        u = users.get(d["author"]["id"])
        if not u or u["deleted"]:
            err(f"{wid}: author missing or soft-deleted")
        elif d["author"]["username"] != u["username"] or d["author"]["displayName"] != u["display_name"]:
            err(f"{wid}: author snapshot differs from account.users")
        if "moderation" in d and d["moderation"] and d["moderation"]["moderatorId"] not in users:
            err(f"{wid}: unknown moderator")
    for c in docs["collections"]:
        if c["ownerId"] not in users:
            err(f"collection {c['_id']}: unknown owner")
        for w in c["wallpaperIds"]:
            if w not in wps:
                err(f"collection {c['_id']}: unknown wallpaper {w}")
    for uid, u in users.items():
        for k in ("avatarAssetId", "bannerAssetId"):
            if u[k] and (u[k] not in assets or assets[u[k]]["owner"] != uid):
                err(f"user {u['username']}: {k} missing or owned by someone else")
    for uid in list(inbox):
        if uid not in users or users[uid]["deleted"]:
            err(f"inbox of unknown or deleted user {uid}")
    # image files and checksums
    for a in assets.values():
        p = os.path.join(SEED, "s3", "originals", a["original_key"])
        if not os.path.isfile(p):
            err(f"{a['id']}: original {a['original_key']} is missing")
        elif a["sha256"] and hashlib.sha256(open(p, "rb").read()).hexdigest() != a["sha256"]:
            err(f"{a['id']}: sha256 differs from the file")
        for v in a["variants"]:
            vp = os.path.join(SEED, "s3", "public", v["key"])
            if not os.path.isfile(vp) or os.path.getsize(vp) != v["size_bytes"]:
                err(f"{a['id']}: variant {v['key']} missing or of another size")
    # no file nobody references
    ref = {os.path.join("originals", a["original_key"]) for a in assets.values()} | {os.path.join("public", v["key"]) for a in assets.values() for v in a["variants"]}
    for dp, _, fs in os.walk(os.path.join(SEED, "s3")):
        for f in fs:
            rel = os.path.relpath(os.path.join(dp, f), os.path.join(SEED, "s3")).replace(os.sep, "/")
            if rel not in ref:
                err(f"seed/s3/{rel} is not referenced by any asset")

    if errors:
        print(f"{errors} problem(s) in the seed data")
        return 1
    print(f"seed data OK: {len(docs['wallpapers'])} wallpapers, {len(docs['favorites'])} favorites, {len(docs['collections'])} collections, "
          f"{len(es)} search documents, {len(notif_hashes)} notifications, {len(assets)} assets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
