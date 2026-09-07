# Public presentation site

The lightweight GitHub Pages site shares the recorded twin-rib bracket demo and renders the repository's
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

## Report and evidence contract

The report keeps its stable `docs/reports/mechanical-test-2026-09-06.md` and `.zh-CN.md` source
paths and corresponding hosted HTML URLs. Its public attachments remain
`docs/reports/evidence/2026-09-06/{summary,cases,provenance}.json`, now containing the bracket study.
`examples/gusseted-bracket/demo/evidence.js` exposes the same summary as
`window.SIMSTUDIO_BENCHMARK`, so the viewer also works without fetching JSON in direct file mode.

The suite records five tests and five real solves across three mesh sizes. Numerical study checks
passed; engineering review remains WARN. Automatic visual review and safety factor remain
NOT_RUN, separately from the recorded manual image review. The 252 passed / 20 skipped offline
baseline belongs to the preceding validation round, not the documentation replacement.

The former public demo is retained only in the ignored local archive
`test-records/bracket-primary-swap/old-demo`. It is excluded from the public allowlist and
release presentation; the analytical beam fixture remains under `tests/fixtures/cantilever`.

## Visual source and provenance

`python tools/build_cover.py` regenerates the self-contained `docs/assets/overview.svg` layout.
Render that SVG at its native 1600 × 900 size as `docs/assets/overview.png` with an SVG renderer
(the release preparation used Sharp). Numbers come directly from the public `summary.json`,
selecting `primary_case: mixed_5mm`.
The cover uses the unchanged fine-mesh total-deformation image, maximum displacement and stress,
and the recorded 8 → 5 mm displacement change.
The original Mechanical PNG is displayed whole, without cropping or recoloring. This cover is a
presentation figure, not a new solve or an engineering visual review.

Keep all five original exports (geometry, underside, mesh, total deformation, and equivalent
stress) and their provenance untouched. The three result-image controls always show the 5 mm
combined-load case. Tables show the five real solves and both mesh-refinement comparisons.
Edit the public evidence
exporter and regenerate if evidence must change. Images used courtesy of ANSYS, Inc.

Browser acceptance should cover desktop and narrow screens, all three result-image controls,
optional geometry views, five-case and mesh-change tables, keyboard
activation, Markdown table scrolling, report language switching, download links, and console errors.
Save captures and receipts under a new local `test-records/` directory.

## Publishing

The repository publishes from its protected `gh-pages` source branch. After CI succeeds on
`main`, the Pages workflow builds the explicit public allowlist, commits only that output to
`gh-pages` without a force push, requests a Pages build, and waits for the matching commit
to finish. It does not change environment protections or repository visibility. Older CI runs
are skipped when `main` has already advanced. The branch must be configured as the Pages
publishing source when setting up a fork.
