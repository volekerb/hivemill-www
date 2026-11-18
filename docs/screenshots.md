# Product screenshots

Every screenshot on the site is captured from the Hivemill demo seed (fixed clock, no live data) with headless Chrome at device scale factor 2, cropped to the meaningful region, in light and dark.

## Reproduce

```
git clone https://github.com/volekerb/hivemill /tmp/hivemill
python3 tools/capture.py --hivemill /tmp/hivemill --browser /path/to/chrome-headless-shell --out build/capture
pip install -r requirements-dev.txt
python3 tools/images.py --capture build/capture --src-dir /tmp/hivemill
```

`capture.py` checks out nothing: it verifies the clone is at the pinned SHA, starts the demo server, and writes `<view>-<theme>.png` plus `capture.json`. `images.py` produces the 1x/2x webp and png files in `assets/img/` and rewrites `assets/img/SOURCES.json` (source repo, SHA, path, sha256, crop, size).

## Frame and markup

Pages use `<picture>` with `prefers-color-scheme` sources, explicit width/height, and `srcset` 1x/2x. The frame is the `.fig--shot` class in `assets/css/v2.css`.

## Herdr panel

The Herdr app panel is a real capture at its native 1x size (one theme). It is never upscaled or mocked. A true 2x needs a retina capture.

`python3 -m unittest discover -s tests -p test_images.py` checks that every picture is complete and every file is registered.

## Marketing presentation

WebP derivatives now use lossless compression from the registered PNG originals so small UI text is not softened by another compression pass. On the homepage, the main product showcase embeds the real static demo interface with view selection and opt-in interaction; the screenshot is its no-JavaScript fallback. Product figures can be inspected at their original density. No labels, numbers or controls are synthesized.

The four refreshed overview, agent, goal-list and goal-detail views use complete-width main-content captures from the exported demo at the commit in `demo/manifest.json`. Rebuild their 520×320 / 1040×640 variants with `python3 tools/refresh_marketing_captures.py`. The original full-page captures are committed in `assets/brand/captures/`; provenance and crop bounds are recorded per asset. Run this after the legacy image builder to retain the refreshed views.
