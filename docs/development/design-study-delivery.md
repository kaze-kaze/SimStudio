# Design-study delivery audit

This development record tracks the complete surrogate-assisted design workflow. It does not
declare unfinished features or unavailable Mechanical integrations to be released or verified.
The source design is the September 23, 2026 implementation proposal approved in the task.

## Requirements and evidence

| Requirement | Completion evidence | Current state |
| --- | --- | --- |
| Versioned study specification, units, dependencies and budgets | Schema, parameter validation and budget tests | Offline verified |
| Controlled parametric single-solid bracket and stable faces | Boundary CAD tests and generated baseline STEP | Offline verified; Mechanical import NOT_RUN |
| Deterministic sampling and independent grouped test data | LHS reproducibility, invalid-corner handling and leakage regression tests | Offline verified |
| Serial execution, restart, retries, locks and stale-result detection | Real Python child/timeout tests, nested-process refusal, fault injection and ownership recovery tests on CI | Offline verified; Mechanical interruption acceptance NOT_RUN |
| Portable task/results bundles | Round trip, inventory hashes, path containment, duplicate-name and archive-limit tests | Offline verified |
| Physical checks, mesh study and per-target eligibility | Material, faces, RST binding, reaction, stress-review and per-target tests | Offline verified; new solver evidence NOT_RUN |
| Versioned datasets, exclusions and provenance | Dataset integrity, per-target eligibility and relocation tests | Offline verified |
| Response surface / GPR, persistence and out-of-domain behavior | Analytic numerical tests, serialization, grouped CV and independent scikit-learn reference | Offline verified |
| Budgeted optimization, active samples and candidate confirmation | Proposal identity, retry allowance, frozen partitions and verification tests | Offline verified; real candidates NOT_RUN |
| Independent accuracy and equal-budget comparison | Frozen model/test evidence, boundary/constraint error slices, confusion matrices and frozen comparison-ledger tests | Offline verified; real accuracy/cost comparison NOT_RUN |
| HTML / Markdown report with filters and evidence links | Report contract tests and interactive browser review | Offline verified |
| CLI, Skill, docs, example and distributions | Both Skill validators, sdist/wheel inventory, isolated installed CLI and PowerShell protocol tests | Offline verified; target-machine offline acceptance failed as recorded below |
| Cross-platform CI and single-run compatibility | Ruff, 593 passed / 19 skipped locally; previous six Linux/Windows CI jobs passed | Hosted offline verification passed; licensed integrations NOT_RUN |
| Complete real engineering study | Real dataset, model, holdout, candidate RSTs and direct-search control | NOT_RUN |

## Working baseline

- Base commit: `e4ddbc5` (engineering gusseted bracket already exists).
- Baseline after installing the declared development dependencies: 283 passed, 14 skipped.
- Baseline Ruff: passed. No Mechanical solver was started.
- Branch: `codex/design-study-workflow`.

## Implementation decisions

- Extend the existing Python package with `study`, `surrogate` and optimization modules.
- Preserve the original single-run specification, stable JSON and exit codes.
- Use the existing gusseted bracket as the controlled geometric family.
- Parameters use canonical SI values internally: plate thickness, hole diameter and root fillet.
- Keep numerical quality, design feasibility, execution state and model evidence separate.
- A predictive model is never a Mechanical backend. Prediction cannot start a solver.
- Real execution remains explicit and budgeted; ordinary tests require no solver or network.
- Real engineering completion requires live evidence; historical bracket results are not a new
  parametric dataset or a new acceptance run.

## Current verification record — September 23, 2026

- Current source suite: 593 passed, 19 skipped in 17.74 seconds. The skips are 15 real ANSYS
  integration tests and four PowerShell tests unavailable on this macOS host, not passes.
  All four PowerShell protocol tests subsequently passed on hosted Windows CI.
  The previous implementation commit `7bd2a45` recorded
  471 passed / 15 skipped before this audit hardening.
- The current suite used a dedicated Python 3.13.12 environment with an absolute
  `PYTHONPATH` bound to this checkout. A shared environment changed during parallel work;
  earlier checks that imported its installed package are not current-source evidence.
- Ruff and whitespace/diff checks passed. One deliberate duplicate-ZIP test emits a warning.
- GPR mean/standard-deviation calculations agree with independent scikit-learn reference kernels.
- The installed wheel is loaded from a fresh environment under isolated Python startup; study
  initialization, a 40-design / 120-initial-call plan and a baseline three-mesh dry-run succeeded.
- The installed report/collection and task export/import round trip succeeded with matching identity.
- The fresh installed-wheel environment resolved build123d 0.13.0, NumPy 2.5.3, SciPy 1.18.1
  and scikit-learn 1.9.1. Its imported code fingerprint matched the source-tested revision.
- Package inventory validation includes the new backend timer, generated-runtime timer and
  report-section module, plus the shared Windows process probes, in the wheel and complete
  study sources in the sdist.
- The dry-run has zero solver calls. No generated synthetic or preview value became a training label.
- Active-work accounting includes preparation, single-run execution, collection, training, search
  and evaluation. Waiting for a review is excluded; no backend phase duration is fabricated.
  New runs record Mechanical mesh/solve and CLI backend/postprocessing/report durations.
  Parent activities include their child timings and must not be counted twice.
- Model schema 1.1 binds frozen test designs. The first complete holdout evaluation commits
  the model content ID and test-label/source-evidence hash; subsequent changes are rejected.
- Required numerical checks and selected-face evidence cannot be omitted. Dataset and model
  cards preserve the engineering context, and reports include error slices, confusion matrices,
  constraint margins and separately identified observed versus independently verified designs.
- Direct-search allowance is bound to the research design and attempt ledger. Recorded workflow
  conclusions are invalidated when their supporting ledger or small result artifacts change.
- Both CLI and nested Mechanical owners record process-tree scope. Unverified child trees block
  batch result acceptance, recovery, automatic retries and resumed execution. Process enumeration
  failures remain blocking errors; an exited parent is not sufficient evidence of a stopped tree.
- Windows read-only inspection through the user-authorized remote desktop found the existing
  repository at the same base revision and a working Mechanical environment check with Python
  3.13.2, PyMechanical 0.13.2 and PyDPF 0.16.1. This is not a new solve or license acceptance.

## Hosted verification

[CI run 35929797804](https://github.com/kaze-kaze/SimStudio/actions/runs/35929797804)
passed all six jobs for runtime/test commit `1a38fcdb8f06c98d38cd7a6be68c9c3ec8cbf2ca`
on September 23, 2026:

- Base offline checks on Ubuntu and Windows with Python 3.11 and 3.13.
- Study/CAD/numerical checks plus init, validation, planning, dry-run and report commands on
  Ubuntu and Windows with Python 3.13. The Windows study job recorded 307 passed, including
  all four PowerShell protocol cases; no test in that job was skipped.
- The Windows Python 3.13 base job recorded 467 passed, 56 optional-dependency skips, and
  15 deselected ANSYS integrations. Study dependencies and their tests run in the separate
  study job. Release packaging now installs the study dependencies as well.

The first CI run exposed two recovery fixtures that always wrote POSIX ownership records.
Those fixtures now use the platform's actual contract while retaining their refusal assertions.
The subsequent nested-process correction above was validated in the linked successful run.
The changes remain in [draft PR #3](https://github.com/kaze-kaze/SimStudio/pull/3), without
merging or publishing a new release. Hosted runners have no licensed Mechanical acceptance.

## Remaining acceptance

### Target Windows preparation — September 23, 2026

The r3 package checksum and source commit passed, the isolated environment was installed, and
doctor and Ruff passed. The actual offline suite recorded 513 passed, one failed, eight errors
and six explicit symbolic-link privilege skips (528 collected; ANSYS integrations excluded).
The eight errors came from build123d 0.11.1 importing an unsupported system font; the former
dependency range allowed that version despite the development host using 0.13.0. The CAD extras
now require 0.13.x, whose font loader handles `TTLibError`. The one test failure directly created
a symbolic link without the existing Windows privilege-aware fixture; it now uses that fixture
and retains its real symlink and failed-attempt assertions. The corrected checkout needs a new
target-machine offline run before real acceptance. No Mechanical solver call occurred.

### Outstanding evidence

The corrected Windows environment subsequently recorded 521 passed and seven explicit
symbolic-link privilege skips (528 cases, no failures/errors); the focused check recorded
31 passed and one skip. The original two-design/three-mesh integration test then passed in
233.41 seconds with six successful solver calls and no retries. Its 130.73 MiB results bundle
was transferred and imported with matching study identity, code fingerprint, and payload hashes.

This is execution/portability acceptance, not complete engineering acceptance: collection
rejected both designs because the original face gate compared tessellation-based Mechanical
area/centroid values against exact CAD measurements. An independent read-only inspection of
copies of both saved projects confirmed that analytic curve boundaries match the CAD under
the original strict tolerances. The compiler and quality gate now preserve and measure those
boundaries; the integration test also requires face geometry and material density to pass.
Corrected-runtime solver acceptance is still pending. All later work shares the original
400-call authorization; a new code fingerprint must not reset that allowance. No stress review
or surrogate accuracy claim is established yet.

Four read-only Mechanical starts have now inspected saved project copies without regenerating
meshes or solving. Mesh APIs returned complete native statistics; the original fine meshes
have shape warnings, while maximum-edge-length failure counts conflict with both recorded
limits and worksheet color. Applicable shape checks now validate metric completeness and
consistency. Warnings require an explicit target review bound to the exact RST and raw quality
hash; failures and missing evidence remain blocking. Size-diagnostic inconsistencies are
retained. The original area/centroid tolerances remain unchanged.

A separate three-solve baseline diagnostic tested 2 mm rib-end edge blends under the original
loads, material and 12/8/5 mm meshes. All three solves completed, but the geometry change was
rejected: nodal peak stress rose to 18.40/20.15/19.73 MPa; unaveraged elemental-nodal peaks were
56.80/49.73/61.84 MPa, and the coarse/intermediate meshes reported shape errors. This pilot is
not a training dataset. Its checksummed result archive and all 118 payload hashes were verified
after transfer. New DPF stress diagnostics were exercised against its three real RST files,
including global hotspot coordinates, the exact RST hash and preserved element-local values.

The cumulative authorization ledger is **9 solver attempts + 4 read-only Mechanical starts =
13/400**, leaving at most 387 further starts for all later studies and diagnostics. No retry
occurred in these nine solves. The complete real training, holdout, optimization and comparison
workflow remains unaccepted. The failed geometry pilot is retained as evidence, not promoted
into the controlled generator.

1. Run the offline suite and PowerShell entry point on the actual Windows installation.
2. Complete the opt-in two-design / three-mesh solver acceptance, inspect material and faces,
   verify recovery and export/import real evidence without changing its hashes.
3. Obtain the planned real dataset, assess global stress hotspots and mesh sequences, then
   train and adapt only on training data before committing the final model to the holdout.
4. Complete independently qualified candidate solves and the equal-allowance direct control.
   Record unsuccessful gates as such; do not alter thresholds merely to pass a case.
5. Publish real acceptance evidence and performance claims only after those runs exist.

The original design proposal is retained in `design-study-design.zh-CN.md`. The first real
engineering study may expose mesh or software compatibility issues that offline tests cannot
prove absent. Passing the local suite is not the final release decision.
