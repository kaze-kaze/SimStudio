# Validation policy

Every check has exactly one state: `PASS`, `WARN`, `FAIL`, or `NOT_RUN`. Never convert unavailable
evidence into `PASS`. Aggregate status is `FAIL` if any check fails, otherwise `WARN` when warnings or a
mix of executed/not-run checks remain.

## Before solve

- strict schema and unknown-field rejection
- unit dimension checks and explicit-unit enforcement
- input file existence and enabled suffix
- no unsupported analysis type
- each body has a declared material
- at least one support and one non-zero load
- positive mesh size
- positive characteristic length and analytical force/span/modulus/second moment
- analytical result references must identify a requested displacement quantity
- cross-reference uniqueness
- no unresolved `open_questions` for `--execute`
- exact template objects and runtime scopes resolve once inside Mechanical

## After solve

- no error-level Mechanical message
- one result file exists and PyDPF opens it
- node and element counts are positive
- every requested result is present, finite, non-empty, and unit-qualified
- reaction vector balances explicit applied force within configured relative tolerance; checks with
  pressure or gravity remain `NOT_RUN` until their solver-derived resultants are implemented
- maximum whole-model deformation/characteristic length stays below configured small-deformation warning/failure
  ratios
- configured cantilever benchmark compares `F L^3 / (3 E I)` with the requested FEA tip displacement
- visual exports are attempted and separately reported

Missing numerical values, messages, or global deformation evidence must not be replaced by zero or
an empty-success assumption. Re-inspecting an existing RST does not require the original CAD file;
that input-file check is explicitly `NOT_RUN` for historical inspection.

## Interpretation limits

Equivalent stress near a fixed support, point load, or sharp corner can be singular or mesh-sensitive.
Always emit a review warning when stress is requested. Do not automatically declare a design safe or
unsafe from that local maximum.

Mesh settings are deterministic inputs, not proof of mesh convergence. Safety factor is `NOT_RUN` in
v1 because yield strength is not part of the supported material contract.
