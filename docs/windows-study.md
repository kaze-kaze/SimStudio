# Running a design study on Windows

This guide covers offline preparation on a development host and explicit Mechanical execution on Windows. The study workflow is implemented, but a complete real Windows study has not yet been accepted. A previously reported build123d 0.11.1 font failure and a recorded 0.9.1 path are investigation history, not evidence that either version now works for this study. Check the actual environment and record a new acceptance before making compatibility or performance claims.

## Prepare and package on a development host

Install with Python 3.13 from the repository checkout:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,study]"
.\.venv\Scripts\ansys-sim.exe study plan examples/bracket-study/study.yaml --out build\bracket-study --json
.\.venv\Scripts\ansys-sim.exe study run build\bracket-study --limit 1 --json
.\.venv\Scripts\ansys-sim.exe study report build\bracket-study --json
.\.venv\Scripts\ansys-sim.exe study export build\bracket-study --out build\bracket-task.zip --kind task --json
```

Planning records the sampling and budget but creates no CAD. The bounded dry-run prepares CAD for one design point and checks the generated per-sample inputs without launching Mechanical. Inspect its JSON status and generated report. Do not use the example's `base-simulation.yaml` as a standalone simulation: study preparation supplies each sample's `geometry.step`.

Move the task ZIP to Windows. On the Windows host, install the same source revision and optional runtime into Python 3.13, and install/use a compatible Mechanical client and licensed Mechanical installation separately. Import only into a new study directory:

```powershell
py -3.13 -m venv C:\SimStudio\.venv
C:\SimStudio\.venv\Scripts\python.exe -m pip install ".[study,ansys]"
C:\SimStudio\.venv\Scripts\ansys-sim.exe study import C:\Transfer\bracket-task.zip --out C:\Studies\bracket --json
C:\SimStudio\.venv\Scripts\ansys-sim.exe study status C:\Studies\bracket --json
```

The imported manifest's `code_fingerprint` must match the installed code. Its hash normalizes CRLF to LF, so Windows line endings alone do not change code identity. Import verifies package identity and payload hashes; it does not install ANSYS or transfer a license. Keep task/result bundles private because real result bundles may contain proprietary CAD and solver evidence.

## Execute with an explicit budget

Read `study-plan.json` and the study budgets before authorizing execution. `study run` without `--execute` is a preview. A bounded first real batch can be started directly with:

```powershell
C:\SimStudio\.venv\Scripts\ansys-sim.exe study run C:\Studies\bracket --execute --limit 1 --json
C:\SimStudio\.venv\Scripts\ansys-sim.exe study status C:\Studies\bracket --json
```

After inspecting its generated inputs, continue the already authorized batch with `--execute --resume`; the declared study limits remain in force. Do not repeat an approval prompt for each sample covered by that authorization. A resume is not a fresh authorization and must not be used to exceed or silently enlarge the agreed scope. The repository's `tools/run_study_windows.ps1` can check the installed fingerprint and pass through the study-run exit code; its `-Execute` switch is the explicit solve gate.

For the supplied example, `budget.max_solver_calls: 400` is one ceiling shared by initial samples, adaptive additions, candidate re-solves, retries, and the equal-budget direct-search comparison. The current plan calls for 120 initial mesh solves; the ceiling is not a promise to consume all 400. The demo's 0.025 mm displacement limit and 10 MPa stress response limit were authored with reference to a recorded 0.01935 mm / 9.04 MPa response. The 10 MPa limit is not a material allowable, yield value, strength approval, or certification criterion.

If execution is interrupted, inspect `study status`, the manifest attempt records, and the recorded owned-process state. Use `study recover` only after establishing that the recorded owner processes have stopped. Recovery checks the local lock and both the CLI and nested Mechanical process trees, removes a verified stale lock, and marks abandoned `RUNNING` attempts `INTERRUPTED` while preserving their audit records for a later attempt. A parent-process exit alone is not sufficient: unresolved child processes block result acceptance, automatic retries and resumed execution. A failed process-tree query also blocks automatic continuation. Recovery cannot prove process state on another host. Then resume with the original code and environment. Do not delete attempt directories, RSTs, locks, or manifest history to make a run appear complete.

## Review and close out

After real solves, collect each RST with `study collect`. Stress-target rows remain ineligible until the review file records an explicit review bound to the exact RST SHA-256. Reviewers, rationale, and evidence references must be attributable; an old review will no longer match if the RST changes. Missing review remains `REVIEW_REQUIRED`. Review the report's per-target exclusions before training.

After the training dataset is adequate, train the model and finish adaptive optimization plus every refit before final holdout evaluation. Run `surrogate evaluate` once against the frozen test split; it commits the first evaluated model and prevents further model retraining/adaptation within the study. If frozen test data are incomplete, readiness returns NOT_RUN without inspecting prediction errors or committing the model. A NOT_RUN evaluation returns CLI exit code 6 and is not success. Then verify candidates with real Mechanical evidence and complete any configured direct-search comparison within the same solver-call allowance. Export results only when needed; treat the archive as engineering data.

The installation CI and offline test suite exercise command wiring and deterministic contracts on Linux and Windows. They do not exercise a licensed solver, prove the installed CAD/font stack can generate every sample, or validate the model against real held-out engineering results. Record those checks separately and retain `NOT_RUN` where no evidence exists.
