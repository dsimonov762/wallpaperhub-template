#!/usr/bin/env python3
"""Generate the Bruno collection in bruno/ from the contracts and the seed manifest.

  python3 scripts/bruno-gen.py            write bruno/   (bruno/custom/ is yours and is never touched)
  python3 scripts/bruno-gen.py --check    fail if bruno/ is not what the generator would write (CI, `make bruno-check`)

Inputs: contracts/openapi/*.yaml (operations, examples, x-access, x-error-codes), contracts/graphql/examples/*.graphql,
seed/out/manifest.json (ids for the environments). Output is deterministic, so a contract change shows up as a diff.
Needs PyYAML (the seed and contract tooling already use it).
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OPENAPI = ROOT / "contracts" / "openapi"
GRAPHQL = ROOT / "contracts" / "graphql" / "examples"
MANIFEST = ROOT / "seed" / "out" / "manifest.json"
OUT = ROOT / "bruno"
SERVICES = ["account", "media", "catalog", "notification"]
KEYCLOAK_CLIENT = "e2e-tests"

# --- decisions about how operations are used in the collection ---------------------------------------------------
# Path ids: the id of the *seeded* entity of the active user, unless the operation changes or deletes the entity. Those use
# what the collection created earlier in the same run, so a run never edits or deletes seed data (a failed create leaves the
# variable unresolved and the call answers 404 instead of hitting something real).
PATH_VAR = {"UserId": "otherUserId", "AssetId": "assetId", "WallpaperId": "wallpaperId", "CollectionId": "collectionId",
            "NotificationId": "notificationId"}  # the parameter component name, without a trailing "Path"
CREATED_VAR = {"replaceWallpaper": "createdWallpaperId", "updateWallpaper": "createdWallpaperId",
               "deleteWallpaper": "createdWallpaperId", "replaceCollection": "createdCollectionId",
               "deleteCollection": "createdCollectionId", "deleteMedia": "uploadedAssetId", "deleteUser": "newUserId"}
# Variables a response fills in for the later requests: operationId -> [(runtime variable, JSON path in the body)]
CAPTURE = {"registerUser": [("newUserId", "id")], "createWallpaper": [("createdWallpaperId", "id")],
           "createCollection": [("createdCollectionId", "id")], "uploadMedia": [("uploadedAssetId", "assetId")],
           "createStreamTicket": [("streamTicket", "ticket")]}
# Body fields that must point at something the caller owns: (operationId, field) -> expression
BODY_FIELD = {("createWallpaper", "assetId"): "{{uploadedAssetId}}", ("setAvatar", "assetId"): "{{avatarAssetId}}",
              ("setBanner", "assetId"): "{{bannerAssetId}}", ("uploadMedia", "purpose"): "WALLPAPER", ("registerUser", "username"): "{{newUsername}}",
              ("registerUser", "email"): "{{newUsername}}@example.test"}
# Admin-only in practice although the contract says owner-or-admin: the collection deletes somebody else's (new) user.
EXTRA_TAGS = {"deleteUser": ["admin"]}
# Long-lived connections do not fit a request/response client; the README shows curl for them.
SKIP = {"streamNotifications", "connectNotificationSocket"}
GRAPHQL_VARS = {"Favorite": {"id": "{{wallpaperId}}"}, "Unfavorite": {"id": "{{wallpaperId}}"}, "Search": {"q": "forest"},
                "Me": {}, "WallpapersPage": {}}

_docs = {}


def load(path):
    path = Path(path).resolve()
    if path not in _docs:
        _docs[path] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _docs[path]


def resolve(node, base):
    """Follow $ref chains; returns (node, file the node lives in)."""
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        file_part, _, frag = ref.partition("#")
        if file_part:
            base = (Path(base).parent / file_part).resolve()
        cur = load(base)
        for part in [p for p in frag.split("/") if p]:
            cur = cur[part.replace("~1", "/").replace("~0", "~")]
        node = cur
    return node, base


def example_for(schema, base, depth=0):
    """The example of a schema, or a value built from it (required properties only)."""
    schema, base = resolve(schema, base)
    if not isinstance(schema, dict) or depth > 6:
        return None
    if "example" in schema:
        return schema["example"]
    if "allOf" in schema:
        out = {}
        for part in schema["allOf"]:
            v = example_for(part, base, depth + 1)
            if isinstance(v, dict):
                out.update(v)
        return out
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        out = {}
        for name, sub in (schema.get("properties") or {}).items():
            sub_r, _ = resolve(sub, base)
            if name in schema.get("required", []) or "example" in sub_r:
                out[name] = example_for(sub, base, depth + 1)
        return out
    if t == "array":
        item = example_for(schema.get("items", {}), base, depth + 1)
        return [] if item is None else [item]
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    if t == "integer":
        return schema.get("minimum", 1)
    if t == "number":
        return schema.get("minimum", 1)
    if t == "boolean":
        return True
    if t == "string":
        return "string"
    return None


def indent(text, n=2):
    pad = " " * n
    return "\n".join((pad + line) if line else "" for line in text.rstrip("\n").split("\n"))


def block(name, body):
    return f"{name} {{\n{indent(body)}\n}}\n"


def kv_block(name, pairs):
    return block(name, "\n".join(f"{k}: {v}" for k, v in pairs))


def clean(text):
    return re.sub(r"\s+", " ", (text or "").strip())


# --- OpenAPI -> requests -------------------------------------------------------------------------------------------
def parameters(path_item, op, base):
    out = {}
    for src in (path_item.get("parameters", []), op.get("parameters", [])):
        for p in src:
            ref_name = p["$ref"].split("/")[-1] if "$ref" in p else None
            pr, _ = resolve(p, base)
            out[(pr["name"], pr["in"])] = (pr, ref_name)
    return list(out.values())


QUERY_VALUE = {("searchWallpapers", "q"): "forest", ("searchWallpapers", "tag"): "forest"}


def param_value(op_id, p, base):
    if (op_id, p["name"]) in QUERY_VALUE:
        return QUERY_VALUE[(op_id, p["name"])]
    sch, sbase = resolve(p.get("schema", {}), base)
    for key in ("example", "default"):
        if key in sch:
            value = sch[key]
            return str(value).lower() if isinstance(value, bool) else value
    if "enum" in sch:
        return sch["enum"][0]
    if sch.get("type") == "boolean":
        return "false"
    if sch.get("type") == "array":  # comma separated (style: form, explode: false)
        items, _ = resolve(sch.get("items", {}), sbase)
        return ",".join(items.get("enum", []))
    return ""


def build_http(service, path, method, op, path_item, base, seq):
    op_id = op["operationId"]
    params = parameters(path_item, op, base)
    url = "{{baseUrl}}/api/v1" + path
    for pr, ref_name in params:
        if pr["in"] == "path":
            var = CREATED_VAR.get(op_id) or PATH_VAR.get((ref_name or "").removesuffix("Path"))
            if not var:
                raise SystemExit(f"bruno-gen: {op_id}: no variable for path parameter {pr['name']} ({ref_name}); add it to PATH_VAR")
            url = url.replace("{" + pr["name"] + "}", "{{" + var + "}}")
    queries, headers, in_url = [], [], []
    for pr, ref_name in params:
        value = param_value(op_id, pr, base)
        if pr["in"] == "query":
            if pr.get("required") and value == "":
                raise SystemExit(f"bruno-gen: {op_id}: required query parameter {pr['name']} has no example; add it to QUERY_VALUE")
            on = "" if pr.get("required") else "~"
            queries.append(f"{on}{pr['name']}: {value}")
            if on == "":  # Bruno sends the URL, so enabled parameters must be in it (the block mirrors them for the UI)
                in_url.append(f"{pr['name']}={value}")
        elif pr["in"] == "header":
            if pr["name"] == "Idempotency-Key":
                headers.append("Idempotency-Key: {{$guid}}")
            elif pr["name"] == "If-Match":
                headers.append("If-Match: {{etag}}")
            elif pr["name"] == "Last-Event-ID":
                continue
            else:
                headers.append(f"~{pr['name']}: {value}")

    if in_url:
        url += "?" + "&".join(in_url)
    public = op.get("security") == []
    access = op.get("x-access", "authenticated")
    tags = [access, "read" if method == "get" else "write"] + EXTRA_TAGS.get(op_id, [])
    status = next((c for c in op["responses"] if str(c).startswith("2")), "200")

    body_kind, body_text = "none", None
    rb = op.get("requestBody")
    if rb:
        rb, rbase = resolve(rb, base)
        media = rb["content"]
        if "application/json" in media:
            m = media["application/json"]
            data = m["example"] if "example" in m else example_for(m.get("schema", {}), rbase)
            if isinstance(data, dict):
                data = {k: BODY_FIELD.get((op_id, k), v) for k, v in data.items()}
            if op_id == "createCollection" and isinstance(data, dict) and "wallpaperIds" in data:
                data["wallpaperIds"] = ["{{wallpaperId}}"]
            if op_id in ("refreshToken", "logout") and isinstance(data, dict):
                data["refreshToken"] = "{{refreshToken}}"
            body_kind, body_text = "json", json.dumps(data, indent=2, ensure_ascii=False)
        elif "multipart/form-data" in media:
            sch, sbase = resolve(media["multipart/form-data"]["schema"], rbase)
            lines = []
            for name, sub in sch.get("properties", {}).items():
                sub_r, sub_b = resolve(sub, sbase)
                if sub_r.get("format") == "binary":
                    lines.append(f"{name}: @file({SAMPLE_IMAGE})")
                else:
                    lines.append(f"{name}: {BODY_FIELD.get((op_id, name)) or example_for(sub, sbase)}")
            body_kind, body_text = "multipartForm", "\n".join(lines)
        else:
            raise SystemExit(f"bruno-gen: {op_id}: unsupported request body {list(media)}")

    parts = [block("meta", "name: " + op["summary"] + f"\ntype: http\nseq: {seq}\ntags: [\n" + indent("\n".join(tags)) + "\n]")]
    parts.append(block(method, f"url: {url}\nbody: {body_kind}\nauth: {'none' if public else 'inherit'}"))
    if queries:
        parts.append(block("params:query", "\n".join(queries)))
    if headers:
        parts.append(block("headers", "\n".join(headers)))
    if body_kind == "json":
        parts.append(block("body:json", body_text))
    elif body_kind == "multipartForm":
        parts.append(block("body:multipart-form", body_text))

    pre, post = [], []
    for (o, f), expr in BODY_FIELD.items():
        if o == op_id and op_id in ("setAvatar", "setBanner"):  # only users that have such an image in the seed can run these
            var = expr.strip("{}")
            pre.append(f'if (!bru.getEnvVar("{var}")) bru.runner.skipRequest(); // this user has no seeded image of that kind')
    if op_id == "registerUser":
        pre.append('bru.setVar("newUsername", "dev" + Date.now().toString(36));')
    for var, jpath in CAPTURE.get(op_id, []):
        post.append(f'if (res.status < 300 && res.body && res.body.{jpath}) bru.setVar("{var}", res.body.{jpath});')
    if op_id == "refreshToken":
        post.append('if (res.status === 200 && res.body.refreshToken) bru.setVar("refreshToken", res.body.refreshToken);')
    if pre:
        parts.append(block("script:pre-request", "\n".join(pre)))
    if post:
        parts.append(block("script:post-response", "\n".join(post)))
    parts.append(block("assert", f"res.status: eq {status}"))

    codes = op.get("x-error-codes") or []
    doc = [op["summary"] + " (" + op_id + ")", "", op.get("description", "").strip(), "", f"Access: `{access}`."]
    if op_id in CREATED_VAR:
        doc.append(f"Works on `{{{{{CREATED_VAR[op_id]}}}}}`, which an earlier request of this collection creates, so seed data stays untouched.")
    if op_id in ("setAvatar", "setBanner"):
        doc.append("Uses an image of the active user from the seed (`{{" + ("avatarAssetId" if op_id == "setAvatar" else "bannerAssetId") + "}}`); skipped for users that have none.")
    if op_id == "deleteUser":
        doc.append("Run as `admin`: the user it deletes is the one `Register a user` created.")
    if codes:
        doc.append("Error codes: " + ", ".join(f"`{c}`" for c in codes) + ".")
    parts.append(block("docs", "\n".join(doc)))
    return op_id, "\n".join(parts)


def openapi_requests():
    """{service: {tag: [(operationId, text)]}} in contract order."""
    out = {}
    for svc in SERVICES:
        path = OPENAPI / f"{svc}.yaml"
        spec = load(path)
        folders, seq = {}, 0
        for p, item in spec["paths"].items():
            for method in ("get", "post", "put", "patch", "delete"):
                if method not in item:
                    continue
                op = item[method]
                if op["operationId"] in SKIP:
                    continue
                seq += 1
                folders.setdefault(op["tags"][0], []).append(build_http(svc, p, method, op, item, path, seq))
        out[svc] = folders
    return out


# --- GraphQL -------------------------------------------------------------------------------------------------------
def graphql_requests():
    ops = []
    for f in sorted(GRAPHQL.glob("*.graphql")):
        text = f.read_text(encoding="utf-8")
        chunks = re.split(r"(?m)^(?=(?:query|mutation)\s)", text)
        for chunk in chunks:
            m = re.match(r"(query|mutation)\s+(\w+)", chunk)
            if not m:
                continue
            kind, name = m.groups()
            ops.append((kind, name, chunk.rstrip() + "\n", f.name))
    out = []
    for seq, (kind, name, query, src) in enumerate(ops, 1):
        if name not in GRAPHQL_VARS:
            raise SystemExit(f"bruno-gen: GraphQL operation {name} ({src}) has no entry in GRAPHQL_VARS")
        decls = re.findall(r"\$(\w+):\s*([^,)=]+)", query.split("{", 1)[0])
        required = [v for v, t in decls if t.strip().endswith("!") and "=" not in t]
        missing = [v for v in required if v not in GRAPHQL_VARS[name]]
        if missing:
            raise SystemExit(f"bruno-gen: GraphQL operation {name} needs variables {missing}; add them to GRAPHQL_VARS")
        tags = ["authenticated", "write" if kind == "mutation" else "read"]
        text = "\n".join([
            block("meta", f"name: {name}\ntype: graphql\nseq: {seq}\ntags: [\n" + indent("\n".join(tags)) + "\n]"),
            block("post", "url: {{baseUrl}}/graphql\nbody: graphql\nauth: inherit"),
            block("body:graphql", query),
            block("body:graphql:vars", json.dumps(GRAPHQL_VARS[name], indent=2)),
            block("assert", "res.status: eq 200\nres.body.errors: isUndefined"),
            block("docs", f"{kind.capitalize()} `{name}` from contracts/graphql/examples/{src}.\n\nGraphQL answers 200 even for errors, so the assertion also checks that `errors` is absent."),
        ])
        out.append((name, text))
    return out


# --- environments --------------------------------------------------------------------------------------------------
def environments(manifest):
    users = manifest["users"]
    envs = {}
    wallpapers, assets = manifest["wallpapers"], manifest["assets"]
    for u in users:
        if u["deleted"] or not (u["in_keycloak"] or u["username"] in ("alice", "mod", "admin")):
            continue
        uid = u["id"]
        pub = [w for w in wallpapers if w["status"] == "PUBLISHED"]
        wp = next((w for w in pub if w["authorId"] == uid), pub[0])
        other = next(x for x in users if x["id"] != uid and x["status"] == "ACTIVE" and not x["deleted"])
        cols = [c for c in manifest["collections"] if c["ownerId"] == uid] or manifest["collections"]
        unread = [n for n in manifest["notifications"] if n["userId"] == uid and not n["read"]]
        mine = [n for n in manifest["notifications"] if n["userId"] == uid]
        note = (unread or mine or manifest["notifications"])[0]
        own_assets = [a for a in assets if a["owner"] == uid and a["status"] == "READY"]
        asset = next((a for a in own_assets if a["purpose"] == "WALLPAPER"), own_assets[0] if own_assets else assets[0])
        avatar = u.get("avatarAssetId") or next((a["id"] for a in own_assets if a["purpose"] == "AVATAR"), "")
        banner = u.get("bannerAssetId") or next((a["id"] for a in own_assets if a["purpose"] == "BANNER"), "")
        pairs = [("baseUrl", "http://localhost:8080"), ("keycloakUrl", "http://localhost:8180"), ("realm", "wallpaperhub"),
                 ("clientId", KEYCLOAK_CLIENT), ("username", u["username"]), ("password", "password"),
                 ("serviceClient", "catalog-svc"), ("serviceSecret", "catalog-svc-dev-secret"),
                 ("userId", uid), ("otherUserId", other["id"]), ("wallpaperId", wp["id"]), ("collectionId", cols[0]["id"]),
                 ("notificationId", note["id"]), ("assetId", asset["id"]), ("avatarAssetId", avatar), ("bannerAssetId", banner)]
        envs[u["username"]] = kv_block("vars", pairs)
    return envs


# --- collection files ----------------------------------------------------------------------------------------------
COLLECTION_BRU = """auth {
  mode: oauth2
}

auth:oauth2 {
  grant_type: password
  access_token_url: {{keycloakUrl}}/realms/{{realm}}/protocol/openid-connect/token
  refresh_token_url:
  username: {{username}}
  password: {{password}}
  client_id: {{clientId}}
  client_secret:
  scope:
  credentials_placement: body
  credentials_id: {{realm}}-{{username}}
  token_placement: header
  token_header_prefix: Bearer
  auto_fetch_token: true
  auto_refresh_token: true
}

script:pre-request {
  // If-Match is only sent when an earlier response gave an ETag (otherwise the write is unconditional).
  if (!bru.getVar("etag")) req.deleteHeader("If-Match");
}

script:post-response {
  // Remember the newest ETag; the next PUT/PATCH sends it back as If-Match.
  const etag = res.getHeader("etag");
  if (etag) bru.setVar("etag", etag);
}

docs {
  Wallpaper Hub through the gateway.

  Generated by `make bruno-gen` from contracts/openapi, contracts/graphql/examples and the seed manifest: do not edit
  the generated folders by hand, put your own requests in `custom/`. See bruno/README.md.

  Pick an environment (the user you want to be). The token is fetched with the OAuth2 password grant of the
  `e2e-tests` client and refreshed automatically.
}
"""

KEYCLOAK_REQUESTS = {
    "password-grant": """meta {
  name: Password grant (raw token answer)
  type: http
  seq: 1
  tags: [
    keycloak
  ]
}

post {
  url: {{keycloakUrl}}/realms/{{realm}}/protocol/openid-connect/token
  body: formUrlEncoded
  auth: none
}

body:form-urlencoded {
  grant_type: password
  client_id: {{clientId}}
  username: {{username}}
  password: {{password}}
}

script:post-response {
  if (res.status === 200) bru.setVar("refreshToken", res.body.refresh_token);
}

assert {
  res.status: eq 200
}

docs {
  The full token answer for the active user, including the refresh token. Stores `refreshToken` for the
  Refresh and Logout requests of the account service.
}
""",
    "service-token": """meta {
  name: Service token (client credentials)
  type: http
  seq: 2
  tags: [
    keycloak
  ]
}

post {
  url: {{keycloakUrl}}/realms/{{realm}}/protocol/openid-connect/token
  body: formUrlEncoded
  auth: none
}

body:form-urlencoded {
  grant_type: client_credentials
  client_id: {{serviceClient}}
  client_secret: {{serviceSecret}}
}

script:post-response {
  if (res.status === 200) bru.setVar("serviceToken", res.body.access_token);
}

assert {
  res.status: eq 200
}

docs {
  A token of a service account (`internal` role), what one service presents to another. Stored as `serviceToken`;
  use it as `Authorization: Bearer {{serviceToken}}` on a request, for example `Get a media asset`, which the
  contract allows for owner or internal callers.
}
""",
}


def folder_bru(name, seq):
    return block("meta", f"name: {name}\nseq: {seq}")


def generate(target: Path):
    global SAMPLE_IMAGE
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sample = sorted((a for a in manifest["assets"] if a["purpose"] == "WALLPAPER" and a["status"] == "READY"),
                    key=lambda a: (a["size_bytes"], a["id"]))[0]
    rel = Path("seed") / "s3" / "originals" / sample["original_key"]
    if not (ROOT / rel).is_file():
        raise SystemExit(f"bruno-gen: sample upload {rel} is missing; run make seed-build")
    SAMPLE_IMAGE = "../" + rel.as_posix()

    files = {"bruno.json": json.dumps({"version": "1", "name": "Wallpaper Hub", "type": "collection",
                                      "ignore": ["node_modules", ".git"]}, indent=2) + "\n",
             "collection.bru": COLLECTION_BRU}
    for name, text in environments(manifest).items():
        files[f"environments/{name}.bru"] = text
    files["keycloak/folder.bru"] = folder_bru("Keycloak", 1)
    for fname, text in KEYCLOAK_REQUESTS.items():
        files[f"keycloak/{fname}.bru"] = text
    for i, (svc, folders) in enumerate(openapi_requests().items(), 2):
        files[f"{svc}/folder.bru"] = folder_bru(svc.capitalize(), i)
        for j, (tag, reqs) in enumerate(folders.items(), 1):
            for op_id, text in reqs:
                files[f"{svc}/{tag.lower()}/{op_id}.bru"] = text
            files[f"{svc}/{tag.lower()}/folder.bru"] = folder_bru(tag, j)
    files["graphql/folder.bru"] = folder_bru("GraphQL", 6)
    for name, text in graphql_requests():
        files[f"graphql/{name}.bru"] = text
    managed = {p.split("/")[0] for p in files}
    for rel_path, text in files.items():
        p = target / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    return managed


def snapshot(base: Path, managed):
    out = {}
    for top in managed:
        p = base / top
        if p.is_file():
            out[top] = p.read_text(encoding="utf-8")
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    out[f.relative_to(base).as_posix()] = f.read_text(encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="compare instead of writing")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        managed = generate(tmp)
        if args.check:
            want, have = snapshot(tmp, managed), snapshot(OUT, managed)
            problems = [f"missing: {k}" for k in want if k not in have] + [f"stale: {k}" for k in have if k not in want] \
                + [f"differs: {k}" for k in want if k in have and have[k] != want[k]]
            if problems:
                print("bruno/ is out of date with the contracts or the seed data:", file=sys.stderr)
                for line in problems[:20]:
                    print("  " + line, file=sys.stderr)
                print("run: make bruno-gen", file=sys.stderr)
                return 1
            print(f"bruno/ is up to date ({len(want)} files)")
            return 0
        OUT.mkdir(exist_ok=True)
        for top in managed:
            p = OUT / top
            if p.is_dir():
                shutil.rmtree(p)
            elif p.is_file():
                p.unlink()
        for f in sorted(tmp.rglob("*")):
            if f.is_file():
                dest = OUT / f.relative_to(tmp)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dest)
        print(f"wrote {sum(1 for _ in tmp.rglob('*') if _.is_file())} files to bruno/")
    return 0


SAMPLE_IMAGE = ""

if __name__ == "__main__":
    sys.exit(main())
