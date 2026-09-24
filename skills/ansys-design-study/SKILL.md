---
name: ansys-design-study
description: Plan, execute, audit, and report bounded surrogate-assisted parameter studies for SimStudio's controlled gusseted-bracket geometry using ANSYS Mechanical linear-static solves. Use for study.yaml workflows, sample budgets, RST-bound stress review, portable task bundles, safe surrogate models, and candidate verification. This is a separate capability from one-off Mechanical simulations and does not cover arbitrary CAD families, CFD, nonlinear or transient physics, or autonomous design approval.
license: MIT
---

# ANSYS Mechanical design studies

Use this Skill for the repository's independent `ansys-sim study` and `ansys-sim surrogate` workflow. It covers only the versioned, unit-aware gusseted-bracket study contract. The study implementation and offline checks exist in the source tree; complete real Windows/Mechanical acceptance remains pending. Do not claim real-data accuracy, mass reduction, or speed improvement without accepted, reproducible evidence.

## Route the request

- For repeated parameterized bracket samples, study datasets, surrogate proposals, RST review, task transfer, or equal-budget comparison, read the relevant sections of [the CLI and workflow contract](references/workflow.md).
- For fields, dimensions, parameter bounds, sampling, targets, and budgets, read [the specification reference](references/specification.md).
- For real-run eligibility, stress singularity review, candidate verification, and claims, read [the quality and evidence reference](references/quality-evidence.md).
- For import/export, interruption recovery, code fingerprints, and Windows operation, read [the portability reference](references/portability-windows.md).
- For training, holdout evaluation, predictions, and search comparisons, read [the surrogate reference](references/surrogates.md).

Route ordinary single-run simulations to $ansys-mechanical-static. Do not turn a single static simulation request into a design study unless the user wants a parameterized campaign. Unsupported physics or arbitrary geometry require a separate workflow.

## Operate the study

Inspect the user's inputs and current study directory first. Preserve existing attempt records, generated evidence, and unrelated edits. Use `study init` only for a new/empty input directory, `study validate` on `study.yaml`, and `study plan` to create a fresh plan directory. `study plan` freezes the portable plan; CAD is generated later while `study run` prepares samples. The paired `base-simulation.yaml` is a study-owned template: never pass it to the ordinary single-run `validate`, `compile`, or `run` commands.

Default to `--json` and dry-run. `study run` without `--execute` prepares sample CAD and per-mesh inputs and invokes the ordinary workflow in dry-run mode; use `--limit` to bound preview work. A real solve requires an explicit user request and the explicit `--execute` switch. Respect the one study-wide solver-call ceiling, wall-time limit, retries, the requested sample limit, and the selected platform. The example's `max_solver_calls: 400` covers the initial plan, adaptive additions, candidate re-solves, retries, and the equal-budget direct-search comparison; its current initial plan uses 120 calls. Once the user authorizes a bounded study batch, continue that batch within its declared limits without asking them to approve each sample. Do not use resume to expand the authorized budget or scope.

Before collecting data, confirm that every proposed training/verification RST exists and remains hash-verified. Use `study collect --reviews FILE` for stress targets and preserve per-target exclusions. Missing stress review means `REVIEW_REQUIRED`; never infer the review from a plot or ask for per-sample reauthorization. Continue to training only when the dataset actually meets the study's eligibility counts. Finish training-set optimization, adaptive sampling, and every refit before calling `surrogate evaluate` once on the final model. That consumes the frozen holdout and prevents retraining/adaptation in this study. A NOT_RUN evaluation returns exit code 6 and is not success.

Generate reports from recorded artifacts, distinguish plan/preview/solve/model/engineering states, and report exact output paths. Prediction is not a solve. Model files are JSON, not pickle. Candidate proposals require explicit confirmation solves and recorded engineering evidence; a direct-search advantage is reportable only after the configured same-call-budget comparison completes.

## Report honestly

State whether CAD generation, preview, real Mechanical execution, data collection, attributable stress review, frozen holdout evaluation, candidate confirmation, and direct-search comparison each ran. Use `NOT_RUN`, `REVIEW_REQUIRED`, `NEEDS_SOLVE`, `WARN`, or failure states as recorded; do not promote a partial workflow into a completed engineering study. Keep demonstration limits distinct from product requirements. In the supplied example, 10 MPa is an authored response constraint, not a material allowable or certification criterion.

For Windows task transfer or real acceptance, follow [the portability reference](references/portability-windows.md). A transferred task must match the creating study's code fingerprint. The fingerprint normalizes CRLF to LF, so Windows line endings alone do not change code identity. Documented historical build123d/font behavior is not current compatibility evidence; report the live host result and leave unverified behavior explicit.
