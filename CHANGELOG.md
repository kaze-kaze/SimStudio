# Changelog

## 0.1.0 — Alpha — 2026-09-06

This entry describes the Alpha source-release candidate and its recorded local acceptance.
It does not assert that a public tag, package upload, hosted CI run or site deployment has completed.

### Compiler and explicit execution

- Deterministic, reviewable compilation of `simulation.yaml` into normalized input, a Mechanical
  plan and a saved Mechanical script for the supported linear-static structural scope.
- Validation, environment checks, compilation, dry-run, explicitly requested execution,
  independent DPF extraction, verification and reporting through the `ansys-sim` CLI and Codex
  Skill. Dry-run remains the default; a solve requires `--execute`.
- Explicit local Windows `mechanical_batch` execution, with no automatic fallback from gRPC.
  Batch execution checks both process exit code and structured solve status, requires result
  files, confines reported paths to the run directory, and targets its owned process tree on
  timeout. Offline tests cover these boundaries without starting Mechanical.

### Compatibility fixes driven by real runs

- Adapted the Mechanical compatibility layer to the observed static-analysis enums,
  `ANSYSAnalysisSettings` type and passive entries in the built-in Structural Steel inventory.
  The benchmark uses the observed imported body name `CantileverBeam|Solid`.
- Cleared evaluated generated results before updating locations; synchronized force and result
  coordinates, displacement direction/scope and support-reaction binding in saved templates.
- Preserved localized diagnostics with IronPython Unicode conversion and message-source
  information. Corrected an underdefined fixture coordinate system without suppressing errors.
- Extracted nodal-averaged equivalent stress through DPF `stress_eqv_as_mechanical` instead of
  assuming an unavailable result attribute. Support resultants use componentwise reaction sums;
  the largest single-node reaction is reported separately.
- Documented the Python 3.12+ requirement of PyMechanical 0.13.2 separately from the base CLI's
  declared Python 3.11–3.13 range. Development dependencies include the local build tools.

### Recorded acceptance and limits

- The September 6, 2026 Windows acceptance on ANSYS Student Mechanical 2026 R1, CPython 3.13.2,
  PyMechanical 0.13.2 and PyDPF 0.16.1 recorded **9 passing cases across 5 real batch solves**,
  with zero failures, errors or skips in that final real suite (194.345 seconds in JUnit).
  Cases cover force, pressure, gravity, three image exports, raw-RST inspection/reporting and
  `.mechdat` / `.mechdb` template synchronization/readback.
- The force case's signed tip-Z displacement was approximately −0.127583 mm, 2.0664% from the
  0.125 mm analytical magnitude within the recorded 15% tolerance. The support-Z resultant was
  approximately 1000.000000009 N. All five meshes had 1077 nodes and 160 elements.
- **Overall engineering verification remains `WARN` for all five runs.** Stress-singularity
  review remains `WARN`; safety factor and visual engineering review remain `NOT_RUN`.
  Independent pressure/gravity benchmark assertions passed, while their generic
  `reaction_balance` and `cantilever_analytical` checks remain `NOT_RUN`.
- The initial real local gRPC handshake failed; batch acceptance does not establish gRPC
  recovery. Remote transport/authentication, other Mechanical versions, mesh convergence and
  explicit element-order overrides remain unverified.
- The historical offline baseline is **175 passed, 11 skipped in 11.03 seconds**. Later local
  publication checks are documented separately; neither the historical baseline nor an updated
  test count represents a new licensed solve or a successful hosted CI matrix.

See the [English test report](docs/reports/mechanical-test-2026-09-06.md),
[Simplified Chinese test report](docs/reports/mechanical-test-2026-09-06.zh-CN.md) and
[Windows acceptance record](docs/windows-acceptance-2026-09-06.md) for full methods and limitations.

### Public presentation and release packaging

- English and Simplified Chinese project READMEs, a project cover, and static-site sources with
  a report template and a Markdown-to-site builder. Optional site scripts, SVG assets,
  documentation and a site checker are included when present.
- An offline-capable cantilever viewer with three original Mechanical images, source YAML and
  STEP links, plus bilingual test reports and field-allowlisted JSON/JUnit evidence. Original
  source hashes, published-file hashes, measured values and historical report data are retained.
  The cover and presentation pages do not add solver evidence.
- Source packages include the Skill, benchmark, reports, evidence and presentation sources.
  The wheel is CLI-only with runtime code and package metadata/licenses. The release source ZIP
  is derived from the checked sdist rather than the working tree.
- Distribution checks enforce required public sources, reject private solver artifacts and
  unsafe archive members, and keep optional presentation files optional. Private `build/` and
  `test-records/` content is excluded from public packages.

See [release preparation](docs/release-preparation.md) for package checks, evidence preservation
and the distinction between observed local verification and hosted publication.
