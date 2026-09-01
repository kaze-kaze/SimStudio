from __future__ import annotations

import pytest
from ansys_skill.compiler.selection import (
    FaceCandidate,
    choose_axis_extreme_face,
    require_exact_name,
)
from ansys_skill.errors import SpecValidationError


def test_scope_missing_fails() -> None:
    with pytest.raises(SpecValidationError, match="found 0"):
        require_exact_name([], "FixedEnd", get_name=lambda item: str(item))


def test_scope_multiple_matches_fail() -> None:
    with pytest.raises(SpecValidationError, match="found 2"):
        require_exact_name(["FixedEnd", "FixedEnd"], "FixedEnd", get_name=str)


def test_scope_exact_match_succeeds() -> None:
    assert require_exact_name(["A", "B"], "B", get_name=str) == "B"


def test_axis_extreme_unique_match() -> None:
    faces = [
        FaceCandidate("left", (0.0, 0.0, 0.0), 1.0, (-1.0, 0.0, 0.0)),
        FaceCandidate("right", (1.0, 0.0, 0.0), 1.0, (1.0, 0.0, 0.0)),
    ]
    result = choose_axis_extreme_face(faces, axis="x", extreme="max", tolerance=1e-9)
    assert result.entity == "right"


def test_axis_extreme_ambiguous_match_fails() -> None:
    faces = [
        FaceCandidate("a", (1.0, 0.0, 0.0), 1.0, (1.0, 0.0, 0.0)),
        FaceCandidate("b", (1.0, 1.0, 0.0), 1.0, (1.0, 0.0, 0.0)),
    ]
    with pytest.raises(SpecValidationError, match="found 2"):
        choose_axis_extreme_face(faces, axis="x", extreme="max", tolerance=1e-9)
