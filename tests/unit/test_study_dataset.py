"""Collection contract tests using explicitly synthetic protocol fixtures."""
from __future__ import annotations

import shutil

import pytest
from ansys_skill.study import dataset, project, quality
from ansys_skill.study.sampling import sample_record
from ansys_skill.study.storage import artifact_hashes, atomic_json, read_json
from ansys_skill.study.templates import init_study


@pytest.fixture
def collection_root(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "plan_samples", lambda spec: ([sample_record(spec.baseline(), "baseline")], []))
    init_study(tmp_path / "inputs")
    root = tmp_path / "study"
    project.create_plan(tmp_path / "inputs" / "study.yaml", root)
    _, _, manifest = project.load_project(root)
    sample = manifest["samples"][0]
    sample["geometry"] = {"mass_kg": 1.0, "geometry_sha256": "a" * 64}
    for job in sample["jobs"]:
        path = f"samples/{sample['sample_id']}/mesh-{job['mesh_index']}/attempt-001/run"
        directory = root / path
        directory.mkdir(parents=True)
        atomic_json(directory / "fixture.json", {"synthetic": True, "mesh_index": job["mesh_index"]})
        job["status"] = "SOLVED"
        job["attempts"].append({"status": "SOLVED", "path": path,
                                "hashes": artifact_hashes(directory), "elapsed_seconds": 1.0})
    manifest["solver_calls"] = 3
    sample["status"] = "SOLVED"
    project.save_project(root, manifest)
    return root


def test_target_specific_quality_is_not_replaced_by_overall_status(collection_root, monkeypatch):
    def evaluate(run_dir, study, geometry, reviews):
        return {"status": "WARN", "synthetic": False,
                "values": {"displacement": 2e-5, "stress": 9e6},
                "accepted_targets": ["displacement"],
                "checks": [], "target_checks": {},
                "evidence": {"fixture": "Injected eligibility, not solver evidence"}}
    monkeypatch.setattr(quality, "evaluate_run", evaluate)
    monkeypatch.setattr(quality, "assess_mesh_convergence", lambda *args: {
        "status": "WARN", "targets": {"displacement": {"status": "PASS"},
                                        "stress": {"status": "NOT_RUN"}}})
    result = dataset.collect_dataset(collection_root)
    data = dataset.load_dataset(collection_root / result["dataset"])
    context = data["engineering_context"]
    assert context["geometry"] == {"generator": "gusseted_bracket", "generator_version": "1"}
    assert context["material_evidence"]["density"] == "7850 kg/m^3"
    assert {load["type"] for load in context["simulation"]["loads"]} == {"force", "pressure", "gravity"}
    assert "inputs" not in context["simulation"]
    row = data["rows"][0]
    assert row["accepted_targets"] == ["displacement"]
    assert row["feasibility"] == {"displacement": "FEASIBLE", "stress": "UNKNOWN"}
    again = dataset.collect_dataset(collection_root)
    assert again["dataset_id"] == result["dataset_id"]
    assert len(read_json(collection_root / "study-manifest.json")["datasets"]) == 1


def test_integrity_failure_never_enters_training(collection_root, monkeypatch):
    def cannot_evaluate(*args):
        pytest.fail("Corrupted artifact was evaluated")
    monkeypatch.setattr(quality, "evaluate_run", cannot_evaluate)
    for file in collection_root.glob("samples/**/fixture.json"):
        file.write_text("tampered")
    result = dataset.collect_dataset(collection_root)
    data = dataset.load_dataset(collection_root / result["dataset"])
    assert data["rows"][0]["accepted_targets"] == []
    assert data["excluded"]


def test_dry_runs_have_no_numerical_training_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "plan_samples", lambda spec: ([sample_record(spec.baseline(), "baseline")], []))
    init_study(tmp_path / "inputs")
    root = tmp_path / "study"
    project.create_plan(tmp_path / "inputs" / "study.yaml", root)
    result = dataset.collect_dataset(root)
    assert result["accepted"] == {"displacement": 0, "stress": 0}
    assert result["engineering_validation"] == "NOT_RUN"
    assert dataset.load_dataset(root / result["dataset"])["rows"] == []


def test_mutated_dataset_is_rejected(tmp_path):
    path = tmp_path / "dataset.json"
    atomic_json(path, {"dataset_id": "a" * 64, "rows": []})
    from ansys_skill.errors import SpecValidationError
    with pytest.raises(SpecValidationError, match="hash"):
        dataset.load_dataset(path)


def test_dataset_identity_survives_project_relocation(collection_root, tmp_path, monkeypatch):
    def fixture_quality(run_dir, *args):
        return {"status": "WARN", "synthetic": True, "values": {}, "accepted_targets": [],
                "checks": [], "evidence": {"run_directory": str(run_dir),
                                            "fixture": "Portable synthetic protocol fixture"}}

    monkeypatch.setattr(quality, "evaluate_run", fixture_quality)
    original = dataset.collect_dataset(collection_root)
    destination = tmp_path / "imported-study"
    shutil.copytree(collection_root, destination)
    relocated = dataset.collect_dataset(destination)
    assert relocated["dataset_id"] == original["dataset_id"]
    row = dataset.load_dataset(destination / relocated["dataset"])["rows"][0]
    assert row["quality"][0]["evidence"]["run_directory"].startswith("samples/")
