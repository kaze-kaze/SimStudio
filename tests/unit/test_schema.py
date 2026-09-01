from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from ansys_skill.errors import SpecValidationError, UnsupportedFeatureError
from ansys_skill.schema import SimulationSpec, load_spec


def _write(tmp_path: Path, document: dict[str, object]) -> Path:
    path = tmp_path / "simulation.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_example_schema_loads(valid_spec_path: Path) -> None:
    spec, raw = load_spec(valid_spec_path)
    assert spec.schema_version == "1.0"
    assert raw["mode"] == "from_geometry"
    assert spec.open_questions == []


def test_unknown_field_is_rejected(tmp_path: Path, valid_document: dict[str, object]) -> None:
    document = copy.deepcopy(valid_document)
    document["typo_field"] = True
    with pytest.raises(SpecValidationError) as exc_info:
        load_spec(_write(tmp_path, document))
    assert "extra_forbidden" in str(exc_info.value.details)


def test_nested_unknown_field_is_rejected(
    tmp_path: Path, valid_document: dict[str, object]
) -> None:
    document = copy.deepcopy(valid_document)
    document["mesh"]["global_size"] = "5 mm"  # type: ignore[index]
    with pytest.raises(SpecValidationError):
        load_spec(_write(tmp_path, document))


def test_missing_unit_is_rejected(tmp_path: Path, valid_document: dict[str, object]) -> None:
    document = copy.deepcopy(valid_document)
    document["mesh"]["global_element_size"] = "10"  # type: ignore[index]
    with pytest.raises(SpecValidationError, match="explicit unit"):
        load_spec(_write(tmp_path, document))


def test_declared_unit_dimension_is_validated(valid_document: dict[str, object]) -> None:
    document = copy.deepcopy(valid_document)
    document["units"]["force"] = "mm"  # type: ignore[index]
    with pytest.raises(Exception, match="expected force"):
        SimulationSpec.model_validate(document)


def test_unsupported_analysis_is_rejected(
    tmp_path: Path, valid_document: dict[str, object]
) -> None:
    document = copy.deepcopy(valid_document)
    document["analysis"]["type"] = "nonlinear_static"  # type: ignore[index]
    with pytest.raises(SpecValidationError):
        load_spec(_write(tmp_path, document))


def test_unresolved_questions_block_execution(
    tmp_path: Path, valid_document: dict[str, object]
) -> None:
    document = copy.deepcopy(valid_document)
    document["open_questions"] = ["What is the exact load scope?"]
    spec, _ = load_spec(_write(tmp_path, document))
    with pytest.raises(SpecValidationError, match="open_questions"):
        spec.assert_execution_ready()


def test_custom_material_blocks_real_execution(valid_document: dict[str, object]) -> None:
    document = copy.deepcopy(valid_document)
    material = document["materials"][0]  # type: ignore[index]
    material.clear()
    material.update(
        {
            "name": "custom",
            "source": "isotropic",
            "youngs_modulus": "200 GPa",
            "poissons_ratio": 0.3,
        }
    )
    document["bodies"][0]["material"] = "custom"  # type: ignore[index]
    spec = SimulationSpec.model_validate(document)
    with pytest.raises(UnsupportedFeatureError, match="material-authoring"):
        spec.assert_execution_ready()


def test_non_local_host_requires_explicit_enable(valid_document: dict[str, object]) -> None:
    document = copy.deepcopy(valid_document)
    document["execution"]["host"] = "mechanical.example.test"  # type: ignore[index]
    with pytest.raises(Exception, match="allow_remote"):
        SimulationSpec.model_validate(document)


def test_non_local_host_requires_authenticated_transport(
    valid_document: dict[str, object],
) -> None:
    document = copy.deepcopy(valid_document)
    execution = document["execution"]  # type: ignore[index]
    execution["host"] = "mechanical.example.test"
    execution["allow_remote"] = True
    execution["transport_mode"] = "insecure"
    with pytest.raises(Exception, match="authenticated transport"):
        SimulationSpec.model_validate(document)


def test_non_local_host_cannot_request_local_start(valid_document: dict[str, object]) -> None:
    document = copy.deepcopy(valid_document)
    execution = document["execution"]  # type: ignore[index]
    execution["host"] = "mechanical.example.test"
    execution["allow_remote"] = True
    execution["transport_mode"] = "mtls"
    execution["certs_dir"] = "/tmp/certs"
    execution["start_instance"] = "yes"
    with pytest.raises(Exception, match="only for localhost"):
        SimulationSpec.model_validate(document)


def test_duplicate_scope_ids_fail(valid_document: dict[str, object]) -> None:
    document = copy.deepcopy(valid_document)
    document["scopes"][1]["id"] = "fixed_face"  # type: ignore[index]
    with pytest.raises(Exception, match="duplicate scope"):
        SimulationSpec.model_validate(document)


def test_force_requires_one_representation(valid_document: dict[str, object]) -> None:
    document = copy.deepcopy(valid_document)
    document["loads"][0]["magnitude"] = "1000 N"  # type: ignore[index]
    document["loads"][0]["direction"] = [0, 0, -1]  # type: ignore[index]
    with pytest.raises(Exception, match="either components"):
        SimulationSpec.model_validate(document)


def test_from_geometry_rejects_ignored_object_name(valid_document: dict[str, object]) -> None:
    document = copy.deepcopy(valid_document)
    document["loads"][0]["object_name"] = "Ignored Force"  # type: ignore[index]
    with pytest.raises(Exception, match="forbids object_name"):
        SimulationSpec.model_validate(document)


def test_reaction_result_rejects_conflicting_scope(valid_document: dict[str, object]) -> None:
    document = copy.deepcopy(valid_document)
    reaction = next(
        result
        for result in document["requested_results"]  # type: ignore[union-attr]
        if result["type"] == "reaction_force"
    )
    reaction["scope"] = "fixed_face"
    with pytest.raises(Exception, match="derives scope from support"):
        SimulationSpec.model_validate(document)


def test_standard_axis_aligned_gravity_is_supported(valid_document: dict[str, object]) -> None:
    document = copy.deepcopy(valid_document)
    document["loads"] = [
        {
            "id": "gravity",
            "type": "gravity",
            "magnitude": "9.80665 m/s^2",
            "direction": [0, 0, -1],
        }
    ]
    spec = SimulationSpec.model_validate(document)
    assert spec.loads[0].type == "gravity"


@pytest.mark.parametrize(
    "load",
    [
        {
            "id": "gravity",
            "type": "gravity",
            "magnitude": "10 m/s^2",
            "direction": [0, 0, -1],
        },
        {
            "id": "gravity",
            "type": "gravity",
            "magnitude": "9.80665 m/s^2",
            "direction": [1, 1, 0],
        },
    ],
)
def test_nonstandard_gravity_is_rejected(
    load: dict[str, object], valid_document: dict[str, object]
) -> None:
    document = copy.deepcopy(valid_document)
    document["loads"] = [load]
    with pytest.raises(Exception, match="EarthGravity"):
        SimulationSpec.model_validate(document)
