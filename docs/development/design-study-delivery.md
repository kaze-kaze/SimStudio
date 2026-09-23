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
| Serial execution, restart, retries, locks and stale-result detection | Real Python child/timeout tests, fault injection and ownership recovery tests | Offline verified; Windows interruption acceptance NOT_RUN |
| Portable task/results bundles | Round trip, inventory hashes, path containment, duplicate-name and archive-limit tests | Offline verified |
| Physical checks, mesh study and per-target eligibility | Material, faces, RST binding, reaction, stress-review and per-target tests | Offline verified; new solver evidence NOT_RUN |
| Versioned datasets, exclusions and provenance | Dataset integrity, per-target eligibility and relocation tests | Offline verified |
| Response surface / GPR, persistence and out-of-domain behavior | Analytic numerical tests, serialization, grouped CV and independent scikit-learn reference | Offline verified |
| Budgeted optimization, active samples and candidate confirmation | Proposal identity, retry allowance, frozen partitions and verification tests | Offline verified; real candidates NOT_RUN |
| Independent accuracy and equal-budget comparison | Frozen model/test evidence, boundary/constraint error slices, confusion matrices and frozen comparison-ledger tests | Offline verified; real accuracy/cost comparison NOT_RUN |
| HTML / Markdown report with filters and evidence links | Report contract tests and interactive browser review | Offline verified |
| CLI, Skill, docs, example and distributions | Both Skill validators, sdist/wheel inventory and isolated installed CLI | Offline verified; Windows helper execution NOT_RUN |
| Cross-platform CI and single-run compatibility | Ruff, 520 passed / 15 skipped locally; Linux/Windows jobs configured | Local verified; hosted CI NOT_RUN |
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

- Current source suite: 520 passed, 15 skipped in 12.32 seconds. Skips are real ANSYS
  integration tests, not passes. The previous implementation commit `7bd2a45` recorded
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
  report-section module in the wheel and complete study sources in the sdist.
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
- Windows read-only inspection through the user-authorized remote desktop found the existing
  repository at the same base revision and a working Mechanical environment check with Python
  3.13.2, PyMechanical 0.13.2 and PyDPF 0.16.1. This is not a new solve or license acceptance.

## Remaining acceptance

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
