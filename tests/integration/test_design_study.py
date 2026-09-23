"""Opt-in acceptance of parameterized CAD, serial solves and portable evidence."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from ansys_skill.study.bundles import export_bundle, import_bundle
from ansys_skill.study.project import create_plan, load_project
from ansys_skill.study.quality import evaluate_run
from ansys_skill.study.runner import run_study
from ansys_skill.study.storage import read_json, verify_hashes
from ansys_skill.study.templates import init_study

pytestmark = [
    pytest.mark.ansys_integration,
    pytest.mark.skipif(os.getenv("ANSYS_AVAILABLE") != "1",
                       reason="NOT_RUN: real design study requires ANSYS_AVAILABLE=1"),
]


def test_real_parameterized_study_resume_and_evidence_bundle(tmp_path: Path, request) -> None:
    if sys.platform != "win32":
        pytest.skip("NOT_RUN: controlled study acceptance uses local Windows Mechanical batch")
    if hasattr(request.config, "workerinput") or os.getenv("PYTEST_XDIST_WORKER"):
        pytest.fail("Real study acceptance must run serially")
    pytest.importorskip("build123d", reason="NOT_RUN: study CAD dependency unavailable")
    pytest.importorskip("scipy", reason="NOT_RUN: study sampling dependency unavailable")
    inputs, study_root = tmp_path / "inputs", tmp_path / "study"
    init_study(inputs)
    create_plan(inputs / "study.yaml", study_root)
    first = run_study(study_root, execute=True, limit=1)
    assert first["solver_calls"] == 3
    spec, _, first_manifest = load_project(study_root)
    baseline = first_manifest["samples"][0]
    assert baseline["status"] == "SOLVED"
    saved = [job["attempts"][-1]["hashes"] for job in baseline["jobs"]]
    resumed = run_study(study_root, execute=True, resume=True, limit=1)
    assert resumed["solver_calls"] == 6
    _, _, manifest = load_project(study_root)
    assert [job["attempts"][-1]["hashes"] for job in manifest["samples"][0]["jobs"]] == saved
    for sample in manifest["samples"][:2]:
        assert sample["status"] == "SOLVED"
        assert sample["geometry"]["solid_count"] == 1
        for job in sample["jobs"]:
            attempt = job["attempts"][-1]
            directory = study_root / attempt["path"]
            verify_hashes(directory, attempt["hashes"])
            summary = read_json(directory / "results-summary.json")
            assert summary["synthetic"] is False and summary["node_count"] > 0
            quality = evaluate_run(directory, spec, sample["geometry"])
            checks = {item["name"]: item["status"] for item in quality["checks"]}
            for name in ("real_solve", "source_configuration", "geometry_provenance",
                         "derived_reaction_balance"):
                assert checks[name] == "PASS", quality
            assert "stress" not in quality["accepted_targets"], "Stress needs an explicit review"
    archive = tmp_path / "results.zip"
    export_bundle(study_root, archive, kind="results")
    recovered = tmp_path / "recovered"
    import_bundle(archive, recovered, expected_study_id=manifest["study_id"])
    _, _, imported = load_project(recovered)
    assert imported == manifest
    for sample in imported["samples"][:2]:
        for job in sample["jobs"]:
            attempt = job["attempts"][-1]
            verify_hashes(recovered / attempt["path"], attempt["hashes"])
