"""Focused tests for strict raw mesh quality evidence and warning reviews."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from ansys_skill.study.mesh_quality import (
    assess_mesh_quality,
    mesh_quality_review_check,
    mesh_target_gate,
)
from ansys_skill.study.storage import canonical_hash

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "mesh-quality" / "mechanical-2026-r1.json"
_RST_HASH = "a" * 64


@pytest.fixture
def real_quality() -> dict:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["source"]["r3"] and fixture["source"]["r2"]
    assert len(fixture["projects"]) == 5
    assert all(project["sample_id"] and project["source_project_sha256"]
               for project in fixture["projects"])
    assert all(len(project["mesh_quality"]["metrics"]) == 10
               for project in fixture["projects"])
    return fixture["projects"][0]["mesh_quality"]


def _fixture_projects() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["projects"]


def _passing_quality(source: dict) -> dict:
    quality = copy.deepcopy(source)
    shape_directions = {
        "AspectRatio": "higher",
        "ElementQuality": "lower",
        "JacobianRatioCornerNodes": "lower",
        "JacobianRatioGaussPoints": "lower",
        "MaximumCornerAngle": "higher",
        "Skewness": "higher",
        "TetCollapse": "lower",
    }
    for metric in quality["metrics"]:
        if metric["metric"] not in shape_directions:
            continue
        metric["error_count"] = 0
        metric["warning_count"] = 0
        warning_limit = metric["warning_limit"]["value"]
        epsilon = max(abs(warning_limit) * 1e-6, 1e-9)
        worst = warning_limit - epsilon if shape_directions[metric["metric"]] == "higher" else warning_limit + epsilon
        metric["worst"]["value"] = worst
        metric["average"]["value"] = worst - epsilon if shape_directions[metric["metric"]] == "higher" else worst + epsilon
    return quality


def _review(quality: dict, *, targets=("displacement",)) -> dict:
    return {_RST_HASH: {
        "mesh_quality_review": {
            "status": "PASS",
            "quality_sha256": canonical_hash(quality),
            "targets": list(targets),
            "reviewer": "reviewer",
            "rationale": "Reviewed the recorded shape warnings and their locations.",
            "evidence": ["mesh-quality worksheet evidence"],
        },
    }}


def test_real_r3_fixture_retains_raw_diagnostics_and_is_warn(real_quality: dict) -> None:
    result = assess_mesh_quality(real_quality)

    assert result["status"] == "WARN"
    assert result["quality_sha256"] == canonical_hash(real_quality)
    assert result["evidence"]["warning_metrics"] == [
        "AspectRatio", "JacobianRatioCornerNodes", "MaximumCornerAngle", "Skewness",
    ]
    assert any("MaxEdgeLength" in item
               for item in result["evidence"]["diagnostic_count_contradictions"])
    assert len(result["evidence"]["record"]["metrics"]) == 10


def test_real_r2_pilot_records_fail_only_on_shape_error_limits() -> None:
    projects = {item["sample_id"]: item for item in _fixture_projects()[2:]}
    twelve = assess_mesh_quality(projects["12 mm"]["mesh_quality"])
    eight = assess_mesh_quality(projects["8 mm"]["mesh_quality"])
    five = assess_mesh_quality(projects["5 mm"]["mesh_quality"])

    assert twelve["status"] == "FAIL"
    assert twelve["evidence"]["error_metrics"] == ["MaximumCornerAngle", "Skewness"]
    assert eight["status"] == "FAIL"
    assert eight["evidence"]["error_metrics"] == ["MaximumCornerAngle"]
    assert five["status"] == "WARN"
    assert all(any(metric["metric"] == "MaxEdgeLength"
                   for metric in result["evidence"]["record"]["metrics"])
               for result in (twelve, eight, five))
    assert all("MaxEdgeLength" not in result["evidence"]["error_metrics"]
               for result in (twelve, eight, five))


def test_complete_seven_metric_shape_set_can_pass_without_changing_limits(real_quality: dict) -> None:
    quality = _passing_quality(real_quality)
    original_limits = {metric["metric"]: (metric["error_limit"], metric["warning_limit"])
                       for metric in real_quality["metrics"]}
    result = assess_mesh_quality(quality)

    assert result["status"] == "PASS"
    assert len([metric for metric in result["evidence"]["record"]["metrics"]
                if metric["metric"] in {"AspectRatio", "ElementQuality",
                                            "JacobianRatioCornerNodes",
                                            "JacobianRatioGaussPoints",
                                            "MaximumCornerAngle", "Skewness",
                                            "TetCollapse"}]) == 7
    assert original_limits == {metric["metric"]: (metric["error_limit"], metric["warning_limit"])
                               for metric in quality["metrics"]}


def test_shape_gate_needs_all_seven_required_metrics(real_quality: dict) -> None:
    quality = copy.deepcopy(real_quality)
    quality["metrics"] = [m for m in quality["metrics"] if m["metric"] != "TetCollapse"]

    result = assess_mesh_quality(quality)

    assert result["status"] == "NOT_RUN"
    assert result["evidence"]["missing_metrics"] == ["TetCollapse"]


@pytest.mark.parametrize("malformation", ["duplicate", "nonfinite", "unit", "negative_count"])
def test_malformed_raw_metric_records_fail(real_quality: dict, malformation: str) -> None:
    quality = copy.deepcopy(real_quality)
    metric = next(item for item in quality["metrics"] if item["metric"] == "ElementQuality")
    if malformation == "duplicate":
        quality["metrics"].append(copy.deepcopy(metric))
    elif malformation == "nonfinite":
        metric["worst"]["value"] = float("inf")
    elif malformation == "unit":
        metric["worst"]["unit"] = "deg"
    else:
        metric["warning_count"] = -1

    assert assess_mesh_quality(quality)["status"] == "FAIL"


def test_shape_count_contradiction_is_not_approved(real_quality: dict) -> None:
    quality = copy.deepcopy(real_quality)
    metric = next(item for item in quality["metrics"] if item["metric"] == "AspectRatio")
    metric["warning_count"] = 0

    assert assess_mesh_quality(quality)["status"] == "NOT_RUN"


def test_mesh_warning_review_requires_current_hashes_and_explicit_target(real_quality: dict) -> None:
    digest = canonical_hash(real_quality)
    accepted = mesh_quality_review_check("displacement", _RST_HASH, digest,
                                         _review(real_quality), "WARN")
    wrong_target = mesh_quality_review_check("stress", _RST_HASH, digest,
                                             _review(real_quality), "WARN")
    wrong_quality_hash = _review(real_quality)
    wrong_quality_hash[_RST_HASH]["mesh_quality_review"]["quality_sha256"] = "b" * 64
    mismatched = mesh_quality_review_check("displacement", _RST_HASH, digest,
                                           wrong_quality_hash, "WARN")
    wrong_rst = mesh_quality_review_check("displacement", "c" * 64, digest,
                                          _review(real_quality), "WARN")

    assert accepted["status"] == "PASS"
    assert wrong_target["status"] == "NOT_RUN"
    assert mismatched["status"] == "FAIL"
    assert wrong_rst["status"] == "NOT_RUN"


@pytest.mark.parametrize(("raw_status", "review_status", "expected"), [
    ("PASS", "NOT_RUN", "PASS"),
    ("WARN", None, "NOT_RUN"),
    ("WARN", "PASS", "PASS"),
    ("FAIL", "PASS", "FAIL"),
    ("NOT_RUN", "PASS", "NOT_RUN"),
])
def test_review_only_resolves_raw_warning(raw_status: str, review_status: str | None, expected: str) -> None:
    assert mesh_target_gate(raw_status, review_status).value == expected


def test_review_cannot_replace_native_error_limit(real_quality: dict) -> None:
    quality = copy.deepcopy(real_quality)
    metric = next(item for item in quality["metrics"] if item["metric"] == "ElementQuality")
    metric["worst"]["value"] = 0.0001
    metric["error_count"] = 1
    result = assess_mesh_quality(quality)
    review = mesh_quality_review_check("displacement", _RST_HASH, result["quality_sha256"],
                                       _review(quality), result["status"])

    assert result["status"] == "FAIL"
    assert metric["error_limit"]["value"] == 0.0005
    assert review["status"] == "FAIL"
