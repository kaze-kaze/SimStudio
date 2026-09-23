from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from ansys_skill.errors import SpecValidationError
from ansys_skill.study import optimization, project
from ansys_skill.study.sampling import sample_record
from ansys_skill.study.templates import init_study


def point(thickness: float, hole: float, fillet: float) -> dict[str, float]:
    return {
        "plate_thickness": thickness,
        "hole_diameter": hole,
        "fillet_radius": fillet,
    }


BASELINE = point(0.020, 0.014, 0.010)
TRAIN_POINTS = [
    point(0.018, 0.012, 0.008),
    point(0.021, 0.015, 0.009),
    point(0.019, 0.016, 0.011),
    point(0.022, 0.011, 0.008),
    point(0.017, 0.013, 0.012),
    point(0.023, 0.014, 0.010),
]
TEST_POINTS = [
    point(0.016, 0.012, 0.009),
    point(0.024, 0.010, 0.006),
    point(0.018, 0.017, 0.012),
]
CANDIDATE_POINTS = [
    TEST_POINTS[0],
    point(0.018, 0.013, 0.007),
    point(0.022, 0.012, 0.011),
    point(0.017, 0.016, 0.010),
]


@pytest.fixture
def optimization_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    from ansys_skill import surrogate
    from ansys_skill.study import geometry

    inputs = tmp_path / "inputs"
    init_study(inputs)
    source = inputs / "study.yaml"
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    document["sampling"].update(train_samples=6, test_samples=3, include_corners=False)
    document["budget"]["max_solver_calls"] = 60
    document["optimization"].update(
        candidate_pool=16,
        batch_size=2,
        max_rounds=1,
        verification_candidates=1,
    )
    source.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    initial = [sample_record(BASELINE, "baseline")]
    initial.extend(sample_record(parameters, "train", ordinal=index + 1)
                   for index, parameters in enumerate(TRAIN_POINTS))
    initial.extend(sample_record(parameters, "test", ordinal=index + 7)
                   for index, parameters in enumerate(TEST_POINTS))
    monkeypatch.setattr(project, "plan_samples", lambda study: (copy.deepcopy(initial), []))
    root = tmp_path / "study"
    project.create_plan(source, root)
    study, _, manifest = project.load_project(root)

    # Initial evidence is represented only as a completed ledger; no solver is invoked.
    for sample in manifest["samples"]:
        sample["status"] = "SOLVED"
        for job in sample["jobs"]:
            job["status"] = "SOLVED"
            job["attempts"] = [{"status": "SOLVED"}]
    manifest["solver_calls"] = sum(len(sample["jobs"]) for sample in manifest["samples"])
    project.save_project(root, manifest)

    model_directory = tmp_path / "model"
    model_document = {
        "model_id": "fixture-model-v1",
        "study_fingerprint": manifest["study_fingerprint"],
    }
    monkeypatch.setattr(optimization, "latest_model", lambda *_args, **_kwargs: model_directory)
    monkeypatch.setattr(surrogate, "load_model", lambda _directory: model_document)

    sample_points = copy.deepcopy(CANDIDATE_POINTS)
    latin_calls: list[int] = []

    def fixed_latin_points(_bounds, count: int, _seed: int) -> list[dict[str, float]]:
        latin_calls.append(count)
        return copy.deepcopy(sample_points)

    monkeypatch.setattr(optimization, "latin_points", fixed_latin_points)

    prediction_statuses: dict[tuple[float, float, float], str] = {}

    def predict(_directory: Path, parameters: dict[str, float]) -> dict:
        key = tuple(parameters[name] for name in ("plate_thickness", "hole_diameter", "fillet_radius"))
        status = prediction_statuses.get(key, "PREDICTED")
        predictions = {}
        for name, target in study.targets.items():
            metadata = target.canonical()
            predictions[name] = {
                "value": metadata["limit"] * 0.75,
                "std": metadata["reference_scale"] * 0.01,
                "unit": metadata["unit"],
            }
        return {"status": status, "predictions": predictions}

    monkeypatch.setattr(surrogate, "predict_model", predict)

    cad_calls: list[dict[str, float]] = []

    def mock_controlled_cad_summary(parameters: dict[str, float], _density: float) -> dict:
        cad_calls.append(dict(parameters))
        return {"mass_kg": parameters["plate_thickness"]}

    monkeypatch.setattr(geometry, "geometry_summary", mock_controlled_cad_summary)

    return {
        "root": root,
        "study": study,
        "latin_calls": latin_calls,
        "cad_calls": cad_calls,
        "prediction_statuses": prediction_statuses,
    }


def complete_mock_solver_jobs(
    root: Path,
    *,
    execute: bool,
    resume: bool,
    splits: tuple[str, ...],
    solver_call_limit: int,
) -> dict:
    assert execute is True
    assert resume is True
    assert splits in {("train",), ("verification",)}
    _, _, manifest = project.load_project(root)
    added_calls = 0
    for sample in manifest["samples"]:
        if sample["split"] not in splits or "candidate_plan" not in sample:
            continue
        for job in sample["jobs"]:
            if job["status"] == "SOLVED":
                continue
            job["status"] = "SOLVED"
            job["attempts"].append({"status": "SOLVED"})
            added_calls += 1
        sample["status"] = "SOLVED"
    manifest["solver_calls"] += added_calls
    project.save_project(root, manifest)
    return {
        "status": "SOLVED",
        "new_solver_calls": added_calls,
        "solver_call_limit": solver_call_limit,
    }


def test_adaptive_proposal_is_reused_before_round_limit_and_freezes_test(optimization_case):
    root = optimization_case["root"]
    first = optimization.propose_candidates(root)
    dry_run = optimization.execute_proposal(root, first, execute=False)
    second = optimization.propose_candidates(root)

    assert first["purpose"] == "adaptive"
    assert first["status"] == "PROPOSED"
    assert dry_run["plan_id"] == first["plan_id"]
    assert second == first
    assert len(optimization_case["latin_calls"]) == 1
    assert len(optimization_case["cad_calls"]) == 3
    assert not ({candidate["design_id"] for candidate in first["candidates"]}
                & set(project.load_project(root)[2]["frozen_test_designs"]))
    assert len(project.load_project(root)[2]["rounds"]) == 1


def test_adaptive_proposal_and_execution_are_blocked_after_comparison_creation(optimization_case):
    root = optimization_case["root"]
    plan = optimization.propose_candidates(root)
    _, _, manifest = project.load_project(root)
    manifest["direct_comparison"] = {"status": "PLANNED"}
    project.save_project(root, manifest)
    sample_count = len(manifest["samples"])

    with pytest.raises(SpecValidationError, match="after a direct comparison plan"):
        optimization.propose_candidates(root)
    with pytest.raises(SpecValidationError, match="after a direct comparison plan"):
        optimization.execute_proposal(root, plan, execute=True)

    assert len(project.load_project(root)[2]["samples"]) == sample_count


def test_plan_hash_rejects_candidate_content_changes_before_execution(optimization_case, monkeypatch):
    plan = optimization.propose_candidates(optimization_case["root"])
    plan["candidates"][0]["mass_kg"] += 1.0
    runner_calls = []
    monkeypatch.setattr(optimization, "run_study", lambda *args, **kwargs: runner_calls.append(kwargs))

    with pytest.raises(SpecValidationError, match="Candidate plan was modified"):
        optimization.execute_proposal(optimization_case["root"], plan, execute=True)

    assert runner_calls == []
    assert len(project.load_project(optimization_case["root"])[2]["samples"]) == 10


def test_candidate_budget_matches_mock_solver_attempt_ledger(optimization_case, monkeypatch):
    root = optimization_case["root"]
    plan = optimization.propose_candidates(root)
    before = project.load_project(root)[2]

    assert plan["budget"]["solver_calls_used"] == 30
    assert plan["budget"]["reserved_final_verification_calls"] == 6
    assert plan["candidate_solver_calls"] == len(plan["candidates"]) * 3 == 6
    assert plan["budget"]["planned_candidate_calls"] == plan["candidate_solver_calls"]
    assert plan["budget"]["max_candidate_solver_calls"] == 12
    monkeypatch.setattr(optimization, "run_study", complete_mock_solver_jobs)

    result = optimization.execute_proposal(root, plan, execute=True)
    after = project.load_project(root)[2]
    actual_new_calls = after["solver_calls"] - before["solver_calls"]

    assert actual_new_calls == plan["candidate_solver_calls"]
    assert result["new_solver_calls"] == actual_new_calls
    assert result["solver_call_limit"] == 30
    assert all(sample["split"] == "train" for sample in after["samples"][-len(plan["candidates"]):])
    assert after["rounds"][plan["round"]]["status"] == "SOLVED"
    assert optimization.propose_candidates(root)["status"] == "ROUND_LIMIT"


def test_interrupted_execution_resumes_the_same_candidates(optimization_case, monkeypatch):
    root = optimization_case["root"]
    plan = optimization.propose_candidates(root)
    attempts = []

    def interrupt_once(*_args, **_kwargs):
        attempts.append("interrupted")
        raise KeyboardInterrupt

    monkeypatch.setattr(optimization, "run_study", interrupt_once)
    with pytest.raises(KeyboardInterrupt):
        optimization.execute_proposal(root, plan, execute=True)

    _, _, scheduled = project.load_project(root)
    scheduled_samples = [sample for sample in scheduled["samples"] if sample.get("candidate_plan") == plan["plan"]]
    assert len(scheduled_samples) == len(plan["candidates"])
    assert scheduled["rounds"][plan["round"]]["status"] == "SCHEDULED"

    monkeypatch.setattr(optimization, "run_study", complete_mock_solver_jobs)
    optimization.execute_proposal(root, plan, execute=True)
    _, _, resumed = project.load_project(root)
    resumed_samples = [sample for sample in resumed["samples"] if sample.get("candidate_plan") == plan["plan"]]

    assert len(attempts) == 1
    assert len(resumed_samples) == len(plan["candidates"])
    assert resumed["solver_calls"] - scheduled["solver_calls"] == plan["candidate_solver_calls"]
    assert all(sample["status"] == "SOLVED" for sample in resumed_samples)


def test_needs_solve_candidates_keep_values_but_are_never_marked_supported(optimization_case):
    statuses = optimization_case["prediction_statuses"]
    for parameters in CANDIDATE_POINTS[1:]:
        statuses[tuple(parameters[name] for name in ("plate_thickness", "hole_diameter", "fillet_radius"))] = "NEEDS_SOLVE"

    plan = optimization.propose_candidates(optimization_case["root"])

    assert len(plan["candidates"]) == 2
    assert all(candidate["prediction_status"] == "NEEDS_SOLVE" for candidate in plan["candidates"])
    assert all(candidate["surrogate_supported"] is False for candidate in plan["candidates"])
    assert all(candidate["violation_score"] is None for candidate in plan["candidates"])
    assert all(candidate["solver_confirmation_required"] is True for candidate in plan["candidates"])
    assert all(candidate["predictions"] for candidate in plan["candidates"])


def test_repeated_verification_proposal_reuses_registered_plan(optimization_case):
    root = optimization_case["root"]

    first = optimization.verify_candidates(root, execute=False)
    second = optimization.verify_candidates(root, execute=False)

    assert first["purpose"] == second["purpose"] == "verification"
    assert first["plan_id"] == second["plan_id"]
    assert len(first["candidates"]) == 1
    assert len(optimization_case["latin_calls"]) == 1
    assert len(optimization_case["cad_calls"]) == 3
    _, _, manifest = project.load_project(root)
    assert len(manifest["rounds"]) == 1
    assert not ({candidate["design_id"] for candidate in first["candidates"]}
                & set(manifest["frozen_test_designs"]))


def test_comparison_rows_are_allowed_but_isolated_from_training_and_test(tmp_path: Path):
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    from ansys_skill.surrogate import models

    rows = []
    for index, x in enumerate((0.0, 0.2, 0.4, 0.6, 0.8, 1.0)):
        rows.append({
            "sample_id": f"train-{index}", "design_id": f"train-design-{index}",
            "split": "train", "parameters": {"x": x},
            "targets": {"response": 1.0 + 2.0 * x}, "accepted_targets": ["response"],
            "source": {"synthetic": True, "kind": "analytic_test"},
        })
    for index, x in enumerate((0.15, 0.5, 0.85)):
        rows.append({
            "sample_id": f"test-{index}", "design_id": f"test-design-{index}",
            "split": "test", "parameters": {"x": x},
            "targets": {"response": 1.0 + 2.0 * x}, "accepted_targets": ["response"],
            "source": {"synthetic": True, "kind": "analytic_test"},
        })
    rows.append({
        "sample_id": "comparison-0", "design_id": "comparison-design-0",
        "split": "comparison", "parameters": {"x": 0.33},
        "targets": {"response": 1000.0}, "accepted_targets": ["response"],
        "source": {"synthetic": True, "kind": "analytic_test"},
    })
    dataset = {
        "schema_version": "1.0", "dataset_id": "comparison-isolation-fixture",
        "study_fingerprint": "comparison-isolation-study", "evidence_kind": "analytic_test",
        "feature_names": ["x"], "feature_units": {"x": "meter"}, "bounds": {"x": [0.0, 1.0]},
        "frozen_test_designs": [f"test-design-{index}" for index in range(3)],
        "targets": {"response": {
            "unit": "meter", "dimension": "length", "absolute_tolerance": 1e-6,
            "relative_tolerance": 1e-6, "reference_scale": 1.0, "limit": 4.0,
        }},
        "rows": rows,
    }
    directory = tmp_path / "analytic-test-model"
    models._train_analytic_test_model(dataset, directory, {"cv_folds": 3})
    model = models.load_model(directory)
    result = models._evaluate_analytic_test_model(directory, dataset)

    assert model["target_models"]["response"]["training_sample_ids"] == [
        f"train-{index}" for index in range(6)
    ]
    assert result["status"] == "PASS"
    assert result["sample_count"] == 3
    assert {point["sample_id"] for point in result["targets"]["response"]["points"]} == {
        "test-0", "test-1", "test-2"
    }
