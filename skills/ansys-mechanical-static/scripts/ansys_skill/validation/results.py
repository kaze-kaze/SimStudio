"""Post-solve numerical and engineering checks."""

from __future__ import annotations

import math

from ansys_skill.schema import ResultType, SimulationSpec
from ansys_skill.units import normalize_direction, normalize_quantity
from ansys_skill.validation.cantilever import validate_cantilever
from ansys_skill.validation.evidence import message_check, result_evidence
from ansys_skill.validation.statuses import Check, CheckStatus


def _load_vector(spec: SimulationSpec) -> tuple[float, float, float]:
    total = [0.0, 0.0, 0.0]
    for load in spec.loads:
        if load.type != "force":
            continue
        if load.components is not None:
            values = [
                normalize_quantity(value, "force").magnitude for value in load.components.values()
            ]
        else:
            assert load.magnitude is not None and load.direction is not None
            magnitude = normalize_quantity(load.magnitude, "force").magnitude
            direction = normalize_direction(load.direction)
            values = [magnitude * component for component in direction]
        for index, value in enumerate(values):
            total[index] += value
    return tuple(total)  # type: ignore[return-value]


def post_solve_checks(spec: SimulationSpec, summary: dict[str, object]) -> list[Check]:
    checks: list[Check] = [message_check(summary)]

    result_file = summary.get("result_file")
    checks.append(
        Check(
            "result_file",
            CheckStatus.PASS if result_file else CheckStatus.FAIL,
            "A DPF-readable result file was found" if result_file else "No result file was found",
        )
    )
    node_count = int(summary.get("node_count", 0) or 0)
    element_count = int(summary.get("element_count", 0) or 0)
    checks.append(
        Check(
            "mesh_counts",
            CheckStatus.PASS if node_count > 0 and element_count > 0 else CheckStatus.FAIL,
            f"Mesh has {node_count} nodes and {element_count} elements",
        )
    )

    results = summary.get("results", {})
    results_dict = results if isinstance(results, dict) else {}
    numeric_values, completeness = result_evidence(spec, results_dict)
    checks.append(completeness)

    reaction_items = [
        results_dict.get(request.id)
        for request in spec.requested_results
        if request.type is ResultType.REACTION_FORCE
    ]
    reactions = [item for item in reaction_items if isinstance(item, dict)]
    unsupported_balance_loads = [load.id for load in spec.loads if load.type != "force"]
    if reactions and unsupported_balance_loads:
        checks.append(
            Check(
                "reaction_balance",
                CheckStatus.NOT_RUN,
                "Reaction balance currently requires all applied loads to be explicit forces; "
                "pressure and gravity need solver-derived resultant loads",
                {"unsupported_loads": unsupported_balance_loads},
            )
        )
    elif reactions:
        reaction_vector = [0.0, 0.0, 0.0]
        missing_vectors: list[str] = []
        for reaction_index, item in enumerate(reactions):
            vector = item.get("canonical_sum_vector", item.get("sum_vector"))
            if isinstance(vector, list) and len(vector) == 3:
                for component_index, value in enumerate(vector):
                    reaction_vector[component_index] += float(value)
            else:
                missing_vectors.append(str(reaction_index))
        if missing_vectors:
            checks.append(
                Check(
                    "reaction_balance",
                    CheckStatus.FAIL,
                    "Reaction-force results did not include complete vector sums",
                    {"missing_reaction_indexes": missing_vectors},
                )
            )
        else:
            load_vector = _load_vector(spec)
            residual = math.sqrt(
                sum((reaction_vector[index] + load_vector[index]) ** 2 for index in range(3))
            )
            scale = max(math.sqrt(sum(value * value for value in load_vector)), 1e-30)
            relative = residual / scale
            checks.append(
                Check(
                    "reaction_balance",
                    CheckStatus.PASS
                    if relative <= spec.validation.reaction_balance_relative_tolerance
                    else CheckStatus.FAIL,
                    "Reaction force balances the applied force"
                    if relative <= spec.validation.reaction_balance_relative_tolerance
                    else "Reaction force does not balance the applied force within tolerance",
                    {
                        "applied_force_N": list(load_vector),
                        "reaction_force_N": reaction_vector,
                        "relative_residual": relative,
                        "relative_tolerance": spec.validation.reaction_balance_relative_tolerance,
                    },
                )
            )
    else:
        checks.append(
            Check(
                "reaction_balance",
                CheckStatus.NOT_RUN,
                "No reaction-force result was requested or available",
            )
        )

    deformation_requests = [
        request.id
        for request in spec.requested_results
        if request.type is ResultType.TOTAL_DEFORMATION and request.scope is None
        and request.id in numeric_values
    ]
    characteristic = spec.validation.characteristic_length
    if deformation_requests and characteristic:
        maximum = max(abs(numeric_values[item]) for item in deformation_requests)
        length = normalize_quantity(characteristic, "length").magnitude
        ratio = maximum / length
        status = CheckStatus.PASS
        if ratio >= spec.validation.small_deformation_fail_ratio:
            status = CheckStatus.FAIL
        elif ratio >= spec.validation.small_deformation_warn_ratio:
            status = CheckStatus.WARN
        checks.append(
            Check(
                "small_deformation",
                status,
                f"Maximum deformation/characteristic length ratio is {ratio:.6g}",
                {"ratio": ratio},
            )
        )
    else:
        checks.append(
            Check(
                "small_deformation",
                CheckStatus.NOT_RUN,
                "A valid whole-model total-deformation result and characteristic_length are required",
            )
        )

    checks.append(validate_cantilever(spec.validation.cantilever, numeric_values))

    if any(
        request.type is ResultType.EQUIVALENT_VON_MISES_STRESS for request in spec.requested_results
    ):
        checks.append(
            Check(
                "stress_singularity_review",
                CheckStatus.WARN,
                "Review the recorded stress maximum and image near fixed supports, point loads, "
                "and sharp corners; this workflow does not turn a local singularity into an "
                "automatic pass/fail design decision",
            )
        )
    checks.append(
        Check(
            "safety_factor",
            CheckStatus.NOT_RUN,
            "Safety factor is not calculated; no yield strength is part of the v1 schema",
        )
    )
    return checks
