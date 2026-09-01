# `simulation.yaml` schema reference

The current schema version is `1.0`. Unknown fields are rejected at every level. The generated JSON
Schema is `schemas/simulation.schema.json`.

## Top-level fields

- `schema_version`: currently `"1.0"`.
- `project`: `name` and optional `description`.
- `mode`: `template` or `from_geometry`.
- `inputs`: exactly one of `project_file` or `geometry_file`, according to mode.
- `units`: reporting preferences. These do not make unitless physical inputs legal.
- `coordinate_systems`: v1 supports the global coordinate system.
- `bodies`: exact body name and material reference.
- `materials`: exact Engineering Data name, or schema-only isotropic properties.
- `scopes`: reusable exact scope definitions.
- `analysis`: only `linear_static_structural` plus `deformation: small`.
- `mesh`: explicit positive `global_element_size`.
- `supports`: fixed supports.
- `loads`: force, pressure, or gravity.
- `requested_results`: supported Mechanical/DPF outputs.
- `validation`: tolerances and optional analytical checks.
- `assumptions`: text plus required source.
- `open_questions`: a non-empty list blocks `--execute`.
- `output`: project/image choices.
- `execution`: backend, host, port, transport, ownership, and timeout.

## Physical quantities

Write physical values as strings with units: `20 kN`, `210 GPa`, `5 mm`, `7850 kg/m^3`, or
`9.80665 m/s^2`. A bare `20` is rejected. Poisson's ratio and relative tolerances are dimensionless
numbers. The compiler converts executable values to SI while preserving the original specification.
Generated Markdown reports list both the original input string and canonical SI value. For real DPF
results, declared `units` entries also select the reported length, force, and stress units. The
preferences are dimension-checked and never supply an omitted input unit.

## Materials

`source: engineering_data` requires `engineering_data_name` and uses exact matching in Mechanical. It
never guesses from a part name.

`source: isotropic` requires Young's modulus and Poisson's ratio, with optional density. The schema
retains this migration path, but v0.1 blocks real execution because stable material authoring has not
been integration-tested across supported Mechanical versions.

## Force and gravity

Provide exactly one representation:

- `components: {x, y, z}`, each with units; or
- positive `magnitude` with units plus a non-zero three-number `direction`.

The compiler normalizes force magnitude/direction and emits deterministic components. Pressure accepts
one non-zero magnitude. Gravity uses Mechanical's fixed EarthGravity load: specify exactly
9.80665 m/s^2 plus one global axis direction such as [0, 0, -1]. Arbitrary acceleration vectors are
not silently approximated as Earth gravity.

## Execution transport

Localhost defaults to explicit `insecure` gRPC. A non-local host requires `allow_remote: true` and
authenticated `wnua` or `mtls`; `wnua` requires a Windows client and `mtls` requires an existing
certificate directory. `start_instance: yes` is local-only.

## Migration

All input passes through `migrate_document()`. Version `1.0` is currently identity-migrated. A future
version must add an explicit migration function and tests; never reinterpret an old file silently.
