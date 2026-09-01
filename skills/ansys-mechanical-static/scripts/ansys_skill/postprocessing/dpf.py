"""PyDPF result extraction isolated from Mechanical execution."""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ansys_skill.errors import PostprocessingError, SpecValidationError
from ansys_skill.schema import ResultType, ScopeKind, SimulationSpec
from ansys_skill.units import convert_canonical_value, normalize_quantity


def _flat_rows(data: Any) -> list[list[float]]:
    raw = data.tolist() if hasattr(data, "tolist") else list(data)
    if not raw:
        return []
    if isinstance(raw[0], (list, tuple)):
        return [[float(value) for value in row] for row in raw]
    return [[float(value)] for value in raw]


def _field_summary(
    fields: Iterable[Any],
    *,
    dimension: str,
    component: int | None = None,
    report_unit: str | None = None,
) -> dict[str, object]:
    maximum: float | None = None
    canonical_maximum: float | None = None
    max_id: int | None = None
    maximum_unit: str | None = None
    canonical_unit: str | None = None
    location: str | None = None
    raw_sum_vectors: dict[str, list[float]] = {}
    canonical_sum_vector: list[float] | None = None
    unit_scales: dict[str, float] = {}
    count = 0
    for field in fields:
        unit = str(getattr(field, "unit", "")).strip()
        if not unit:
            raise PostprocessingError("DPF result field has no unit")
        if unit not in unit_scales:
            try:
                normalized_unit = normalize_quantity(f"1 {unit}", dimension)
            except SpecValidationError as exc:
                raise PostprocessingError(
                    f"DPF unit {unit!r} is incompatible with {dimension}"
                ) from exc
            unit_scales[unit] = normalized_unit.magnitude
            canonical_unit = normalized_unit.unit
        scale = unit_scales[unit]
        location = str(getattr(field, "location", location or "")) or location
        rows = _flat_rows(field.data)
        ids = list(getattr(getattr(field, "scoping", None), "ids", []))
        if rows and len(rows[0]) == 3:
            raw_sum = raw_sum_vectors.setdefault(unit, [0.0, 0.0, 0.0])
            if canonical_sum_vector is None:
                canonical_sum_vector = [0.0, 0.0, 0.0]
            for row in rows:
                for index, value in enumerate(row):
                    raw_sum[index] += value
                    canonical_sum_vector[index] += value * scale
        for index, row in enumerate(rows):
            raw_value = (
                row[component]
                if component is not None
                else math.sqrt(sum(item * item for item in row))
            )
            if len(row) == 1:
                raw_value = row[0]
            if not math.isfinite(raw_value):
                raise PostprocessingError("DPF returned a non-finite result value")
            canonical_value = raw_value * scale
            count += 1
            if canonical_maximum is None or abs(canonical_value) > abs(canonical_maximum):
                maximum = raw_value
                maximum_unit = unit
                canonical_maximum = canonical_value
                max_id = int(ids[index]) if index < len(ids) else None
    if count == 0 or maximum is None or canonical_maximum is None:
        raise PostprocessingError("DPF result data is empty")
    result: dict[str, object] = {
        "maximum": maximum,
        "unit": maximum_unit,
        "canonical_maximum": canonical_maximum,
        "canonical_unit": canonical_unit,
        "location": location,
        "scoping_id": max_id,
        "value_count": count,
    }
    if canonical_sum_vector is not None:
        result["canonical_sum_vector"] = canonical_sum_vector
        result["canonical_sum_vector_unit"] = canonical_unit
        if len(raw_sum_vectors) == 1:
            raw_unit, raw_vector = next(iter(raw_sum_vectors.items()))
            result["sum_vector"] = raw_vector
            result["sum_vector_unit"] = raw_unit
    if report_unit is not None:
        result["reported_maximum"] = convert_canonical_value(
            canonical_maximum, dimension, report_unit
        )
        result["reported_unit"] = report_unit
        if canonical_sum_vector is not None:
            result["reported_sum_vector"] = [
                convert_canonical_value(value, dimension, report_unit)
                for value in canonical_sum_vector
            ]
    return result


def _evaluate(result: Any, scope_name: str | None = None) -> list[Any]:
    if scope_name:
        result = result.on_named_selection(scope_name)
    container = result.on_last_time_freq.eval()
    return list(container)


def _scope_name(spec: SimulationSpec, scope_id: str | None) -> str | None:
    if scope_id is None:
        return None
    scope = next(item for item in spec.scopes if item.id == scope_id)
    if scope.kind is ScopeKind.NAMED_SELECTION:
        return scope.name
    if scope.kind is ScopeKind.AXIS_EXTREME_FACE:
        return f"TTA_SCOPE_{scope.id}"
    raise PostprocessingError(
        f"DPF cannot deterministically scope object_name reference {scope.id!r}"
    )


def inspect_result_file(rst_path: Path, spec: SimulationSpec | None = None) -> dict[str, object]:
    try:
        from ansys.dpf import core as dpf
    except ImportError as exc:
        raise PostprocessingError(
            "ansys-dpf-core is not installed; install the 'ansys' extra"
        ) from exc
    if not rst_path.is_file():
        raise PostprocessingError(f"Result file does not exist: {rst_path}")
    try:
        model = dpf.Model(str(rst_path))
        mesh = model.metadata.meshed_region
        node_count = len(mesh.nodes)
        element_count = len(mesh.elements)
        results: dict[str, object] = {}
        unavailable_results: dict[str, str] = {}
        if spec is None:
            raw_requests = [
                ("total_deformation", "displacement"),
                ("equivalent_stress", "stress_eqv_von_mises"),
                ("reaction_force", "reaction_force"),
            ]
            for result_id, provider_name in raw_requests:
                try:
                    result = getattr(model.results, provider_name, None)
                    if result is None and provider_name == "reaction_force":
                        result = getattr(model.results, "nodal_force", None)
                    if result is None:
                        raise PostprocessingError(
                            f"Result provider {provider_name!r} is unavailable"
                        )
                    dimension = {
                        "total_deformation": "length",
                        "equivalent_stress": "pressure",
                        "reaction_force": "force",
                    }[result_id]
                    results[result_id] = _field_summary(
                        _evaluate(result), dimension=dimension
                    )
                except Exception as exc:
                    unavailable_results[result_id] = str(exc)
            return {
                "status": "POSTPROCESSED",
                "synthetic": False,
                "inspection_mode": "raw_rst",
                "result_file": str(rst_path.resolve()),
                "node_count": node_count,
                "element_count": element_count,
                "results": results,
                "unavailable_results": unavailable_results,
            }

        for request in spec.requested_results:
            if request.type in {
                ResultType.SOLVER_MESSAGES,
                ResultType.NODE_COUNT,
                ResultType.ELEMENT_COUNT,
            }:
                continue
            result_scope = request.scope
            if request.type is ResultType.REACTION_FORCE:
                support = next(item for item in spec.supports if item.id == request.support)
                result_scope = support.scope
            scope_name = _scope_name(spec, result_scope)
            if request.type is ResultType.TOTAL_DEFORMATION:
                result = model.results.displacement
                results[request.id] = _field_summary(
                    _evaluate(result, scope_name),
                    dimension="length",
                    report_unit=spec.units.length,
                )
            elif request.type is ResultType.DIRECTIONAL_DEFORMATION:
                result = model.results.displacement
                component = {"x": 0, "y": 1, "z": 2}[request.direction]
                results[request.id] = _field_summary(
                    _evaluate(result, scope_name),
                    dimension="length",
                    component=component,
                    report_unit=spec.units.length,
                )
            elif request.type is ResultType.EQUIVALENT_VON_MISES_STRESS:
                result = getattr(model.results, "stress_eqv_von_mises", None)
                if result is None:
                    raise PostprocessingError(
                        "The result file does not expose stress_eqv_von_mises"
                    )
                results[request.id] = _field_summary(
                    _evaluate(result, scope_name),
                    dimension="pressure",
                    report_unit=spec.units.stress,
                )
            elif request.type is ResultType.REACTION_FORCE:
                result = getattr(model.results, "reaction_force", None)
                if result is None:
                    result = getattr(model.results, "nodal_force", None)
                if result is None:
                    raise PostprocessingError(
                        "The result file exposes neither reaction_force nor nodal_force"
                    )
                results[request.id] = _field_summary(
                    _evaluate(result, scope_name),
                    dimension="force",
                    report_unit=spec.units.force,
                )
        return {
            "status": "POSTPROCESSED",
            "synthetic": False,
            "result_file": str(rst_path.resolve()),
            "node_count": node_count,
            "element_count": element_count,
            "results": results,
        }
    except PostprocessingError:
        raise
    except Exception as exc:
        raise PostprocessingError(f"DPF could not open or inspect {rst_path}: {exc}") from exc
