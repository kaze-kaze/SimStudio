# Public presentation site

The lightweight GitHub Pages site shares the recorded cantilever demo and renders the repository's
Markdown reports with a common reading layout. It contains no solver endpoint, analytics, external
fonts, or JavaScript dependencies. Opening it cannot start Mechanical.

## Build and check

From a development environment with `python -m pip install -e ".[dev]"`:

```console
python tools/export_benchmark_evidence.py
python tools/build_site.py --out build/site
python tools/build_site.py --check build/site
```

Use a new or empty output directory. Open the generated `index.html` directly, or serve that
directory with your preferred static server. Project-relative links work under `/SimStudio/` and
in direct file mode. `site-manifest.json` records the exact output hashes.

`tools/build_site.py` copies only its explicit public allowlist. It never copies `build/`,
`test-records/`, environments, Mechanical projects, RST files, or license diagnostics. Markdown
source files remain available alongside their generated pages. Other source links point to GitHub.

## Visual source and provenance

`python tools/build_cover.py` regenerates the self-contained `docs/assets/overview.svg` layout.
Render that SVG at its native 1600 × 900 size as `docs/assets/overview.png` with an SVG renderer
(the release preparation used Sharp). Numbers come directly from the public `summary.json`.
The original Mechanical PNG is displayed whole, without cropping or recoloring. This cover is a
presentation figure, not a new solve or an engineering visual review.

Keep the three original result images and their provenance untouched. Edit the public evidence
exporter and regenerate if evidence must change. Images used courtesy of ANSYS, Inc.

Browser acceptance should cover desktop and narrow screens, all three demo controls, keyboard
activation, Markdown table scrolling, report language switching, download links, and console errors.
Save captures and receipts under a new local `test-records/` directory.
