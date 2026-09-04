"""Unit-qualified summaries of DPF fields."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from ansys_skill.errors import PostprocessingError, SpecValidationError
from ansys_skill.units import convert_canonical_value, normalize_quantity


def _flat_rows(data: Any) -> list[list[float]]:
    raw = data.tolist() if hasattr(data, "tolist") else list(data)
    if not raw:
        return []
    if isinstance(raw[0], (list, tuple)):
        return [[float(value) for value in row] for row in raw]
    return [[float(value)] for value in raw]


def field_summary(
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
        if len(ids) != len(rows):
            raise PostprocessingError(
                "DPF field values do not map one-to-one to entity IDs; request nodal output"
            )
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
            if not math.isfinite(canonical_value):
                raise PostprocessingError("DPF result overflows canonical units")
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
