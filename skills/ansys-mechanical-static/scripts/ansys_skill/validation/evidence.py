"""Validate the evidence used by numerical acceptance checks."""

from __future__ import annotations

import math

from ansys_skill.errors import SpecValidationError
from ansys_skill.schema import ResultType, SimulationSpec
from ansys_skill.units import normalize_quantity
from ansys_skill.validation.statuses import Check, CheckStatus


def message_check(summary: dict[str, object]) -> Check:
    messages = summary.get("solver_messages")
    if not isinstance(messages, list):
        return Check(
            "mechanical_messages", CheckStatus.NOT_RUN, "Mechanical message evidence is unavailable"
        )
    errors = [
        item
        for item in messages
        if isinstance(item, dict) and "ERROR" in str(item.get("severity", "")).upper()
    ]
    unknown = [
        item
        for item in messages
        if not isinstance(item, dict)
        or str(item.get("severity", "")).upper() in {"", "UNKNOWN"}
        or "message api unavailable" in str(item.get("text", "")).lower()
    ]
    status = CheckStatus.FAIL if errors else CheckStatus.WARN if unknown else CheckStatus.PASS
    return Check(
        "mechanical_messages",
        status,
        "Mechanical reported error-level messages"
        if errors
        else "Mechanical message severity could not be fully verified"
        if unknown
        else "No error-level message was reported",
        {"error_count": len(errors), "unknown_count": len(unknown)},
    )


def result_evidence(spec: SimulationSpec, results: dict) -> tuple[dict[str, float], Check]:
    values: dict[str, float] = {}
    invalid: list[str] = []
    dimensions = {
        ResultType.TOTAL_DEFORMATION: "length",
        ResultType.DIRECTIONAL_DEFORMATION: "length",
        ResultType.EQUIVALENT_VON_MISES_STRESS: "pressure",
        ResultType.REACTION_FORCE: "force",
    }
    for request in spec.requested_results:
        if request.type not in dimensions:
            continue
        item = results.get(request.id)
        try:
            if not isinstance(item, dict) or not item.get("unit"):
                raise ValueError("Missing result or unit")
            dimension = dimensions[request.type]
            normalize_quantity(f"1 {item['unit']}", dimension)
            if item.get("canonical_maximum") is not None:
                value = float(item["canonical_maximum"])
            else:
                value = normalize_quantity(f"{item['maximum']} {item['unit']}", dimension).magnitude
            if not math.isfinite(value) or int(item.get("value_count", 1)) <= 0:
                raise ValueError("Non-finite or empty result")
            values[request.id] = value
        except (KeyError, ValueError, TypeError, OverflowError, SpecValidationError):
            invalid.append(request.id)
    return values, Check(
        "requested_results",
        CheckStatus.FAIL if invalid else CheckStatus.PASS,
        f"Missing or invalid requested results: {', '.join(invalid)}"
        if invalid
        else "All requested numerical results are present, finite, and unit-qualified",
    )
