# PyDPF postprocessing

Use PyDPF after a real solve so numerical extraction is as independent as practical from the
Mechanical UI tree. Open the unique `.rst` with `ansys.dpf.core.Model`. Read mesh counts from
`model.metadata.meshed_region` and requested result providers from `model.results`.

Current mappings:

- total deformation: vector norm of `model.results.displacement`
- directional deformation: selected X/Y/Z component of displacement
- equivalent von Mises stress: `dpf.operators.result.stress_eqv_as_mechanical`, with explicit
  data sources, last result-set ID, nodal location, and optional named-selection scoping
- reaction force: `model.results.reaction_force`; fail explicitly if unavailable rather than
  substituting the different `nodal_force` provider

Resolve each named selection uniquely against the actual names in the RST. Generated selections are
sent to the solver explicitly. Do not guess a scope from topology order or silently choose one of
multiple case-insensitive matches.

Equivalent stress is derived from the stored stress tensor. A normal Mechanical RST need not expose
an equivalent-stress attribute in `model.results`; requiring that attribute rejected the real
2026 R1 benchmark. The explicit operator was verified against Mechanical's exported stress maximum.

Evaluate the last time/frequency set. Record the original maximum and field unit, canonical SI value
and unit, the specification-selected reporting value/unit, native location, scoping ID, value count,
and raw/canonical/reporting vector sums when applicable. All engineering checks use canonical values.
Empty, non-finite, unitless, dimensionally incompatible, or missing requested data is a
postprocessing/verification failure.

Do not calculate safety factor without an explicit yield strength. Do not treat an image as numerical
evidence. Do not treat a numerical maximum as proof that a stress singularity is physically meaningful.

If DPF cannot open the result because the server/product combination is incompatible, return exit code
5 and preserve the original result and logs for version-specific diagnosis.
