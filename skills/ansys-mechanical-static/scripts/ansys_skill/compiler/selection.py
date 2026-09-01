"""Pure selection contracts mirrored by the generated Mechanical runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TypeVar

from ansys_skill.errors import SpecValidationError

T = TypeVar("T")


@dataclass(frozen=True)
class FaceCandidate:
    entity: object
    centroid: tuple[float, float, float]
    area: float
    normal: tuple[float, float, float]


def require_exact_name(objects: Iterable[T], name: str, *, get_name: Callable[[T], str]) -> T:
    matches = [item for item in objects if get_name(item) == name]
    if len(matches) != 1:
        raise SpecValidationError(
            f"Expected exactly one object named {name!r}; found {len(matches)}"
        )
    return matches[0]


def choose_axis_extreme_face(
    candidates: Iterable[FaceCandidate],
    *,
    axis: str,
    extreme: str,
    tolerance: float,
) -> FaceCandidate:
    items = list(candidates)
    if not items:
        raise SpecValidationError("axis_extreme_face found no candidate faces")
    if tolerance <= 0:
        raise SpecValidationError("axis_extreme_face tolerance must be positive")
    axis_index = {"x": 0, "y": 1, "z": 2}.get(axis)
    if axis_index is None or extreme not in {"min", "max"}:
        raise SpecValidationError("axis_extreme_face axis/extreme is invalid")
    coordinates = [item.centroid[axis_index] for item in items]
    target = min(coordinates) if extreme == "min" else max(coordinates)
    matches = [item for item in items if abs(item.centroid[axis_index] - target) <= tolerance]
    if len(matches) != 1:
        raise SpecValidationError(
            f"axis_extreme_face expected exactly one face; found {len(matches)}"
        )
    return matches[0]
