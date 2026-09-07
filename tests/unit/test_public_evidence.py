from __future__ import annotations

import copy
import json
import runpy
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = runpy.run_path(str(ROOT / "tools/export_benchmark_evidence.py"))


def test_public_snapshot_is_self_contained_and_hash_verified():
    assert TOOL["check"](ROOT) == {
        "status": "PASS", "published_files": 8, "real_cases": 5,
        "solves": 5, "solver_started": False,
    }


def source_case():
    evidence = json.loads((ROOT / TOOL["EVIDENCE"] / "summary.json").read_text(encoding="utf-8"))
    public = next(case for case in evidence["cases"] if case["id"] == evidence["primary_case"])
    summary = {**public, "result_file": "C:/Users/private-user/project/file.rst"}
    verification = {"status": public["verification_status"], "checks": public["checks"]}
    manifest = {**public, "status": "SOLVED", "environment": {"license_token": "do-not-publish"}}
    return summary, verification, manifest


def test_allowlist_retains_resultants_and_warnings_without_host_details():
    summary, verification, manifest = source_case()
    exported = TOOL["public_case"]("mixed_5mm", summary, verification, manifest)
    text = json.dumps(exported)
    assert "private-user" not in text and "do-not-publish" not in text
    reaction = exported["results"]["mounting_reaction"]
    assert reaction["canonical_sum_vector"] == pytest.approx([-1000, -1500, 3977.9670171685343])
    assert reaction["reported_maximum"] == pytest.approx(94.25915585594748)
    assert exported["verification_status"] == "WARN"
    assert {x["name"]: x["status"] for x in exported["checks"]}["visual_review"] == "NOT_RUN"


def test_engineering_evidence_drops_nested_private_diagnostics():
    summary, verification, manifest = source_case()
    engineering = copy.deepcopy(summary)
    engineering["checks"] = engineering["engineering_checks"]
    force = next(item for item in engineering["checks"] if item["name"] == "force_balance")
    force["evidence"]["debug_path"] = "C:/Users/private-user/solver/ds.dat"
    force["evidence"]["license_token"] = "do-not-publish"
    exported = TOOL["public_case"]("mixed_5mm", summary, verification, manifest, engineering)
    text = json.dumps(exported)
    assert "private-user" not in text and "do-not-publish" not in text
    published = next(item for item in exported["engineering_checks"] if item["name"] == "force_balance")
    assert published["evidence"]["relative_residual"] < 0.005


def test_public_check_binds_the_current_geometry_to_recorded_results(tmp_path):
    shutil.copytree(ROOT / TOOL["EVIDENCE"], tmp_path / TOOL["EVIDENCE"])
    example = TOOL["DEMO"].parent
    shutil.copytree(ROOT / example, tmp_path / example)
    assert TOOL["check"](tmp_path)["status"] == "PASS"
    geometry = tmp_path / example / "gusseted-bracket.step"
    geometry.write_bytes(geometry.read_bytes() + b"changed input")
    with pytest.raises(ValueError, match="geometry hash mismatch"):
        TOOL["check"](tmp_path)


@pytest.mark.parametrize("synthetic", [True, None])
def test_unverified_or_synthetic_results_cannot_be_published_as_real(synthetic):
    summary, verification, manifest = source_case()
    summary["synthetic"] = synthetic
    with pytest.raises(ValueError, match="synthetic or unknown"):
        TOOL["public_case"]("mixed_5mm", summary, verification, manifest)


def test_public_check_rejects_tampered_evidence(tmp_path):
    for relative in (TOOL["EVIDENCE"], TOOL["DEMO"]):
        shutil.copytree(ROOT / relative, tmp_path / relative)
    path = tmp_path / TOOL["EVIDENCE"] / "summary.json"
    data = copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
    data["cases"][0]["results"]["mounting_reaction"]["canonical_sum_vector"][2] = 94.259156
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        TOOL["check"](tmp_path)


@pytest.mark.parametrize("name", ["offline.log", "junit.xml"])
def test_raw_test_records_cannot_reenter_public_evidence(tmp_path, name):
    for relative in (TOOL["EVIDENCE"], TOOL["DEMO"]):
        shutil.copytree(ROOT / relative, tmp_path / relative)
    (tmp_path / TOOL["EVIDENCE"] / name).write_text("local working record", encoding="utf-8")
    with pytest.raises(ValueError, match="local archive"):
        TOOL["check"](tmp_path)
