# PyDPF postprocessing

Use PyDPF after a real solve so numerical extraction is as independent as practical from the
Mechanical UI tree. Open the unique `.rst` with `ansys.dpf.core.Model`. Read mesh counts from
`model.metadata.meshed_region` and requested result providers from `model.results`.

Current mappings:

- total deformation: vector norm of `model.results.displacement`
- directional deformation: selected X/Y/Z component of displacement
- equivalent von Mises stress: `model.results.stress_eqv_von_mises`
- reaction force: `model.results.reaction_force`, with `nodal_force` as the documented compatibility
  fallback to verify against a live Mechanical-generated RST

Evaluate the last time/frequency set. Record the original maximum and field unit, canonical SI value
and unit, the specification-selected reporting value/unit, native location, scoping ID, value count,
and raw/canonical/reporting vector sums when applicable. All engineering checks use canonical values.
Empty, non-finite, unitless, dimensionally incompatible, or missing requested data is a
postprocessing/verification failure.

Do not calculate safety factor without an explicit yield strength. Do not treat an image as numerical
evidence. Do not treat a numerical maximum as proof that a stress singularity is physically meaningful.

If DPF cannot open the result because the server/product combination is incompatible, return exit code
5 and preserve the original result and logs for version-specific diagnosis.
