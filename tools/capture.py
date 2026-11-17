#!/usr/bin/env python3
"""Capture the Hivemill web UI views from the demo seed at 2x, light and dark.

Reproduces every product screenshot on the site. It drives the pinned headless
Chrome of volekerb/hivemill (ci/demo_cdp.py) against a fictional demo home that
ci/demo_seed.py builds; nothing is drawn or edited, a view is a crop of a real
page. Output goes to a work directory as <view>-<theme>.png (2x, lossless);
tools/images.py turns those into the site's responsive files.

Usage:
  python3 tools/capture.py --hivemill DIR [--browser PATH] [--out DIR] [--probe]
    --hivemill  a checkout of volekerb/hivemill at the pinned SHA (git checkout SHA)
    --browser   an existing chrome-headless-shell (else the pinned one is downloaded)
    --out       where the 2x PNGs go (default: build/capture, gitignored)
    --probe     also write each full 1280x1000 viewport, for choosing crops
Stdlib only; the demo home and browser profile live in a temp dir that is removed.
"""
import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SHA = "53b6a6f92a3f88983593a92caa765419764323c3"
NOW = "2026-11-10T12:00:00+00:00"  # fixed: the seed and the pages are the same on every run
WIDTH, HEIGHT, SCALE = 1280, 1000, 2
ROOT = Path(__file__).resolve().parent.parent

# view -> (url path, crop in CSS px (x, y, w, h)). Every crop starts at y=64, below the page header (it holds a
# wall-clock "Updated" badge), and drops the app sidebar. "col" crops are 480 CSS px wide: shown in a 700 px column
# or a 358 px phone column they stay readable. "wide" is the 1024 px hero crop.
COL = (240, 64, 480, 540)
VIEWS = {
    "tasks-wide": ("/tasks", (240, 64, 1024, 560)),
    "tasks": ("/tasks", COL),
    "agents": ("/agents", COL),
    "goals": ("/goals", COL),
    "goal": ("/goal/G-002", COL),
    "home": ("/", COL),
}
THEMES = ("light", "dark")


def load_hivemill(src):
    src = Path(src).resolve()
    head = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True)
    if head.returncode != 0 or head.stdout.strip() != SHA:
        sys.exit(f"{src} is not volekerb/hivemill at {SHA}. Run: git -C {src} checkout {SHA}")
    sys.path.insert(0, str(src / "ci"))
    import demo_cdp  # noqa: E402
    import screenshots  # noqa: E402
    return demo_cdp, screenshots


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hivemill", required=True)
    ap.add_argument("--browser")
    ap.add_argument("--out", default=str(ROOT / "build" / "capture"))
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--only", help="comma list of views")
    args = ap.parse_args()
    cdp, shots = load_hivemill(args.hivemill)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    views = {k: v for k, v in VIEWS.items() if not args.only or k in args.only.split(",")}
    tmp = Path(tempfile.mkdtemp(prefix="hm-capture-"))
    server = None
    try:
        binary = cdp.browser_binary(tmp, args.browser)
        demo = tmp / "demo"
        cdp.seed_demo(demo, NOW)
        port, server = cdp.serve_demo(demo)
        with cdp.Browser.launch(binary, WIDTH, HEIGHT, work=tmp / "work") as br:
            br.scale = SCALE
            for name, (path, crop) in views.items():
                for theme in THEMES:
                    br.new_page(f"http://127.0.0.1:{port}{path}")
                    br.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": theme}]})
                    br.send("Runtime.evaluate", {"expression": "document.fonts.ready", "awaitPromise": True})
                    br.evaluate("new Promise(r => setTimeout(r, 600))")
                    if args.probe:
                        (out / f"probe-{name}-{theme}.png").write_bytes(br.screenshot())
                    x, y, w, h = crop
                    res = br.send("Page.captureScreenshot", {"format": "png", "clip": {
                        "x": x, "y": y, "width": w, "height": h, "scale": 1}})
                    (out / f"{name}-{theme}.png").write_bytes(base64.b64decode(res["data"]))
                    print(f"{name}-{theme}")
    finally:
        if server is not None:
            cdp.stop(server)
        shutil.rmtree(tmp, ignore_errors=True)
    json.dump({"hivemill_sha": SHA, "now": NOW, "width": WIDTH, "scale": SCALE}, (out / "capture.json").open("w"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
