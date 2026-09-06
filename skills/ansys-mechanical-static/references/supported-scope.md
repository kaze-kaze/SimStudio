# Supported analysis scope

## Supported

- ANSYS Mechanical linear static structural analysis
- small deformation only
- one analysis per run
- `template` mode using an existing `.mechdat` or `.mechdb` and exact names
- `from_geometry` mode for one simple solid
- exact Mechanical named selections and object names
- one strictly unique `axis_extreme_face` on a simple body
- exact Engineering Data material references
- fixed support, force, pressure, and gravity
- global element size
- total/directional deformation, equivalent von Mises stress, reaction force, solver messages, node
  count, and element count
- saved dry-runs, manifests, DPF inspection, numerical checks, visual-review status, and reports

Enabled geometry suffixes are `.step` and `.stp`. Mechanical's
`GeometryImportPreference.Format.Automatic` selects the importer. Other formats may be available in a
particular ANSYS installation, but v0.1 does not claim or enable them until a live supported product
and required CAD interface have been tested.

## `axis_extreme_face` contract

The selector traverses all geometry bodies, requires one exact body (or one body total), records every
face's centroid and area with geometry-database units, evaluates a representative normal with
`ParamAtPoint` and `NormalAtParam`, converts the explicit tolerance from canonical meters to
`GeoData.Unit`, then selects centroids within that tolerance of the axis minimum or maximum. Exactly one
face must match. Zero or multiple matches fail before meshing. The run writes
`face-selection-report.json`.

If the installed Mechanical version does not expose the documented geometry-entity interfaces, fail
with `UnsupportedMechanicalApi`; do not fall back to an unreviewed ID, topology order, or nearest face.

## Runtime template checks

The runtime verifies the actual active body inventory, one analysis in the model, and ownership of
every referenced load, support, and result. Undeclared active analysis objects, contacts, joints,
springs, and command/Python objects are rejected rather than deleted or ignored. Template force and
result coordinate systems are reset to global, and result direction, scope, and reaction support are
synchronized with the specification.

Engineering Data properties are checked against the explicit linear-static allowlist in
`MechanicalCompat.assert_linear_material`. Unknown or nonlinear property sets fail with the actual
property inventory for review. A material name alone is not proof of linear behavior. The installed
Student Mechanical 2026 R1 Structural Steel inventory, template object types, and both template
formats were exercised through explicit local batch execution on 2026-09-06. This does not certify
other material libraries or product versions; see the recorded acceptance evidence.

## Unsupported

- Fluent, CFX, explicit dynamics, or LS-DYNA
- transient, plastic, nonlinear, large-deformation, buckling, fatigue, fracture, topology, or modal
  analyses
- automatic contact inference or arbitrary multi-body assemblies
- remote force until a live supported API path is tested
- automatic material, support, load, contact, yield strength, or safety-factor inference
- "best mesh" claims, mesh-convergence claims without a configured study, or certification
- raw Mechanical face IDs as durable user scopes

Name unsupported work explicitly and recommend a separate future Skill or a split workflow. Never
silently approximate it with the linear-static model.
