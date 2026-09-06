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
        "status": "PASS", "published_files": 8, "real_cases": 9,
        "solves": 5, "solver_started": False,
    }


def source_case():
    public = json.loads((ROOT / TOOL["EVIDENCE"] / "summary.json").read_text(encoding="utf-8"))["cases"][0]
    summary = {**public, "result_file": "C:/Users/private-user/project/file.rst"}
    verification = {"status": public["verification_status"], "checks": public["checks"]}
    manifest = {**public, "status": "SOLVED", "environment": {"license_token": "do-not-publish"}}
    return summary, verification, manifest


def test_allowlist_retains_resultants_and_warnings_without_host_details():
    summary, verification, manifest = source_case()
    exported = TOOL["public_case"]("cantilever", summary, verification, manifest)
    text = json.dumps(exported)
    assert "private-user" not in text and "do-not-publish" not in text
    reaction = exported["results"]["fixed_reaction"]
    assert reaction["canonical_sum_vector"][2] == pytest.approx(1000)
    assert reaction["reported_maximum"] == pytest.approx(1564.2596703544452)
    assert exported["verification_status"] == "WARN"
    assert {x["name"]: x["status"] for x in exported["checks"]}["visual_review"] == "NOT_RUN"


@pytest.mark.parametrize("synthetic", [True, None])
def test_unverified_or_synthetic_results_cannot_be_published_as_real(synthetic):
    summary, verification, manifest = source_case()
    summary["synthetic"] = synthetic
    with pytest.raises(ValueError, match="synthetic or unknown"):
        TOOL["public_case"]("cantilever", summary, verification, manifest)


def test_public_check_rejects_tampered_evidence(tmp_path):
    for relative in (TOOL["EVIDENCE"], TOOL["DEMO"]):
        shutil.copytree(ROOT / relative, tmp_path / relative)
    path = tmp_path / TOOL["EVIDENCE"] / "summary.json"
    data = copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
    data["cases"][0]["results"]["fixed_reaction"]["canonical_sum_vector"][2] = 1564.25967
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        TOOL["check"](tmp_path)
