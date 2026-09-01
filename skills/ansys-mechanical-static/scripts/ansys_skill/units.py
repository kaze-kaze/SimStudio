"""Strict physical quantity parsing and canonical conversion."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from pint import Quantity, UnitRegistry
from pint.errors import DimensionalityError, UndefinedUnitError

from ansys_skill.errors import SpecValidationError

UREG = UnitRegistry(autoconvert_offset_to_baseunit=True)
Q_ = UREG.Quantity

DIMENSIONS = {
    "length": "[length]",
    "area": "[length] ** 2",
    "second_moment": "[length] ** 4",
    "force": "[mass] * [length] / [time] ** 2",
    "pressure": "[mass] / [length] / [time] ** 2",
    "density": "[mass] / [length] ** 3",
    "acceleration": "[length] / [time] ** 2",
    "mass": "[mass]",
    "time": "[time]",
}

CANONICAL_UNITS = {
    "length": "meter",
    "area": "meter ** 2",
    "second_moment": "meter ** 4",
    "force": "newton",
    "pressure": "pascal",
    "density": "kilogram / meter ** 3",
    "acceleration": "meter / second ** 2",
    "mass": "kilogram",
    "time": "second",
}

_UNIT_TOKEN = re.compile(r"[A-Za-zµμ°]")


@dataclass(frozen=True)
class NormalizedQuantity:
    raw: str
    magnitude: float
    unit: str
    dimension: str

    def as_dict(self) -> dict[str, object]:
        return {
            "raw": self.raw,
            "canonical_value": self.magnitude,
            "canonical_unit": self.unit,
            "dimension": self.dimension,
        }


def parse_quantity(raw: object, dimension: str) -> Quantity:
    if not isinstance(raw, str) or not raw.strip():
        raise SpecValidationError(
            f"Physical quantity must be a non-empty string with units: {raw!r}"
        )
    if not _UNIT_TOKEN.search(raw):
        raise SpecValidationError(f"Physical quantity is missing an explicit unit: {raw!r}")
    try:
        quantity = Q_(raw.strip())
    except (UndefinedUnitError, ValueError) as exc:
        raise SpecValidationError(f"Invalid physical quantity {raw!r}: {exc}") from exc
    expected = DIMENSIONS[dimension]
    try:
        if not quantity.check(expected):
            raise SpecValidationError(
                f"Quantity {raw!r} has incompatible dimensions; expected {dimension}"
            )
    except DimensionalityError as exc:
        raise SpecValidationError(
            f"Quantity {raw!r} has incompatible dimensions; expected {dimension}"
        ) from exc
    if not math.isfinite(float(quantity.magnitude)):
        raise SpecValidationError(f"Quantity must be finite: {raw!r}")
    return quantity


def normalize_quantity(raw: object, dimension: str) -> NormalizedQuantity:
    quantity = parse_quantity(raw, dimension).to(CANONICAL_UNITS[dimension])
    return NormalizedQuantity(
        raw=str(raw),
        magnitude=float(quantity.magnitude),
        unit=str(quantity.units),
        dimension=dimension,
    )


def mechanical_quantity(raw: object, dimension: str) -> str:
    normalized = normalize_quantity(raw, dimension)
    unit_map = {
        "meter": "m",
        "meter ** 2": "m^2",
        "meter ** 4": "m^4",
        "newton": "N",
        "pascal": "Pa",
        "kilogram / meter ** 3": "kg m^-3",
        "meter / second ** 2": "m s^-2",
        "kilogram": "kg",
        "second": "s",
    }
    return f"{normalized.magnitude:.17g} [{unit_map[normalized.unit]}]"


def convert_canonical_value(value: float, dimension: str, target_unit: str) -> float:
    normalize_quantity(f"1 {target_unit}", dimension)
    converted = Q_(value, CANONICAL_UNITS[dimension]).to(target_unit)
    magnitude = float(converted.magnitude)
    if not math.isfinite(magnitude):
        raise SpecValidationError("Converted physical quantity must be finite")
    return magnitude


def vector_magnitude(values: list[str], dimension: str) -> float:
    canonical = [normalize_quantity(value, dimension).magnitude for value in values]
    return math.sqrt(sum(value * value for value in canonical))


def normalize_direction(values: list[float]) -> tuple[float, float, float]:
    if len(values) != 3 or any(not math.isfinite(value) for value in values):
        raise SpecValidationError("Direction must contain three finite numbers")
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        raise SpecValidationError("Direction vector must be non-zero")
    return tuple(value / norm for value in values)  # type: ignore[return-value]
