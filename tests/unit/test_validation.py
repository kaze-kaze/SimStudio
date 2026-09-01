from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from ansys_skill.schema import SimulationSpec, load_spec
from ansys_skill.validation.cantilever import (
    analytical_tip_displacement,
    validate_cantilever,
)
from ansys_skill.validation.preflight import preflight_checks
from ansys_skill.validation.results import post_solve_checks
from ansys_skill.validation.statuses import Check, CheckStatus, aggregate_checks


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([CheckStatus.PASS], CheckStatus.PASS),
        ([CheckStatus.PASS, CheckStatus.WARN], CheckStatus.WARN),
        ([CheckStatus.PASS, CheckStatus.NOT_RUN], CheckStatus.WARN),
        ([CheckStatus.NOT_RUN], CheckStatus.NOT_RUN),
        ([CheckStatus.WARN, CheckStatus.FAIL], CheckStatus.FAIL),
    ],
)
def test_status_aggregation(statuses: list[CheckStatus], expected: CheckStatus) -> None:
    checks = [Check(str(index), status, "test") for index, status in enumerate(statuses)]
    assert aggregate_checks(checks) is expected


def test_cantilever_formula(valid_spec_path: Path) -> None:
    spec, _ = load_spec(valid_spec_path)
    config = spec.validation.cantilever
    assert analytical_tip_displacement(config) == pytest.approx(0.000125)
    check = validate_cantilever(config, {"tip_z": -0.000125})
    assert check.status is CheckStatus.PASS


def test_cantilever_failure(valid_spec_path: Path) -> None:
    spec, _ = load_spec(valid_spec_path)
    check = validate_cantilever(spec.validation.cantilever, {"tip_z": 0.001})
    assert check.status is CheckStatus.FAIL


def test_post_solve_checks_pass_core_contract(valid_spec_path: Path) -> None:
    spec, _ = load_spec(valid_spec_path)
    summary = {
        "result_file": "file.rst",
        "node_count": 100,
        "element_count": 50,
        "solver_messages": [],
        "results": {
            "total_deformation": {"maximum": 0.000125, "unit": "m"},
            "tip_z": {"maximum": -0.000125, "unit": "m"},
            "equivalent_stress": {"maximum": 50e6, "unit": "Pa"},
            "fixed_reaction": {
                "maximum": 1000.0,
                "unit": "N",
                "sum_vector": [0.0, 0.0, 1000.0],
            },
        },
    }
    checks = post_solve_checks(spec, summary)
    by_name = {check.name: check.status for check in checks}
    assert by_name["requested_results"] is CheckStatus.PASS
    assert by_name["reaction_balance"] is CheckStatus.PASS
    assert by_name["small_deformation"] is CheckStatus.PASS
    assert by_name["cantilever_analytical"] is CheckStatus.PASS
    assert by_name["stress_singularity_review"] is CheckStatus.WARN
    assert by_name["safety_factor"] is CheckStatus.NOT_RUN


def test_pressure_load_makes_reaction_balance_not_run(
    valid_document: dict[str, object],
) -> None:
    document = copy.deepcopy(valid_document)
    document["loads"] = [
        {
            "id": "surface_pressure",
            "type": "pressure",
            "scope": "load_face",
            "magnitude": "1 MPa",
        }
    ]
    spec = SimulationSpec.model_validate(document)
    summary = {
        "result_file": "file.rst",
        "node_count": 100,
        "element_count": 50,
        "solver_messages": [],
        "results": {
            "total_deformation": {"maximum": 0.0001, "unit": "m"},
            "tip_z": {"maximum": -0.0001, "unit": "m"},
            "equivalent_stress": {"maximum": 50e6, "unit": "Pa"},
            "fixed_reaction": {
                "maximum": 1000.0,
                "unit": "N",
                "sum_vector": [0.0, 0.0, 1000.0],
            },
        },
    }
    checks = post_solve_checks(spec, summary)
    reaction = next(check for check in checks if check.name == "reaction_balance")
    assert reaction.status is CheckStatus.NOT_RUN


def test_unknown_mechanical_message_severity_warns(valid_spec_path: Path) -> None:
    spec, _ = load_spec(valid_spec_path)
    summary = {
        "result_file": "file.rst",
        "node_count": 10,
        "element_count": 5,
        "solver_messages": [
            {"severity": "UNKNOWN", "text": "Message API unavailable: fixture"}
        ],
        "results": {},
    }
    check = post_solve_checks(spec, summary)[0]
    assert check.name == "mechanical_messages"
    assert check.status is CheckStatus.WARN


def test_unverified_geometry_suffix_is_rejected(
    tmp_path: Path, valid_document: dict[str, object]
) -> None:
    geometry = tmp_path / "beam.iges"
    geometry.write_text("fixture", encoding="utf-8")
    document = copy.deepcopy(valid_document)
    document["inputs"]["geometry_file"] = geometry.name  # type: ignore[index]
    spec_path = tmp_path / "simulation.yaml"
    spec_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    spec, _ = load_spec(spec_path)
    input_check = next(
        check for check in preflight_checks(spec, spec_path) if check.name == "input_file"
    )
    assert input_check.status is CheckStatus.FAIL
