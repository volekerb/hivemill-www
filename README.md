# hivemill-www

Static site for hivemill.dev, served by GitHub Pages from the repo root. No framework, no bundler, no build step.

## Preview the redesign

From this directory, run `python3 -m http.server 18440 --bind 127.0.0.1`, then open `http://127.0.0.1:18440/`.

- `/`: the redesigned B2B homepage, customer workflow examples and developer catalog entry.
- `/demo/`: the actual dashboard exported with fictional demo data. Goals, tasks, resources, usage, alerts, selected filters and themes are browsable. No live factory is connected and no agents run. Some compound filters and fictional external PR links are unavailable and labeled accordingly.
- `/catalog/`: searchable developer library with concise component rows and individual installation/reference pages.
- `/guides/install/`, `/guides/ask-to-merge/`, `/guides/watch/`: installation, delivery and monitoring guides.
- `/factories/what/`, `/factories/who-merges/`: the factory model and an interactive merge-gate explanation.
- `/work-with-me/`: a scoped implementation and pilot path.
- `/film/`: a silent, approximately 30-second product film with seekable chapters. The full film plays on request; the small homepage machinery loop pauses offscreen and respects reduced motion.

The central message is “Close your laptop. Keep work moving.” Agent execution happens on the customer's infrastructure. Monitoring helps the team oversee the work; the catalog helps developers compose a factory from individual roles, skills and plugins. The three business stories are examples, not customer case studies.

GitHub Pages publishes the repository root on `main` to https://hivemill.dev/. Changes are checked through a pull request before merging into that publishing branch.

## Design and assets

- `assets/css/factory.css`: new typography, amber and graphite brand treatment, shared navigation, responsive layouts and light/dark themes.
- `assets/js/factory.js`: workflow playback, business story selection, theme control, product image inspection and interactive real-dashboard previews. Motion respects reduced-motion preferences; content remains available without JavaScript.
- `assets/brand/`: Higgsfield industrial imagery, original masters and the product film. `SOURCES.json` records generation IDs and capture provenance. Generated imagery is a brand metaphor; product screenshots preserve the real interface.
- `tools/render_promo.py`: local film renderer using Pillow, fonttools with Brotli and imageio-ffmpeg. Install these optional authoring dependencies in a virtual environment, then run `python tools/render_promo.py`. Re-rendering locally consumes no credits. Its five-second Higgsfield source shot used 80 credits once; the source is reused for the opening, closing and lightweight homepage loop. Product captures stay fixed between crossfades to avoid camera jitter. Captures use fictional data; the film has no audio.

## Refresh the demo

Clone the public factory repository alongside this website, install its normal Python requirements if needed, then run `python3 tools/export_demo.py --factory ../hivemill`. The exporter creates a temporary isolated demo, starts only a loopback read-only server, exports the allowed view graph, and stops that server. It never connects to a configured or live factory. `demo/manifest.json` records the source commit and exported routes. Refresh all demo views together when the product changes.

Demo pages are generated artifacts. Keep them separate from the marketing CSS so visitors see the actual product. They require no server-side application on GitHub Pages; only the requested page and shared assets are loaded.

## Validation

Install `requirements-dev.txt`, then run `python3 -m unittest discover -s tests`. The demo integrity checks cover local links/assets, honest labels, route boundaries and removal of fictional external PR destinations. Set `HIVEMILL_SOURCE` to a factory checkout to include its public-text guard locally. The existing CI runs catalog and image tests, checks the pinned catalog, and verifies snippet references. Run the complete suite with `HIVEMILL_SOURCE` set before publishing demo changes. Regenerate catalog pages with `python3 tools/catalog.py render --out catalog/index.html` after editing either catalog template or the generator.

## Existing foundation

- `assets/css/v2.css`: tokens (color, type, spacing, motion), light and dark, and the class names pages share. The class list is at the top of the file.
- `assets/js/motion.js`: scroll reveals and the pipeline piece. Transform and opacity only. It does nothing under `prefers-reduced-motion: reduce`; every page is complete with JS off.
- `assets/icons/icons.svg`: one stroke icon set (`currentColor`).
- `assets/fonts/`: self-hosted Bricolage Grotesque and Instrument Sans (SIL OFL), `font-display: swap`, metric-matched fallbacks.
- `assets/img/`: WebP and PNG derivatives of real Hivemill screenshots. Capture and rebuild: see `docs/screenshots.md`. `assets/img/SOURCES.json` records the source repo, commit, path and sha256 for every file.
- Runtime remains native HTML/CSS/JavaScript with no framework bundle. The homepage video loop is approximately 360 KB and is paused when offscreen. The full film is not preloaded. Generated demo pages are fetched individually, never as a single payload.
- `assets/css/editorial.css`: shared guide, explainer and implementation-page layouts. All public pages use the same brand and navigation.
- Product WebP derivatives use lossless compression, with the original PNG pixels retained. The homepage product showcase renders the actual interface, so text stays sharp at any screen density. Small Herdr panels retain their native capture resolution.
