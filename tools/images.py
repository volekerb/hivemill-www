#!/usr/bin/env python3
"""Build responsive WebP and PNG derivatives from real Hivemill screenshots.

Sources are PNG files of volekerb/hivemill at a pinned commit. Nothing is
drawn, mocked or edited: a derivative is a resize, optionally after a crop.
Every derivative is recorded in assets/img/SOURCES.json with the source
repo, sha, path and the sha256 of the source bytes.

Usage:  python3 tools/images.py [--src-dir DIR]
  --src-dir  a local checkout of volekerb/hivemill at SHA (skips the download)
Needs Pillow (requirements-dev.txt). Dev-only; the site itself has no build step.
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image

REPO = "volekerb/hivemill"
SHA = "53b6a6f92a3f88983593a92caa765419764323c3"
WIDTHS = (480, 960, 1600)
OUT = Path(__file__).resolve().parent.parent / "assets" / "img"

# name -> (source path, crop box (l, t, r, b) in source pixels or None)
IMAGES = {
    "tasks": ("docs/images/tasks-light.png", None),
    "agents": ("docs/images/agents-light.png", (0, 0, 2560, 1700)),
    "goals": ("docs/images/goals-light.png", (0, 0, 2560, 1700)),
    "herdr-panel": ("docs/film/stills/herdr-core.png", None),
    "skills": ("docs/film/stills/skills.png", None),
}


def fetch(path, src_dir):
    if src_dir:
        return (Path(src_dir) / path).read_bytes()
    url = f"https://raw.githubusercontent.com/{REPO}/{SHA}/{path}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-dir")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.iterdir():
        if old.suffix in (".webp", ".png"):
            old.unlink()
    entries = []
    for name, (path, crop) in IMAGES.items():
        data = fetch(path, args.src_dir)
        tmp = OUT / f".{name}.src"
        tmp.write_bytes(data)
        img = Image.open(tmp).convert("RGB")
        tmp.unlink()
        if crop:
            img = img.crop(crop)
        for w in WIDTHS:
            h = round(img.height * w / img.width)
            small = img.resize((w, h), Image.LANCZOS)
            for ext, opts in (("webp", {"quality": 78, "method": 6}), ("png", {"optimize": True})):
                fn = f"{name}-{w}.{ext}"
                small.save(OUT / fn, **opts)
                entries.append({"file": fn, "width": w, "height": h, "source_repo": REPO,
                                "source_sha": SHA, "source_path": path,
                                "source_sha256": hashlib.sha256(data).hexdigest(),
                                "crop": list(crop) if crop else None})
    (OUT / "SOURCES.json").write_text(json.dumps(entries, indent=1) + "\n")
    print(f"wrote {len(entries)} derivatives")
    return 0


if __name__ == "__main__":
    sys.exit(main())
