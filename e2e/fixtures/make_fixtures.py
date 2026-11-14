#!/usr/bin/env python3
"""Regenerates the e2e image fixtures with the standard library only (no Pillow):  python3 make_fixtures.py
  python3 make_fixtures.py unique OUT.png   a fresh random 1920x1080 picture (used per run, see unique_png)
  wallpaper-1920x1080.png   valid wallpaper (>= 1920x1080, README 5.2)
  tiny-100x100.png          valid PNG, too small          -> media REJECTED / TOO_SMALL
  not-an-image.png          text with a .png name         -> media REJECTED / UNSUPPORTED_FORMAT (magic bytes decide)
The files are committed, so running this is only needed to change them."""
import os, struct, sys, zlib

def png(path, w, h, seed):
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter: none
        for x in range(w):
            raw += bytes(((x * 255 // w + seed) % 256, (y * 255 // h) % 256, (seed * 40) % 256))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    open(path, "wb").write(data)
    print(path, len(data), "bytes")

def unique_png(path, w=1920, h=1080, cols=16, rows=9):
    """A 16x9 grid of random colour blocks. Media rejects duplicates by SHA-256 and perceptual hash (README 5.2),
    so every e2e run needs a picture that looks different from all earlier ones; run.sh calls this per run."""
    rnd = os.urandom(cols * rows * 3)
    raw = bytearray()
    for r in range(rows):
        row = bytearray([0])
        for c in range(cols):
            i = (r * cols + c) * 3
            row += bytes(rnd[i:i + 3]) * (w // cols)
        row += bytes(rnd[0:3]) * (w - (w // cols) * cols)
        y0, y1 = r * h // rows, (r + 1) * h // rows
        raw += bytes(row) * (y1 - y0)
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))

if len(sys.argv) == 3 and sys.argv[1] == "unique":
    unique_png(sys.argv[2])
    sys.exit(0)

here = os.path.dirname(os.path.abspath(__file__))
png(os.path.join(here, "wallpaper-1920x1080.png"), 1920, 1080, 3)
png(os.path.join(here, "tiny-100x100.png"), 100, 100, 5)
open(os.path.join(here, "not-an-image.png"), "w").write("this is not an image\n")
