from __future__ import annotations

import pytest
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
    assert comparison.run_comparison(tmp_path, execute=True)["status"] == "NOT_RUN"
    sample = manifest["samples"][0]
    dataset["rows"].append({**baseline, "sample_id": sample["sample_id"],
                            "design_id": sample["design_id"], "split": "comparison"})
    assert comparison.run_comparison(tmp_path, execute=True)["status"] == "PASS"
