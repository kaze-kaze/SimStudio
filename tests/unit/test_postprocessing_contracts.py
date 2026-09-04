from __future__ import annotations

import json

from ansys_skill.cli import _find_result_file


def test_recorded_result_takes_precedence_over_project_copy(tmp_path):
    result = tmp_path / "solver/file.rst"
    result.parent.mkdir()
    result.write_bytes(b"current result")
    (tmp_path / "project-copy.rst").write_bytes(b"same solve, project copy")
    (tmp_path / "mechanical-artifacts.json").write_text(
        json.dumps({"result_files": ["solver/file.rst"]})
    )
    assert _find_result_file(tmp_path) == result
