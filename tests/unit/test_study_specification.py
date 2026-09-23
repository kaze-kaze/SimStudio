from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from ansys_skill.errors import SpecValidationError
from ansys_skill.schema import SimulationSpec
from ansys_skill.study.project import load_project, validate_base
from ansys_skill.study.schema import StudySpec
from ansys_skill.study.storage import (
    atomic_json,
    canonical_hash,
    read_json,
    recover_lock,
    recovery_guard,
    study_lock,
)
from ansys_skill.study.templates import example_simulation, example_study, init_study
from pydantic import ValidationError


def test_example_is_unit_qualified_and_budget_covers_mesh_and_holdout():
    study = StudySpec.model_validate(example_study())
    base = SimulationSpec.model_validate(example_simulation())
    validate_base(study, base)
    assert study.bounds()["plate_thickness"] == pytest.approx([0.014, 0.024])
    assert study.targets["stress"].canonical()["limit"] == pytest.approx(10e6)
    assert study.initial_solver_calls() == 123


@pytest.mark.parametrize("change", [
    lambda x: x["parameters"]["plate_thickness"].update(lower="14"),
    lambda x: x["parameters"]["hole_diameter"].update(upper="8 mm"),
    lambda x: x["parameters"]["fillet_radius"].update(baseline="20 mm"),
    lambda x: x.update(budget={"max_solver_calls": 1}),
    lambda x: x.update(mesh={"sizes": ["5 mm", "8 mm", "12 mm"]}),
    lambda x: x["targets"]["stress"].update(require_stress_review=False),
    lambda x: x["targets"]["displacement"].update(limit="1 MPa"),
    lambda x: x.update(python="print('not executable')"),
])
def test_invalid_studies_are_rejected_before_sampling(change):
    data = example_study()
    change(data)
    with pytest.raises((ValidationError, SpecValidationError)):
        StudySpec.model_validate(data)


def test_base_mismatch_cannot_silently_change_loading_faces():
    study = StudySpec.model_validate(example_study())
    base = example_simulation()
    base["scopes"][1]["axis"] = "y"
    with pytest.raises(SpecValidationError, match="front_face"):
        validate_base(study, SimulationSpec.model_validate(base))


def test_installed_template_initialization_needs_no_repository(tmp_path):
    result = init_study(tmp_path / "inputs")
    assert result["solver_started"] is False
    document = yaml.safe_load((tmp_path / "inputs" / "study.yaml").read_text())
    assert StudySpec.model_validate(document).name == "bracket-lightweighting"
    with pytest.raises(SpecValidationError):
        init_study(tmp_path / "inputs")


def test_atomic_json_rejects_nonfinite_and_preserves_previous_value(tmp_path):
    path = tmp_path / "state.json"
    atomic_json(path, {"sample": 3})
    with pytest.raises(ValueError):
        atomic_json(path, {"sample": float("nan")})
    assert read_json(path) == {"sample": 3}
    assert not list(tmp_path.glob(".write-*"))


def test_lock_blocks_concurrent_writer_and_cannot_recover_live_owner(tmp_path):
    with study_lock(tmp_path):
        with pytest.raises(SpecValidationError, match="locked"), study_lock(tmp_path):
            pytest.fail("Second writer entered")
        with (
            recovery_guard(tmp_path) as recovery_token,
            pytest.raises(SpecValidationError, match="still running"),
        ):
            recover_lock(tmp_path, recovery_token=recovery_token)
    assert not (tmp_path / ".study.lock").exists()


def test_changed_frozen_partition_is_detected(tmp_path, monkeypatch):
    from ansys_skill.study import project

    monkeypatch.setattr(project, "plan_samples", lambda spec: ([
        {"sample_id": "test-one", "design_id": "not-the-design-id", "split": "test",
         "parameters": spec.baseline(), "status": "PLANNED"},
    ], []))
    init_study(tmp_path / "inputs")
    project.create_plan(tmp_path / "inputs" / "study.yaml", tmp_path / "plan")
    with pytest.raises(SpecValidationError, match="design identity"):
        load_project(tmp_path / "plan")


def test_study_digest_is_independent_of_dictionary_order():
    first = example_study()
    second = copy.deepcopy(first)
    second["parameters"] = dict(reversed(list(second["parameters"].items())))
    assert canonical_hash(first) == canonical_hash(second)


def test_generated_schema_matches_source():
    root = Path(__file__).resolve().parents[2]
    assert json.loads((root / "schemas" / "study.schema.json").read_text()) == StudySpec.model_json_schema()
