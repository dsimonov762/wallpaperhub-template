#!/usr/bin/env python3
"""Builds the seed data of every store from seed/dataset.yaml.

    python seed/build.py            generate missing images, write seed/out/*  (needs: pyyaml, pillow, numpy)
    python seed/build.py --regen    also regenerate every image
    python seed/build.py --check    write nothing; fail when seed/out/ or the images are stale (needs only: pyyaml)

Output (all committed, so `make seed` needs nothing but the images the stack already pulled):
    seed/s3/originals/**, seed/s3/public/**   image files, same layout as the buckets
    seed/images.lock.json                     what was derived from the pixels (phash, blurhash, palette) + parameters
    seed/out/keycloak-users.json              Keycloak partial import body
    seed/out/account.sql  media.sql           Postgres, `INSERT ... ON CONFLICT DO NOTHING`
    seed/out/catalog.js                       mongosh script (upserts with $setOnInsert, validators stay active)
    seed/out/catalog.es.ndjson                Elasticsearch _bulk body (op create)
    seed/out/notification.redis shared.redis  redis-cli command files
    seed/out/manifest.json                    the whole dataset as neutral JSON (for tests and the validator)
    seed/CATALOG.md                           readable id table

Image files are only derived once and then treated as source files: the lock records the parameters they were made from,
so a changed motif/palette/size shows up as "stale" and everything else is a pure function of dataset + files + i18n.
"""
from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seed"
OUT = SEED / "out"
S3 = SEED / "s3"
LOCK = SEED / "images.lock.json"
GEN_VERSION = 1  # bump when the drawing code changes, so --check reports every image as stale

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
REJECT_LABEL_KEY = "media.reject-reason."


# ---------------------------------------------------------------------------------------------------------------------
# small helpers
def sha(s: str) -> bytes:
    return hashlib.sha256(s.encode()).digest()


def h_int(s: str) -> int:
    return int.from_bytes(sha(s)[:8], "big")


def ulid(ts_ms: int, seed: str) -> str:
    value = (ts_ms << 80) | int.from_bytes(sha(seed)[:10], "big")
    chars = []
    for _ in range(26):
        chars.append(ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def uuid_of(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def jitter(key: str, minutes: int) -> int:
    return h_int("j:" + key) % minutes


def hexcolor(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, round(c)))) for c in rgb)


def rgb(hexs: str):
    return tuple(int(hexs[i:i + 2], 16) for i in (1, 3, 5))


def mix(a, b, t):
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))


# ---------------------------------------------------------------------------------------------------------------------
# JavaScript / SQL / Redis literals
class Raw(str):
    """JavaScript source inserted as it is."""


class I(int):
    """Written as NumberInt(n): the validator accepts int and long, never double."""


def js(v, ind=0):
    pad = "  " * ind
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Raw):
        return str(v)
    if isinstance(v, I):
        return f"NumberInt({int(v)})"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, datetime):
        return f'new Date("{iso(v)}")'
    if isinstance(v, list):
        if not v:
            return "[]"
        if all(isinstance(x, (str, int)) and not isinstance(x, I) for x in v):
            return "[" + ", ".join(js(x) for x in v) + "]"
        return "[\n" + ",\n".join(pad + "  " + js(x, ind + 1) for x in v) + "\n" + pad + "]"
    if isinstance(v, dict):
        if not v:
            return "{}"
        return "{\n" + ",\n".join(f"{pad}  {json.dumps(k)}: {js(x, ind + 1)}" for k, x in v.items()) + "\n" + pad + "}"
    raise TypeError(type(v))


def sq(v) -> str:
    """SQL literal."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, datetime):
        return f"'{iso(v)}'"
    return "'" + str(v).replace("'", "''") + "'"


def rq(v) -> str:
    """redis-cli argument: double quoted, only backslash, quote and control characters are escaped."""
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return '"' + s + '"'


def jdump(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------------------------------------------------
# image pipeline pieces (PIL / numpy are imported lazily: --check does not need them)
def drawing():
    global np, Image, ImageDraw, ImageFilter, ImageFont
    import numpy as np  # noqa
    from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa
    return True


def vgrad(w, h, top, bot):
    t = np.linspace(0, 1, h)[:, None, None]
    arr = np.array(top, dtype=float)[None, None, :] * (1 - t) + np.array(bot, dtype=float)[None, None, :] * t
    return Image.fromarray(np.broadcast_to(arr, (h, w, 3)).astype("uint8"))


def glow(img, layer_fn, radius, scale=4):
    """Draw with layer_fn(draw, w, h) on a small RGBA layer, blur it and composite (cheap soft shapes)."""
    w, h = img.size
    sw, sh = max(1, w // scale), max(1, h // scale)
    layer = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    layer_fn(ImageDraw.Draw(layer), sw, sh)
    # blur premultiplied colour, otherwise the transparent black of the layer darkens every soft edge
    a = np.asarray(layer, dtype=float)
    alpha = a[..., 3:4] / 255.0
    pre = Image.fromarray((a[..., :3] * alpha).astype("uint8"))
    al = Image.fromarray(a[..., 3].astype("uint8"))
    pre = np.asarray(pre.filter(ImageFilter.GaussianBlur(radius)).resize((w, h), Image.BILINEAR), dtype=float)
    al = np.asarray(al.filter(ImageFilter.GaussianBlur(radius)).resize((w, h), Image.BILINEAR), dtype=float)[..., None] / 255.0
    out = np.asarray(img, dtype=float) * (1 - al) + pre
    img.paste(Image.fromarray(np.clip(out, 0, 255).astype("uint8")), (0, 0))


def motif_hills(w, h, p, r, tags):
    top, bot, acc = map(rgb, p)
    img = vgrad(w, h, top, mix(top, acc, 0.55))
    sx, sy = r.uniform(0.2, 0.8), r.uniform(0.2, 0.4)
    if "night" in tags or "aurora" in tags:
        glow(img, lambda d, W, H: [d.ellipse([W * 0.15, H * 0.05, W * 0.85, H * 0.6], fill=rgb(p[2]) + (150,))], 18)
    else:
        glow(img, lambda d, W, H: d.ellipse([W * sx - H * 0.2, H * sy - H * 0.2, W * sx + H * 0.2, H * sy + H * 0.2], fill=acc + (255,)), 6)
    n = 5
    for i in range(n):
        t = i / (n - 1)
        col = mix(mix(top, bot, 0.35), bot, t)
        base = h * (0.42 + 0.11 * i)
        amp = h * (0.07 + 0.01 * i)
        f1, f2 = r.uniform(1.5, 3.0) / w * 6.283, r.uniform(4.0, 7.0) / w * 6.283
        p1, p2 = r.uniform(0, 6.28), r.uniform(0, 6.28)
        pts = [(x, base + amp * (math.sin(x * f1 + p1) + 0.45 * math.sin(x * f2 + p2))) for x in range(0, w + 8, 8)]
        ImageDraw.Draw(img).polygon(pts + [(w, h), (0, h)], fill=tuple(int(c) for c in col))
        if i < n - 1:  # fog between the ridges
            a = np.exp(-(((np.arange(h) - (base + amp * 1.4)) / (h * 0.07)) ** 2))[:, None, None] * 0.38
            arr = np.asarray(img, dtype=float)
            arr = arr * (1 - a) + np.array(acc, dtype=float)[None, None, :] * a
            img = Image.fromarray(arr.astype("uint8"))
    return img


def motif_waves(w, h, p, r, tags):
    top, bot, acc = map(rgb, p)
    hor = 0.42
    img = vgrad(w, h, top, mix(top, acc, 0.6))
    glow(img, lambda d, W, H: d.ellipse([W * 0.35, H * (hor - 0.12), W * 0.65, H * (hor + 0.03)], fill=acc + (170,)), 10)
    n = 8
    for i in range(n):
        t = i / (n - 1)
        col = mix(mix(top, bot, 0.3), bot, t)
        base = h * (hor + 0.55 * (i / n) ** 1.2 * (1 - hor) / 0.58 * 0.58)
        amp = h * (0.004 + 0.006 * i)
        f = r.uniform(0.8, 1.6) / w * 6.283 * (1 + 0.1 * i)
        ph = r.uniform(0, 6.28)
        pts = [(x, base + amp * math.sin(x * f + ph)) for x in range(0, w + 8, 8)]
        ImageDraw.Draw(img).polygon(pts + [(w, h), (0, h)], fill=tuple(int(c) for c in col))
    return img


def motif_blobs(w, h, p, r, tags):
    top, bot, acc = map(rgb, p)
    img = vgrad(w, h, top, mix(top, bot, 0.35))
    colors = [bot, acc, mix(bot, acc, 0.5), mix(top, acc, 0.4)]

    def layer(d, W, H):
        for _ in range(8):
            rad = r.uniform(0.12, 0.32) * W
            cx, cy = r.uniform(0, W), r.uniform(0, H)
            d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=tuple(int(c) for c in r.choice(colors)) + (205,))
    glow(img, layer, 14)
    return img


def motif_stars(w, h, p, r, tags):
    top, bot, acc = map(rgb, p)
    img = vgrad(w, h, top, bot)
    glow(img, lambda d, W, H: [d.ellipse([W * x - W * 0.2, H * y - H * 0.3, W * x + W * 0.2, H * y + H * 0.3], fill=acc + (55,)) for x, y in ((r.random(), r.random()), (r.random(), r.random()))], 20)
    d = ImageDraw.Draw(img)
    for _ in range(int(w * h / 3000)):
        x, y, b = r.randrange(w), r.randrange(h), r.random()
        c = int(120 + 135 * b)
        if b > 0.985:
            d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(255, 255, 255))
        else:
            d.point((x, y), fill=(c, c, min(255, c + 20)))

    def sphere(cx, cy, rad, col):
        ys, xs = np.mgrid[0:h, 0:w]
        dist = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
        mask = dist <= rad
        lx, ly = cx - rad * 0.4, cy - rad * 0.4
        shade = np.clip(1 - np.sqrt((xs - lx) ** 2 + (ys - ly) ** 2) / (rad * 1.7), 0.12, 1)[..., None]
        arr = np.asarray(img, dtype=float)
        arr[mask] = (np.array(col, dtype=float)[None, None, :] * shade)[mask]
        return Image.fromarray(arr.astype("uint8"))

    if "deep-field" in tags:
        pass
    elif "moon" in tags:
        img = sphere(w * 0.5, h * 1.25, h * 0.6, (225, 225, 225))
    elif "binary" in tags:
        img = sphere(w * 0.32, h * 0.38, h * 0.12, acc)
        img = sphere(w * 0.62, h * 0.52, h * 0.07, mix(acc, (255, 255, 255), 0.4))
    else:
        cx, cy, rad = w * r.uniform(0.55, 0.7), h * r.uniform(0.4, 0.55), h * (0.2 if "rings" in tags else 0.12)
        if "rings" in tags:
            d = ImageDraw.Draw(img)
            box = [cx - rad * 2.1, cy - rad * 0.45, cx + rad * 2.1, cy + rad * 0.45]
            d.ellipse(box, outline=mix(acc, (255, 255, 255), 0.3) and tuple(int(c) for c in mix(acc, (255, 255, 255), 0.3)), width=int(rad * 0.12))
            img = sphere(cx, cy, rad, acc)
            d = ImageDraw.Draw(img)
            d.arc(box, 0, 180, fill=tuple(int(c) for c in mix(acc, (255, 255, 255), 0.3)), width=int(rad * 0.12))
        else:
            img = sphere(cx, cy, rad, acc)
    return img


def motif_city(w, h, p, r, tags):
    warm, dark, light = map(rgb, p)
    img = vgrad(w, h, mix(dark, warm, 0.25), warm)
    d = ImageDraw.Draw(img)
    rows = [(0.55, 0.30, 0.55, 0.0), (0.75, 0.40, 0.8, 0.25), (1.0, 0.55, 1.0, 0.45)]
    for ri, (ground, hmax, shade, win_p) in enumerate(rows):
        col = tuple(int(c) for c in mix(warm, dark, shade))
        x = -r.randrange(40)
        while x < w:
            bw = int(r.uniform(0.03, 0.08) * w)
            bh = int(r.uniform(0.25, 1.0) * hmax * h)
            top_y = int(h * ground) - bh
            d.rectangle([x, top_y, x + bw, h], fill=col)
            if win_p:
                step = max(10, w // 120)
                for wy in range(top_y + step, int(h * ground) - step, step * 2):
                    for wx in range(x + step // 2, x + bw - step, step * 2):
                        if r.random() < win_p:
                            d.rectangle([wx, wy, wx + step // 2, wy + step // 2 + 2], fill=light)
            x += bw + r.randrange(0, max(1, w // 150))
    return img


def motif_grid(w, h, p, r, tags):
    top, bot, acc = map(rgb, p)
    img = vgrad(w, h, top, bot)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    step = w // 32
    for x in range(0, w, step):
        od.line([(x, 0), (x, h)], fill=acc + (30,), width=1)
    for y in range(0, h, step):
        od.line([(0, y), (w, y)], fill=acc + (30,), width=1)
    img.paste(overlay, (0, 0), overlay)

    def traces(d, W, H, k=1.0):
        s = W / 32
        for _ in range(26):
            x, y = r.randrange(32) * s, r.randrange(18) * s
            pts = [(x, y)]
            for _ in range(r.randrange(4, 10)):
                dx, dy = r.choice([(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1)])
                n = r.randrange(1, 5)
                x, y = x + dx * s * n, y + dy * s * n
                pts.append((x, y))
            d.line(pts, fill=acc + (255,), width=max(1, int(3 * k)))
            d.ellipse([x - 5 * k, y - 5 * k, x + 5 * k, y + 5 * k], outline=acc + (255,), width=max(1, int(2 * k)))
    state = r.getstate()
    glow(img, lambda d, W, H: traces(d, W, H, 0.5), 3)
    r.setstate(state)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    traces(ImageDraw.Draw(overlay), w, h, 1.0)
    img.paste(overlay, (0, 0), overlay)
    return img


def motif_minimal(w, h, p, r, tags):
    bg, band, acc = map(rgb, p)
    img = Image.new("RGB", (w, h), tuple(int(c) for c in bg))
    d = ImageDraw.Draw(img)
    if "horizon" in tags:
        d.rectangle([0, int(h * 0.62), w, h], fill=tuple(int(c) for c in band))
        d.rectangle([0, int(h * 0.62) - 3, w, int(h * 0.62) + 3], fill=acc)
    elif "arc" in tags:
        d.arc([w * 0.25, h * 0.15, w * 0.75, h * 1.15], 200, 340, fill=acc, width=int(h * 0.04))
    else:
        rad = h * 0.18
        d.ellipse([w / 2 - rad, h / 2 - rad, w / 2 + rad, h / 2 + rad], fill=acc)
    return img


def motif_critter(w, h, p, r, tags):
    top, bot, acc = map(rgb, p)
    img = vgrad(w, h, top, bot)
    glow(img, lambda d, W, H: d.ellipse([W * 0.25, H * 0.05, W * 0.75, H * 0.95], fill=mix(top, bot, 0.5) and tuple(int(c) for c in mix(bot, acc, 0.25)) + (120,)), 12)
    d = ImageDraw.Draw(img)
    cx, cy, s = w / 2, h * 0.48, h * 0.30

    def poly(pts, col):
        d.polygon([(cx + x * s, cy + y * s) for x, y in pts], fill=tuple(int(c) for c in col))

    def mirror(pts):
        return [(-x, y) for x, y in pts]
    dark = mix(top, (0, 0, 0), 0.35)
    owl = "owl" in tags
    face = acc if not owl else mix(acc, bot, 0.25)
    ear = [(-1, -0.2), (-0.95, -1.2), (-0.3, -0.65)]
    poly(ear, mix(face, dark, 0.35))
    poly(mirror(ear), mix(face, dark, 0.35))
    poly([(-1, -0.2), (-0.3, -0.65), (0.3, -0.65), (1, -0.2), (0, 1.05)], face)
    cheek = [(-1, -0.2), (-0.12, 0.2), (0, 1.05)]
    poly(cheek, mix(face, (255, 255, 255), 0.65))
    poly(mirror(cheek), mix(face, (255, 255, 255), 0.55))
    if owl:
        for sx in (-1, 1):
            d.ellipse([cx + sx * 0.42 * s - 0.24 * s, cy - 0.12 * s - 0.24 * s, cx + sx * 0.42 * s + 0.24 * s, cy - 0.12 * s + 0.24 * s], fill=(250, 250, 245))
            d.ellipse([cx + sx * 0.42 * s - 0.1 * s, cy - 0.12 * s - 0.1 * s, cx + sx * 0.42 * s + 0.1 * s, cy - 0.12 * s + 0.1 * s], fill=tuple(int(c) for c in dark))
        poly([(-0.12, 0.3), (0.12, 0.3), (0, 0.62)], mix(acc, (240, 160, 40), 0.7))
    else:
        eye = [(-0.52, -0.22), (-0.22, -0.08), (-0.5, -0.02)]
        poly(eye, dark)
        poly(mirror(eye), dark)
        poly([(-0.14, 0.88), (0.14, 0.88), (0, 1.05)], dark)
    return img


def motif_avatar(size, n, name):
    hue = (n * 47 % 360) / 360
    a = tuple(c * 255 for c in colorsys.hsv_to_rgb(hue, 0.55, 0.85))
    b = tuple(c * 255 for c in colorsys.hsv_to_rgb((hue + 0.12) % 1, 0.7, 0.55))
    t = (np.linspace(0, 1, size)[None, :] + np.linspace(0, 1, size)[:, None]) / 2
    arr = np.array(a)[None, None, :] * (1 - t[..., None]) + np.array(b)[None, None, :] * t[..., None]
    img = Image.fromarray(arr.astype("uint8"))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=int(size * 0.5))
    except TypeError:  # very old Pillow: bitmap font, still readable
        font = ImageFont.load_default()
    d.text((size / 2, size / 2), name[0].upper(), fill=(255, 255, 255), font=font, anchor="mm")
    return img


MOTIFS = {"hills": motif_hills, "waves": motif_waves, "blobs": motif_blobs, "stars": motif_stars, "city": motif_city,
          "grid": motif_grid, "minimal": motif_minimal, "critter": motif_critter}


def blurhash_encode(img, cx=4, cy=3):
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#$%*+,-.:;=?@[]^_{|}~"

    def b83(v, n):
        return "".join(chars[(v // 83 ** (n - i)) % 83] for i in range(1, n + 1))

    def lin(v):
        v = v / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    def srgb(v):
        v = max(0, min(1, v))
        return int(v * 12.92 * 255 + 0.5) if v <= 0.0031308 else int((1.055 * v ** (1 / 2.4) - 0.055) * 255 + 0.5)

    def spow(v, e):
        return math.copysign(abs(v) ** e, v)
    small = img.convert("RGB").resize((32, 32), Image.LANCZOS)
    a = np.vectorize(lin)(np.asarray(small, dtype=float))
    hh, ww = a.shape[:2]
    xs, ys = np.arange(ww), np.arange(hh)
    factors = []
    for j in range(cy):
        for i in range(cx):
            norm = 1 if (i == 0 and j == 0) else 2
            basis = np.outer(np.cos(math.pi * j * ys / hh), np.cos(math.pi * i * xs / ww))
            factors.append(tuple((norm / (ww * hh)) * float((basis[..., None] * a).sum(axis=(0, 1))[c]) for c in range(3)))
    dc, ac = factors[0], factors[1:]
    out = b83((cx - 1) + (cy - 1) * 9, 1)
    if ac:
        mx = max(abs(c) for f in ac for c in f)
        q = int(max(0, min(82, math.floor(mx * 166 - 0.5))))
        maxval = (q + 1) / 166
    else:
        q, maxval = 0, 1
    out += b83(q, 1)
    out += b83((srgb(dc[0]) << 16) + (srgb(dc[1]) << 8) + srgb(dc[2]), 4)
    for f in ac:
        qs = [int(max(0, min(18, math.floor(spow(c / maxval, 0.5) * 9 + 9.5)))) for c in f]
        out += b83(qs[0] * 361 + qs[1] * 19 + qs[2], 2)
    return out


def phash64(img) -> str:
    g = np.asarray(img.convert("L").resize((9, 8), Image.LANCZOS), dtype=int)
    return "".join("1" if g[y, x] > g[y, x + 1] else "0" for y in range(8) for x in range(8))


def palette5(img):
    q = img.convert("RGB").resize((96, 54), Image.BILINEAR).quantize(colors=5)
    pal = q.getpalette()[:15]
    counts = sorted(q.getcolors(), reverse=True)
    return [hexcolor(pal[i * 3:i * 3 + 3]) for _, i in counts]


# ---------------------------------------------------------------------------------------------------------------------
class Build:
    def __init__(self, ds, args):
        self.ds, self.args = ds, args
        self.anchor = datetime.fromisoformat(ds["anchor"].replace("Z", "+00:00"))
        self.lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
        self.new_lock = {}
        self.problems = []
        self.files = {}  # relative path -> bytes (text outputs)
        self.bundles = {l: json.loads((ROOT / f"contracts/i18n/messages.{l}.json").read_text(encoding="utf-8")) for l in ("en", "de", "es")}

    # ---- images ------------------------------------------------------------------------------------------------
    def image_files(self, stem, kind, params, variants, original_ext, original_ct, gen):
        """Return the derived facts of one picture. `gen` renders it (only called when files must be (re)made)."""
        params_hash = hashlib.sha256(jdump({"v": GEN_VERSION, **params}).encode()).hexdigest()[:16]
        lock = self.lock.get(stem)
        orig_path = S3 / "originals" / f"{stem}/original.{original_ext}"
        files = {"orig": orig_path}
        for k, (w, h, ext) in variants.items():
            files[k] = S3 / "public" / f"{stem}/{k.lower()}.{ext}"
        fresh = lock and lock["params"] == params_hash and all(p.exists() for p in files.values())
        if not fresh and self.args.check:
            self.problems.append(f"image {stem} is missing or stale (run: make seed-build)")
            return {"params": params_hash, "sha256": "0" * 64, "size": 1, "phash": "0" * 64, "blurhash": "L00000fQfQfQfQfQfQfQfQfQfQfQ", "palette": ["#000000"], "variants": {k: 1 for k in variants}}
        if not fresh or self.args.regen:
            drawing()
            img = gen()
            lock = {"params": params_hash, "phash": phash64(img), "blurhash": blurhash_encode(img), "palette": palette5(img)}
            for p in files.values():
                p.parent.mkdir(parents=True, exist_ok=True)
            if original_ext == "jpg":
                img.convert("RGB").save(orig_path, "JPEG", quality=85, optimize=True)
            elif original_ext == "png":
                img.convert("RGB").save(orig_path, "PNG", optimize=True)
            else:
                img.convert("RGB").save(orig_path, "WEBP", quality=88, method=4)
            for k, (w, h, ext) in variants.items():
                (img if img.size == (w, h) else img.resize((w, h), Image.LANCZOS)).save(files[k], "WEBP", quality=80, method=4)
            print(f"  image {stem}")
        ob = orig_path.read_bytes()
        self.new_lock[stem] = {"params": params_hash, "phash": lock["phash"], "blurhash": lock["blurhash"], "palette": lock["palette"]}
        return {"params": params_hash, "sha256": hashlib.sha256(ob).hexdigest(), "size": len(ob), "phash": lock["phash"],
                "blurhash": lock["blurhash"], "palette": lock["palette"], "variants": {k: files[k].stat().st_size for k in variants}}

    # ---- model -------------------------------------------------------------------------------------------------
    def model(self):
        ds, A = self.ds, self.anchor
        users, assets, wallpapers = {}, [], {}
        notes = []
        for name, u in ds["users"].items():
            uid = uuid_of(u["n"])
            created = A - timedelta(days=u["joined"], minutes=jitter("u" + name, 600))
            users[name] = {"key": name, "id": uid, "username": name, "email": f"{name}@wallpaperhub.local", "display_name": u["name"],
                           "bio": u.get("bio"), "locale": u["locale"], "status": u.get("status", "ACTIVE"), "roles": u["roles"],
                           "created": created, "updated": created, "version": 0, "avatar": None, "banner": None,
                           "deleted": (A - timedelta(days=u["deleted"])) if u.get("deleted") else None,
                           "in_keycloak": u["n"] > 3 and not u.get("deleted"), "n": u["n"], "spec": u}

        def mk_asset(key, owner, purpose, status, created, size, motif, palette, tags, ext, ct, variants, reject=None, original_dims=None, avatar_of=None):
            aid = "ast_" + ulid(ms(created), "asset:" + key)
            y, m = f"{created.year:04d}", f"{created.month:02d}"
            stem = f"{purpose.lower()}/{y}/{m}/{aid}"
            ow, oh = original_dims or size
            if purpose == "AVATAR":
                gen = lambda: motif_avatar(512, avatar_of["n"], avatar_of["name"])
            else:
                gen = lambda: MOTIFS[motif](ow, oh, palette, random.Random(h_int("img:" + key)), tags)
            vspec = {k: (w, h, "webp") for k, (w, h) in variants.items()} if status == "READY" else {}
            facts = self.image_files(stem, purpose, {"key": key, "motif": motif, "p": palette, "size": [ow, oh], "tags": tags, "ext": ext}, vspec, ext, ct, gen)
            a = {"key": key, "id": aid, "owner": owner, "purpose": purpose, "status": status, "created": created,
                 "updated": created + timedelta(minutes=1) if status != "PROCESSING" else created, "version": 0 if status == "PROCESSING" else 1,
                 "original_key": f"{stem}/original.{ext}", "content_type": ct, "size_bytes": facts["size"], "sha256": facts["sha256"] if status != "PROCESSING" else None,
                 "width": ow if status == "READY" else None, "height": oh if status == "READY" else None,
                 "phash": facts["phash"] if status == "READY" else None, "blurhash": facts["blurhash"] if status == "READY" else None,
                 "palette": facts["palette"] if status == "READY" else [], "reject_reason": reject, "variants": []}
            for k, (w, h) in variants.items():
                if status == "READY":
                    a["variants"].append({"kind": k, "key": f"{stem}/{k.lower()}.webp", "width": w, "height": h, "format": "webp", "size_bytes": facts["variants"][k]})
            assets.append(a)
            return a

        # avatars and banners
        for name, u in users.items():
            spec = u["spec"]
            if spec.get("avatar"):
                a = mk_asset(f"avatar:{name}", u["id"], "AVATAR", "READY", u["created"] + timedelta(hours=1), (512, 512), None, [], [], "png", "image/png",
                             {"AVATAR_512": (512, 512), "AVATAR_128": (128, 128), "AVATAR_48": (48, 48)}, avatar_of={"n": spec["n"], "name": spec["name"]})
                u["avatar"] = a
                u["version"] += 1
                u["updated"] = a["updated"] + timedelta(minutes=1)
            if spec.get("banner"):
                hue = (spec["n"] * 61 % 360) / 360
                pal = [hexcolor(c * 255 for c in colorsys.hsv_to_rgb(hue, 0.3, 0.9)), hexcolor(c * 255 for c in colorsys.hsv_to_rgb(hue, 0.6, 0.3)), hexcolor(c * 255 for c in colorsys.hsv_to_rgb((hue + 0.08) % 1, 0.4, 1))]
                a = mk_asset(f"banner:{name}", u["id"], "BANNER", "READY", u["created"] + timedelta(hours=2), (1500, 500), "hills", pal, [], "jpg", "image/jpeg",
                             {"BANNER_1500": (1500, 500), "BANNER_750": (750, 250)})
                u["banner"] = a
                u["version"] += 1
                u["updated"] = max(u["updated"], a["updated"] + timedelta(minutes=1))
            if u["deleted"]:
                u["updated"], u["version"] = u["deleted"], u["version"] + 1

        # wallpapers
        mod_id = users["mod"]["id"]
        for key, w in ds["wallpapers"].items():
            author = users[w["a"]]
            status = w.get("status", "PUBLISHED")
            pending = status == "PENDING_MEDIA"
            rejected_by_media = "asset_reject" in w
            if w["ago"] == 0:
                created = A - timedelta(minutes=5 + 20 * (int(key[1:]) % 3))
            else:
                created = A - timedelta(days=w["ago"], minutes=jitter(key, 600))
            sw, sh = w["size"]
            vmap = {"FULL": (sw, sh), "PREVIEW": (1280, round(sh * 1280 / sw)), "THUMBNAIL": (320, round(sh * 320 / sw))}
            ext = w.get("orig", "jpg")
            ct = {"jpg": "image/jpeg", "webp": "image/webp"}[ext]
            astatus = "PROCESSING" if pending else ("REJECTED" if rejected_by_media else "READY")
            a = mk_asset(f"wallpaper:{key}", author["id"], "WALLPAPER", astatus, created - timedelta(minutes=2), (sw, sh), w["m"], w["p"], w["tags"], ext, ct,
                         vmap, reject=w.get("asset_reject"), original_dims=(sw, sh))
            published = a["updated"] + timedelta(minutes=1)
            moderation = None
            version = 0 if pending else 1
            updated = created if pending else published
            if "mod" in w:
                decided = A - timedelta(days=w["mod"]["ago"], minutes=jitter("m" + key, 300))
                moderation = {"decision": w["mod"]["d"], "reason": w["mod"].get("reason"), "moderatorId": mod_id, "decidedAt": decided}
                version, updated = 2, decided
            pop = w["pop"]
            hv = h_int("v" + key)
            views = 0 if (pending or rejected_by_media) else pop * pop * 120 + hv % 300
            dls = 0 if views == 0 else int(views * (0.08 + (hv % 10) / 100))
            wallpapers[key] = {"key": key, "id": "wp_" + ulid(ms(created), "wp:" + key), "author": author, "title": w["t"], "description": w["d"], "tags": w["tags"],
                               "category": w["c"], "status": status, "asset": a, "created": created, "updated": updated, "version": version,
                               "moderation": moderation, "views": views, "downloads": dls, "published": published, "pop": pop, "favorites": 0}
        # stuck asset
        for key, e in ds["extra_assets"].items():
            owner = users[e["owner"]]
            created = A - timedelta(minutes=e["minutes_ago"])
            mk_asset(f"extra:{key}", owner["id"], e["purpose"], e["status"], created, (1920, 1080), "hills", ["#b8c4d9", "#41506b", "#f0e6d2"], [], "jpg", "image/jpeg",
                     {"FULL": (1920, 1080), "PREVIEW": (1280, 720), "THUMBNAIL": (320, 180)})

        # favorites
        favorites = []
        published = [w for w in wallpapers.values() if w["status"] == "PUBLISHED"]
        for uname, k in ds["fav_count"].items():
            u = users[uname]
            cands = [w for w in published if w["author"]["key"] != uname]
            scored = sorted(cands, key=lambda w: -((h_int(f"fav:{uname}:{w['key']}") / 2 ** 64) ** (1 / w["pop"] ** 2)))[:k]
            for w in sorted(scored, key=lambda w: w["key"]):
                at = min(max(w["published"], u["created"]) + timedelta(hours=1 + h_int(f"favat:{uname}:{w['key']}") % 72), A - timedelta(hours=1))
                favorites.append({"user": u, "wallpaper": w, "created": at, "oid": f"{int(at.timestamp()):08x}" + hashlib.sha256(f"fav:{u['id']}:{w['id']}".encode()).hexdigest()[:16]})
                w["favorites"] += 1

        # collections
        collections = []
        for i, (key, c) in enumerate(ds["collections"].items()):
            owner = users[c["owner"]]
            created = A - timedelta(days=10 + i, minutes=jitter(key, 600))
            collections.append({"key": key, "id": "col_" + ulid(ms(created), "col:" + key), "owner": owner, "title": c["title"], "description": c["d"],
                                "items": [wallpapers[x] for x in c["items"]], "created": created, "updated": created + timedelta(days=1), "version": 1})

        # notifications
        b = self.bundles

        def fmt(lang, key, **kw):
            s = b[lang][key]
            for k, v in kw.items():
                s = s.replace("{" + k + "}", v)
            return s

        def note(user, typ, title, body, data, created):
            read = (A - created) > timedelta(days=4)
            notes.append({"user": user, "id": "ntf_" + ulid(ms(created), f"ntf:{user['key']}:{typ}:{len(notes)}:{created.isoformat()}"), "type": typ, "title": title, "body": body,
                          "data": data, "read": read, "readAt": (created + timedelta(hours=2 + h_int('r' + user['key'] + typ) % 30)) if read else None, "created": created})
        for u in users.values():
            if u["deleted"]:
                continue
            L = u["locale"]
            note(u, "WELCOME", b[L]["notification.welcome.inbox-title"], b[L]["notification.welcome.inbox-body"], {}, u["created"] + timedelta(minutes=1))
        for w in wallpapers.values():
            u, L = w["author"], w["author"]["locale"]
            if w["status"] in ("PUBLISHED", "REJECTED", "REMOVED") and w["asset"]["status"] == "READY":
                note(u, "WALLPAPER_PUBLISHED", b[L]["notification.wallpaper-published.inbox-title"], fmt(L, "notification.wallpaper-published.inbox-body", title=w["title"]),
                     {"wallpaperId": w["id"], "assetId": w["asset"]["id"]}, w["published"])
            if w["moderation"]:
                m = w["moderation"]
                d = m["decision"]
                body = fmt(L, f"notification.wallpaper-moderated.{d}.inbox-body", title=w["title"])
                if m["reason"]:
                    body += " " + fmt(L, "notification.wallpaper-moderated.reason-line", reason=m["reason"])
                note(u, "WALLPAPER_MODERATED", b[L][f"notification.wallpaper-moderated.{d}.inbox-title"], body, {"wallpaperId": w["id"], "decision": d}, m["decidedAt"])
            if w["asset"]["status"] == "REJECTED":
                reason = b[L][REJECT_LABEL_KEY + w["asset"]["reject_reason"]]
                note(u, "ASSET_REJECTED", b[L]["notification.asset-rejected.inbox-title"], fmt(L, "notification.asset-rejected.inbox-body", reason=reason),
                     {"assetId": w["asset"]["id"]}, w["asset"]["updated"])
        notes.sort(key=lambda n: (n["created"], n["id"]))
        return users, assets, wallpapers, favorites, collections, notes

    # ---- emitters ----------------------------------------------------------------------------------------------
    def emit(self):
        ds = self.ds
        users, assets, wallpapers, favorites, collections, notes = self.model()
        self.parts = (users, assets, wallpapers, favorites, collections, notes)
        base = Raw('U("%s")')
        F = self.files

        def U(key):
            return Raw('U(%s)' % json.dumps(key))

        # keycloak
        kc = []
        for u in users.values():
            if not u["in_keycloak"]:
                continue
            first, _, last = u["spec"]["name"].partition(" ")
            kc.append({"id": u["id"], "username": u["username"], "email": u["email"], "emailVerified": True, "enabled": u["status"] != "SUSPENDED",
                       "firstName": first, "lastName": last, "attributes": {"locale": [u["locale"]]},
                       "realmRoles": ["default-roles-wallpaperhub"] + u["roles"], "credentials": [{"type": "password", "value": "password", "temporary": False}]})
        F["out/keycloak-users.json"] = json.dumps({"ifResourceExists": "SKIP", "users": kc}, indent=2, ensure_ascii=False) + "\n"

        # account.sql
        rows = []
        for u in users.values():
            rows.append("(" + ", ".join(sq(x) for x in (u["id"], u["username"], u["email"], u["display_name"], u["bio"], u["locale"], u["avatar"]["id"] if u["avatar"] else None,
                                                         u["banner"]["id"] if u["banner"] else None, u["status"], u["deleted"], u["created"], u["updated"], u["version"])) + ")")
        audit = []
        for u in users.values():
            audit.append((u["id"], "USER_REGISTERED", "user", u["id"], None, jdump({"username": u["username"], "email": u["email"]}), u["created"]))
            if u["avatar"]:
                audit.append((u["id"], "PROFILE_UPDATED", "user", u["id"], jdump({"avatarAssetId": None}), jdump({"avatarAssetId": u["avatar"]["id"]}), u["avatar"]["updated"] + timedelta(minutes=1)))
            if u["deleted"]:
                audit.append((u["id"], "USER_DELETED", "user", u["id"], jdump({"status": "ACTIVE"}), jdump({"deletedAt": iso(u["deleted"])}), u["deleted"]))
        arows = ",\n".join("  (" + ", ".join(sq(x) for x in r) + ")" for r in audit)
        F["out/account.sql"] = f"""-- GENERATED by seed/build.py from seed/dataset.yaml: do not edit. Seed data of account-service.
-- Insert-if-missing: re-running changes nothing that already exists. Credentials live in Keycloak (keycloak-users.json).
INSERT INTO users (id, username, email, display_name, bio, locale, avatar_asset_id, banner_asset_id, status, deleted_at, created_at, updated_at, version) VALUES
{",\n".join("  " + r for r in rows)}
ON CONFLICT DO NOTHING;

INSERT INTO audit_log (actor_id, action, entity_type, entity_id, before, after, created_at)
SELECT v.actor_id::uuid, v.action, v.entity_type, v.entity_id, v.before::jsonb, v.after::jsonb, v.created_at::timestamptz
FROM (VALUES
{arows}
) AS v(actor_id, action, entity_type, entity_id, before, after, created_at)
WHERE NOT EXISTS (SELECT 1 FROM audit_log a WHERE a.entity_type = v.entity_type AND a.entity_id = v.entity_id
                  AND a.action = v.action AND a.created_at = v.created_at::timestamptz);
"""
        # media.sql
        arows, vrows = [], []
        for a in assets:
            arows.append("  (" + ", ".join(sq(x) for x in (a["id"], a["owner"], a["purpose"], a["status"], a["original_key"], a["content_type"], a["size_bytes"], a["width"], a["height"], a["sha256"]))
                         + ", " + ("B'" + a["phash"] + "'" if a["phash"] else "NULL") + ", " + ", ".join(sq(x) for x in (a["blurhash"],)) + ", " + sq(jdump(a["palette"])) + "::jsonb, "
                         + ", ".join(sq(x) for x in (a["reject_reason"], a["created"], a["updated"], a["version"])) + ")")
            for v in a["variants"]:
                vrows.append("  (" + ", ".join(sq(x) for x in (a["id"], v["kind"], v["key"], v["width"], v["height"], v["format"], v["size_bytes"])) + ")")
        F["out/media.sql"] = f"""-- GENERATED by seed/build.py from seed/dataset.yaml: do not edit. Seed data of media-service.
-- The files behind original_key and the variant keys are uploaded by the s3 seed job (seed/s3/).
INSERT INTO media_asset (id, owner_id, purpose, status, original_key, content_type, size_bytes, width, height, sha256, phash, blurhash, palette, reject_reason, created_at, updated_at, version) VALUES
{",\n".join(arows)}
ON CONFLICT DO NOTHING;

INSERT INTO media_variant (asset_id, kind, key, width, height, format, size_bytes) VALUES
{",\n".join(vrows)}
ON CONFLICT DO NOTHING;
"""
        # catalog.js
        wdocs, es = [], []
        for w in sorted(wallpapers.values(), key=lambda w: w["created"]):
            a, u = w["asset"], w["author"]
            ready = a["status"] == "READY"
            doc = {"_id": w["id"], "title": w["title"], "description": w["description"], "tags": w["tags"], "category": w["category"], "status": w["status"], "assetId": a["id"],
                   "variants": [{"kind": v["kind"], "url": U(v["key"]), "width": I(v["width"]), "height": I(v["height"])} for v in a["variants"]],
                   "dimensions": {"width": I(a["width"]), "height": I(a["height"])} if ready else None, "palette": a["palette"], "blurhash": a["blurhash"],
                   "author": {"id": u["id"], "username": u["username"], "displayName": u["display_name"],
                              "avatarUrl": U(next(v["key"] for v in u["avatar"]["variants"] if v["kind"] == "AVATAR_128")) if u["avatar"] else None},
                   "favoriteCount": I(w["favorites"]), "viewCount": I(w["views"]), "downloadCount": I(w["downloads"]),
                   "moderation": ({"decision": w["moderation"]["decision"], "reason": w["moderation"]["reason"], "moderatorId": w["moderation"]["moderatorId"], "decidedAt": w["moderation"]["decidedAt"]}
                                  if w["moderation"] else None),
                   "createdAt": w["created"], "updatedAt": w["updated"], "version": I(w["version"])}
            wdocs.append(doc)
            if w["status"] == "PUBLISHED":
                es.append(json.dumps({"create": {"_index": "wallpapers", "_id": w["id"]}}) + "\n" + jdump(
                    {"title": w["title"], "description": w["description"], "tags": w["tags"], "category": w["category"], "status": "PUBLISHED", "authorId": u["id"],
                     "dimensions": {"width": a["width"], "height": a["height"]}, "favoriteCount": w["favorites"], "createdAt": iso(w["created"]), "updatedAt": iso(w["updated"])}))
        fdocs = [{"_id": Raw(f'ObjectId("{f["oid"]}")'), "userId": f["user"]["id"], "wallpaperId": f["wallpaper"]["id"], "createdAt": f["created"]} for f in favorites]
        cdocs = [{"_id": c["id"], "ownerId": c["owner"]["id"], "title": c["title"], "description": c["description"], "wallpaperIds": [x["id"] for x in c["items"]],
                  "createdAt": c["created"], "updatedAt": c["updated"], "version": I(c["version"])} for c in collections]
        adocs = []
        for w in wallpapers.values():
            if w["moderation"]:
                m = w["moderation"]
                adocs.append({"actorId": m["moderatorId"], "action": "WALLPAPER_" + m["decision"], "entityType": "wallpaper", "entityId": w["id"],
                              "before": {"status": "PUBLISHED"}, "after": {"status": w["status"] if m["decision"] != "APPROVED" else "PUBLISHED", "reason": m["reason"]},
                              "traceId": None, "createdAt": m["decidedAt"]})
        F["out/catalog.js"] = f"""// GENERATED by seed/build.py from seed/dataset.yaml: do not edit. Seed data of catalog-service for mongosh.
// Insert-if-missing ($setOnInsert): re-running changes nothing that already exists. The $jsonSchema validators stay active,
// so a seed document the schema rejects fails loudly. Image URLs use S3_PUBLIC_BASE_URL (default: the compose S3 port).
const cdb = db.getSiblingDB("catalog");
const BASE = (process.env.S3_PUBLIC_BASE_URL || "http://localhost:9000/wallpaperhub-media").replace(/\\/$/, "");
const U = (key) => BASE + "/" + key;

const wallpapers = {js(wdocs)};
const favorites = {js(fdocs)};
const collections = {js(cdocs)};
const audit = {js(adocs)};

function upsertAll(coll, docs, filterOf) {{
  const res = cdb.getCollection(coll).bulkWrite(docs.map((d) => {{
    const {{ _id, ...rest }} = d;
    const filter = filterOf(d);
    return {{ updateOne: {{ filter, update: {{ $setOnInsert: _id === undefined ? rest : Object.assign({{ _id }}, rest) }}, upsert: true }} }};
  }}), {{ ordered: true }});
  print(`catalog.${{coll}}: ${{res.upsertedCount}} inserted, ${{docs.length - res.upsertedCount}} already there`);
}}
upsertAll("wallpapers", wallpapers, (d) => ({{ _id: d._id }}));
upsertAll("favorites", favorites, (d) => ({{ userId: d.userId, wallpaperId: d.wallpaperId }}));
upsertAll("collections", collections, (d) => ({{ _id: d._id }}));
upsertAll("audit", audit, (d) => ({{ entityType: d.entityType, entityId: d.entityId, action: d.action }}));
"""
        F["out/catalog.es.ndjson"] = "\n".join(es) + "\n"

        # redis
        nl = []  # no comment lines: redis-cli would run them as commands
        for n in notes:
            f = {"id": n["id"], "userId": n["user"]["id"], "type": n["type"], "title": n["title"], "body": n["body"], "data": jdump(n["data"]), "read": 1 if n["read"] else 0,
                 "readAt": ms(n["readAt"]) if n["readAt"] else "", "createdAt": ms(n["created"])}
            nl.append("HSET " + rq("notif:" + n["id"]) + " " + " ".join(f"{k} {rq(v)}" for k, v in f.items()))
            nl.append(f"EXPIRE {rq('notif:' + n['id'])} 7776000")
            nl.append(f"ZADD {rq('inbox:' + n['user']['id'])} {ms(n['created'])} {rq(n['id'])}")
            if not n["read"]:
                nl.append(f"ZADD {rq('inbox:unread:' + n['user']['id'])} {ms(n['created'])} {rq(n['id'])}")
        for uname, p in ds["prefs"].items():
            u = users[uname]
            nl.append(f"HSET {rq('prefs:' + u['id'])} locale {p['locale']} email {p['email']} inApp {p['inApp']} digest {p['digest']} version {p['version']} updatedAt {ms(u['updated'])}")
        F["out/notification.redis"] = "\n".join(nl) + "\n"
        trending = sorted((w for w in wallpapers.values() if w["status"] == "PUBLISHED"), key=lambda w: -(w["favorites"] * 3 + w["views"] / 100 + w["downloads"] / 20))[:12]
        sl = []
        for w in trending:
            sl.append(f"ZADD zset:trending {round(w['favorites'] * 3 + w['views'] / 100 + w['downloads'] / 20, 2)} {w['id']}")
        F["out/shared.redis"] = "\n".join(sl) + "\n"

        # manifest + catalog
        def plain(v):
            if isinstance(v, datetime):
                return iso(v)
            if isinstance(v, dict):
                return {k: plain(x) for k, x in v.items() if k not in ("spec",)}
            if isinstance(v, list):
                return [plain(x) for x in v]
            return v
        man = {"anchor": ds["anchor"],
               "users": [{k: plain(u[k]) for k in ("id", "username", "email", "display_name", "locale", "status", "roles", "created", "deleted", "in_keycloak")}
                         | {"avatarAssetId": u["avatar"]["id"] if u["avatar"] else None, "bannerAssetId": u["banner"]["id"] if u["banner"] else None} for u in users.values()],
               "assets": [plain({k: a[k] for k in ("id", "owner", "purpose", "status", "original_key", "content_type", "size_bytes", "width", "height", "sha256", "phash", "blurhash", "palette", "reject_reason", "created", "variants")}) for a in assets],
               "wallpapers": [plain({"key": w["key"], "id": w["id"], "authorId": w["author"]["id"], "title": w["title"], "category": w["category"], "status": w["status"], "assetId": w["asset"]["id"],
                                     "favorites": w["favorites"], "tags": w["tags"], "moderation": w["moderation"]}) for w in wallpapers.values()],
               "collections": [{"id": c["id"], "ownerId": c["owner"]["id"], "title": c["title"], "wallpaperIds": [x["id"] for x in c["items"]]} for c in collections],
               "favorites": [{"userId": f["user"]["id"], "wallpaperId": f["wallpaper"]["id"]} for f in favorites],
               "notifications": [plain({"id": n["id"], "userId": n["user"]["id"], "type": n["type"], "read": n["read"], "createdAt": n["created"], "data": n["data"]}) for n in notes]}
        F["out/manifest.json"] = json.dumps(man, indent=1, ensure_ascii=False) + "\n"

        md = ["# Seed data catalogue\n", "Generated by `seed/build.py` from `seed/dataset.yaml`: do not edit. Every user logs in with the password `password`.\n",
              "## Users\n", "| user | id (= Keycloak sub) | role | locale | status | notes |", "|---|---|---|---|---|---|"]
        for u in users.values():
            note_ = "soft-deleted, not in Keycloak" if u["deleted"] else ("disabled in Keycloak" if u["status"] == "SUSPENDED" else ("from the realm export" if u["n"] <= 3 else ""))
            md.append(f"| {u['username']} | `{u['id']}` | {', '.join(u['roles'])} | {u['locale']} | {u['status']} | {note_} |")
        md += ["", "## Wallpapers\n", "| key | id | title | author | category | status | favorites | asset |", "|---|---|---|---|---|---|---|---|"]
        for w in wallpapers.values():
            md.append(f"| {w['key']} | `{w['id']}` | {w['title']} | {w['author']['username']} | {w['category']} | {w['status']}{' (asset ' + w['asset']['status'] + ')' if w['asset']['status'] not in ('READY',) else ''} | {w['favorites']} | `{w['asset']['id']}` |")
        md += ["", "## Collections\n", "| id | owner | title | wallpapers |", "|---|---|---|---|"]
        for c in collections:
            md.append(f"| `{c['id']}` | {c['owner']['username']} | {c['title']} | {len(c['items'])} |")
        md += ["", f"Totals: {len(users)} users, {len(assets)} assets, {len(wallpapers)} wallpapers, {len(favorites)} favorites, {len(collections)} collections, {len(notes)} notifications.", ""]
        F["CATALOG.md"] = "\n".join(md)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--regen", action="store_true", help="regenerate every image")
    args = ap.parse_args()
    ds = yaml.safe_load((SEED / "dataset.yaml").read_text(encoding="utf-8"))
    b = Build(ds, args)
    b.emit()
    lock_text = json.dumps(dict(sorted(b.new_lock.items())), indent=1) + "\n"
    if args.check:
        bad = list(b.problems)
        for rel, text in b.files.items():
            p = SEED / rel
            if not p.exists() or p.read_text(encoding="utf-8") != text:
                bad.append(f"seed/{rel} is out of date")
        if not b.problems and (not LOCK.exists() or LOCK.read_text() != lock_text):
            bad.append("seed/images.lock.json is out of date")
        stray = {str(p.relative_to(S3)) for p in S3.rglob("*") if p.is_file()} if S3.exists() else set()
        if bad:
            print("seed is stale:\n  " + "\n  ".join(bad) + "\nrun: make seed-build", file=sys.stderr)
            return 1
        print(f"seed up to date ({len(b.files)} generated files, {len(stray)} image files)")
        return 0
    for rel, text in b.files.items():
        p = SEED / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    LOCK.write_text(lock_text)
    # drop image files nobody references any more
    keep = set()
    for stem in b.new_lock:
        for p in S3.rglob(f"{stem.split('/')[-1]}/*"):
            keep.add(p)
    for p in list(S3.rglob("*")):
        if p.is_file() and p not in keep:
            p.unlink()
            print("  removed unused", p.relative_to(SEED))
    print(f"wrote {len(b.files)} files to seed/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
