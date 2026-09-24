"""Offline quality-gate tests; fixture runs are explicitly synthetic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ansys_skill.manifest import sha256_file
from ansys_skill.schema import load_spec
from ansys_skill.study.quality import (
    _applied_loads,
    _material_density_check,
    _mesh_shape_check,
    _mesh_target_valid,
    _review_check,
    _selected_faces_check,
    _status,
    _target_value_check,
    assess_mesh_convergence,
    evaluate_run,
)
from ansys_skill.study.schema import load_study
from ansys_skill.validation.statuses import CheckStatus

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "bracket-study"
BASE_SIMULATION = EXAMPLE / "base-simulation.yaml"
STUDY_FILE = EXAMPLE / "study.yaml"
_DENSITY = 7850.0
_SCOPES = {
    "mounting_face": {
        "area_m2": 0.02, "centroid_m": [0.0, 0.0, 0.09],
        "normal": [-1.0, 0.0, 0.0], "axis": "x", "extreme": "min",
    },
    "front_face": {
        "area_m2": 0.0032, "centroid_m": [0.24, 0.0, 0.17],
        "normal": [1.0, 0.0, 0.0], "axis": "x", "extreme": "max",
    },
    "bearing_pad": {
        "area_m2": 0.0042, "centroid_m": [0.165, 0.035, 0.188],
        "normal": [0.0, 0.0, 1.0], "axis": "z", "extreme": "max",
    },
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False) + "\n", encoding="utf-8")


def _geometry(run_dir: Path, simulation) -> dict:
    cad = run_dir / simulation.inputs.geometry_file
    cad.parent.mkdir(parents=True, exist_ok=True)
    cad.write_bytes(b"synthetic unit-test CAD fixture\n")
    volume = 0.001
    return {
        "volume_m3": volume, "mass_kg": volume * _DENSITY,
        "center_of_mass_m": [0.12, 0.04, 0.10],
        "geometry_sha256": sha256_file(cad),
        "body_name": simulation.bodies[0].name,
        "scopes": _SCOPES.copy(),
    }


def _face_records(scopes: dict | None = None) -> list[dict]:
    scopes = scopes or _SCOPES
    return [
        {
            "scope_id": name, "axis": scope["axis"], "extreme": scope["extreme"],
            "matched": [{
                "area": scope["area_m2"], "area_unit": "m^2",
                "centroid": scope["centroid_m"], "centroid_unit": "m",
                "normal": scope["normal"],
            }],
        }
        for name, scope in scopes.items()
    ]


def _make_synthetic_run(tmp_path: Path, *, density: float = _DENSITY,
                        wrong_face: bool = False) -> tuple[Path, object, dict, dict, Path]:
    study = load_study(STUDY_FILE)
    simulation, _ = load_spec(BASE_SIMULATION)
    run_dir = tmp_path / "synthetic-run"
    run_dir.mkdir()
    geometry = _geometry(run_dir, simulation)
    (run_dir / "ds.dat").write_text(
        f"/UNITS,MKS\nMP,DENS,1,{density}\n", encoding="ascii"
    )
    face_records = _face_records()
    if wrong_face:
        face_records[-1]["matched"][0]["area"] *= 0.8
    _write_json(run_dir / "face-selection-report.json", face_records)

    selected = {name: {key: scope[key] for key in ("area_m2", "centroid_m", "normal")}
                for name, scope in _SCOPES.items()}
    applied, _ = _applied_loads(simulation, geometry, selected, _DENSITY)
    reaction = [-component for component in [sum(row[i] for row in applied) for i in range(3)]]
    result_values = {
        "total_deformation": {"canonical_maximum": 1e-5, "canonical_unit": "meter",
                                "value_count": 8},
        "equivalent_stress": {"canonical_maximum": 1e7, "canonical_unit": "pascal",
                                "value_count": 8},
        "mounting_reaction": {"canonical_sum_vector": reaction,
                                "canonical_sum_vector_unit": "newton", "value_count": 4},
    }
    rst = run_dir / "solver" / "solution.rst"
    rst.parent.mkdir(parents=True)
    rst.write_bytes(b"synthetic RST placeholder; not an ANSYS result\n")
    summary = {
        "status": "POSTPROCESSED", "synthetic": True,
        "result_file": r"C:\solver-export\solution.rst",
        "node_count": 100, "element_count": 40, "results": result_values,
    }
    _write_json(run_dir / "results-summary.json", summary)
    check_items = [
        {"name": "mechanical_messages", "status": "PASS", "message": "fixture", "evidence": {}},
        {"name": "requested_results", "status": "PASS", "message": "fixture", "evidence": {}},
        {"name": "small_deformation", "status": "PASS", "message": "fixture", "evidence": {}},
        {"name": "reaction_balance", "status": "NOT_RUN", "message": "fixture", "evidence": {}},
        {"name": "stress_singularity_review", "status": "WARN", "message": "review required", "evidence": {}},
    ]
    _write_json(run_dir / "verification.json", {"status": _status(check_items), "checks": check_items})
    _write_json(run_dir / "mechanical-artifacts.json", {
        "status": "SOLVED", "result_files": ["solver/solution.rst"],
    })
    normalized = run_dir / "normalized-simulation.yaml"
    normalized.write_text(BASE_SIMULATION.read_text(encoding="utf-8"), encoding="utf-8")
    input_hash = sha256_file(run_dir / simulation.inputs.geometry_file)
    _write_json(run_dir / "run-manifest.json", {
        "status": "SOLVED", "synthetic": True, "failure_stage": None,
        "execution_mode": simulation.execution.backend,
        "hashes": {
            "input_sha256": input_hash, "source_spec_sha256": "a" * 64,
            "normalized_spec_sha256": sha256_file(normalized),
        },
    })
    return run_dir, study, geometry, summary, rst


def _target_check_records(study, target_name: str, *, review_status: str | None = None) -> list[dict]:
    names = ["verification_evidence", "source_configuration", "real_solve",
             "result_file", "material_density", "geometry_provenance", "selected_face_geometry",
             "mesh_shape_quality",
             f"target_value:{target_name}", *study.targets[target_name].required_checks]
    records = [{"name": name, "status": "PASS"} for name in dict.fromkeys(names)]
    if review_status is not None:
        records.append({"name": f"stress_review:{target_name}", "status": review_status})
    return records


def test_evaluate_run_with_missing_artifacts_does_not_accept_targets(tmp_path: Path) -> None:
    result = evaluate_run(tmp_path, load_study(STUDY_FILE), {})

    assert result["accepted_targets"] == []
    assert result["synthetic"] is True
    assert any(item["status"] == "NOT_RUN" for item in result["checks"])


def test_mesh_shape_gate_uses_complete_real_quality_fixture():
    fixture = json.loads((ROOT / "tests/fixtures/mesh-quality/mechanical-2026-r1.json")
                         .read_text(encoding="utf-8"))
    quality = next(project["mesh_quality"] for project in fixture["projects"]
                   if project["sample_id"] == "baseline-745f20e3fbfb55402bb7")

    result = _mesh_shape_check({"analysis": {"mesh_quality": quality}})

    assert result["status"] == "WARN"
    assert len(result["evidence"]["record"]["metrics"]) == 10
    assert result["evidence"]["warning_metrics"]


def test_missing_mesh_statistics_do_not_become_a_pass():
    assert _mesh_shape_check({})["status"] == "NOT_RUN"


def test_complete_synthetic_fixture_is_parsed_but_rejected(tmp_path: Path) -> None:
    run_dir, study, geometry, summary, rst = _make_synthetic_run(tmp_path)
    attempt = {
        "status": "SOLVED",
        "path": run_dir.relative_to(tmp_path).as_posix(),
        "hashes": {
            path.relative_to(run_dir).as_posix(): sha256_file(path)
            for path in run_dir.rglob("*") if path.is_file()
        },
    }
    study_manifest = {"samples": [{"jobs": [{"attempts": [attempt]}]}]}
    _write_json(tmp_path / "study-manifest.json", study_manifest)
    result = evaluate_run(run_dir, study, geometry)
    by_name = {item["name"]: item for item in result["checks"]}

    assert result["synthetic"] is True
    assert result["accepted_targets"] == []
    assert by_name["real_solve"]["status"] == "FAIL"
    assert by_name["result_file"]["status"] == "PASS"
    assert by_name["result_file"]["evidence"]["actual_sha256"] == sha256_file(rst)
    assert summary["result_file"].startswith("C:\\solver-export")
    assert sha256_file(rst) == result["evidence"]["result_file_sha256"]
    assert json.loads((run_dir / "results-summary.json").read_text(encoding="utf-8"))["result_file"] == summary["result_file"]
    assert all(by_name[name]["status"] == "PASS" for name in
               ("source_configuration", "material_density", "geometry_provenance"))

    attempt["hashes"]["solver/solution.rst"] = "0" * 64
    _write_json(tmp_path / "study-manifest.json", study_manifest)
    mismatched = evaluate_run(run_dir, study, geometry)
    mismatch_check = next(item for item in mismatched["checks"]
                          if item["name"] == "result_file")
    assert mismatch_check["status"] == "FAIL"


def test_target_value_requires_canonical_units_and_samples(tmp_path: Path) -> None:
    study = load_study(STUDY_FILE)
    simulation, _ = load_spec(BASE_SIMULATION)
    summary = {"results": {"total_deformation": {
        "canonical_maximum": -2e-5, "canonical_unit": "meter", "value_count": 4,
    }}}
    check, value = _target_value_check(study, "displacement", summary, simulation)
    assert check["status"] == "PASS" and value == 2e-5

    summary["results"]["total_deformation"]["value_count"] = 0
    check, value = _target_value_check(study, "displacement", summary, simulation)
    assert check["status"] == "FAIL" and value is None


def test_material_density_reads_matching_solver_deck(tmp_path: Path) -> None:
    study = load_study(STUDY_FILE)
    simulation, _ = load_spec(BASE_SIMULATION)
    (tmp_path / "ds.dat").write_text("/UNITS,MKS\nMP,DENS,1,7850\n", encoding="ascii")

    check, density = _material_density_check(tmp_path, study, simulation)

    assert check["status"] == "PASS"
    assert density == _DENSITY


def test_material_density_rejects_deck_mismatch(tmp_path: Path) -> None:
    study = load_study(STUDY_FILE)
    simulation, _ = load_spec(BASE_SIMULATION)
    (tmp_path / "ds.dat").write_text("/UNITS,MKS\nMP,DENS,1,7800\n", encoding="ascii")

    check, density = _material_density_check(tmp_path, study, simulation)

    assert check["status"] == "FAIL"
    assert density is None


def test_selected_face_geometry_matches_controlled_scopes(tmp_path: Path) -> None:
    simulation, _ = load_spec(BASE_SIMULATION)
    report = _face_records()
    (tmp_path / "face-selection-report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )

    check, selected = _selected_faces_check(tmp_path, _SCOPES, simulation)

    assert check["status"] == "PASS"
    assert set(selected) == set(_SCOPES)
    assert selected["bearing_pad"]["area_m2"] == pytest.approx(0.0042)


def test_selected_face_geometry_rejects_area_mismatch(tmp_path: Path) -> None:
    simulation, _ = load_spec(BASE_SIMULATION)
    report = _face_records()
    report[-1]["matched"][0]["area"] *= 0.8
    (tmp_path / "face-selection-report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )

    check, _ = _selected_faces_check(tmp_path, _SCOPES, simulation)

    assert check["status"] == "FAIL"


def test_stress_review_is_required_and_bound_to_rst_hash(tmp_path: Path) -> None:
    run_dir, study, geometry, _, rst = _make_synthetic_run(tmp_path)
    digest = sha256_file(rst)
    missing = _review_check("stress", digest, None)
    result = evaluate_run(run_dir, study, geometry, {digest: {
        "reviewer": "engineer@example.invalid",
        "rationale": "Reviewed the fixture only.",
        "evidence": ["test://mesh-review"], "status": "PASS",
    }})
    review = next(item for item in result["checks"] if item["name"] == "stress_review:stress")

    assert missing["status"] == "NOT_RUN"
    assert missing["evidence"]["review_status"] == "REVIEW_REQUIRED"
    assert review["status"] == "PASS"
    assert review["evidence"]["result_file_sha256"] == digest
    assert review["evidence"]["review_status"] == "PASS"
    assert result["synthetic"] is True and result["accepted_targets"] == []


def test_target_mesh_gate_ignores_unrelated_stress_review_failure() -> None:
    study = load_study(STUDY_FILE)
    level = {
        "status": "FAIL", "synthetic": True,
        "accepted_targets": ["displacement"],
        "target_checks": {
            "displacement": _target_check_records(study, "displacement"),
            "stress": _target_check_records(study, "stress", review_status="NOT_RUN"),
        },
    }

    displacement, _ = _mesh_target_valid(level, "displacement", study.targets["displacement"])
    stress, _ = _mesh_target_valid(level, "stress", study.targets["stress"])
    level["target_checks"]["displacement"] = _target_check_records(study, "displacement")
    level["target_checks"]["displacement"].append(
        {"name": "requested_results", "status": "FAIL"}
    )
    requested_results, _ = _mesh_target_valid(
        level, "displacement", study.targets["displacement"]
    )

    assert displacement is CheckStatus.PASS
    assert stress is CheckStatus.NOT_RUN
    assert requested_results is CheckStatus.FAIL


def test_mesh_convergence_requires_three_real_levels_and_tracks_changes(monkeypatch) -> None:
    study = load_study(STUDY_FILE)
    insufficient = assess_mesh_convergence(study, [])
    assert insufficient["checks"][0]["status"] == "NOT_RUN"

    # The synthetic rows are rejected by the normal level gate. Stub only global provenance below
    # to exercise target-local convergence arithmetic without claiming a real solver result.
    levels = [
        {"status": "FAIL", "synthetic": True,
         "accepted_targets": ["displacement"],
         "target_checks": {
             "displacement": _target_check_records(study, "displacement"),
             "stress": _target_check_records(study, "stress", review_status="NOT_RUN"),
         },
         "values": {"displacement": value, "stress": 1e7 + index * 500},
         "evidence": {"mesh_size_m": size, "node_count": nodes, "element_count": elements}}
        for index, (value, size, nodes, elements) in enumerate((
            (1.0e-5, 0.012, 100, 40), (1.04e-5, 0.008, 180, 80), (1.06e-5, 0.005, 300, 150),
        ))
    ]
    rejected = assess_mesh_convergence(study, levels)
    assert rejected["targets"]["displacement"]["status"] == "FAIL"
    monkeypatch.setattr(
        "ansys_skill.study.quality._mesh_level_valid",
        _mesh_target_valid,
    )
    result = assess_mesh_convergence(study, levels)

    displacement = result["targets"]["displacement"]
    assert displacement["status"] == "PASS"
    assert displacement["values"] == [1.0e-5, 1.04e-5, 1.06e-5]
    assert len(displacement["adjacent_changes"]) == 2
    assert result["targets"]["stress"]["status"] == "NOT_RUN"

    levels[-1]["values"]["displacement"] = 1.09e-5
    worsening = assess_mesh_convergence(study, levels)["targets"]["displacement"]
    assert worsening["status"] == "WARN"
    assert "worsening" in worsening["message"]


def test_mesh_rejects_global_requested_results_failure() -> None:
    study = load_study(STUDY_FILE)
    checks = _target_check_records(study, "displacement")
    next(item for item in checks if item["name"] == "requested_results")["status"] = "FAIL"
    level = {
        "status": "FAIL", "synthetic": True,
        "accepted_targets": ["displacement"],
        "target_checks": {"displacement": checks},
    }

    status, reason = _mesh_target_valid(level, "displacement", study.targets["displacement"])

    assert status is CheckStatus.FAIL
    assert "requested_results" in reason


def test_dpf_worker_failure_leaves_moment_not_run(tmp_path: Path, monkeypatch) -> None:
    simulation, _ = load_spec(BASE_SIMULATION)
    geometry = {"volume_m3": 0.001, "center_of_mass_m": [0.12, 0.04, 0.10]}
    selected = {name: {key: scope[key] for key in ("area_m2", "centroid_m", "normal")}
                for name, scope in _SCOPES.items()}
    rst = tmp_path / "solution.rst"
    rst.write_bytes(b"test placeholder")
    calls = []

    def unavailable(command, **_kwargs):
        calls.append(command)
        raise FileNotFoundError("worker runtime unavailable")

    monkeypatch.setattr("ansys_skill.study.quality.subprocess.run", unavailable)
    from ansys_skill.study.quality import _reaction_checks

    reaction, moment = _reaction_checks(
        tmp_path, simulation, {"results": {}}, rst, geometry, selected, _DENSITY, True,
        real_solve=True,
    )

    assert calls and Path(calls[0][1]).name == "quality_dpf_worker.py"
    assert reaction["status"] == "NOT_RUN"
    assert moment is not None and moment["status"] == "NOT_RUN"
