# Simulation brief procedure

Create `simulation_brief.md` before editing `simulation.yaml`. The brief is the human review layer; it
must not become executable source.

Record, in order:

1. Engineering objective and the decision the analysis informs.
2. Mode (`template` or `from_geometry`) and exact input path.
3. Product/version information known from the user or template.
4. Coordinate convention and every input/output unit.
5. Exact body names and exact Engineering Data material names.
6. Scope definitions: named selection, exact object, or unique axis-extreme face.
7. Supports and loads, including components or magnitude/direction.
8. Global mesh size and why it is suitable only as a starting mesh.
9. Requested numerical and visual results.
10. Acceptance checks and configured tolerances.
11. Assumptions, each labeled with its source.
12. Open questions that block a safe or uniquely scoped execution.

Do not convert vague statements such as "use steel", "fix the left side", "apply operating load",
or "use a safe factor" into executable values. Ask one focused question for the first blocking issue,
or leave it in `open_questions` and keep the workflow in dry-run.
