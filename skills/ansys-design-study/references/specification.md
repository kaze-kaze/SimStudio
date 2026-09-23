# Study specification

The source of truth is `schemas/study.schema.json` plus `ansys_skill.study.schema.StudySpec`. Unknown fields are rejected. Physical values are unit-qualified strings and converted to canonical SI for hashes and computation. Validate the actual input rather than constructing schema details from memory.

## Current geometry and parameters

Schema version `1.0` supports the controlled `gusseted_bracket` family only. It requires exactly `plate_thickness`, `hole_diameter`, and `fillet_radius`; each has `lower`, `upper`, and `baseline` values with length units. Positive ordered bounds and an in-range baseline are mandatory. Geometry construction performs further interaction and solid-validity checks before persisting sample CAD. Do not claim this is a general CAD parameterization API.

`base_simulation` points to a neighboring single-run YAML with a one-solid `GussetedBracket|Solid`, matching Engineering Data material, required `mounting_face`, `front_face`, and `bearing_pad` axis-extreme selectors, one mounting fixed support, and requested target/reaction results. It cannot use the fake backend or have open questions. `study plan` consumes this file and writes a portable study template. It is not a supported standalone `ansys-sim validate` or run input because sample geometry is supplied only during preparation.

Material evidence records an Engineering Data name, positive density, and a property-source statement. Density is used for the generated geometry's mass; it does not prove the solver material's complete properties. Compare each saved solver input and real environment before interpreting results.

## Targets, sampling, meshes, and budgets

Each target names a unique result ID, dimension (`length` or `pressure`), display unit, positive limit, acceptance source, absolute tolerance, reference scale, and optional relative and mesh tolerances/checks. A pressure/stress target must set `require_stress_review: true`. Target feasibility is distinct from whether its numerical evidence is eligible for training.

Sampling is seeded Latin hypercube with separate train and test counts and optional corners. The test design identities are frozen into the plan. Mesh sizes must contain at least three positive, strictly decreasing values; the element order is `linear` or `quadratic`. Budget limits cover total solver calls, wall time, and retries per job; the initial planned mesh calls must fit the solver budget.

Model options define seed, cross-validation folds, maximum normalized distance, and relative standard-deviation threshold. Optimization settings define candidate-pool size, batch size, adaptive rounds, final verification count, improvement tolerance, and whether equal-budget direct-search comparison is required. For the supplied example, `max_solver_calls: 400` is one shared cap for initial calls, adaptive sampling, candidate re-solves, retries, and equal-budget direct search. The current plan has 120 initial mesh calls; the cap does not promise all calls will be used.
