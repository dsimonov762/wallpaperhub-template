#!/usr/bin/env python3
"""Regenerates the localized problem+json replies of the gateway (envoy.yaml, local_reply_config.mappers) from the
i18n bundles, so the gateway says exactly what the services say:   python3 scripts/gen-gateway-errors.py [--check]

  problem.<slug>.title / .detail   in contracts/i18n/messages.{en,de,es}.json
  language = first tag of Accept-Language (de / es), English otherwise (same fallback as the services)
Run it after changing a problem.* text; --check fails when envoy.yaml is out of date (used by make lint)."""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENVOY = os.path.join(ROOT, "services/gateway/envoy/envoy.yaml")
BEGIN = "# BEGIN generated: local_reply mappers (scripts/gen-gateway-errors.py, do not edit by hand)"
END = "# END generated"
# slug -> status codes answered by the gateway itself
ERRORS = [("unauthorized", [401]), ("not-found", [404]), ("payload-too-large", [413]),
          ("rate-limited", [429]), ("upstream-unavailable", [502, 503, 504])]
LANGS = ["de", "es", "en"]   # specific languages first, English (no header test) last: first match wins
I = " " * 20

def q(s):  # YAML double-quoted scalar
    return json.dumps(s, ensure_ascii=False)

def sp(n):
    return " " * n

def status_lines(codes, ind):
    """status_code_filter (one code) or or_filter (several) as YAML lines whose first key sits at column `ind`."""
    one = lambda c, i: [f"{sp(i)}status_code_filter:",
                        f"{sp(i + 2)}comparison: {{ op: EQ, value: {{ default_value: {c}, runtime_key: gateway.lr.{c} }} }}"]
    if len(codes) == 1:
        return one(codes[0], ind)
    out = [f"{sp(ind)}or_filter:", f"{sp(ind + 2)}filters:"]
    for c in codes:
        l = one(c, ind + 6)
        out += [f"{sp(ind + 4)}- {l[0].lstrip()}", l[1]]
    return out

def mapper(lang, slug, codes, msgs):
    title, detail = msgs[lang][f"problem.{slug}.title"], msgs[lang][f"problem.{slug}.detail"]
    base = 20
    lines = [f"{sp(base)}- filter:"]
    if lang == "en":
        lines += status_lines(codes, base + 4)
    else:
        lines += [f"{sp(base + 4)}and_filter:", f"{sp(base + 6)}filters:"]
        st = status_lines(codes, base + 10)
        lines += [f"{sp(base + 8)}- {st[0].lstrip()}"] + st[1:]
        lines += [f"{sp(base + 8)}- header_filter:", f"{sp(base + 12)}header:", f"{sp(base + 14)}name: accept-language",
                  f"{sp(base + 14)}string_match:",
                  f"{sp(base + 16)}safe_regex: {{ regex: {q('(?i)^\\s*' + lang + r'([-_;,\s].*)?$')} }}"]
    lines += [f"{I}  headers_to_add:",
              f"{I}    - {{ append_action: OVERWRITE_IF_EXISTS_OR_ADD, header: {{ key: content-language, value: {lang} }} }}",
              f"{I}  body_format_override:", f"{I}    content_type: application/problem+json", f"{I}    json_format:",
              f"{I}      type: https://wallpaperhub.dev/problems/{slug}", f"{I}      title: {q(title)}",
              f"{I}      status: \"%RESPONSE_CODE%\"", f"{I}      detail: {q(detail)}",
              f"{I}      instance: \"%PATH(NQ)%\"", f"{I}      requestId: \"%REQ(X-REQUEST-ID)%\""]
    return "\n".join(lines) + "\n"

def generate():
    msgs = {l: json.load(open(os.path.join(ROOT, f"contracts/i18n/messages.{l}.json"), encoding="utf-8")) for l in LANGS}
    out = f"{I}{BEGIN}\n"
    out += (f"{I}# GET /health answered by the health_check filter (200 only while every upstream is healthy)\n"
            f"{I}- filter:\n{I}    status_code_filter:\n{I}      comparison: {{ op: EQ, value: {{ default_value: 200, runtime_key: gateway.lr.200 }} }}\n"
            f"{I}  body_format_override:\n{I}    content_type: application/json\n{I}    json_format:\n{I}      status: UP\n")
    for lang in LANGS:
        for slug, codes in ERRORS:
            out += mapper(lang, slug, codes, msgs)
    out += f"{I}{END}\n"
    return out

def main():
    s = open(ENVOY, encoding="utf-8").read()
    pat = re.compile(r"^ *" + re.escape(BEGIN) + r".*?^ *" + re.escape(END) + r"\n", re.S | re.M)
    new = generate()
    if pat.search(s):
        updated = pat.sub(lambda m: new, s)
    else:  # first run: replace everything from "mappers:" to the end of the list (the "body_format:" default)
        a = s.index("                  mappers:\n") + len("                  mappers:\n")
        b = s.index("                  body_format:\n")
        updated = s[:a] + new + s[b:]
    if "--check" in sys.argv:
        if updated != s:
            print("envoy.yaml is out of date: run python3 scripts/gen-gateway-errors.py"); sys.exit(1)
        print("gateway error mappers up to date"); return
    open(ENVOY, "w", encoding="utf-8").write(updated)
    print("envoy.yaml updated")

main()
