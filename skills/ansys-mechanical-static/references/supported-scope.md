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
