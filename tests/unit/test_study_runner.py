"""Fault-injection tests for orchestration; none is Mechanical acceptance evidence."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest
import yaml
from ansys_skill.errors import SpecValidationError
from ansys_skill.manifest import sha256_file
from ansys_skill.study import project, runner
from ansys_skill.study.sampling import sample_record
from ansys_skill.study.storage import atomic_json, read_json
from ansys_skill.study.templates import init_study


@pytest.fixture
def study_root(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "plan_samples", lambda spec: ([sample_record(spec.baseline(), "baseline")], []))
    init_study(tmp_path / "inputs")
    root = tmp_path / "study"
    project.create_plan(tmp_path / "inputs" / "study.yaml", root)

    def prepare(root, sample, study, base):
        directory = project.sample_directory(root, sample)
        directory.mkdir(parents=True, exist_ok=True)
        source = Path(__file__).resolve().parents[1] / "fixtures" / "cantilever" / "cantilever.step"
        geometry = directory / "geometry.step"
        geometry.write_bytes(source.read_bytes())
        sample["geometry"] = {"geometry_sha256": sha256_file(geometry), "mass_kg": 1.0}
        for job in sample["jobs"]:
            path = directory / f"mesh-{job['mesh_index']}.yaml"
            data = base.model_dump(mode="json", exclude_none=True)
            data["inputs"] = {"geometry_file": "geometry.step"}
            data["mesh"]["global_element_size"] = job["mesh_size"]
            path.write_text(yaml.safe_dump(data))
            job["specification"] = path.relative_to(root).as_posix()
            job["spec_sha256"] = sha256_file(path)
    monkeypatch.setattr(runner, "prepare_sample", prepare)
    return root


def solver_protocol_stub(monkeypatch, failures=0, synthetic=False):
    calls = []

    def call(specification, directory, execute, **_kwargs):
        calls.append((specification, directory, execute))
        directory.mkdir()
        if len(calls) <= failures:
            (directory / "failure.txt").write_text("Injected test failure, not solver output")
            return 4, {"status": "ERROR", "error": "Injected transport failure"}
        atomic_json(directory / "run-manifest.json", {"mechanical_product_version": "fixture-only"})
        (directory / "fixture.txt").write_text("Protocol fixture only; no Mechanical execution occurred")
        return 0, {"status": "SOLVED", "synthetic": synthetic}
    monkeypatch.setattr(runner, "_call_single_run", call)
    monkeypatch.setattr(runner, "_execution_context", lambda base: {"fixture": True})
    return calls


def test_default_study_run_does_not_call_solver_and_outputs_machine_json(study_root, monkeypatch):
    def prohibited(*args, **kwargs):
        pytest.fail("Dry-run attempted environment execution or a solver")
    monkeypatch.setattr(runner, "_execution_context", prohibited)
    result = runner.run_study(study_root)
    assert result["status"] == "DRY_RUN"
    assert result["solver_calls"] == 0
    _, _, manifest = project.load_project(study_root)
    jobs = manifest["samples"][0]["jobs"]
    assert len(jobs) == 3
    assert all(job["attempts"] == [] for job in jobs)
    for job in jobs:
        preview = study_root / job["previews"][-1]["path"]
        summary = read_json(preview / "results-summary.json")
        assert summary["status"] == "NOT_RUN"


def test_failure_retries_use_distinct_directories_and_resume_reuses_intact_results(study_root, monkeypatch):
    calls = solver_protocol_stub(monkeypatch, failures=1)
    first = runner.run_study(study_root, execute=True)
    assert first["status"] == "SOLVED"
    assert first["solver_calls"] == 4
    assert len({call[1] for call in calls}) == 4
    with pytest.raises(SpecValidationError, match="resume"):
        runner.run_study(study_root, execute=True)
    second = runner.run_study(study_root, execute=True, resume=True)
    assert second["solver_calls"] == 4
    assert len(calls) == 4
    assert list(study_root.glob("samples/**/failure.txt"))


def test_modified_result_is_not_reused(study_root, monkeypatch):
    calls = solver_protocol_stub(monkeypatch)
    runner.run_study(study_root, execute=True)
    calls[0][1].joinpath("fixture.txt").write_text("Changed")
    with pytest.raises(SpecValidationError, match="changed"):
        runner.run_study(study_root, execute=True, resume=True)
    assert len(calls) == 3


def test_synthetic_response_cannot_count_as_solved(study_root, monkeypatch):
    calls = solver_protocol_stub(monkeypatch, synthetic=True)
    result = runner.run_study(study_root, execute=True)
    assert result["status"] == "PARTIAL"
    assert result["samples"] == {"FAILED": 1}
    assert len(calls) == 2


def test_budget_exhaustion_keeps_attempts_and_can_be_reported(study_root, monkeypatch):
    calls = solver_protocol_stub(monkeypatch, failures=100)
    # Use a smaller valid declared budget before any run, not a mutable execution counter.
    study_path = study_root / "study.yaml"
    study_data = yaml.safe_load(study_path.read_text())
    study_data["sampling"] = {"train_samples": 6, "test_samples": 3, "include_corners": False}
    study_data["budget"]["max_solver_calls"] = 30
    study_path.write_text(yaml.safe_dump(study_data))
    # Changed inputs must be rejected instead of silently increasing the existing budget.
    with pytest.raises(SpecValidationError, match="input changed"):
        runner.run_study(study_root, execute=True)
    assert calls == []


def test_input_and_ledger_tampering_are_rejected(study_root):
    manifest_path = study_root / "study-manifest.json"
    document = json.loads(manifest_path.read_text())
    document["solver_calls"] = 1
    atomic_json(manifest_path, document)
    with pytest.raises(SpecValidationError, match="attempt ledger"):
        project.load_project(study_root)


def test_dry_run_does_not_demote_a_successful_sample(study_root, monkeypatch):
    solver_protocol_stub(monkeypatch)
    assert runner.run_study(study_root, execute=True)["status"] == "SOLVED"

    result = runner.run_study(study_root)

    _, _, manifest = project.load_project(study_root)
    assert result["status"] == "SOLVED"
    assert manifest["status"] == "SOLVED"
    assert manifest["samples"][0]["status"] == "SOLVED"


def test_resume_rejects_changed_attempt_input(study_root, monkeypatch):
    calls = solver_protocol_stub(monkeypatch)
    runner.run_study(study_root, execute=True)
    attempt_specification = calls[0][1].parent / "simulation.yaml"
    attempt_specification.write_text(attempt_specification.read_text() + "# changed\n")

    with pytest.raises(SpecValidationError, match=r"input.*changed"):
        runner.run_study(study_root, execute=True, resume=True)


def test_resume_rejects_unrecorded_output_files(study_root, monkeypatch):
    calls = solver_protocol_stub(monkeypatch)
    runner.run_study(study_root, execute=True)
    calls[0][1].joinpath("unexpected.txt").write_text("unrecorded output")

    with pytest.raises(SpecValidationError, match="changed"):
        runner.run_study(study_root, execute=True, resume=True)


def test_solver_call_limit_counts_retries_across_resume(study_root, monkeypatch):
    calls = solver_protocol_stub(monkeypatch, failures=1)

    first = runner.run_study(study_root, execute=True, solver_call_limit=3)
    second = runner.run_study(study_root, execute=True, resume=True, solver_call_limit=3)

    assert first["status"] == "BUDGET_EXHAUSTED"
    assert second["status"] == "BUDGET_EXHAUSTED"
    assert first["solver_calls"] == second["solver_calls"] == 3
    assert len(calls) == 3


def test_resume_rejects_a_changed_execution_environment(study_root, monkeypatch):
    solver_protocol_stub(monkeypatch)
    runner.run_study(study_root, execute=True)
    monkeypatch.setattr(runner, "_execution_context", lambda _base: {"fixture": "changed"})

    with pytest.raises(SpecValidationError, match="environment changed"):
        runner.run_study(study_root, execute=True, resume=True)


def test_execution_context_time_consumes_wall_budget(study_root, monkeypatch):
    study, base, manifest = project.load_project(study_root)
    budget = study.budget.model_copy(update={"max_wall_seconds": 60})
    study = study.model_copy(update={"budget": budget})
    monkeypatch.setattr(runner, "load_project", lambda *_args, **_kwargs: (study, base, manifest))
    clock = {"now": 0.0}
    monkeypatch.setattr(runner, "time", type("Clock", (), {"monotonic": staticmethod(lambda: clock["now"])})())
    monkeypatch.setattr(
        runner, "_call_single_run",
        lambda *_args, **_kwargs: pytest.fail("budget should be exhausted before a call"),
    )

    def inspect_environment(_base):
        clock["now"] += 61
        return {"fixture": True}

    monkeypatch.setattr(runner, "_execution_context", inspect_environment)
    result = runner.run_study(study_root, execute=True)

    assert result["status"] == "BUDGET_EXHAUSTED"
    assert result["elapsed_seconds"] >= 61
    assert result["solver_calls"] == 0


def test_real_python_child_is_isolated_and_records_ownership(tmp_path, monkeypatch):
    variable = "SIMSTUDIO_TEST_CHILD_ENV"
    monkeypatch.delenv(variable, raising=False)
    command = [
        sys.executable,
        "-c",
        ("import json, os; os.environ['SIMSTUDIO_TEST_CHILD_ENV']='child-only'; "
         "print(json.dumps({'status':'SOLVED','synthetic':False}))"),
    ]

    code, payload = runner._run_cli_child(command, tmp_path, timeout=5)

    owner = read_json(tmp_path / "owned-process.json")
    assert code == 0
    assert payload == {"status": "SOLVED", "synthetic": False}
    assert owner["pid"] > 0
    assert owner["ended_at"]
    assert owner["tree_verified"] is True
    assert variable not in os.environ


def test_real_python_child_timeout_stops_owned_process(tmp_path):
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    started = time.monotonic()

    code, payload = runner._run_cli_child(command, tmp_path, timeout=0.2)

    owner = read_json(tmp_path / "owned-process.json")
    assert code != 0
    assert payload["status"] == "ERROR"
    assert owner["tree_verified"] is True
    assert time.monotonic() - started < 5


def test_finalization_failure_cannot_leave_a_solved_attempt(study_root, monkeypatch):
    def call(_specification, directory, _execute, **_kwargs):
        directory.mkdir()
        atomic_json(directory / "run-manifest.json", {"mechanical_product_version": "fixture-only"})
        (directory / "fixture.txt").write_text("Protocol fixture only; no Mechanical execution occurred")
        (directory / "outside-link").symlink_to(Path(__file__))
        return 0, {"status": "SOLVED", "synthetic": False}

    monkeypatch.setattr(runner, "_call_single_run", call)
    monkeypatch.setattr(runner, "_execution_context", lambda _base: {"fixture": True})

    with pytest.raises(SpecValidationError, match="symbolic links"):
        runner.run_study(study_root, execute=True)

    manifest = read_json(study_root / "study-manifest.json")
    attempt = manifest["samples"][0]["jobs"][0]["attempts"][0]
    assert attempt["status"] == "FAILED"
    assert manifest["status"] == "FAILED"
