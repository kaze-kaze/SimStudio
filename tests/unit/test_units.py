from __future__ import annotations

import math

import pytest
from ansys_skill.errors import SpecValidationError
from ansys_skill.units import (
    mechanical_quantity,
    normalize_direction,
    normalize_quantity,
    vector_magnitude,
)


@pytest.mark.parametrize(
    ("raw", "dimension", "expected"),
    [
        ("5 mm", "length", 0.005),
        ("20 kN", "force", 20_000.0),
        ("210 GPa", "pressure", 210_000_000_000.0),
        ("7850 kg/m^3", "density", 7850.0),
        ("106666.6666667 mm^4", "second_moment", 1.066666666667e-7),
    ],
)
def test_quantity_conversion(raw: str, dimension: str, expected: float) -> None:
    result = normalize_quantity(raw, dimension)
    assert result.magnitude == pytest.approx(expected)
    assert result.raw == raw


@pytest.mark.parametrize("raw", [20, "20", "", None])
def test_missing_unit_fails(raw: object) -> None:
    with pytest.raises(SpecValidationError, match="unit"):
        normalize_quantity(raw, "force")


def test_wrong_dimension_fails() -> None:
    with pytest.raises(SpecValidationError, match="expected force"):
        normalize_quantity("5 mm", "force")


def test_mechanical_quantity_is_canonical() -> None:
    assert mechanical_quantity("20 kN", "force") == "20000 [N]"


def test_vector_helpers() -> None:
    assert vector_magnitude(["3 N", "4 N", "0 N"], "force") == pytest.approx(5.0)
    direction = normalize_direction([0.0, 3.0, 4.0])
    assert direction == pytest.approx((0.0, 0.6, 0.8))
    assert math.sqrt(sum(value * value for value in direction)) == pytest.approx(1.0)


def test_zero_direction_fails() -> None:
    with pytest.raises(SpecValidationError, match="non-zero"):
        normalize_direction([0.0, 0.0, 0.0])
