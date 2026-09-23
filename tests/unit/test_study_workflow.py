"""Integration of orchestration stages using explicit test doubles, never solver evidence."""
from __future__ import annotations

import copy

import pytest
from ansys_skill.errors import SpecValidationError
from ansys_skill.study import comparison, modeling, report, workflow
from ansys_skill.study.schema import StudySpec
from ansys_skill.study.storage import atomic_json, read_json
from ansys_skill.study.templates import example_study


@pytest.fixture
def workflow_state(tmp_path, monkeypatch):
    spec = StudySpec.model_validate(example_study())
    spec.optimization.max_rounds = 0
    manifest = {"models": [], "datasets": []}
    rows = [{"split": "train", "accepted_targets": ["displacement", "stress"],
             "mass_kg": 12.0, "feasibility": {"displacement": "FEASIBLE", "stress": "FEASIBLE"}}
            for _ in range(8)]
    data = {"rows": rows, "targets": {"displacement": {}, "stress": {}}}
    calls = []
    monkeypatch.setattr(workflow, "load_project", lambda *a, **k: (spec, None, manifest))
    monkeypatch.setattr(workflow, "latest_dataset", lambda *a: data)
    monkeypatch.setattr(workflow, "run_study", lambda *a, **k: {"status": "SOLVED" if k["execute"] else "DRY_RUN"})
    monkeypatch.setattr(workflow, "collect_dataset", lambda *a, **k: calls.append("collect"))
    monkeypatch.setattr(workflow, "train_study",
                        lambda *a: (calls.append("train") or {"status": "TRAINED"}))
    monkeypatch.setattr(workflow, "evaluate_study", lambda *a: {"status": "PASS"})
    monkeypatch.setattr(workflow, "verify_candidates", lambda *a, **k: {"status": "PASS"})
    monkeypatch.setattr(comparison, "run_comparison", lambda *a, **k: {"status": "PASS"})
    monkeypatch.setattr(report, "generate_study_report", lambda *a: {"status": "REPORTED"})
    return tmp_path, data, calls


def test_default_workflow_stops_after_dry_run_without_training(workflow_state):
    root, _, calls = workflow_state
    assert workflow.complete_workflow(root)["status"] == "DRY_RUN"
    assert calls == []


def test_missing_stress_quality_blocks_training(workflow_state):
    root, data, calls = workflow_state
    for row in data["rows"]:
        row["accepted_targets"] = ["displacement"]
    result = workflow.complete_workflow(root, execute=True)
    assert result["status"] == "REVIEW_REQUIRED"
    assert calls == ["collect"]


def test_model_failure_blocks_real_candidate_verification(workflow_state, monkeypatch):
    root, _, calls = workflow_state
    monkeypatch.setattr(workflow, "evaluate_study", lambda *a: {"status": "FAIL"})
    monkeypatch.setattr(workflow, "verify_candidates", lambda *a, **k: pytest.fail("Unqualified model was verified"))
    result = workflow.complete_workflow(root, execute=True)
    assert result["status"] == "FAIL"
    assert result["stage"] == "independent_model_evaluation"
    assert calls == ["collect", "train"]


def test_required_comparison_cannot_be_silently_skipped(workflow_state, monkeypatch):
    root, _, _ = workflow_state
    monkeypatch.setattr(comparison, "run_comparison", lambda *a, **k: {"status": "NOT_RUN"})
    result = workflow.complete_workflow(root, execute=True)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["engineering_validation"] == "PASS"
    assert result["equal_budget_comparison"]["status"] == "NOT_RUN"


@pytest.fixture
def model_lifecycle(tmp_path, monkeypatch):
    from ansys_skill import surrogate

    spec = StudySpec.model_validate(example_study())
    manifest = {"study_id": "lifecycle-fixture", "study_fingerprint": "fixture",
                "code_fingerprint": "fixture-code", "models": [],
                "datasets": ["datasets/fixture.json"], "frozen_test_designs": ["test-1"]}
    data = {"dataset_id": "fixture-data", "rows": [{"design_id": "test-1", "split": "test",
             "accepted_targets": ["displacement", "stress"]}]}
    state_path = tmp_path / "state.json"
    atomic_json(state_path, manifest)
    monkeypatch.setattr(modeling, "load_project",
                        lambda *a, **k: (spec, None, read_json(state_path)))
    monkeypatch.setattr(modeling, "save_project", lambda root, state: atomic_json(state_path, state))
    monkeypatch.setattr(modeling, "latest_dataset", lambda *a: copy.deepcopy(data))

    def train_fixture(dataset, directory, options):
        atomic_json(directory / "model.json", {"model_id": "fixture-model",
                                               "evidence_kind": "analytic_test"})
        return {"model_id": "fixture-model"}

    monkeypatch.setattr(surrogate, "train_model", train_fixture)
    monkeypatch.setattr(surrogate, "load_model", lambda directory: read_json(directory / "model.json"))
    return tmp_path, state_path, data


def test_atomic_model_is_registered_after_manifest_publication_interruption(model_lifecycle, monkeypatch):
    from ansys_skill.study import timing

    root, state_path, _ = model_lifecycle
    save = modeling.save_project
    timing_save = timing.save_project

    def interrupted(*args):
        raise OSError("Injected manifest publication failure")

    monkeypatch.setattr(modeling, "save_project", interrupted)
    monkeypatch.setattr(timing, "save_project", interrupted)
    with pytest.raises(OSError, match="publication"):
        modeling.train_study(root)
    assert read_json(state_path)["models"] == []
    assert len(list(root.glob("models/*/model.json"))) == 1
    monkeypatch.setattr(modeling, "save_project", save)
    monkeypatch.setattr(timing, "save_project", timing_save)
    recovered = modeling.train_study(root)
    assert recovered["reused"] is True
    records = read_json(state_path)["models"]
    assert len(records) == 1 and records[0]["path"] == recovered["path"]
    modeling.train_study(root)
    assert len(read_json(state_path)["models"]) == 1


def test_incomplete_holdout_does_not_publish_errors_or_freeze_training(model_lifecycle, monkeypatch):
    from ansys_skill import surrogate

    root, state_path, data = model_lifecycle
    data["rows"][0]["accepted_targets"] = ["displacement"]
    monkeypatch.setattr(modeling, "latest_model", lambda *a: root / "models/fixture")
    monkeypatch.setattr(surrogate, "evaluate_model", lambda *a: pytest.fail("Premature test inspection"))
    result = modeling.evaluate_study(root)
    assert result["status"] == "NOT_RUN" and result["missing_design_ids"] == ["test-1"]
    assert "holdout_evaluated" not in read_json(state_path)


def test_holdout_commit_survives_evaluation_interruption_and_rejects_model_switch(model_lifecycle, monkeypatch):
    from ansys_skill import surrogate

    root, state_path, _ = model_lifecycle
    model = root / "models/fixture"
    monkeypatch.setattr(modeling, "latest_model", lambda *a: model)

    def interrupted(*args):
        assert read_json(state_path)["holdout_evaluated"]["model"] == "models/fixture"
        raise OSError("Injected evaluation failure")

    monkeypatch.setattr(surrogate, "evaluate_model", interrupted)
    with pytest.raises(OSError, match="evaluation"):
        modeling.evaluate_study(root)
    monkeypatch.setattr(modeling, "latest_model", lambda *a: root / "models/other")
    with pytest.raises(SpecValidationError, match="first evaluated model"):
        modeling.evaluate_study(root)
    monkeypatch.setattr(modeling, "latest_model", lambda *a: model)
    monkeypatch.setattr(surrogate, "evaluate_model", lambda *a: {"status": "PASS"})
    assert modeling.evaluate_study(root)["status"] == "PASS"
    assert read_json(model / "evaluation.json")["status"] == "PASS"


def test_failed_analysis_time_counts_against_later_work(model_lifecycle, monkeypatch):
    from ansys_skill import surrogate
    from ansys_skill.study import timing

    root, state_path, _ = model_lifecycle
    clock = {"now": 0.0}
    monkeypatch.setattr(timing.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(timing, "save_project",
                        lambda directory, manifest: atomic_json(state_path, manifest))

    def failed_training(*args):
        clock["now"] = 90000.0
        raise OSError("Injected training failure")

    monkeypatch.setattr(surrogate, "train_model", failed_training)
    with pytest.raises(OSError, match="training failure"):
        modeling.train_study(root)
    state = read_json(state_path)
    assert state["elapsed_seconds"] == 90000.0
    assert state["phase_timings"]["model_training"]["calls"] == 1
    monkeypatch.setattr(surrogate, "train_model", lambda *a: pytest.fail("Budget exhausted"))
    assert modeling.train_study(root)["status"] == "BUDGET_EXHAUSTED"
