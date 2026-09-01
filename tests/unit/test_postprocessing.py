from __future__ import annotations

from pathlib import Path

import pytest
from ansys_skill.cli import _find_result_file
from ansys_skill.errors import PostprocessingError
from ansys_skill.postprocessing.dpf import _field_summary, inspect_result_file
from ansys_skill.schema import load_spec


def test_result_file_missing(valid_spec_path: Path, tmp_path: Path) -> None:
    with pytest.raises(PostprocessingError, match=r"No \.rst"):
        _find_result_file(tmp_path)


def test_dpf_postprocessing_failure_is_explicit(valid_spec_path: Path, tmp_path: Path) -> None:
    spec, _ = load_spec(valid_spec_path)
    with pytest.raises(PostprocessingError):
        inspect_result_file(tmp_path / "missing.rst", spec)


def test_field_summary_preserves_raw_and_canonical_units() -> None:
    class Scoping:
        def __init__(self) -> None:
            self.ids = [10, 11]

    class Field:
        def __init__(self) -> None:
            self.unit = "mm"
            self.location = "Nodal"
            self.scoping = Scoping()
            self.data = [[0.0, 0.0, 1.0], [0.0, 0.0, -2.0]]

    summary = _field_summary(
        [Field()], dimension="length", component=2, report_unit="mm"
    )
    assert summary["maximum"] == -2.0
    assert summary["unit"] == "mm"
    assert summary["canonical_maximum"] == pytest.approx(-0.002)
    assert summary["canonical_unit"] == "meter"
    assert summary["canonical_sum_vector"] == pytest.approx([0.0, 0.0, -0.001])
    assert summary["reported_maximum"] == pytest.approx(-2.0)
    assert summary["reported_unit"] == "mm"
