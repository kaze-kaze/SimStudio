"""Analytical Euler-Bernoulli cantilever validator."""

from __future__ import annotations

from ansys_skill.schema import CantileverValidationSpec
from ansys_skill.units import normalize_quantity
from ansys_skill.validation.statuses import Check, CheckStatus


def analytical_tip_displacement(config: CantileverValidationSpec) -> float:
    if not config.enabled:
        raise ValueError("Cantilever validation is disabled")
    force = normalize_quantity(config.load_magnitude, "force").magnitude
    span = normalize_quantity(config.span, "length").magnitude
    modulus = normalize_quantity(config.youngs_modulus, "pressure").magnitude
    inertia = normalize_quantity(config.second_moment_of_area, "second_moment").magnitude
    return force * span**3 / (3.0 * modulus * inertia)


def validate_cantilever(config: CantileverValidationSpec, result_values: dict[str, float]) -> Check:
    if not config.enabled:
        return Check("cantilever_analytical", CheckStatus.NOT_RUN, "Validator is disabled")
    assert config.result_id is not None
    actual = result_values.get(config.result_id)
    if actual is None:
        return Check(
            "cantilever_analytical",
            CheckStatus.FAIL,
            f"Requested cantilever result {config.result_id!r} is missing",
        )
    expected = analytical_tip_displacement(config)
    relative_error = abs(abs(actual) - expected) / expected
    status = CheckStatus.PASS if relative_error <= config.relative_tolerance else CheckStatus.FAIL
    return Check(
        "cantilever_analytical",
        status,
        "FEA tip displacement agrees with the Euler-Bernoulli benchmark"
        if status is CheckStatus.PASS
        else "FEA tip displacement exceeds the configured analytical tolerance",
        {
            "actual_m": actual,
            "expected_m": expected,
            "relative_error": relative_error,
            "relative_tolerance": config.relative_tolerance,
        },
    )
