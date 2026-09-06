# Public release preparation

## Final local presentation candidate

The completed presentation sources were checked on September 6, 2026 with real integration disabled:

| Check | Observed result |
| --- | --- |
| Full default suite | 239 passed, 15 skipped in 12.67 s |
| Ruff | PASS |
| New public-site, distribution and evidence regressions | 64 passed, 4 skipped |
| Public snapshot | All 8 provenance-tracked files verified; 9 historical cases and 5 solves unchanged |
| Built website | 13 HTML pages; all internal file links and anchors checked |
| Source package / source ZIP | 140 files each; identical member paths and bytes; no private archives |
| Wheel | 44 CLI-only files; clean base-dependency installation and DRY_RUN passed |
| Unpacked source | Public evidence verification and website build passed |

The 15 local skips comprise nine opt-in real cases and six Windows symbolic-link checks without
the required OS privilege. No real solve was started for these publication checks. The revised
site's browser acceptance and the remote workflow results are separate from this local record.

The 1600 × 900 README figure is composed from the complete, unchanged total-deformation export
and exact public numerical evidence. Its vector source and generator are included. No missing
solve images or engineering validation were synthesized.

This is a source-release candidate for the existing `0.1.0` alpha. The repository's historical real
Mechanical acceptance is documented in the [test report](reports/mechanical-test-2026-09-06.md).
Publication preparation does not expand that acceptance to another version, mesh, or transport.

## Public deliverables

- English and Simplified Chinese project READMEs, the [Alpha changelog](../CHANGELOG.md), and
  `docs/assets/overview.png` as the project cover, separate from the original solver images.
- Static-site sources under `docs/site/` and `tools/build_site.py` for rendering the Markdown
  reports into a browsable site. The source package retains the report template; the rendered
  deployment is produced separately by the site builder.
- English and Simplified Chinese test reports under `docs/reports/`.
- Field-allowlisted evidence, test counts, and original/public SHA-256 values under
  `docs/reports/evidence/2026-09-06/`.
- A dependency-free, offline-capable [cantilever viewer](../examples/cantilever/demo/index.html),
  three original Mechanical plots, and links to the complete YAML and neutral STEP fixture.
- MIT-licensed project source, existing contributor/security guides, and updated image notices.

The source distribution includes these deliverables. A public source ZIP must be converted from the
checked sdist, retaining its single top-level directory and identical file bytes. Do not ZIP the
working tree: local records, environments and solver outputs are not release content.
The wheel contains only the Python CLI, its runtime package and distribution metadata/licenses.
Use a repository checkout, sdist or its source ZIP for the complete benchmark and site sources.

### Source-package contract

In addition to the existing reports, evidence, demo, license and neutral geometry, the checker
requires `README.zh-CN.md`, `CHANGELOG.md`, `docs/release-preparation.md`, `docs/assets/overview.png`,
`docs/site/index.html`, `docs/site/site.css`, `docs/site/report.html` and `tools/build_site.py`.
`MANIFEST.in` includes `.html`, `.css`, `.js` and `.svg` files beneath `docs/site/`, plus `.png` and
`.svg` files beneath `docs/assets/`. Existing Markdown and Python rules cover `docs/site/README.md`
and `tools/check_site.py` if supplied. These two files and `docs/site/site.js` are optional; the
checker does not require them.

`tools/check_distribution.py` reads wheel, sdist and source-ZIP member tables without extraction.
It rejects private directories, solver/project formats, embedded archives, licensing logs,
non-regular entries including links, unsafe paths, multiple source roots and duplicate file names
(including case collisions on Windows). Complete member paths are checked before removing the
source root. For wheels, only runtime Python files under `ansys_skill/` and `.dist-info` metadata
are accepted. Success keeps JSON on stdout; failures use stderr and exit 1, with argument errors
using exit 2. Presence and path checks do not replace the separate public-evidence hash check.

## Evidence publication

The exporter reads existing saved files only. It never launches a solver or infers new results.
Its field allowlist removes machine names, absolute paths, free-form diagnostic payloads, and
license/process details. Exact measured numbers, units, check statuses, suite timing and source hashes
remain traceable. Synthetic or unknown results are rejected from this dated real benchmark.

Original Mechanical projects, RST files, raw archives, licensing logs and desktop captures stay in
ignored local directories. Never upload `build/`, `test-records/` or solver files as release assets.
Both Git ignores and explicit sdist pruning protect `build/` and `test-records/`; package checks
reject their inclusion and known solver/project extensions elsewhere in an archive.
Three benchmark PNGs are included explicitly,
with `Images used courtesy of ANSYS, Inc.` next to their display. See [NOTICE](../NOTICE).

Ansys academic publication guidance was checked on September 6, 2026. It calls for the product/release
to be identified and the image acknowledgment to accompany published images; restrictions on academic
software use still apply. Source: https://ansys.synopsys.com/academic/terms-and-conditions

## Reproduce publication checks

### Observed local preparation results — September 6, 2026

| Check | Observed result |
| --- | --- |
| Public-evidence regression | 5 passed |
| Ruff | PASS |
| Full default suite with real execution disabled | 180 passed, 11 skipped in 10.15 s |
| Source distribution and wheel build | PASS; wheel added to the development extra after the first no-isolation build identified it as missing |
| Package contents | PASS; public report/demo assets included in sdist, private archives excluded |
| Independent wheel installation | PASS; base runtime dependencies only, no ANSYS clients |
| Fresh development environment | 180 passed, 11 skipped in 8.34 s with no ANSYS clients; the dev extra explicitly supplies setuptools and wheel for no-isolation builds |
| Wheel validation and default dry-run | PASS; returned DRY_RUN without starting a solver |
| Unpacked-source demo, direct file mode | PASS at 1440 px and 390 px; three views, nine file links, keyboard activation, no external requests or JavaScript errors |

These checks were local Windows checks, not a completed GitHub-hosted matrix run. No new licensed
solve was performed during publication preparation; the separate nine-case real benchmark remains
the historical record. Full local logs, dry-run outputs and screenshots are retained outside the
public distribution.

The table is the earlier publication-preparation record, not a claim that subsequent site, README
or package-contract changes have already passed those same checks. Keep new validation results
separate from both that table and the dated Mechanical acceptance evidence. Configuring CI, a
release workflow or a Pages workflow does not establish a successful hosted run or deployment.

### Package-contract review — September 6, 2026

The following results were observed locally after adding the source-package contract and archive
regressions, while the presentation sources were still being prepared in parallel:

| Check | Observed result |
| --- | --- |
| Distribution and public-evidence regressions | 42 passed in 0.64 s |
| `ruff check .` | PASS |
| Full default suite with `ANSYS_AVAILABLE=0` | 217 passed, 11 skipped in 12.36 s |
| Public snapshot hash check | PASS; 8 published files, 9 recorded cases, 5 recorded solves; no solver started |
| Historical reports and provenance | SHA-256 unchanged from the start of this review |
| Existing wheel contents | PASS; 44 files, CLI-only scope |
| Existing source ZIP versus existing sdist | Same member paths and file bytes |
| Existing source archives against the new contract | FAIL as expected: the earlier bundle lacks the changelog and six new core presentation sources |
| Rebuilt complete presentation source package | NOT_RUN at this review; six core presentation sources had not yet landed |

The six pending files were `README.zh-CN.md`, `docs/assets/overview.png`, `docs/site/index.html`,
`docs/site/site.css`, `docs/site/report.html` and `tools/build_site.py`. Rebuild and validate the
final archives after those files land. Archive-contract fixtures validate the packaging rules but
do not establish that a complete release artifact was built. Real integration was not enabled
for this review and remains `NOT_RUN` here; the historical real acceptance is unchanged.

Install the existing development extra, then run from the repository root:

```bash
python -m pytest -q tests/unit/test_distribution.py tests/unit/test_public_evidence.py
ruff check .
python -m pytest -q
python tools/export_benchmark_evidence.py
python -m build --no-isolation
python tools/check_distribution.py dist
```

Use a fresh output directory for each candidate so older archives cannot be mistaken for the
current build. Once the source ZIP has been converted from the validated sdist, run the package
checker again on the directory containing all final release assets. Compare the ZIP and sdist
file paths and bytes, including `provenance.json`, the two historical reports and all published
evidence. In the unpacked source, run `python tools/export_benchmark_evidence.py` without
`--archive` to verify the existing snapshot without regeneration. Build and check the site from
that unpacked source using `tools/build_site.py` and, when present, `tools/check_site.py`; consult
their `--help` for output-directory options. Only the site builder's public output belongs in a
Pages artifact, never its parent `build/` directory or the solver records beside it.

Install the wheel in an independent environment with only its base dependencies, then validate
and dry-run the source package's cantilever input. Require `DRY_RUN`; installing a wheel or
building the documentation must not implicitly start Mechanical.

Keep `ANSYS_AVAILABLE` unset or `0` for these offline checks. Real integration stays explicitly
opt-in. Dependency installation can require network access; the installed offline tests and public
evidence checker do not. CI checks editable source plus package contents; its matrix and declared
dependency ranges are not a claim of byte-identical builds across future runner images.

For maintainers with the original local archive, regenerate public evidence with:

```bash
python tools/export_benchmark_evidence.py --archive <local-evidence-archive>
```

Review the changed public files and hashes before release. The full local archive is not an upload
bundle. No GitHub push, repository visibility change, tag, or public deployment is implied by these
preparation commands.
