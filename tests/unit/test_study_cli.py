from __future__ import annotations

import json
from pathlib import Path

from ansys_skill.cli import build_parser, main
from ansys_skill.errors import ExitCode
from ansys_skill.study.cli import _result


def test_study_and_surrogate_commands_are_in_the_installed_parser():
    parser = build_parser()
    run = parser.parse_args(["study", "run", "study", "--json"])
    assert run.execute is False and run.resume is False
    workflow = parser.parse_args(["study", "workflow", "study", "--json"])
    assert workflow.execute is False
    predict = parser.parse_args(["surrogate", "predict", "model", "--parameters", "point.json"])
    assert not hasattr(predict, "execute")


def test_initialization_from_cli_emits_json_without_solver_or_repository(tmp_path, capsys):
    directory = tmp_path / "case"
    code = main(["study", "init", str(directory), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["solver_started"] is False
    assert (directory / "study.yaml").exists()


def test_invalid_study_preserves_validation_exit_code(tmp_path, capsys):
    path = tmp_path / "study.yaml"
    path.write_text("schema_version: '1.0'\npython: 'not executable'\n")
    assert main(["study", "validate", str(path), "--json"]) == ExitCode.VALIDATION_FAILED
    assert json.loads(capsys.readouterr().out)["status"] == "ERROR"


def test_unavailable_prediction_and_unknown_validation_never_return_success(capsys):
    args = build_parser().parse_args(["study", "status", str(Path("study")), "--json"])
    for status in ("NEEDS_SOLVE", "NOT_RUN", "REVIEW_REQUIRED"):
        assert _result({"status": status}, args) == ExitCode.VERIFICATION_FAILED
        assert json.loads(capsys.readouterr().out)["status"] == status
    assert _result({"status": "FAILED"}, args) == ExitCode.MECHANICAL_FAILED
    assert json.loads(capsys.readouterr().out)["status"] == "FAILED"
