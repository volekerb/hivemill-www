# hivemill-www

Static site for hivemill.dev, served by GitHub Pages from the repo root. No framework, no bundler, no build step.

## Design (v2)

- `assets/css/v2.css`: tokens (color, type, spacing, motion), light and dark, and the class names pages share. The class list is at the top of the file.
- `assets/js/motion.js`: scroll reveals and the pipeline piece. Transform and opacity only. It does nothing under `prefers-reduced-motion: reduce`; every page is complete with JS off.
- `assets/icons/icons.svg`: one stroke icon set (`currentColor`).
- `assets/fonts/`: self-hosted Bricolage Grotesque and Instrument Sans (SIL OFL), `font-display: swap`, metric-matched fallbacks.
- `assets/img/`: WebP and PNG derivatives of real Hivemill screenshots. Rebuild with `pip install -r requirements-dev.txt && python3 tools/images.py`. `assets/img/SOURCES.json` records the source repo, commit, path and sha256 for every file.
- Budgets: CSS 40 KB, JS 30 KB (uncompressed), hero image 200 KB as served.
- Pages `guides/` and `factories/` still use `assets/site.css`.
