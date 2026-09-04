"""PyDPF result extraction isolated from Mechanical execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansys_skill.errors import PostprocessingError
from ansys_skill.postprocessing.fields import field_summary as _field_summary
from ansys_skill.schema import ResultType, ScopeKind, SimulationSpec


def _evaluate(result: Any, scope_name: str | None = None, *, nodal: bool = False) -> list[Any]:
    if scope_name:
        result = result.on_named_selection(scope_name)
    if nodal:
        result = result.on_location("Nodal")
    container = result.on_last_time_freq.eval()
    return list(container)


def _scope_name(spec: SimulationSpec, scope_id: str | None) -> str | None:
    if scope_id is None:
        return None
    scope = next(item for item in spec.scopes if item.id == scope_id)
    if scope.kind is ScopeKind.NAMED_SELECTION:
        return scope.name
    if scope.kind is ScopeKind.AXIS_EXTREME_FACE:
        return f"TTA_SCOPE_{scope.id}".upper()
    raise PostprocessingError(
        f"DPF cannot deterministically scope object_name reference {scope.id!r}"
    )


def _resolve_scope(model: Any, name: str | None) -> str | None:
    if name is None:
        return None
    available = list(model.metadata.available_named_selections)
    matches = [str(item) for item in available if str(item).casefold() == name.casefold()]
    if len(matches) != 1:
        raise PostprocessingError(
            f"Expected one RST named selection matching {name!r}; found {matches}"
        )
    return matches[0]


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
                        _evaluate(result, nodal=provider_name == "stress_eqv_von_mises"), dimension=dimension
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
            scope_name = _resolve_scope(model, _scope_name(spec, result_scope))
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
                    _evaluate(result, scope_name, nodal=True),
                    dimension="pressure",
                    report_unit=spec.units.stress,
                )
            elif request.type is ResultType.REACTION_FORCE:
                result = getattr(model.results, "reaction_force", None)
                if result is None:
                    raise PostprocessingError(
                        "The result file does not expose reaction_force; nodal_force is not an equivalent substitute"
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
