# Surrogate-assisted design studies

SimStudio's design-study workflow explores a controlled family of single-solid gusseted brackets with ANSYS Mechanical linear-static solves. It records an immutable sample plan, solver evidence, quality decisions, dataset and model provenance, candidate verification, and a rebuildable report. The workflow is implemented in the source tree; a complete Windows run against real Mechanical data has not yet been accepted. This documentation makes no accuracy, mass-reduction, or speedup claim.

## Install and start

Use Python 3.13 for the study toolchain. From a checkout, install the offline and CAD/numerical dependencies with:

```console
python -m pip install -e ".[dev,study]"
ansys-sim study init build/bracket-inputs --json
```

`init` writes `study.yaml` and `base-simulation.yaml` into a new directory. Review their units, material evidence, loads, parameter bounds, target limits, mesh sizes, and solver budget before planning. The supplied bracket files under `examples/bracket-study/` are authored demonstration inputs; their acceptance limits are not production requirements.

Plan from `study.yaml`, then inspect the plan before preparing any samples:

```console
ansys-sim study validate build/bracket-inputs/study.yaml --json
ansys-sim study plan build/bracket-inputs/study.yaml --out build/bracket-study --json
ansys-sim study status build/bracket-study --json
```

`plan` writes portable `study.yaml`, `base-simulation.yaml`, `study-plan.json`, and `study-manifest.json`. It does not create CAD. `study run` prepares each sample's controlled CAD and saved simulation inputs, then previews the normal single-run workflow without starting Mechanical unless `--execute` is present. For a bounded offline preview, use a new study directory and `--limit 1`:

```console
ansys-sim study run build/bracket-study --limit 1 --json
ansys-sim study report build/bracket-study --json
```

Do not pass `examples/bracket-study/base-simulation.yaml` or a generated study `base-simulation.yaml` to ordinary `ansys-sim validate` or `ansys-sim run`. These are study-owned templates with a per-sample `geometry.step` that is generated during study preparation. Use `study plan` and `study run` so geometry, immutable sample inputs, and hashes stay associated.

## Command contract

A payload with status NOT_RUN returns CLI exit code 6. Preserve that status and code; an evaluation without eligible frozen-holdout evidence is not a successful model evaluation.

All study and surrogate commands accept `--json`. Study execution is a preview by default. `--execute` explicitly permits Mechanical calls; the study's solver-call and wall-time budgets still apply. `--limit` is available on `study run` and caps additional design points, not mesh levels. Reusing existing attempts requires `--resume`. An explicit authorization for one bounded study run covers its samples within that declared budget; do not interrupt the batch to request approval for every sample.

| Command | Purpose and boundary |
| --- | --- |
| `study init DIR` | Write editable starter inputs; requires a new or empty destination. |
| `study validate STUDY.yaml` | Validate study/base inputs, constraints, and sampling without starting a solver. |
| `study plan STUDY.yaml --out DIR` | Create the portable immutable plan and identity manifest. |
| `study run DIR [--limit N] [--resume] [--execute]` | Generate controlled per-sample CAD and preview or execute serial mesh jobs. |
| `study status DIR` | Read study and sample execution state. |
| `study recover DIR` | Remove a stale local lock only after verifying its processes are stopped. It does not repair or erase attempt records. |
| `study collect DIR [--reviews FILE]` | Assess saved real RST evidence and create a versioned, target-specific dataset. |
| `study report DIR` | Rebuild HTML and Markdown reports from saved evidence. |
| `study export DIR --out ZIP [--kind task\|results]` | Create a hash-checked portable task or results bundle. |
| `study import ZIP --out NEW_DIR [--expected-study-id ID]` | Validate a bundle and import it to a fresh directory. |
| `study optimize DIR [--model PATH] [--execute]` | Propose constrained candidates; execution is opt-in and budgeted. |
| `study verify DIR [--model PATH] [--reviews FILE] [--execute]` | Confirm proposed candidates with Mechanical when explicitly enabled. |
| `study compare DIR [--reviews FILE] [--execute]` | Compare direct search against the recorded surrogate search allowance. |
| `study workflow DIR [--resume] [--reviews FILE] [--execute]` | Orchestrate the gated study. Without `--execute`, it prepares previews and a report only. |
| `surrogate train DIR` | Fit eligible training rows and write a safe JSON model artifact. |
| `surrogate evaluate DIR [--model PATH]` | Evaluate against the frozen test split; evaluation consumes that holdout. |
| `surrogate predict MODEL_DIR --parameters JSON` | Predict from a model directory; report out-of-domain or uncertain requests as needing a solve. |

The workflow is serial. It records attempts, process state, time and solver-call consumption, supports checked continuation after interruption, and refuses to reuse a study after its code identity changes. Keep each study directory with its generated inputs and evidence. A fresh import destination is required; the bundle verifies file hashes, study identity, schema version, and code fingerprint. Run an imported study with the same SimStudio code fingerprint that created it.

## Quality and model evidence

The example specifies three unit-qualified geometry parameters, target limits with their evidence source, three strictly refined mesh sizes, explicit sampling seeds, and a solver-call and wall-time budget. Its single `max_solver_calls: 400` value is the shared ceiling for the initial plan, adaptive additions, candidate re-solves, retries, and the equal-budget direct-search comparison. The current authored example plans 120 initial mesh solver calls; 400 is a ceiling, not a promise that all calls will be used. Every actual solver attempt consumes that same study-wide allowance. The active-time ledger includes CAD preparation, single-run execution, data collection, training, candidate search, and evaluation, including failed analysis attempts. Idle review time is excluded. Work is gated at stage boundaries; an in-progress numerical fit is not forcibly interrupted. Single-run elapsed time includes meshing, solving, and postprocessing; separate timings are not inferred when the backend does not provide them.

The demonstration displacement limit is `0.025 mm` and the stress response limit is `10 MPa`. These were authored with reference to the recorded baseline response (about 0.01935 mm displacement and 9.04 MPa nodal-averaged equivalent stress). The 10 MPa value is a manually authored response constraint; it is not a material allowable, yield value, strength approval, or certification criterion. Neither limit makes the example suitable for production decisions.

The required mechanical-message, requested-result, small-deformation and reaction-balance checks cannot be removed from a target. Actual selected-face geometry is required even for a gravity-only case. Samples have baseline, training, and frozen test partitions; later adaptive and candidate-verification samples are recorded separately. Data are eligible per target only when the required numerical and engineering evidence and configured mesh-convergence checks pass.

Equivalent-stress targets require a recorded, attributable singularity review. A review file maps the SHA-256 of each exact RST to `status: PASS`, a reviewer, a rationale, and non-empty evidence references. Missing review is `REVIEW_REQUIRED`; a review for a different RST hash does not apply. Review saved results as a set for the authorized study batch; no per-sample reauthorization is needed. Never infer a pass from an absent RST or a screenshot.

Models are stored as validated JSON (`model.json` and a model card), not pickle. Training uses eligible training rows; held-out evaluation reports per-target metrics and false-safe outcomes. Prediction does not call Mechanical and may return `NEEDS_SOLVE` when a point is outside the supported domain or uncertainty limit. Optimization proposals are not engineering approval: confirm candidates with real Mechanical evidence, review target quality, and use the same solver-call allowance for the direct-search comparison before making any comparative claim.

Finish training-set optimization, adaptive sampling, and every model refit before final surrogate evaluation. Evaluate the selected final model against the frozen holdout once; evaluation consumes that evidence and blocks later retraining/adaptation within the study. A NOT_RUN result returns exit code 6 rather than reporting evaluation success.

Read [the specification and schema guide](design-studies.zh-CN.md) for field-level context, [Windows execution](windows-study.md) for task transfer and host setup, and [the example notes](../examples/bracket-study/README.md) for the supplied demonstration. The independent Codex Skill is [ansys-design-study](../skills/ansys-design-study/SKILL.md).

## Verification status

Model JSON schema 1.1 binds the frozen test design IDs to the model. Evaluation rejects unplanned test rows and frozen designs in another split. It reports overall errors, design-space boundary errors, constraint-near errors and the full constraint confusion matrix. Empty slices are NOT_RUN with null metrics. Dataset and model-card artifacts retain materials, loads, supports, target definitions and execution context. Prediction accepts a JSON file of SI parameters; object key order is immaterial.

The study commits the evaluated model by path and content ID. A direct-search comparison freezes the research designs and attempt ledger used to establish its allowance. Changed research evidence invalidates that control. Reports distinguish the best observed search design from the separately solver-confirmed recommendation and include constraint margins. A recorded workflow outcome is shown only while its ledger and result-artifact fingerprint match.

New runs record Mechanical mesh/solve durations and CLI backend, postprocessing and report durations. Missing stages remain NOT_RUN. Parent and child timings overlap: mesh/solve belong to backend time; prediction and candidate CAD belong to search time. Do not sum overlapping durations.

Offline unit tests and Linux/Windows Python 3.13 CI exercise the study and installation workflow without ANSYS. They do not establish solver accuracy. The controlled sample CAD, fonts and package compatibility, real RST quality reviews, model holdout accuracy, candidate solves, and equal-budget comparison still require recorded Windows acceptance against the intended Mechanical installation. Until then, report real-engineering results as `NOT_RUN`; do not claim a validated accuracy percentage, mass reduction, or speed improvement.
