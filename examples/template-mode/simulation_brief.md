# Template static-analysis brief

## Objective

Demonstrate exact-name modification of an existing Mechanical static structural template.

## Inputs

- Mode: `template`
- Project: `REPLACE-WITH-YOUR-TEMPLATE.mechdat`
- Analysis object: `Static Structural`
- Body: `BeamBody`
- Named selections: `FixedEnd`, `LoadEnd`
- Existing objects: `Fixed Support`, `Applied Force`, `Total Deformation`, `Equivalent Stress`,
  `Fixed Reaction`

## Physics

- Exact Engineering Data material: `Structural Steel`
- Fixed support on `FixedEnd`
- Force of `-1000 N` in global Y on `LoadEnd`
- Linear static, small deformation

## Open question

Replace the placeholder project path and verify every exact name against the licensed template.
