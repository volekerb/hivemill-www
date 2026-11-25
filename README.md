# hivemill-www

Static site for hivemill.dev. GitHub Actions stages the marketing pages, generates the real product demo with fictional data, tests the resulting site, and publishes it through GitHub Pages. Runtime remains native HTML/CSS/JavaScript; no application server or frontend bundle is needed.

## Preview the redesign

Build and preview the same artifact used in production:

```sh
python3 -m venv .local/venv
.local/venv/bin/python -m pip install -r requirements-dev.txt
git clone https://github.com/volekerb/hivemill .local/demo-source
git -C .local/demo-source checkout --detach "$(python3 -c 'import json; print(json.load(open("demo/source.json"))["sha"])')"
.local/venv/bin/python tools/build_site.py --factory .local/demo-source
python3 -m http.server 18440 --bind 127.0.0.1 --directory build/site
```

Open `http://127.0.0.1:18440/`. Re-run the build after editing source files. The build replaces only `build/site`, and leaves the last successful artifact intact if generation fails.

- `/`: the redesigned B2B homepage, customer workflow examples and developer catalog entry.
- `/demo/`: the actual dashboard exported with fictional demo data. Goals, tasks, resources, usage, alerts, selected filters and themes are browsable. No live factory is connected and no agents run. Some compound filters and fictional external PR links are unavailable and labeled accordingly.
- `/catalog/`: searchable developer library with concise component rows and individual installation/reference pages.
- `/factories/what/`: how the factory works, including the boundary between your host and model providers.
- `/guides/install/`, `/guides/ask-to-merge/`, `/guides/watch/`: installation, a worked delivery example, and monitoring. Existing guide URLs remain available.
- `/factories/who-merges/`: configurable merge policy and an interactive example of the default gate.
- `/work-with-me/`: a scoped implementation and pilot path.
- `/film/`: a silent, approximately 30-second product film with seekable chapters. The full film plays on request; the small homepage machinery loop pauses offscreen and respects reduced motion.

The central message is “Close your laptop. Keep work moving.” The homepage shows the product before explaining its workflow. Agent sessions run on the customer's host; Claude Code and Cursor still use their model providers. Monitoring distinguishes resource and usage caps from estimated monetary cost. The catalog helps developers compose a factory from individual roles, skills and plugins. The three business stories are examples, not customer case studies.

The `site` workflow builds and tests every pull request. Only a push or manual workflow run on `main` deploys `build/site` to https://hivemill.dev/. Pull requests and scheduled checks never deploy.

GitHub Pages uses **GitHub Actions** as its deployment source, with the existing `hivemill.dev` custom domain. Generated demo pages are deployment output and are not committed to `main`.

## Design and assets

- `assets/css/factory.css`: new typography, amber and graphite brand treatment, shared navigation, responsive layouts and light/dark themes.
- `assets/js/factory.js`: workflow playback, business story selection, theme control, product image inspection and interactive real-dashboard previews. Motion respects reduced-motion preferences; content remains available without JavaScript.
- `assets/brand/`: Higgsfield industrial imagery, original masters and the product film. `SOURCES.json` records generation IDs and capture provenance. Generated imagery is a brand metaphor; product screenshots preserve the real interface.
- `tools/render_promo.py`: local film renderer using Pillow, fonttools with Brotli and imageio-ffmpeg. Install these optional authoring dependencies in a virtual environment, then run `python tools/render_promo.py`. Re-rendering locally consumes no credits. Its five-second Higgsfield source shot used 80 credits once; the source is reused for the opening, closing and lightweight homepage loop. Product captures stay fixed between crossfades to avoid camera jitter. Captures use fictional data; the film has no audio.

## Refresh the demo

`demo/source.json` is the source of truth for the demo renderer commit, seed time, render time, timezone, fictional machine, and existing URL contract. It is intentionally independent of the catalog’s source pin. The current contract covers all 800 existing demo URLs, including timestamp-based resource pagination.

`tools/build_site.py` copies only public files into a fresh staging directory and calls `tools/export_demo.py`. The exporter seeds a temporary factory home and runs only its read-only loopback server. It inherits no caller credentials or live factory settings. A build-only child freezes the sample’s clock, initializes token data before serving, and uses fictional machine telemetry so CI does not change the scenario. It stops the server and removes the temporary factory when finished. No database or factory process is deployed.

The exported HTML, shared product assets, and `demo/manifest.json` exist only under ignored `build/site/demo/` and in the deployment artifact. Do not edit or commit them. CSS font paths remain relative to `/demo/static/`; theme preferences remain isolated from a live factory. Navigation, filters, details, disclosures, and themes use the same product UI as before.

To update the product demo, review a new factory commit, update `demo/source.json`, check out that commit, and rebuild. A changed route contract deliberately fails the build: review removed/added URLs and preserve compatibility before updating its count and SHA-256 (computed from `json.dumps(routes, sort_keys=True)`). Keep the seed and renderer clocks aligned so time-windowed charts remain populated. To export only the demo, use `python3 tools/export_demo.py --factory PATH --out FRESH_DIRECTORY`.

## Validation

After building, run `.local/venv/bin/python -m unittest discover -s tests`. Demo checks read `build/site` by default; set `SITE_ROOT` to inspect another complete artifact. Missing output fails instead of silently skipping checks. The suite validates the existing route contract, every demo link and asset, public-page packaging, source exclusions, font paths, theme isolation, honest labels, and unavailable fictional PR destinations.

Set `HIVEMILL_SOURCE` to a clean checkout at `catalog/catalog.json`’s source SHA to include the factory public-text guard. CI checks out the catalog and demo pins separately, runs the full suite, checks catalog output, and verifies all snippet references before publishing. Regenerate catalog pages with `python3 tools/catalog.py render --out catalog/index.html` after editing either catalog template or the generator.

## Checks

The `lighthouse` job of the `site` workflow runs Lighthouse CI on the tested artifact (`build/site`) before anything deploys. `lighthouserc.json` lists every public page (`tools/site_metadata.py` `page_paths`) and measures each at the default mobile form factor, 3 runs per page. On the median run, performance must be at least 0.9, accessibility at least 0.9 and cumulative layout shift at most 0.01. Reports stay in `.lighthouseci/` and are not uploaded. `tests/test_pages.py` fails when a public page is missing from `lighthouserc.json` or a threshold changes.

Run the same checks locally from the repo root (Node and Chrome required; lhci uses the version pinned in the workflow):

```sh
.local/venv/bin/python tools/build_site.py --factory .local/demo-source
npx --yes "@lhci/cli@$(sed -n 's/^ *LHCI_VERSION: "\([0-9.]*\)"$/\1/p' .github/workflows/site.yml)" autorun
python3 -m unittest discover -s tests -p test_pages.py
```

When you add a public page, add its `http://localhost/<path>/index.html` URL to `lighthouserc.json`.

## Search metadata and page copy

Each page owns its visible copy, title and description. `tools/site_metadata.py` derives canonical URLs, social previews and the supported structured data from those facts. After changing a title or description, run:

```sh
python3 tools/site_metadata.py --write
python3 tools/site_metadata.py --check
```

Catalog summaries belong in `catalog/overrides.json`; keep the pinned prompts and source instructions intact. Rebuild the catalog from its pinned source and render its pages after changing those summaries. The catalog renderer uses the same metadata helper as the editorial pages.

The build rejects stale metadata, excludes catalog source templates from the public artifact, and generates `sitemap.xml` and `robots.txt` inside `build/site`. The sitemap includes only the intended marketing and reference pages. The fictional demo remains crawlable so search engines can read its `noindex` directive, and its 800 route variants are excluded from the sitemap. Search and training crawler access remain unchanged. No special AI crawler file, fabricated review markup or guaranteed search ranking is implied.

## Existing foundation

- `assets/css/v2.css`: tokens (color, type, spacing, motion), light and dark, and the class names pages share. The class list is at the top of the file.
- `assets/js/motion.js`: scroll reveals and the pipeline piece. Transform and opacity only. It does nothing under `prefers-reduced-motion: reduce`; every page is complete with JS off.
- `assets/icons/icons.svg`: one stroke icon set (`currentColor`).
- `assets/fonts/`: self-hosted Bricolage Grotesque and Instrument Sans (SIL OFL), `font-display: swap`, metric-matched fallbacks.
- `assets/img/`: WebP and PNG derivatives of real Hivemill screenshots. Capture and rebuild: see `docs/screenshots.md`. `assets/img/SOURCES.json` records the source repo, commit, path and sha256 for every file.
- Runtime remains native HTML/CSS/JavaScript with no framework bundle. The homepage video loop is approximately 360 KB and is paused when offscreen. The full film is not preloaded. Generated demo pages are fetched individually, never as a single payload.
- `assets/css/editorial.css`: shared guide, explainer and implementation-page layouts. All public pages use the same brand and navigation.
- Product WebP derivatives use lossless compression, with the original PNG pixels retained. The homepage product showcase renders the actual interface, so text stays sharp at any screen density. Small Herdr panels retain their native capture resolution.
