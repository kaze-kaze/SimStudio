# Windows Mechanical acceptance — 2026-09-06

## Result

**The explicit local `mechanical_batch` workflow passed all 9 real acceptance cases.**
Five licensed Mechanical solves were performed by the final suite, followed by independent PyDPF
extraction and saved-project readbacks. Results are real (`synthetic: false`). Local PyMechanical
gRPC failed at handshake and is not covered by the batch success.

| Environment | Observed value |
|---|---|
| Host | Windows 11, AMD64 |
| Mechanical | ANSYS Student 2026 R1; executable file version `26,2026,13,1` |
| Product API | `Project.ProductVersion == "2026 R1"` |
| Python | CPython 3.13.2 |
| PyMechanical / PyDPF | 0.13.2 / 0.16.1 |
| DPF server | 11.0, client-managed `InProcessServer` |
| Real execution | Explicit `mechanical_batch`, with `--execute` |
| Original desktop session | Preserved; test batch processes owned and exited by their runs |

## Final verification

| Check | Observed result |
|---|---|
| `ruff check .` | PASS |
| `pytest -q` with real execution opt-in unset | 175 passed, 11 skipped |
| Explicit real suite with `ANSYS_AVAILABLE=1`, `ANSYS_TEST_BACKEND=mechanical_batch` | 9 passed in 194.35 seconds |
| Unit-test skips | 2 native symlink checks: Windows `WinError 1314`, recorded as NOT_RUN |
| Other default-suite skips | 9 real cases intentionally require the explicit opt-in; they passed in the separate real suite |
| Final diff whitespace check | PASS |

The nine real cases are the cantilever numerical check, three image checks, raw-RST inspection and
report regeneration, pressure, gravity, and `.mechdat` / `.mechdb` template synchronization. The
original numerical acceptance tolerances were retained. See [Windows testing](windows-testing.md)
for the reproducible commands, backend choice, fresh output directories, and environment restoration.

## Numerical evidence

All five final meshes contain **1077 nodes and 160 elements**. The beam is
`200 mm x 20 mm x 40 mm`, with exact Engineering Data material `Structural Steel`. Material density
was independently read in Mechanical as `7850 kg/m^3`; body mass was `1.25599999999 kg`.

| Case / quantity | Measured value | Acceptance |
|---|---:|---|
| Force cantilever, tip Z | -0.127583025483 mm | PASS; 2.0664% from the 0.125 mm Euler-Bernoulli reference, tolerance 15% |
| Force cantilever, maximum total deformation | 0.128950635781 mm | PASS; deformation/length ratio 0.000644753 |
| Force cantilever, support reaction Z sum | 1000.000000009 N | PASS; relative force residual 1.176e-11, tolerance 5% |
| Force cantilever, nodal equivalent-stress maximum | 38.0902173163 MPa | Extracted with Mechanical-compatible nodal averaging; agrees with exported plot |
| Pressure, 1 MPa on X-max face, reaction X sum | 799.999999999942 N | PASS against pressure times 800 mm^2 face area |
| Pressure, tip X | -0.000995021458 mm | PASS against -0.001 mm axial reference, tolerance 5% |
| Gravity, -Z at 9.80665 m/s^2, reaction Z sum | 12.317152400047 N | PASS against density times volume times gravity, tolerance 5% |
| Gravity, tip Z | -0.000592845373 mm | PASS; finite and in the expected direction |
| Both template formats, tip Z and support reaction | Same as the force cantilever | PASS |

Reaction sums above are support resultants, not the largest individual nodal reaction. The general
validator deliberately retains `reaction_balance: NOT_RUN` for pressure/gravity; those cases use
independent benchmark assertions for `p A` and `rho V g`. No unsupported general load-resultant
inference was added.

## Template and artifact evidence

The template fixture starts from the solved beam and deliberately sets a fully defined coordinate
system rotated 90 degrees about X, different force components, an X-direction result scoped to the
fixed face, and a reaction linked to an alternate suppressed support. A fresh Mechanical process
reads each saved output and confirms:

- force coordinate system ID 0 and components `[0, 0, -1000] N`;
- displacement coordinate system ID 0, Z axis, and `TTA_SCOPE_LOAD_FACE` with Component scoping;
- reaction coordinate system ID 0 and BoundaryCondition location bound to `fixed_support`;
- original template, compiled input snapshot, and original baseline project hashes are preserved.

Mesh, total-deformation, and equivalent-stress images passed per-file PNG signature, header/dimension,
and non-empty checks. Raw-RST inspection extracted displacement, stress, and reactions with no missing
providers; values and mesh counts matched the original run. Report regeneration preserved the RST
hash and numerical summary.

## Changes driven by actual failures

1. **Python extra compatibility:** PyMechanical 0.13.2 requires Python 3.12 or later; document the
   narrower extra range while retaining Python 3.11 for the base offline CLI.
2. **Execution path:** add explicit local Windows batch execution. Require the structured result
   artifact as well as exit code; native script failures were observed with executable exit code 0.
3. **Native API contracts:** accept the actual `Static` / `Mechanical` analysis enums and
   `ANSYSAnalysisSettings` object type. Use the observed exact imported body name `CantileverBeam|Solid`.
4. **Material inventory:** retain the linear-material guard while accepting the passive Appearance,
   Material Unique Id, Resistivity, and Relative Permeability entries in v261 Structural Steel.
5. **Saved result updates:** clear generated results before editing locations; let `Location` update
   Geometry/Component scoping. Preserve global-coordinate, direction, scope, and reaction binding checks.
6. **Localized diagnostics:** use IronPython's Unicode constructor and retain message source object
   names/types. An empty error message was traced to an underdefined coordinate system in the test
   fixture; its origin was explicitly defined. The error check was not suppressed.
7. **DPF:** compute equivalent stress from the stored tensor using `stress_eqv_as_mechanical`; a
   normal RST did not expose the previously assumed equivalent-stress result attribute.

## Saved local evidence

A [public test report](reports/mechanical-test-2026-09-06.md),
[field-allowlisted evidence snapshot](reports/evidence/2026-09-06/summary.json), and
[static demonstration](../examples/cantilever/demo/index.html) now provide portable evidence.
The original complete records described below remain local.

Evidence remains under the ignored build directory; proprietary product files and local license
details are not committed. Relative paths from the repository root:

- `build/windows-acceptance-final-20260906.xml`: final JUnit record, 9 tests, no failures or skips;
- `build/windows-acceptance-final-20260906.log`: final real-suite output;
- `build/windows-acceptance-final-20260906/real-cantilever0/run/`: full final cantilever artifacts;
- `build/windows-acceptance-final-20260906/test_real_pressure0/run/` and `test_real_gravity0/run/`;
- `build/windows-acceptance-final-20260906/test_real_template_synchroniza0/` and
  `test_real_template_synchroniza1/`: source templates, seed/readback JSON, snapshots, and results;
- `build/offline-final.log`: final default-suite output;
- `build/live-initial.log`, `build/grpc-handshake.log`, and `build/grpc-server-stderr.log`:
  initial failed gRPC test and handshake diagnostics.

The redistributable STEP input SHA-256 is
`af9d6111c31ee448916d0c29e0361a9307265bf1f45c3333bd71d3a199fb56db`. Each run manifest records
its own input, source-specification, normalized-specification, and generated-script hashes.

## Evidence boundaries

The tested Student installation's gRPC listener checked out a license but closed HTTP/2 connections
during handshake. The initial integration test failed after 604.24 seconds with CLI exit code 4.
Legacy startup, WNUA-client, and an older grpcio probe also failed. No change to installed product
binaries or security settings was made. Remote transport, authentication, upload/download, and live
gRPC timeout cancellation remain NOT_RUN; batch timeout handling has offline ownership tests.

These runs do not establish other Mechanical versions, nonlinear behavior, arbitrary assemblies,
custom material authoring, mesh convergence, or a safety factor. Explicit mesh element-order overrides
were not exercised. Expected overall verification remains WARN because stress-singularity review
requires judgment; automatic visual review and safety-factor checks remain NOT_RUN.
