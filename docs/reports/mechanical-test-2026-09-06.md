# Mechanical acceptance report — 2026-09-06

## Conclusion

The recorded local Windows `mechanical_batch` acceptance suite passed **9 cases across 5 real solves**, with zero failures, errors, or skips. JUnit records 194.345 seconds from `2026-09-06T02:42:49.859730-05:00`. Every solve has `synthetic=false`, a `SOLVED` manifest, and `POSTPROCESSED` numerical results. **Overall engineering status remains WARN for all five runs.**

The first real PyMechanical gRPC attempt failed; batch success does not establish gRPC recovery. Remote execution remains `NOT_RUN`. These results cover the recorded linear-static compiler workflow and its stated checks.

The historical default-suite baseline is **175 passed, 11 skipped in 11.03 seconds**. Publication checks are recorded separately in the [release preparation record](../release-preparation.md); the historical benchmark is not presented as a new solve.

## Environment and method

Recorded environment: ANSYS Student Mechanical 2026 R1, Windows 11 AMD64, CPython 3.13.2, PyMechanical 0.13.2, PyDPF 0.16.1, and DPF server 11.0. Product identity comes from the acceptance record; runtime versions and results were checked against final JSON and JUnit.

The benchmark uses a 200 × 20 × 40 mm steel beam, Young's modulus 200 GPa, a fixed X-min face, and a −1000 N Z load on the X-max face. All five runs contain 1077 nodes and 160 elements, with 10 mm global sizing and `program_controlled` element order.

Compilation, explicit local batch execution, independent DPF extraction, verification, and reporting were exercised serially. Template fixtures deliberately changed coordinates, forces, result scope/axis, and reaction binding; fresh processes read back saved outputs. Input-preservation claims refer to historical test assertions.

## Nine acceptance cases

| JUnit case | Run | Status | Seconds |
| --- | --- | --- | ---: |
| `test_real_cantilever` | R1 | PASS | 35.465 |
| `test_real_image_export[mesh.png]` | R1 reused | PASS | 0.001 |
| `test_real_image_export[total-deformation.png]` | R1 reused | PASS | 0.001 |
| `test_real_image_export[equivalent-stress.png]` | R1 reused | PASS | 0.001 |
| `test_real_raw_rst_inspect_and_report` | R1 reused | PASS | 3.269 |
| `test_real_pressure` | R2 | PASS | 34.591 |
| `test_real_gravity` | R3 | PASS | 35.379 |
| `test_real_template_synchronization[.mechdat]` | R4 | PASS | 42.889 |
| `test_real_template_synchronization[.mechdb]` | R5 | PASS | 42.706 |

Durations are JUnit case times, not isolated solver timings. PNG checks require a unique PASS export record, more than 33 bytes, valid PNG/IHDR headers, and positive dimensions. They independently cover R1 only; other image-export statuses come from JSON.

Raw-RST extraction matched baseline displacement, stress, and nodal reaction maxima with `rel=1e-8, abs=1e-12` in canonical units; reaction vectors used `rel=1e-8, abs=1e-6 N`. Report regeneration preserved summaries and RST hashes in the historical assertions.

Both template readbacks confirmed coordinate IDs 0, force `[0,0,-1000] N`, `ZAxis`, `Component` scope `TTA_SCOPE_LOAD_FACE`, and `BoundaryCondition` reaction binding to `fixed_support`.

## Numerical results and tolerances

Displayed values below are rounded. Directional displacement selects the largest absolute component among 37 load-face nodes while retaining its sign; it is not a face average. Stress is the maximum of `stress_eqv_as_mechanical` nodal-averaged output.

| Run | Tip component (mm) | Maximum total displacement (mm) | Maximum equivalent stress (MPa) | Maximum nodal reaction magnitude (N) |
| --- | ---: | ---: | ---: | ---: |
| R1 force | Z: −0.127583025482 | 0.128950635781 | 38.0902173163 | 1564.25967035445 |
| R2 pressure | X: −0.000995021458 | 0.000995586612 | 1.19715891066 | 59.1860091398 |
| R3 gravity | Z: −0.000592845373 | 0.000597726930 | 0.230504482861 | 9.53210636828 |
| R4 .mechdat | Z: −0.127583025482 | 0.128950635781 | 38.0902173163 | 1564.25967035445 |
| R5 .mechdb | Z: −0.127583025482 | 0.128950635781 | 38.0902173163 | 1564.25967035445 |

**Support resultants sum all 37 support-node reactions componentwise.** Their recorded principal components are R1/R4/R5 Z = `1000.0000000088805 N`, R2 X = `799.999999999942 N`, and R3 Z = `12.317152400047146 N`; transverse components are near zero. R1's `1564.2596703544452 N` is the maximum single-node magnitude at node 936, not the support resultant. Balance uses `canonical_sum_vector`, not `reported_maximum`.

- **Force:** `||R + [0,0,-1000]||₂ / 1000 ≤ 0.05`; recorded relative residual `1.1759996441626767e-11`. Euler–Bernoulli reference magnitude is approximately 0.125 mm; `abs(abs(actual)-expected)/expected = 0.020664203857241034`, or 2.0664%, against 15% tolerance. R4/R5 share these results.
- **Pressure:** `pA = 1 MPa × 800 mm² = 800 N`. Vector distance from `[800,0,0] N` must be ≤ 40 N; axial displacement is compared with −0.001 mm at 5% relative tolerance.
- **Gravity:** `ρVg = 7850 × (0.2 × 0.02 × 0.04) × 9.80665 = 12.3171524 N`. Vector error must be ≤ 5% of this weight. Displacement must be finite, negative, and expressed in meters; no analytical gravity-deflection tolerance was asserted.
- **Small deformation:** maximum displacement / 200 mm is 0.000644753179, 0.00000497793306, and 0.00000298863465 for force, pressure, and gravity respectively. All pass below 0.02; [0.02, 0.1) gives WARN, and ≥ 0.1 gives FAIL.

Pressure/gravity independent assertions passed, while generic `reaction_balance` and `cantilever_analytical` remain `NOT_RUN`. Their independent residual scalars were not separately archived.

## Failure-driven fixes

Python 3.11 installation failed against PyMechanical 0.13.2's Python ≥ 3.12 requirement. Recovered output confirms exit 1 but is truncated. The first real gRPC case failed after 604.240 seconds with CLI exit 4; connection probes, including grpcio 1.71.0, did not resolve it. Its precise root cause remains open. Batch was explicitly selected, never an automatic fallback.

Early batch failures exposed static-analysis enum, built-in material inventory, and result-scoping compatibility defects. The exact imported body name was corrected in the input. DPF extraction switched from an unavailable equivalent-stress property to `stress_eqv_as_mechanical`; a temporary missing batch-module import also interrupted inspection.

The first complete suite had 7 passes and 2 template failures. Subsequent fixes addressed IronPython Unicode conversion, read-only scoping, and clearing evaluated results before changing `Location`. An empty-text Error then identified an underdefined fixture coordinate system. Completing its definition enabled readback acceptance without weakening error checks. Native exit 0 had accompanied script failure, so structured status must also be checked.

## WARN and NOT_RUN

All runs retain `stress_singularity_review: WARN`, `safety_factor: NOT_RUN` because yield strength is absent from the v1 specification, and `visual_review: NOT_RUN`. Raw-RST engineering validation and specification recovery remain `NOT_RUN`.

Batch doctor retains `license`, `port`, `pymechanical`, and `transport` prechecks as `NOT_RUN`. Remote authentication, transfer/upload/download, live gRPC timeout/cancellation, mesh convergence, explicit element-order coverage, and other Mechanical versions remain unverified. Historical skips comprise nine opt-in real cases and two native symlink checks blocked by `WinError 1314`; those two remain `NOT_RUN`.

## Reproduction

Follow [Windows testing](../windows-testing.md) from the repository root:

1. Create a Python 3.13 environment and install `.[dev,ansys]`; provision Mechanical separately.
2. Copy the existing [specification](../../examples/cantilever/simulation.yaml) using the documented procedure, preserving geometry resolution and explicitly choosing `mechanical_batch`.
3. Run `doctor`, `validate`, and the default dry-run; require `DRY_RUN` and review generated inputs before execution.
4. For an explicitly requested solve, follow the documented `run --execute`, `inspect`, and `report` commands. For all nine cases, use the documented serial pytest invocation with `ANSYS_AVAILABLE=1` and `ANSYS_TEST_BACKEND=mechanical_batch`, restoring both variables afterward. Use fresh output and pytest directories.

## Public evidence and images

Public evidence: [summary](evidence/2026-09-06/summary.json), [cases](evidence/2026-09-06/cases.json), [JUnit](evidence/2026-09-06/junit.xml), [offline log](evidence/2026-09-06/offline.log), and [provenance](evidence/2026-09-06/provenance.json). The field-allowlisted snapshot retains exact numbers, check states, and source hashes while excluding host paths and licensing details. Verify it with `python tools/export_benchmark_evidence.py`.

## Next validation priorities

Before expanding compatibility claims, reproduce the gRPC handshake failure on a supported execution
host and exercise a second Mechanical version. Before using peak stress for design decisions, add a
mesh-refinement study and an engineering review of fixed-end and load-region stress concentrations.
Whether pressure/gravity resultants can be generalized safely, and whether explicit element-order
settings behave consistently, remain open implementation questions.

[Cantilever demonstration](../../examples/cantilever/demo/index.html). Original Student exports:

- [Mesh](../../examples/cantilever/demo/assets/mesh.png) — Images used courtesy of ANSYS, Inc.
- [Total deformation](../../examples/cantilever/demo/assets/total-deformation.png) — Images used courtesy of ANSYS, Inc.
- [Equivalent stress](../../examples/cantilever/demo/assets/equivalent-stress.png) — Images used courtesy of ANSYS, Inc.

Exports establish artifact availability; visual engineering review remains pending. Later interface captures do not substitute for solve images. Early manifests sometimes stop at `COMPILED`; empty logs, truncated outputs, and reused intermediate directories limit historical reconstruction. No missing timings, hashes, or failure details are inferred.
