"""Collect raw and canonical input quantities for deterministic reports."""

from __future__ import annotations

from typing import Any

from ansys_skill.schema import MaterialSource, SimulationSpec
from ansys_skill.units import normalize_quantity


def normalized_input_quantities(spec: SimulationSpec) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(label: str, raw: str | None, dimension: str) -> None:
        if raw is None:
            return
        normalized = normalize_quantity(raw, dimension)
        rows.append(
            {
                "label": label,
                "raw": normalized.raw,
                "canonical_value": normalized.magnitude,
                "canonical_unit": normalized.unit,
            }
        )

    add("mesh.global_element_size", spec.mesh.global_element_size, "length")
    for scope in spec.scopes:
        add(f"scopes.{scope.id}.tolerance", scope.tolerance, "length")
    for material in spec.materials:
        if material.source is MaterialSource.ISOTROPIC:
            add(
                f"materials.{material.name}.youngs_modulus",
                material.youngs_modulus,
                "pressure",
            )
            add(f"materials.{material.name}.density", material.density, "density")
    for load in spec.loads:
        if load.type == "force" and load.components is not None:
            for axis, raw in zip(("x", "y", "z"), load.components.values(), strict=True):
                add(f"loads.{load.id}.components.{axis}", raw, "force")
        elif load.type == "force":
            add(f"loads.{load.id}.magnitude", load.magnitude, "force")
        elif load.type == "pressure":
            add(f"loads.{load.id}.magnitude", load.magnitude, "pressure")
        elif load.type == "gravity":
            add(f"loads.{load.id}.magnitude", load.magnitude, "acceleration")
    add(
        "validation.characteristic_length",
        spec.validation.characteristic_length,
        "length",
    )
    cantilever = spec.validation.cantilever
    add("validation.cantilever.span", cantilever.span, "length")
    add(
        "validation.cantilever.second_moment_of_area",
        cantilever.second_moment_of_area,
        "second_moment",
    )
    add(
        "validation.cantilever.load_magnitude",
        cantilever.load_magnitude,
        "force",
    )
    add(
        "validation.cantilever.youngs_modulus",
        cantilever.youngs_modulus,
        "pressure",
    )
    return rows
