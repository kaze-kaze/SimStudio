from __future__ import annotations

import pytest
from ansys_skill.errors import SpecValidationError
from ansys_skill.study import comparison
from ansys_skill.study.schema import StudySpec
from ansys_skill.study.storage import atomic_json
from ansys_skill.study.templates import example_study


def _sample(split, calls):
    return {"split": split, "design_id": split, "jobs": [{"attempts": [{}] * calls}]}


def test_direct_comparison_counts_training_retries_and_final_verification(tmp_path, monkeypatch):
    spec = StudySpec.model_validate(example_study())
    manifest = {"samples": [_sample("baseline", 3), _sample("test", 6),
                             _sample("train", 22), _sample("verification", 6)],
                "solver_calls": 37}
    monkeypatch.setattr(comparison, "load_project", lambda *a, **k: (spec, None, manifest))
    monkeypatch.setattr(comparison, "save_project", lambda *a: None)
    monkeypatch.setattr(comparison, "latin_points", lambda bounds, count, seed: [
        {"plate_thickness": 0.014 + i * 0.0001, "hole_diameter": 0.014, "fillet_radius": 0.008}
        for i in range(count)])
    result = comparison.comparison_plan(tmp_path)
    assert result["shared_solver_calls"] == 9
    assert result["direct_search_allowance"] == 28
    assert result["surrogate_solver_calls"] == 37
    assert result["sample_count"] == 9
    assert result["inference_used_for_sampling"] is False
    assert len(result["parameters"]) == 9
    assert comparison.comparison_plan(tmp_path) == result


def test_comparison_cannot_exceed_total_study_budget(tmp_path, monkeypatch):
    spec = StudySpec.model_validate(example_study())
    manifest = {"samples": [_sample("baseline", 3), _sample("train", 210)],
                "solver_calls": 213}
    monkeypatch.setattr(comparison, "load_project", lambda *a, **k: (spec, None, manifest))
    result = comparison.comparison_plan(tmp_path)
    assert result["status"] == "BUDGET_EXHAUSTED"
    assert result["required_solver_calls"] == 210
    assert not (tmp_path / "comparison-plan.json").exists()


def test_registered_comparison_plan_freezes_research_designs_and_attempt_ledger(tmp_path, monkeypatch):
    spec = StudySpec.model_validate(example_study())
    manifest = {"samples": [_sample(split, 3) for split in
                             ("baseline", "test", "train", "verification")],
                "solver_calls": 12}
    monkeypatch.setattr(comparison, "load_project", lambda *a, **k: (spec, None, manifest))
    monkeypatch.setattr(comparison, "save_project", lambda *a: None)
    monkeypatch.setattr(comparison, "latin_points", lambda bounds, count, seed: [
        {"plate_thickness": 0.014 + i * 0.0001, "hole_diameter": 0.014, "fillet_radius": 0.008}
        for i in range(count)])

    plan = comparison.comparison_plan(tmp_path)
    manifest["samples"].append(_sample("comparison", 1))
    assert comparison.comparison_plan(tmp_path) == plan
    manifest["samples"][2]["jobs"][0]["attempts"].append({"status": "FAILED"})

    with pytest.raises(SpecValidationError, match="comparison plan is stale"):
        comparison.comparison_plan(tmp_path)
    with pytest.raises(SpecValidationError, match="comparison plan is stale"):
        comparison.run_comparison(tmp_path, execute=True)
    assert plan["research_snapshot"]["design_ids"] == {
        "baseline": ["baseline"], "test": ["test"], "train": ["train"],
        "verification": ["verification"],
    }


def test_registered_comparison_plan_expires_when_verification_design_is_added(tmp_path, monkeypatch):
    spec = StudySpec.model_validate(example_study())
    manifest = {"samples": [_sample(split, 3) for split in ("baseline", "train")],
                "solver_calls": 6}
    monkeypatch.setattr(comparison, "load_project", lambda *a, **k: (spec, None, manifest))
    monkeypatch.setattr(comparison, "save_project", lambda *a: None)
    monkeypatch.setattr(comparison, "latin_points", lambda bounds, count, seed: [
        {"plate_thickness": 0.014 + i * 0.0001, "hole_diameter": 0.014, "fillet_radius": 0.008}
        for i in range(count)])

    comparison.comparison_plan(tmp_path)
    new_verification = _sample("verification", 0)
    new_verification["design_id"] = "verification-new"
    manifest["samples"].append(new_verification)

    with pytest.raises(SpecValidationError, match="comparison plan is stale"):
        comparison.comparison_plan(tmp_path)


def test_verified_candidate_is_read_only_from_verification_artifact(tmp_path):
    spec = StudySpec.model_validate(example_study())
    target_values = {name: target.canonical()["limit"] * 0.5
                     for name, target in spec.targets.items()}
    target_names = list(spec.targets)
    fingerprint = "study-fingerprint"
    model_id = "frozen-model"
    plan_path = "optimization/round-000/plan.json"
    candidate = {
        "sample_id": "verification-abc",
        "design_id": "abc",
        "mass_kg": 1.25,
        "targets": target_values,
        "accepted_targets": target_names,
        "verified": True,
        "feasible": True,
        "prediction_errors": {name: 0.0 for name in target_names},
    }
    atomic_json(tmp_path / plan_path, {
        "study_fingerprint": fingerprint, "model_id": model_id,
        "candidates": [{"design_id": candidate["design_id"]}],
    })
    atomic_json(tmp_path / "verification.json", {
        "status": "PASS", "best_sample_id": candidate["sample_id"], "candidates": [candidate],
        "study_fingerprint": fingerprint, "model_id": model_id,
    })
    manifest = {
        "study_fingerprint": fingerprint, "frozen_test_designs": [],
        "rounds": [{"purpose": "verification", "plan": plan_path, "model_id": model_id}],
        "samples": [{"sample_id": candidate["sample_id"], "design_id": candidate["design_id"],
                     "split": "verification", "candidate_plan": plan_path}],
        "holdout_evaluated": {"model_id": model_id},
    }
    row = {
        "sample_id": candidate["sample_id"], "design_id": candidate["design_id"],
        "split": "verification", "mass_kg": candidate["mass_kg"],
        "targets": target_values, "accepted_targets": target_names,
        "feasibility": {name: "FEASIBLE" for name in target_names},
        "source": {"kind": "solver", "synthetic": False, "complete_real_evidence": True},
    }
    dataset = {"study_fingerprint": fingerprint, "frozen_test_designs": [], "rows": [row]}

    result, status = comparison._verified_candidate(tmp_path, spec, dataset, manifest)

    assert status == "RECORDED"
    assert result == {**candidate, "model_id": model_id, "study_fingerprint": fingerprint}

    atomic_json(tmp_path / "verification.json", {
        "status": "PASS", "best_sample_id": candidate["sample_id"], "candidates": [candidate],
        "study_fingerprint": fingerprint, "model_id": "replaced-model",
    })
    assert comparison._verified_candidate(tmp_path, spec, dataset, manifest) == (None, "STALE")


def test_target_margins_use_canonical_limits_and_preserve_missing_evidence():
    spec = StudySpec.model_validate(example_study())
    row = {"targets": {"displacement": 0.5 * spec.targets["displacement"].canonical()["limit"]}}

    margins = comparison._target_margins(row, spec)

    assert margins["displacement"]["margin"] == pytest.approx(
        margins["displacement"]["limit"] - margins["displacement"]["value"])
    assert margins["displacement"]["unit"] == "meter"
    missing = next(name for name in spec.targets if name not in row["targets"])
    assert margins[missing]["status"] == "NOT_RUN"
    assert margins[missing]["value"] is None
    assert margins[missing]["margin"] is None


def test_costs_include_failed_attempts_and_keep_unknown_time_explicit():
    attempts = [
        {"status": "SOLVED", "elapsed_seconds": 2.5},
        {"status": "FAILED", "elapsed_seconds": 1.25},
        {"status": "INTERRUPTED", "elapsed_seconds": None},
    ]

    costs = comparison._cost_summary(attempts)

    assert costs["calls"] == 3
    assert costs["failed_calls"] == 2
    assert costs["known_seconds"] == pytest.approx(3.75)
    assert costs["seconds"] is None
    assert costs["unknown_time_calls"] == 1
    assert costs["status"] == "PARTIAL"


def test_phase_costs_keep_backend_total_separate_and_unknown_stages_not_run():
    manifest = {"samples": [{"split": "comparison", "jobs": [{"attempts": [
        {"status": "FAILED", "phase_timings": {
            "mesh": {"status": "RECORDED", "elapsed_seconds": 1.0},
            "solve": {"status": "RECORDED", "elapsed_seconds": 4.0},
            "backend_total": {"status": "RECORDED", "elapsed_seconds": 5.0},
        }},
        {"status": "SOLVED", "phase_timings": {
            "mesh": {"status": "RECORDED", "elapsed_seconds": 2.0},
        }},
    ]}]}]}

    costs = comparison._phase_costs(manifest)["comparison"]

    assert costs["mesh"]["known_seconds"] == pytest.approx(3.0)
    assert costs["mesh"]["status"] == "RECORDED"
    assert costs["backend_total"]["known_seconds"] == pytest.approx(5.0)
    assert costs["backend_total"]["unknown_attempts"] == 1
    assert costs["backend_total"]["status"] == "PARTIAL"
    assert costs["postprocessing"]["status"] == "NOT_RUN"
    assert costs["postprocessing"]["known_seconds"] is None


def test_comparison_dry_run_never_executes_solver(tmp_path, monkeypatch):
    atomic_json(tmp_path / "placeholder.json", {"test_fixture": True})
    monkeypatch.setattr(comparison, "comparison_plan", lambda root: {"status": "PLANNED"})
    monkeypatch.setattr(comparison, "run_study", lambda *a, **k: pytest.fail("Unexpected solver"))
    assert comparison.run_comparison(tmp_path) == {"status": "PLANNED"}


def test_completed_solver_ledger_without_collected_control_rows_cannot_pass(tmp_path, monkeypatch):
    spec = StudySpec.model_validate(example_study())
    parameters = {"plate_thickness": 0.018, "hole_diameter": 0.012, "fillet_radius": 0.008}
    plan = {"status": "PLANNED", "parameters": [parameters],
            "direct_search_allowance": 3, "shared_solver_calls": 3, "surrogate_solver_calls": 6}
    manifest = {"samples": [], "models": [], "elapsed_seconds": 1}
    plan["research_snapshot"] = comparison._research_snapshot(manifest)
    baseline = {"sample_id": "baseline", "design_id": "baseline", "split": "baseline",
                "mass_kg": 2.0, "targets": {"displacement": 1e-5, "stress": 1e6},
                "accepted_targets": list(spec.targets), "solver_command_seconds": 1.0,
                "feasibility": {name: "FEASIBLE" for name in spec.targets}}
    dataset = {"rows": [baseline]}
    monkeypatch.setattr(comparison, "comparison_plan", lambda root: plan)
    monkeypatch.setattr(comparison, "load_project", lambda *a, **k: (spec, None, manifest))
    monkeypatch.setattr(comparison, "save_project", lambda *a: None)
    monkeypatch.setattr(comparison, "collect_dataset", lambda *a, **k: None)
    monkeypatch.setattr(comparison, "latest_dataset", lambda *a: dataset)

    def solved(*args, **kwargs):
        for sample in manifest["samples"]:
            sample["status"] = "SOLVED"
            for job in sample["jobs"]:
                job["attempts"] = [{"status": "SOLVED"}]
        return {"status": "SOLVED"}

    monkeypatch.setattr(comparison, "run_study", solved)
    first_report = comparison.run_comparison(tmp_path, execute=True)
    assert first_report["status"] == "NOT_RUN"
    assert first_report["recommendation_status"] == "OBSERVED_TRAINING_NOT_INDEPENDENTLY_VERIFIED"
    assert first_report["verified_candidate"] is None
    assert first_report["solver_costs_by_split"]["comparison"]["calls"] == 3
    sample = manifest["samples"][0]
    dataset["rows"].append({**baseline, "sample_id": sample["sample_id"],
                            "design_id": sample["design_id"], "split": "comparison"})
    assert comparison.run_comparison(tmp_path, execute=True)["status"] == "PASS"


@pytest.mark.parametrize(
    ("runner_status", "sample_status", "attempt_status", "expected_status"),
    [
        ("PARTIAL", "FAILED", "FAILED", "FAILED"),
        ("BUDGET_EXHAUSTED", "PLANNED", None, "BUDGET_EXHAUSTED"),
    ],
)
def test_comparison_report_exposes_failure_and_budget_exhaustion(
    tmp_path, monkeypatch, runner_status, sample_status, attempt_status, expected_status,
):
    spec = StudySpec.model_validate(example_study())
    parameters = {"plate_thickness": 0.018, "hole_diameter": 0.012, "fillet_radius": 0.008}
    manifest = {"samples": [], "models": [], "elapsed_seconds": 1, "solver_calls": 0}
    plan = {
        "status": "PLANNED", "parameters": [parameters], "direct_search_allowance": 3,
        "shared_solver_calls": 0, "surrogate_solver_calls": 3,
        "research_snapshot": comparison._research_snapshot(manifest),
    }
    baseline = {
        "sample_id": "baseline", "design_id": "baseline", "split": "baseline",
        "mass_kg": 2.0, "targets": {name: 0.5 * target.canonical()["limit"]
                                       for name, target in spec.targets.items()},
        "accepted_targets": list(spec.targets),
        "feasibility": {name: "FEASIBLE" for name in spec.targets},
    }
    monkeypatch.setattr(comparison, "comparison_plan", lambda _root: plan)
    monkeypatch.setattr(comparison, "load_project", lambda *a, **k: (spec, None, manifest))
    monkeypatch.setattr(comparison, "save_project", lambda *a: None)
    monkeypatch.setattr(comparison, "collect_dataset", lambda *a, **k: None)
    monkeypatch.setattr(comparison, "latest_dataset", lambda *a: {"rows": [baseline]})

    def run(*_args, **_kwargs):
        for sample in manifest["samples"]:
            sample["status"] = sample_status
            if attempt_status is not None:
                for job in sample["jobs"]:
                    job["attempts"] = [{"status": attempt_status, "elapsed_seconds": 2.0}]
        manifest["solver_calls"] = sum(
            len(job["attempts"]) for sample in manifest["samples"] for job in sample["jobs"]
        )
        return {"status": runner_status}

    monkeypatch.setattr(comparison, "run_study", run)
    report = comparison.run_comparison(tmp_path, execute=True)

    assert report["status"] == expected_status
    if expected_status == "FAILED":
        assert report["failures"]["failed_attempts"] == len(spec.mesh.sizes)
        assert report["solver_costs_by_split"]["comparison"]["seconds"] == 2.0 * len(spec.mesh.sizes)
    else:
        assert report["failures"]["budget_exhausted"] is True
