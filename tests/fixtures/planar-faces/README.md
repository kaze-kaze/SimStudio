# Mechanical planar-face API evidence

`mechanical-2026-r1.json` contains a small geometry-only extract from two authored demonstration
brackets inspected with Mechanical 2026 R1 on September 23, 2026. The inspection opened copies
of saved projects and read `IGeoFace.Loops` and `IGeoEdge.PointAtParam`; it did not mesh or solve.
The source project and STEP hashes bind the origin. No project databases or result files are
included here.

`reported_area` and `reported_centroid` are the original tessellation-derived Mechanical values.
`boundary` contains nine points sampled from each actual parametric edge. `expected_scopes`
contains the controlled CAD generator measurements and analytic corner/hole descriptions.
In the mounting face, a rectangle minus four circular holes, the original displayed area differs
by about 0.014 percent while the independently measured boundary agrees with the CAD.

Offline regression tests use this extract to exercise the measurement and rejection contracts.
Passing those tests does not constitute a fresh ANSYS run, stress review, or engineering approval.
