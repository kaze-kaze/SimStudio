# Mechanical engineering acceptance report: twin-rib equipment bracket — 2026-09-06

Dates use the recorded host timezone, America/Chicago (UTC−05:00).

This stable report path now presents the primary bracket example. It summarizes the preceding
completed bracket validation; replacing the presentation does not add a new solve. The former
cantilever remains only as an internal analytical fixture under `tests/fixtures/cantilever`.
Earlier cantilever, template-synchronization, and gRPC diagnostics are historical records and
are not part of the five solves reported here.

[简体中文报告](mechanical-test-2026-09-06.zh-CN.md) ·
[Interactive example](../../examples/gusseted-bracket/demo/index.html) ·
[Public summary](evidence/2026-09-06/summary.json) ·
[Case details](evidence/2026-09-06/cases.json) ·
[Provenance and hashes](evidence/2026-09-06/provenance.json)

## Conclusion

The recorded study passed **5 real integration tests across 5 serial Mechanical solves in
208.16 seconds**. Every run is `SOLVED` and `synthetic: false`. Both mesh-refinement steps meet
the displacement and bearing-pad stress-statistic tolerances. Independent force balance, moment
balance, and gravity-corrected full-field linearity all passed. The elapsed time covers the study
tests and their checks, not isolated solver time.

The preceding validation also completed one nominal 8 mm exploratory solve and the first 12 mm
case of an unsuccessful study attempt: **7 completed real solves in that validation round**,
including the final five. The other four cases in the unsuccessful attempt failed during Python
startup and are not counted as solves. Reopening the fine project to export views did not solve.

The preceding full offline regression recorded **252 passed, 20 skipped**, with `ruff check .`
passing. These are historical baseline results, not freshly executed tests for this presentation
replacement. Skipped integrations remain unexecuted and are not counted as passes.

**Overall engineering status remains WARN.** Global stress peaks require local engineering
interpretation, and no safety factor was calculated. Passing refers to the stated regression
criteria, not design approval.

## Model, loads, and environment

Sources are the [example](../../examples/gusseted-bracket/README.md),
[simulation.yaml](../../examples/gusseted-bracket/simulation.yaml),
[simulation brief](../../examples/gusseted-bracket/simulation_brief.md),
[geometry generator](../../examples/gusseted-bracket/generate_geometry.py), and
[CAD properties](../../examples/gusseted-bracket/geometry-properties.json).
This is an authored engineering regression model with explicitly defined test dimensions and loads.

- One connected solid with 34 CAD faces; overall size 240 × 160 × 188 mm.
- Back plate / shelf / rib thicknesses: 16 / 20 / 12 mm; eight 14 mm mounting holes.
- Inside bend R10, rib-profile rounds R6; eccentric bearing pad 70 × 60 × 8 mm.
- Full X-min rear-face clamp represents an ideal rigid mounting interface.
- Front-face force [1000, 1500, −500] N acts at [240, 0, 170] mm.
- Pad pressure 0.8 MPa over 4200 mm² produces 3360 N along −Z at [165, 35, 188] mm.
- Self-weight acts along −Z with gravitational acceleration 9.80665 m/s².
- CAD volume: 1,532,280.529125 mm³; centroid: [83.288077, 0.767483, 134.178550] mm.
  At 7850 kg/m³ the reference mass is 12.028402 kg and weight is 117.958330 N.

The recorded host used Windows 11, ANSYS Student Mechanical 2026 R1, explicit `mechanical_batch`,
Python 3.13.2, PyMechanical 0.13.2, PyDPF 0.16.1, and local DPF Server 11.0.
Actual `ds.dat` input confirms E = 200 GPa, Poisson ratio 0.3, density 7850 kg/m³, and SOLID187.
SURF154 is permitted for surface loading; independent DPF extraction confirms quadratic solid
topology. The committed specification uses an 8 mm nominal mesh; the study generates explicit
12 / 8 / 5 mm variants.

## Five recorded solves

| Case ID | Loading | Mesh mm | Nodes | Elements | Maximum displacement mm | Maximum equivalent stress MPa |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `mixed_12mm` | Force + eccentric pressure + self-weight | 12 | 7,452 | 3,890 | 0.019119825 | 8.987440 |
| `mixed_8mm` | Force + eccentric pressure + self-weight | 8 | 11,680 | 6,241 | 0.019221773 | 9.008833 |
| `mixed_5mm` | Force + eccentric pressure + self-weight | 5 | 27,980 | 15,508 | 0.019348617 | 9.040418 |
| `gravity_5mm` | Self-weight only | 5 | 27,980 | 15,508 | 0.000159944 | 0.084056 |
| `double_mechanical_5mm` | Twice force/pressure + unchanged self-weight | 5 | 27,980 | 15,508 | 0.038545872 | 18.016176 |

Values are rounded. The primary presentation case is `mixed_5mm`. Its bearing-pad largest
absolute Z component is −0.013381324 mm, mean Z displacement is −0.009268916 mm, and front-face
largest absolute Y component is +0.005086454 mm. Directional extrema retain their signs; they
are not face averages. Global equivalent stress is the maximum of nodal-averaged output and
is reported without using it as a strength acceptance condition.

## Independent engineering acceptance

### Force and moment balance: PASS

Pressure and weight resultants use CAD area, centroid, and volume. The selected Mechanical
faces are checked for position, area, and normal before DPF coordinates and reactions are aligned
by node ID to compute `ΣR` and `Σ(r × R)`. Moments use the global origin and N·m, with coordinates
converted to meters.

For the 5 mm combined-load case:

| Quantity | X | Y | Z |
| --- | ---: | ---: | ---: |
| Applied force resultant N | 1000.000000 | 1500.000000 | −3977.958330 |
| Support force resultant N | −999.999998 | −1500.000002 | 3977.967017 |
| Applied moment resultant N·m | −372.690531 | 854.224522 | 360.000000 |
| Support moment resultant N·m | 372.690562 | −854.224661 | −360.000000 |

Its relative force residual is 1.9891 × 10⁻⁶ and relative moment residual is 1.4196 × 10⁻⁷.
Across all five solves, the largest residuals are **0.007362% for force** and **0.001448% for
moment**, below the respective **0.5% and 1%** tolerances. Each relative residual is the norm
of the resultant residual vector divided by the norm of the corresponding applied vector.
Support resultants sum nodal vectors; they do not use the maximum single-node reaction.
Fixed-support displacement, nonempty mesh, result units, and finite-value checks also passed.

### Mesh-change criteria: PASS

Both consecutive refinements use `abs(fine - coarse) / abs(fine)`.

| Quantity | 12 → 8 mm | 8 → 5 mm | Tolerance |
| --- | ---: | ---: | ---: |
| Maximum total displacement | 0.5304% | 0.6556% | 5% |
| Bearing-pad mean Z displacement | 0.0713% | 0.7879% | 5% |
| Bearing-pad mean equivalent stress | 1.2553% | 2.5512% | 10% |
| Bearing-pad 95th-percentile equivalent stress | 2.3662% | 2.6099% | 10% |

At 5 mm the pad mean stress is 1.291825 MPa and its 95th percentile is 2.027259 MPa.
Pad statistics weight nodes equally; they are not area-weighted. Passing establishes that these
meshes and quantities meet the stated change thresholds. It does not establish a full-field error
bound or general convergence of peaks at fixed edges.

### Gravity-corrected full-field linearity: PASS

Let P denote front-face force and pad pressure, and G denote self-weight. The relation checked is
`u(2P+G) = 2u(P+G) − u(G)`. All three fine-mesh results have the same 27,980 node IDs, with zero
coordinate difference. Every node is compared using
`1e-12 m + 1e-6 × ||predicted displacement||`; no nodes fail.

The full-field relative L2 error is **1.8077 × 10⁻¹¹**, and the largest nodal absolute error is
1.5611 × 10⁻¹⁵ m. Because gravity is unchanged, the test does not simply double a maximum
displacement that includes self-weight.

## Execution failure and corrections

After the first solve in the initial serial attempt, DPF initialization inside the test process
changed the Python environment. Later Python 3.13 subprocesses read the ANSYS-bundled Python 3.10
standard library and failed with `AssertionError: SRE module mismatch`. That attempt reported
five failed tests; the original directories and logs were retained.

The bracket test now performs independent DPF checks in a separate Python worker with separate
DPF logs. Read-only checks against existing RST files confirmed that the parent environment was
unchanged before and after the worker. The final five-solve study then passed in a new directory.
Numerical tolerances were not relaxed; production compiler and default dry-run behavior were not
changed by that fix.

Geometry was generated with build123d 0.9.1; 0.11.1 failed while importing local system fonts.
ANSYS and CAD dependency ranges were unchanged. STEP Git attributes disable newline conversion
to preserve the geometry-properties SHA256 across checkouts.

## Images and modeling boundaries

Each case exported native mesh, total-deformation, and equivalent-stress PNGs. Review found that
a header-only PNG check could accept truncated files. Pillow was added to the development extra
for file-structure verification and complete pixel decoding, with regressions for a valid image,
a header-only image, and an image missing its end block. All 15 saved original exports passed
complete decoding after the correction; no solve was repeated for image verification. The
supplemental receipt is `png-decode-verification.json`; the three offline image tests passed.

Z-up and underside views were exported from the saved 5 mm project, with identical project SHA256
before and after. The recorded review of geometry, underside, mesh, deformation, and stress images
confirmed preserved ribs and holes, continuous mesh, largest displacement near the free end, and
stress hotspots near rib-to-shelf transitions. Image inspection does not replace numerical checks.
Its `visual-review.json` records the hashes of the images actually viewed; it is separate from the
CLI automatic `visual_review` status.

The full rear clamp represents a rigid backing. Mounting holes are geometry only; bolt preload,
contact, slip, and backing compliance are not solved. Ribs, plates, and pad form one continuous
solid; individual weld details are unresolved.

## Reproduction and retained evidence

The primary integration entry is
[test_engineering_bracket.py](../../tests/integration/test_engineering_bracket.py). Follow the
[example README](../../examples/gusseted-bracket/README.md) or
[Windows guide](../windows-testing.md). Real tests require explicit `ANSYS_AVAILABLE=1` and
`ANSYS_TEST_BACKEND=mechanical_batch`, serial execution, and a fresh output directory.

Local archived sources:

- `build/bracket-study-20260906-02/engineering-bracket0/`: final five solves, `study-summary.json`,
  nodal evidence, per-run checks, saved Mechanical projects, and RST files.
- `build/bracket-study-20260906-01/engineering-bracket0/`: unsuccessful first study evidence.
- `build/engineering-bracket-20260906-01/`: nominal trial, dry-run, doctor, both study JUnit files
  and terminal logs, offline regression, and supplemental image evidence.

These ignored local directories are not part of the public software package. Public JSON uses
a field allowlist for numerical values, statuses, and source hashes; it excludes private absolute
paths, licensing logs, Mechanical projects, and RST files.

## Recorded 5 mm presentation images

All images below are unchanged `fine-views` exports from the saved `mixed_5mm` project. The
homepage, cover, and example use this same case. Exported files are checked by SHA256 before
publication, without cropping or recoloring and without a new solve.

![Twin-rib bracket 5 mm mesh](../../examples/gusseted-bracket/demo/assets/mesh.png)

![Twin-rib bracket 5 mm total deformation](../../examples/gusseted-bracket/demo/assets/total-deformation.png)

![Twin-rib bracket 5 mm equivalent stress](../../examples/gusseted-bracket/demo/assets/equivalent-stress.png)

Images used courtesy of ANSYS, Inc. The
[geometry](../../examples/gusseted-bracket/demo/assets/geometry.png) and
[underside](../../examples/gusseted-bracket/demo/assets/underside.png) views show the solid, ribs,
and holes and contain no new simulated results.

## WARN and NOT_RUN

- All five runs retain `stress_singularity_review: WARN`; global peak stress is not a strength
  acceptance criterion.
- `safety_factor: NOT_RUN` reflects unspecified yield strength. Automatic `visual_review: NOT_RUN`
  remains unchanged; the separate recorded manual image review does not turn it into PASS.
- Generic CLI `reaction_balance: NOT_RUN` remains for mixed pressure/gravity loads. Separate
  study force and moment checks passed. Disabled `cantilever_analytical` also remains NOT_RUN.
- Other Mechanical versions and remote execution remain unverified. An earlier local gRPC
  handshake failed; this bracket study did not retest it.
- Mesh-change acceptance covers the two refinements and four quantities listed above, not a
  full-field error bound, general fixed-edge peak convergence, or design approval.
