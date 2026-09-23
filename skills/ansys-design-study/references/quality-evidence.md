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

## Claims and completion

Separate solver execution, numerical quality, design feasibility, model accuracy, and workflow completion in every report. A passing schema check, model cross-validation score, prediction, optimization proposal, or visually plausible plot is not a real candidate confirmation. Evaluate against the untouched frozen test split and inspect false-safe outcomes for every constrained target. After holdout evaluation, do not retrain or adapt that study using the same test evidence; start a fresh study for a new evaluation.

Require saved real candidate RSTs and passing per-target checks for candidate verification. When comparison is configured, use the workflow's recorded equal-budget allowance and report actual calls and statuses. If any evidence is absent, retain `NOT_RUN` or `REVIEW_REQUIRED`; never claim accuracy, mass reduction, or runtime advantage from plans, synthetic fixtures, or incomplete reports. For the example, the 10 MPa stress limit is a manually authored response constraint, not a material allowable, yield value, strength approval, or certification criterion.
