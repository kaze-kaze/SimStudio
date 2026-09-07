# Rectangular cantilever linear-static brief

## Objective

Retain an analytical reference for the v1 `from_geometry` regression tests. Compare the finite-element
tip Z displacement against Euler-Bernoulli beam theory, with isolated pressure and gravity variants
used by the integration suite. The public engineering example is the gusseted equipment bracket.

## Inputs

- Geometry: generated `cantilever.step`
- One solid with the Mechanical 2026 R1 tree name `CantileverBeam|Solid`
- Dimensions: `200 mm x 20 mm x 40 mm` (X/Y/Z)
- Global coordinate system

## Material

- Exact Engineering Data material: `Structural Steel`
- Analytical benchmark modulus: `200 GPa`
- No material is inferred from the body name

## Boundary conditions

- Fixed face: unique X-min face within `0.001 mm` centroid tolerance
- Loaded face: unique X-max face within `0.001 mm` centroid tolerance
- Force: `0 N, 0 N, -1000 N`

## Mesh and results

- Global size: `10 mm`
- Total deformation
- Z directional deformation scoped to the loaded face
- Equivalent von Mises stress
- Fixed-support reaction force
- Solver messages, node count, and element count

## Acceptance

- Reaction relative residual <= 5%
- FEA tip displacement within 15% of `0.125 mm`
- Warn at deformation/length >= 2%; fail at >= 10%
- Review stress near the fixed face for mesh sensitivity/singularity

## Assumptions

- The benchmark intentionally uses Euler-Bernoulli theory as an approximate check, not certification.
- The STEP product is `CantileverBeam`; Mechanical 2026 R1 imports its solid as `CantileverBeam|Solid`.

## Open questions

None for offline compile. A real run still depends on local product/import compatibility and license.
