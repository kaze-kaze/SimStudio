# Eccentrically loaded gusseted equipment bracket

The primary engineering regression example with two rounded ribs, eight mounting holes, an
eccentric bearing pad, multiaxial force, pressure, and self-weight. The
[simulation brief](simulation_brief.md) defines dimensions, assumptions, and acceptance criteria.

The [2026-09-06 test report](../../docs/reports/mechanical-test-2026-09-06.md)
([简体中文](../../docs/reports/mechanical-test-2026-09-06.zh-CN.md))
records five passed integration tests across five real study solves in 208.16 seconds. The fine mesh has 27,980 nodes and 15,508 elements;
maximum displacement is 0.019348617 mm and reported global stress maximum is 9.040418 MPa.
Force/moment balance, mesh-change criteria, and full-field gravity-corrected linearity passed.
The engineering aggregate remains WARN for the stated stress-review limitations. The
[static demonstration](demo/index.html) displays all five cases, both mesh-refinement steps, and
three unchanged result views from `mixed_5mm`, with optional geometry and underside views.

The 252 passed / 20 skipped offline baseline belongs to the preceding validation round. Replacing
the public example does not create a new test or solve record. Public evidence remains available
at the stable [summary](../../docs/reports/evidence/2026-09-06/summary.json),
[cases](../../docs/reports/evidence/2026-09-06/cases.json), and
[provenance](../../docs/reports/evidence/2026-09-06/provenance.json) paths.

| Input | Value |
| --- | --- |
| Overall dimensions | 240 by 160 by 188 mm |
| Back / shelf / rib thickness | 16 / 20 / 12 mm |
| Hole diameter / count | 14 mm / 8 |
| Inside bend / rib profile radius | 10 / 6 mm |
| Material | Installed Structural Steel: E = 200 GPa, nu = 0.3, density = 7850 kg/m^3 |
| Backing | Full rear-face clamp, ideal rigid connection |
| Front-face force | [1000, 1500, -500] N at [240, 0, 170] mm |
| Pad pressure | 0.8 MPa; 3360 N downward at [165, 35, 188] mm |
| Self-weight | Earth gravity, -Z; mass and centroid from CAD |
| Reference mass | 12.028402 kg at 7850 kg/m^3 |
| Nominal specification mesh | 8 mm, explicit quadratic order |
| Study meshes / primary display | 12 / 8 / 5 mm; mixed-load 5 mm images |

This is one continuous solid. The ideal backing excludes bolt preload, slip, contact, and mounting
compliance. Ribs and plates transfer load continuously; individual weld stresses are not modeled.

## Inputs and dry-run

The committed STEP and its generated [CAD properties](geometry-properties.json) are ready to use.
CAD dependencies are required only to regenerate them. On the tested Windows host, use
`build123d==0.9.1` for regeneration (0.11.1 encountered a local system-font import error):

~~~powershell
./.venv/Scripts/python.exe -m pip install "build123d==0.9.1"
./.venv/Scripts/python.exe examples/gusseted-bracket/generate_geometry.py
~~~

From the repository root:

~~~powershell
./.venv/Scripts/python.exe -m ansys_skill.cli validate examples/gusseted-bracket/simulation.yaml --json
./.venv/Scripts/python.exe -m ansys_skill.cli run examples/gusseted-bracket/simulation.yaml --out build/bracket-dry-01 --json
~~~

The specification explicitly selects local Windows `mechanical_batch`. The command above remains
`DRY_RUN`. After reviewing inputs and explicitly choosing to solve on an installed, licensed host:

~~~powershell
./.venv/Scripts/python.exe -m ansys_skill.cli run examples/gusseted-bracket/simulation.yaml --out build/bracket-real-01 --execute --json
~~~

## Five-solve engineering study

Install the project's `dev` and `ansys` extras as described in
[Windows testing](../../docs/windows-testing.md). The development extra includes Pillow for
complete PNG structure verification and pixel decoding.

The integration study performs three combined-load solves on 12, 8, and 5 mm quadratic meshes,
then gravity-only and doubled force/pressure solves on the 5 mm mesh. Gravity stays constant.

| Recorded case | Nodes | Elements | Max displacement mm | Max equivalent stress MPa |
| --- | ---: | ---: | ---: | ---: |
| `mixed_12mm` | 7,452 | 3,890 | 0.019119825 | 8.987440 |
| `mixed_8mm` | 11,680 | 6,241 | 0.019221773 | 9.008833 |
| `mixed_5mm` | 27,980 | 15,508 | 0.019348617 | 9.040418 |
| `gravity_5mm` | 27,980 | 15,508 | 0.000159944 | 0.084056 |
| `double_mechanical_5mm` | 27,980 | 15,508 | 0.038545872 | 18.016176 |

It checks CAD-based force and moment balance, displacement convergence, pad stress statistics,
whole-field linear superposition, native images, solver element/material settings, and input hashes.
Force and moment relative tolerances are 0.5% and 1%. Both consecutive mesh refinements must
meet 5% displacement and 10% pad stress-statistic thresholds. Pad mean and percentile statistics
weight nodes equally, not by area. The 8 → 5 mm maximum-displacement change is 0.6556%.
Full-field relative L2 error is 1.8077 × 10^-11, with no failing nodes at the stated per-node
`1e-12 m + 1e-6 × ||predicted displacement||` tolerance.

Run serially with explicit opt-in and a fresh `--basetemp` directory:

~~~powershell
$previousAvailable = $env:ANSYS_AVAILABLE
$previousBackend = $env:ANSYS_TEST_BACKEND
try {
    $env:ANSYS_AVAILABLE = "1"
    $env:ANSYS_TEST_BACKEND = "mechanical_batch"
    ./.venv/Scripts/python.exe -m pytest -q tests/integration/test_engineering_bracket.py --basetemp build/bracket-study-01 --junitxml=build/bracket-study-01.xml
}
finally {
    $env:ANSYS_AVAILABLE = $previousAvailable
    $env:ANSYS_TEST_BACKEND = $previousBackend
}
~~~

Pytest owns its temporary directory; choose a new path for each study. Each run retains
`engineering-checks.json`, ordinary CLI reports, RST, saved Mechanical project, and solver logs.
The study directory contains `study-summary.json`. An ordinary offline `pytest -q` skips real
integration tests and starts no solver.

The general CLI still reports pressure/gravity `reaction_balance: NOT_RUN`; this fixture's separate
checks supply the independently calculated resultants. `safety_factor` and automatic
`visual_review` remain `NOT_RUN`; the recorded manual image review is separate. Global peak stress retains a review warning
and is not a strength acceptance criterion. Compare the entire displacement field as
`u(2P+G) = 2u(P+G) - u(G)`; do not simply double displacement maxima that include self-weight.

`export_views.py` is an optional fixed Mechanical script for reopening a solved project and exporting
Z-up and underside views. It requires `ANSYS_AVAILABLE=1`, `BRACKET_VIEW_PROJECT` (absolute saved
project path), and `BRACKET_VIEW_OUTPUT` (new directory). It neither solves nor saves the project.
