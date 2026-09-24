# Study CLI and workflow contract

The root command is `ansys-sim`; all `study` and `surrogate` actions support `--json`. Preserve structured stdout and exit-code behavior. Progress is written to stderr. See the live parser in `ansys_skill.study.cli` when a flag or command contract is unclear.

## Lifecycle

1. `study init DIR` writes starter `study.yaml` and `base-simulation.yaml`; DIR must be new or empty.
2. Review both inputs, then `study validate STUDY.yaml` checks their compatibility and sample constraints without a solver.
3. `study plan STUDY.yaml --out DIR` freezes the sampling plan, budgets, fingerprints, manifest, and normalized portable input copies. It does not build CAD.
4. `study run DIR [--limit N]` prepares parameterized geometry and per-mesh simulation YAML, then creates normal single-run dry-run artifacts. Add `--execute` only for explicitly authorized Mechanical calls. Jobs execute serially. `--limit` caps additional design points.
5. Use `study status DIR` to inspect progress. `--resume` is required when continuing execution with existing attempts. `study recover DIR` verifies the local lock owner and every recorded owned Mechanical process have stopped; it then releases the lock and marks abandoned `RUNNING` attempts `INTERRUPTED`, leaving their records for audit and a new attempt. It cannot prove a process on another host has stopped.
6. `study collect DIR [--reviews FILE]` verifies saved artifacts and creates immutable, versioned JSON/CSV data with per-target eligibility and exclusion reasons.
7. Train a surrogate, then complete adaptive sampling/optimization and all model refits against training data. After adaptation is finished, run `surrogate evaluate DIR` once on the final model and frozen holdout. Evaluation consumes that holdout and blocks later retraining/adaptation. A NOT_RUN payload returns CLI exit code 6 and is not evaluation success.
8. `study verify DIR` confirms candidates with real solves. `study compare DIR` creates an independent direct-search plan using the same total study-wide solver-call cap. `study report DIR` rebuilds evidence-linked Markdown/HTML. `study export` and `study import` move private task/results bundles.

`study workflow DIR` orchestrates the gates. Without `--execute`, it prepares previews and a report, not a real study. With explicit execution, it runs within the declared solver and wall-time budgets and can accept `--resume` and `--reviews FILE`. There is no `--limit` flag on `workflow`. Use a bounded `study run --limit N` for a small preview. Once authorization explicitly covers one bounded batch, do not solicit confirmation per sample; stop if continuing would exceed the authorized budget or scope.

## Status distinctions

- `PLANNED` means an immutable plan exists; no geometry or solve is implied.
- `DRY_RUN` means sample geometry and simulation previews were prepared; no Mechanical solve occurred.
- `SOLVED` records real, non-synthetic Mechanical evidence for the relevant attempt. It does not by itself mean the evidence passed engineering checks.
- `REVIEW_REQUIRED` means a required evidence gate, including stress review or accepted training data, is missing.
- `NEEDS_SOLVE` means prediction is insufficient for a decision and requires a real solve.
- `WARN`, `NOT_RUN`, `FAIL`, `BUDGET_EXHAUSTED`, and `INTERRUPTED` must be preserved as distinct states.

The sample plan includes baseline, training, and frozen test designs. Additional adaptive, final-verification, and comparison designs have explicit partitions. Never move a design across partitions or use test outcomes to tune a model.
