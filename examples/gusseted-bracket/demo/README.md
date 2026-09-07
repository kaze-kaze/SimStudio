# Saved real twin-rib bracket demonstration

Open `index.html` directly in a browser after downloading or extracting the source, or use the
project's static site. No npm installation, CDN, server API, ANSYS installation, or license is
required to view it. The page has no solver endpoint and cannot start Mechanical.

The viewer presents the September 6, 2026 study: **five passed tests, five real serial solves,
three quadratic mesh sizes, and 208.16 seconds**. The primary image and side metrics always
refer to **`mixed_5mm`**. The three image buttons switch its unchanged mesh, total-deformation,
and equivalent-stress exports. Geometry and underside images are optional supplemental views
from the same saved project. No image is synthesized for a different mesh or load case.

The five-case table includes `mixed_12mm`, `mixed_8mm`, `mixed_5mm`, `gravity_5mm`, and
`double_mechanical_5mm`. The mesh table shows all four acceptance quantities and both consecutive
relative changes. Full-field linearity preserves gravity: `u(2P+G) = 2u(P+G) - u(G)`.
Pad stress statistics give each node equal weight; they are not area-weighted.

The former cantilever demonstration is archived locally under
`test-records/bracket-primary-swap/old-demo` and is excluded from the public example and site.
The beam remains only as the internal analytical fixture `tests/fixtures/cantilever`.

## Evidence and status

Numbers and check states come from `evidence.js`, generated from the
[public JSON summary](../../../docs/reports/evidence/2026-09-06/summary.json).
It exposes `window.SIMSTUDIO_BENCHMARK` with `primary_case: mixed_5mm`, five `cases`,
`convergence.series`, `linearity`, `suite`, and `fixture`. The viewer performs display-only unit
conversion for convergence values and does not interpolate, solve, or invent new results.
Missing complete real-case evidence is reported as NOT_RUN, never PASS.

These files are attachments to the stable
[English report](../../../docs/reports/mechanical-test-2026-09-06.md) and
[Chinese report](../../../docs/reports/mechanical-test-2026-09-06.zh-CN.md).
Independent numerical checks passed, but global stress-peak review remains WARN; safety factor
and automatic visual review remain NOT_RUN. The recorded manual image review is separate.
Other Mechanical versions and remote execution were not verified. The 252 passed / 20 skipped
offline baseline is from the preceding validation round, not new tests for this viewer replacement.

## Sources and regeneration

`index.html`, `style.css`, and `demo.js` are viewer source. `evidence.js` and `assets/*.png` are
generated artifacts. Maintainers regenerate the snapshot using the exporter and the local folder
containing the saved study plus supplemental process records:

```bash
python tools/export_benchmark_evidence.py --archive <local-archive-root>
```

Readers can verify the committed snapshot without the private archive or a solver:

```bash
python tools/export_benchmark_evidence.py
```

The [provenance file](../../../docs/reports/evidence/2026-09-06/provenance.json) records source
hashes, the field-allowlist transformation, and public-file hashes. All five 1600 × 1000 PNGs
are byte-identical exports from the unchanged saved fine-mesh project; reopening it neither
solved nor saved the project. Original JUnit, Mechanical projects, RST files, and logs stay local.

The committed specification uses an **8 mm nominal mesh** and defaults to dry-run. See the
[example README](../README.md) and [Windows guide](../../../docs/windows-testing.md) for explicit
batch execution and the complete five-solve study. See [NOTICE](../../../NOTICE) for attribution.

Images used courtesy of ANSYS, Inc.
