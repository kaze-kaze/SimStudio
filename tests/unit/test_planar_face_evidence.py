"""Replay recorded API measurements without requiring ANSYS or a license."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from ansys_skill.schema import load_spec
from ansys_skill.study.planar_faces import boundaries_match, measure_planar_face
from ansys_skill.study.quality import _selected_faces_check

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "tests/fixtures/planar-faces/mechanical-2026-r1.json").read_text())["cases"]


def _records(case):
    return [{"scope_id": name, "axis": case["expected_scopes"][name]["axis"],
             "extreme": case["expected_scopes"][name]["extreme"],
             "matched": [{"area": record["reported_area"], "area_unit": record["unit"] + "^2",
                          "centroid": record["reported_centroid"], "centroid_unit": record["unit"],
                          "normal": case["expected_scopes"][name]["normal"],
                          "boundary": {"status": "CAPTURED", **record["boundary"]}}]}
            for name, record in case["mechanical_scopes"].items()]


@pytest.mark.parametrize("case", CASES, ids=["baseline", "training-design"])
def test_actual_curves_match_cad_despite_tessellated_area_error(tmp_path, case):
    simulation, _ = load_spec(ROOT / "examples/bracket-study/base-simulation.yaml")
    report = _records(case)
    (tmp_path / "face-selection-report.json").write_text(json.dumps(report))
    check, selected = _selected_faces_check(tmp_path, case["expected_scopes"], simulation)

    assert check["status"] == "PASS"
    mounting = next(face for face in check["evidence"]["faces"] if face["scope_id"] == "mounting_face")
    assert abs(mounting["reported_tessellation_area_m2"] / mounting["expected_area_m2"] - 1) > 1e-4
    for name, record in case["mechanical_scopes"].items():
        expected = case["expected_scopes"][name]
        measured = measure_planar_face(record["boundary"], axis=expected["axis"],
                                       unit=record["unit"], tolerance_m=1e-9)
        assert boundaries_match(measured["boundary_summary"], expected["boundary_summary"], 1e-9)
        assert selected[name]["area_m2"] == pytest.approx(expected["area_m2"], rel=1e-10)
        assert selected[name]["centroid_m"] == pytest.approx(expected["centroid_m"], abs=1e-12)


@pytest.mark.parametrize("defect", ["missing", "moved-hole", "missing-hole", "bad-curve", "wrong-normal"])
def test_invalid_boundary_never_falls_back_to_matching_display_values(tmp_path, defect):
    simulation, _ = load_spec(ROOT / "examples/bracket-study/base-simulation.yaml")
    case = copy.deepcopy(CASES[0])
    report = _records(case)
    face = next(item["matched"][0] for item in report if item["scope_id"] == "mounting_face")
    face["area"] = case["expected_scopes"]["mounting_face"]["area_m2"] * 1e6
    face["centroid"] = [value * 1e3 for value in case["expected_scopes"]["mounting_face"]["centroid_m"]]
    if defect == "missing":
        face.pop("boundary")
    elif defect == "moved-hole":
        for point in face["boundary"]["loops"][1]["edges"][0]["points"]:
            point[1] += 1.0
    elif defect == "missing-hole":
        face["boundary"]["loops"].pop()
    elif defect == "bad-curve":
        face["boundary"]["loops"][1]["edges"][0]["curve_type"] = "GeoCurveBSpline"
    else:
        face["normal"] = [1, 0, 0]
    (tmp_path / "face-selection-report.json").write_text(json.dumps(report))

    check, _ = _selected_faces_check(tmp_path, case["expected_scopes"], simulation)

    assert check["status"] == ("NOT_RUN" if defect == "missing" else "FAIL")
