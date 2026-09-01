# Failure recovery

Repair the smallest source of responsibility, then rerun from the earliest invalidated stage.

## Exit code 2 — specification or engineering preflight

Fix `simulation.yaml` or the input path. Typical causes: unknown field, missing unit, unsupported
analysis, duplicate ID, missing material, zero load, unresolved question, or unsafe remote host. Rerun
`validate`, then `compile`.

## Exit code 3 — environment or license

Read `environment.json` and `doctor --json`. Distinguish missing PyMechanical/PyDPF, unsupported product
OS, missing executable, unreachable port, transport mismatch, certificate problem, and license failure.
Do not edit model physics to hide an environment problem.

## Exit code 4 — Mechanical or solve

Inspect `mechanical-artifacts.json`, `solver-messages.json`, `solve.out`, and the manifest failure stage.
Check exact object/body names, face-selector candidates, Engineering Data names, geometry import,
constraints, mesh generation, solver messages, and timeout. A sentinel without an RST and clean messages
is not success.

## Exit code 5 — DPF

Preserve the `.rst`. Confirm PyDPF package/server/product compatibility and that the result file is not
truncated. Rerun `inspect`; do not rerun Mechanical unless the result itself is invalid.

## Exit code 6 — engineering verification

Inspect the failed check evidence. Change tolerances only when the engineering acceptance criterion
actually changed. For reaction imbalance, verify all applied forces and reaction scopes. For analytical
mismatch, verify formula inputs, beam assumptions, load direction, mesh, and result scope. For small
deformation failure, route to an appropriate nonlinear workflow instead of suppressing the check.
