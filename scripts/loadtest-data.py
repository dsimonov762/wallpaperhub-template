#!/usr/bin/env python3
"""Makes the unique pictures for the k6 upload profile: loadtest/.data/uploads/0000.png ... (1920x1080, random colour blocks).

Media rejects duplicates by SHA-256 and by perceptual hash (README 5.2), so every upload of a test needs a picture that looks different from
all earlier ones: a picture is used once per test, and the pictures of an earlier test are already in the stack until `make reset`.
Usage: python3 scripts/loadtest-data.py [COUNT=200] [--fresh]    --fresh deletes the existing ones first
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "loadtest" / ".data" / "uploads"
GEN = ROOT / "e2e" / "fixtures" / "make_fixtures.py"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    count = int(args[0]) if args else 200
    OUT.mkdir(parents=True, exist_ok=True)
    if "--fresh" in sys.argv:
        for f in OUT.glob("*.png"):
            f.unlink()
    for i in range(count):
        subprocess.run([sys.executable, str(GEN), "unique", str(OUT / f"{i:04d}.png")], check=True)
    size = sum(f.stat().st_size for f in OUT.glob("*.png"))
    print(f"{count} pictures in {OUT.relative_to(ROOT)} ({size // 1024} KiB). UPLOAD_POOL={count} is the matching setting.")


if __name__ == "__main__":
    main()
