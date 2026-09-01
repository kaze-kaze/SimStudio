# Repository instructions

## Product boundary

- This repository is an auditable compiler and Codex Skill for ANSYS Mechanical linear static
  structural analysis. It is not an autonomous CAE engineer or certification system.
- Keep dry-run as the default. Never add an implicit path that starts a commercial solver.
- Do not add Fluent, CFX, nonlinear, transient, contact inference, or other out-of-scope physics to
  the v1 Skill. Route those requests to a future independent Skill.
- Never execute Python supplied in `simulation.yaml`. Do not add `eval`, `exec`, dynamic imports, or
  templated source fragments derived from user prose.

## Source and generated artifacts

- `simulation.yaml`, Python source, and reference documents are sources of truth.
- `normalized-simulation.yaml`, `mechanical-plan.json`, `generated-mechanical.py`, manifests,
  reports, images, and solver files are generated artifacts.
- Change the compiler or specification and regenerate outputs; do not patch generated artifacts as
  the primary fix.

## Verification

- Run the narrowest relevant test first, then `ruff check .` and `pytest -q`.
- Tests without the `ansys_integration` marker must not require ANSYS, a license, or network access.
- Real integration tests require an explicit `ANSYS_AVAILABLE=1` opt-in. Report unavailable
  integrations as `NOT_RUN`, never `PASS`.
- Preserve exact exit codes and stable JSON keys. stdout is machine-readable; progress belongs on
  stderr.

## API compatibility

- Put PyMechanical signature adaptation in `backends/pymechanical.py`.
- Put Mechanical object-model adaptation inside the generated `MechanicalCompat` layer.
- Do not scatter broad `try/except AttributeError` fallbacks through business logic.
- Update `references/official-api-map.md` whenever a documented API or supported version range
  changes.
