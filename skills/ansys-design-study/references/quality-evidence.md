# Quality gates and engineering evidence

Only real, hash-verified Mechanical attempts can become solver dataset evidence. Dry-run artifacts are previews. Every planned mesh level for a sample is considered; target-specific checks and configured mesh convergence determine each target's eligibility. Inspect `dataset.json`, exclusions, per-level quality, `engineering-checks.json`, `verification.json`, and the linked RST before training. A result row can be excluded for one target and usable for another only when the data contract explicitly records that distinction.

## RST-bound stress review

When a target requires stress review, `study collect`, `study verify`, `study workflow`, and `study compare` accept `--reviews FILE`. The JSON object maps the lowercase SHA-256 digest of the exact RST bytes to a record with all of these fields:

```json
{
  "<rst-sha256>": {
    "status": "PASS",
    "reviewer": "Reviewer name or attributable identity",
    "rationale": "Reasoned singularity and stress-field assessment",
    "evidence": ["Specific saved plot, mesh comparison, or other review reference"]
  }
}
```

The reviewer supplies the engineering judgment and evidence. A missing digest returns `REVIEW_REQUIRED`; malformed or non-passing records fail the review gate. Reviews do not transfer to a changed RST, and they are not a substitute for numerical checks, mesh convergence, material evidence, or the user's acceptance criteria. Review the study's result set within the authorized batch without requesting approval again for each sample.

New equivalent-stress runs also save `global_stress_diagnostics` in `results-summary.json`.
It contains the global top 20 Mechanical-averaged nodes and unaveraged elemental-nodal
elements, their coordinates, units, result set, and exact RST hash. Element-local values are
not assigned to topology nodes when their counts differ. The diagnostic remains global
even for a scoped requested result. `COMPLETED` means extraction completed, not that a
stress singularity review passed; a failed extraction remains `NOT_RUN` with its reason.

## Mesh shape warnings

The controlled tetrahedral study requires measured aspect ratio, element quality, corner-node
and Gauss-point Jacobian ratios, maximum corner angle, skewness, and tetrahedral collapse.
Limits and counts retain Mechanical's recorded values. Missing metrics and contradictory
statistics cannot pass; shape error-limit failures cannot be waived. Edge lengths remain
size diagnostics, and quad-face warping is not a tetrahedral shape metric. The full raw
record is preserved, including diagnostic inconsistencies.

A shape warning remains `WARN` and is excluded until a review addresses its significance
for each named target. An optional `mesh_quality_review` inside the same RST record must
bind both the RST key and the canonical hash of the complete raw `mesh_quality` object:

```json
{
  "<rst-sha256>": {
    "mesh_quality_review": {
      "status": "PASS",
      "quality_sha256": "<canonical-mesh-quality-sha256>",
      "targets": ["displacement"],
      "reviewer": "Attributable reviewer identity",
      "rationale": "Assessment of the actual warned metrics and affected response",
      "evidence": ["Saved mesh statistics, response refinement, and local field evidence"]
    }
  }
}
```

The dataset's `mesh_shape_quality.evidence.quality_sha256` supplies the required hash.
The original warning and separate target-specific review both remain in the dataset.
This record does not approve stress unless that target is named and its separate stress
review also passes. Review cannot turn missing evidence or a shape error into a pass.

## Claims and completion

Mechanical-message, requested-result, small-deformation and reaction-balance checks are mandatory for every study target. Face-selection geometry is mandatory even with gravity-only loading. Additional checks may be required, but configuration cannot remove these minimum checks.

Model schema 1.1 binds the frozen test design IDs. Incomplete test readiness does not inspect errors or commit a model. Once errors are inspected, the study commits both model path and content ID. Evaluation records boundary and constraint-near slices and both constraint misclassification directions, without manufacturing metrics for empty slices.

Separate solver execution, numerical quality, design feasibility, model accuracy, and workflow completion in every report. A passing schema check, model cross-validation score, prediction, optimization proposal, or visually plausible plot is not a real candidate confirmation. Evaluate against the untouched frozen test split and inspect false-safe outcomes for every constrained target. After holdout evaluation, do not retrain or adapt that study using the same test evidence; start a fresh study for a new evaluation.

Require saved real candidate RSTs and passing per-target checks for candidate verification. When comparison is configured, use the workflow's recorded equal-budget allowance and report actual calls and statuses. If any evidence is absent, retain `NOT_RUN` or `REVIEW_REQUIRED`; never claim accuracy, mass reduction, or runtime advantage from plans, synthetic fixtures, or incomplete reports. For the example, the 10 MPa stress limit is a manually authored response constraint, not a material allowable, yield value, strength approval, or certification criterion.
