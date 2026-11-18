#!/usr/bin/env python3
"""Build the site's responsive WebP and PNG files from real Hivemill screenshots.

Two kinds of source, nothing drawn, mocked or edited:
  * web UI views: the 2x PNGs that tools/capture.py makes from the demo seed. The 2x file is the capture
    as is; the 1x file is that capture halved with a Lanczos resize.
  * Herdr desktop panel: a committed native-1x crop of the owner's capture in volekerb/hivemill at a
    pinned commit. It is used at its native size, never scaled up.
Every file is recorded in assets/img/SOURCES.json with its source repo, sha, path, the sha256 of the
source bytes and the crop.

Usage:  python3 tools/images.py --capture DIR [--src-dir DIR]
  --capture  the output directory of tools/capture.py (PNGs plus capture.json)
  --src-dir  a local checkout of volekerb/hivemill at SHA (skips the download of the Herdr crops)
Needs Pillow (requirements-dev.txt). Dev-only; the site itself has no build step.
"""
import argparse
import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image

REPO = "volekerb/hivemill"
SHA = "53b6a6f92a3f88983593a92caa765419764323c3"
OUT = Path(__file__).resolve().parent.parent / "assets" / "img"
CAPTURE_CMD = "python3 tools/capture.py --hivemill <hivemill checkout at SHA>"

# name -> (hivemill path, ffmpeg-style crop of the source frame, for the record only)
PANELS = {
    "herdr-budget": ("docs/film/herdr/panel-budget.png", "crop=616:528:652:131 of the 1920x960 1x app window"),
    "herdr-factory": ("docs/film/herdr/panel-factory.png", "crop=617:194:1280:131 of the 1920x960 1x app window"),
}
# catalog dashboard item (T-1809): real panels, two widths only
CATALOG_PANELS = {
    "herdr-panel": ("docs/film/stills/herdr-core.png", (480, 960, 1600)),
    "panel-factory": ("docs/film/herdr/panel-factory.png", (480, 960)),
    "panel-resources": ("docs/film/herdr/panel-resources.png", (480, 960)),
    "panel-active-goals": ("docs/film/herdr/panel-active-goals.png", (480, 960)),
    "panel-budget": ("docs/film/herdr/panel-budget.png", (480, 960)),
}
WEBP = {"lossless": True, "method": 6}


def fetch(path, src_dir):
    if src_dir:
        return (Path(src_dir) / path).read_bytes()
    url = f"https://raw.githubusercontent.com/{REPO}/{SHA}/{path}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def save(img, stem, entries, meta):
    for ext, opts in (("webp", WEBP), ("png", {"optimize": True})):
        fn = f"{stem}.{ext}"
        img.save(OUT / fn, **opts)
        entries.append({"file": fn, "width": img.width, "height": img.height, **meta})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--src-dir")
    args = ap.parse_args()
    cap = Path(args.capture)
    info = json.loads((cap / "capture.json").read_text())
    if info["hivemill_sha"] != SHA:
        sys.exit(f"{cap} was captured at {info['hivemill_sha']}, not {SHA}. Re-run tools/capture.py.")
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.iterdir():
        if old.suffix in (".webp", ".png"):
            old.unlink()
    entries = []
    for src in sorted(cap.glob("*-*.png")):
        if src.name.startswith("probe-"):
            continue
        data = src.read_bytes()
        stem = src.stem  # <view>-<theme>
        big = Image.open(io.BytesIO(data)).convert("RGB")
        small = big.resize((big.width // 2, big.height // 2), Image.LANCZOS)
        meta = {"source_repo": REPO, "source_sha": SHA, "source_path": f"demo seed, tools/capture.py ({stem})",
                "source_sha256": hashlib.sha256(data).hexdigest(), "crop": "CSS-pixel clip, see tools/capture.py",
                "capture_now": info["now"], "kind": "capture"}
        save(small, f"{stem}-1x", entries, {**meta, "density": 1})
        save(big, f"{stem}-2x", entries, {**meta, "density": 2})
    for name, (path, crop) in PANELS.items():
        data = fetch(path, args.src_dir)
        img = Image.open(io.BytesIO(data)).convert("RGB")
        meta = {"source_repo": REPO, "source_sha": SHA, "source_path": path,
                "source_sha256": hashlib.sha256(data).hexdigest(), "crop": crop,
                "kind": "native-1x-crop", "density": 1}
        for ext, opts in (("webp", {"lossless": True, "method": 6}), ("png", {"optimize": True})):
            fn = f"{name}-1x.{ext}"
            img.save(OUT / fn, **opts)
            entries.append({"file": fn, "width": img.width, "height": img.height, **meta})
    for name, (path, widths) in CATALOG_PANELS.items():
        data = fetch(path, args.src_dir)
        img = Image.open(io.BytesIO(data)).convert("RGB")
        for w in widths:
            h = round(img.height * w / img.width)
            small = img.resize((w, h), Image.LANCZOS)
            for ext, opts in (("webp", {"lossless": True, "method": 6}), ("png", {"optimize": True})):
                fn = f"{name}-{w}.{ext}"
                small.save(OUT / fn, **opts)
                entries.append({"file": fn, "width": w, "height": h, "source_repo": REPO,
                                "source_sha": SHA, "source_path": path,
                                "source_sha256": hashlib.sha256(data).hexdigest(), "crop": None})
    (OUT / "SOURCES.json").write_text(json.dumps(entries, indent=1) + "\n")
    print(f"wrote {len(entries)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
