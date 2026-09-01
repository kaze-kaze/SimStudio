"""Convert validated schemas into a minimal executable Mechanical plan."""

from __future__ import annotations

from pathlib import Path

from ansys_skill.schema import LoadSpec, MaterialSource, ScopeKind, ScopeSpec, SimulationSpec
from ansys_skill.units import mechanical_quantity, normalize_direction, normalize_quantity


def _components(load: LoadSpec, dimension: str) -> list[str]:
    components = load.components
    if components is not None:
        return [mechanical_quantity(value, dimension) for value in components.values()]
    magnitude_raw = load.magnitude
    direction_raw = load.direction
    magnitude = normalize_quantity(magnitude_raw, dimension).magnitude
    direction = normalize_direction(direction_raw)
    unit = "N" if dimension == "force" else "m s^-2"
    return [f"{magnitude * component:.17g} [{unit}]" for component in direction]


def _gravity_orientation(load: LoadSpec) -> str:
    assert load.direction is not None
    direction = normalize_direction(load.direction)
    mappings = {
        (1.0, 0.0, 0.0): "PositiveXAxis",
        (-1.0, 0.0, 0.0): "NegativeXAxis",
        (0.0, 1.0, 0.0): "PositiveYAxis",
        (0.0, -1.0, 0.0): "NegativeYAxis",
        (0.0, 0.0, 1.0): "PositiveZAxis",
        (0.0, 0.0, -1.0): "NegativeZAxis",
    }
    rounded = tuple(0.0 if abs(value) < 1e-9 else float(round(value)) for value in direction)
    return mappings[rounded]


def _dpf_scope_name(scope: ScopeSpec) -> str | None:
    if scope.kind is ScopeKind.NAMED_SELECTION:
        return scope.name
    if scope.kind is ScopeKind.AXIS_EXTREME_FACE:
        return f"TTA_SCOPE_{scope.id}"
    return None


def build_mechanical_plan(
    spec: SimulationSpec, spec_path: Path, input_path: Path
) -> dict[str, object]:
    materials = {material.name: material for material in spec.materials}
    return {
        "plan_version": "1.0",
        "mode": spec.mode.value,
        "input": {
            "absolute_path": str(input_path),
            "basename": input_path.name,
            "source_spec_directory": str(spec_path.parent.resolve()),
        },
        "project_name": spec.project.name,
        "analysis": spec.analysis.model_dump(mode="json", exclude_none=True),
        "bodies": [
            {
                "name": body.name,
                "material_name": materials[body.material].engineering_data_name,
                "material_source": materials[body.material].source.value,
            }
            for body in spec.bodies
        ],
        "scopes": [
            {
                **scope.model_dump(mode="json", exclude_none=True),
                **(
                    {
                        "tolerance_canonical_m": normalize_quantity(
                            scope.tolerance, "length"
                        ).magnitude
                    }
                    if scope.tolerance
                    else {}
                ),
                **(
                    {"dpf_named_selection": _dpf_scope_name(scope)}
                    if _dpf_scope_name(scope)
                    else {}
                ),
            }
            for scope in spec.scopes
        ],
        "mesh": {
            "global_element_size": mechanical_quantity(spec.mesh.global_element_size, "length"),
            "element_order": spec.mesh.element_order,
        },
        "supports": [
            support.model_dump(mode="json", exclude_none=True) for support in spec.supports
        ],
        "loads": [
            {
                **load.model_dump(
                    mode="json",
                    exclude_none=True,
                    exclude={"components", "magnitude", "direction"},
                ),
                **({"components": _components(load, "force")} if load.type == "force" else {}),
                **(
                    {"magnitude": mechanical_quantity(load.magnitude, "pressure")}
                    if load.type == "pressure"
                    else {}
                ),
                **(
                    {
                        "magnitude": mechanical_quantity(load.magnitude, "acceleration"),
                        "gravity_orientation": _gravity_orientation(load),
                    }
                    if load.type == "gravity"
                    else {}
                ),
            }
            for load in spec.loads
        ],
        "requested_results": [
            result.model_dump(mode="json", exclude_none=True) for result in spec.requested_results
        ],
        "output": spec.output.model_dump(mode="json"),
        "custom_materials_present": any(
            material.source is MaterialSource.ISOTROPIC for material in spec.materials
        ),
    }
