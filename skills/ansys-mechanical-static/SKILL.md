---
name: ansys-mechanical-static
description: Create, modify, validate, dry-run, execute, inspect, and report ANSYS Mechanical linear static structural simulations using exact-name mechdat/templates, simple single-body geometry, PyMechanical, PyDPF, or existing RST results. Use for Mechanical load/support/mesh/result setup, batch static solves, template-based load changes, DPF result inspection, RST reporting, 批量静力求解, and 基于模板修改载荷并生成报告. Do not use for general mechanical design, CAD-only work, theoretical finite-element questions, CFD, nonlinear, transient, contact-inference, or certification requests.
---

# ANSYS Mechanical linear static simulation

Turn the user's request into an explicit, reviewable simulation specification and drive only the
deterministic `ansys-sim` workflow. Treat the result as an engineering work product requiring human
review, not an autonomous design approval.

## Classify the request

Proceed only for linear static structural Mechanical work with small deformation. Support two modes:

- `template`: start from an existing `.mechdat`/`.mechdb`; modify exact object names and named
  selections. This is the preferred v1 workflow.
- `from_geometry`: import one simple solid and use exact body names plus named selections or a
  strictly unique `axis_extreme_face` selector. Do not infer contact or accept a multi-body assembly.

If any requested physics or automation is outside the supported scope, name it explicitly and ask the
user to split the task or use a future dedicated Skill. Never approximate nonlinear, transient, CFD,
contact, fatigue, buckling, fracture, or other unsupported physics as linear static. Read
[`references/supported-scope.md`](references/supported-scope.md) when scope is uncertain.

## Required workflow

1. Inspect the supplied project, geometry, prior run directory, or RST before drafting the model.
2. Create or update `simulation_brief.md`. Record objective, exact inputs, units, bodies, materials,
   scopes, loads, supports, requested results, acceptance criteria, assumptions, and open questions.
   Read [`references/simulation-brief.md`](references/simulation-brief.md).
3. Ask one focused question only when missing information prevents a physically safe or uniquely
   scoped execution. Never invent material, support, load scope, contact, or safety factor. Record
   every other assumption with source `user`, `template`, `program`, or `engineering_default`.
4. Create or update `simulation.yaml` using the strict schema. Every physical quantity must include a
   unit. Unknown fields and unitless physical values are errors. Read
   [`references/schema-reference.md`](references/schema-reference.md) when editing the schema.
5. Run `ansys-sim validate <simulation.yaml> --json`. Fix the smallest responsible source field.
6. Run `ansys-sim compile <simulation.yaml> --out <run-directory> --json`. Inspect
   `normalized-simulation.yaml`, `mechanical-plan.json`, and `generated-mechanical.py`; do not edit
   those generated files as the primary fix.
7. Run `ansys-sim doctor --json`. Read
   [`references/mechanical-execution.md`](references/mechanical-execution.md) for connection,
   transport, ownership, timeout, and platform rules. On a local Windows installation, the user
   may explicitly select `execution.backend: mechanical_batch` to run the saved script through
   Mechanical's batch entry point. It is not an automatic fallback from a failed gRPC solve.
8. Default to `ansys-sim run ... --json` without `--execute`. Show the execution plan and unresolved
   blockers. Use `--execute` only when the user explicitly requests a real solve and the specification
   has no open questions, unknown units, ambiguous scopes, or unsupported material authoring.
9. After a real solve, inspect the result through PyDPF. Read
   [`references/dpf-postprocessing.md`](references/dpf-postprocessing.md) and never substitute a
   screenshot for numerical checks.
10. Run reaction balance, result completeness, finite-value/unit, mesh-count, small-deformation, and
    configured analytical checks. Read
    [`references/validation-policy.md`](references/validation-policy.md).
11. Attempt mesh/deformation/stress visual exports and review them. Read
    [`references/visual-review.md`](references/visual-review.md). A failed image export is
    `NOT_RUN` with a reason, not `PASS`.
12. On failure, identify the smallest responsible source file or specification field, repair it,
    recompile, and rerun only the affected checks. Read
    [`references/failure-recovery.md`](references/failure-recovery.md).
13. Deliver exact artifact paths, commands actually run, PASS/WARN/FAIL/NOT_RUN states, assumptions,
    limitations, and whether a real ANSYS solve occurred. Never report fake-backend values as ANSYS
    results.

## Safety invariants

- Do not execute Python from the specification. Do not use `eval` or `exec`.
- Do not insert the user's natural-language brief into executable source. The compiler emits a fixed
  runtime plus encoded, validated execution data.
- Keep real execution opt-in. Reject non-local hosts unless `allow_remote: true` is explicit.
- Do not download Mechanical, accept a license, store credentials, or commit proprietary artifacts.
- Do not close a pre-existing Mechanical instance. Close only an instance created by the current run.
- Require exact one-object matches. Never use "the third item in the tree" or raw Mechanical face IDs
  as a durable user scope.
- Read [`references/engineering-safety.md`](references/engineering-safety.md) before any safety,
  compliance, design-pass/fail, or certification-adjacent request.

## API evidence

Read [`references/official-api-map.md`](references/official-api-map.md) before changing PyMechanical,
Mechanical scripting, geometry selection, transport, or PyDPF integration. Keep version adaptation in
the explicit compatibility layers and mark interfaces not exercised against a real product as
"not integration-tested".
