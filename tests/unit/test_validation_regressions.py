from __future__ import annotations

import copy
import json
from argparse import Namespace
from pathlib import Path

import pytest
import yaml
from ansys_skill import cli
from ansys_skill.backends import environment
from ansys_skill.compiler.mechanical import compile_simulation
from ansys_skill.schema import SimulationSpec, load_spec
from ansys_skill.validation.preflight import preflight_checks
from ansys_skill.validation.results import post_solve_checks
from ansys_skill.validation.statuses import CheckStatus


@pytest.mark.parametrize("value", ["0 mm", "-1 mm"])
def test_characteristic_length_must_be_positive(valid_document, value):
    document = copy.deepcopy(valid_document)
    document["validation"]["characteristic_length"] = value
    with pytest.raises(ValueError, match="positive"):
        SimulationSpec.model_validate(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("span", "0 mm"),
        ("second_moment_of_area", "-1 mm^4"),
        ("youngs_modulus", "0 Pa"),
        ("load_magnitude", "-1 N"),
    ],
)
def test_cantilever_parameters_must_be_positive(valid_document, field, value):
    document = copy.deepcopy(valid_document)
    document["validation"]["cantilever"][field] = value
    with pytest.raises(ValueError, match="positive"):
        SimulationSpec.model_validate(document)


@pytest.mark.parametrize("result_id", ["missing", "equivalent_stress"])
def test_cantilever_requires_a_displacement_result(valid_document, result_id):
    document = copy.deepcopy(valid_document)
    document["validation"]["cantilever"]["result_id"] = result_id
    with pytest.raises(ValueError, match="displacement result"):
        SimulationSpec.model_validate(document)


def test_cli_schema_error_remains_json(valid_document, tmp_path, capsys):
    document = copy.deepcopy(valid_document)
    document["mesh"]["global_element_size"] = "0 mm"
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert cli.main(["validate", str(path), "--json"]) == 2
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["error"]["type"] == "spec_validation_error"
    assert payload["error"]["details"]["errors"][0]["loc"] == ["mesh", "global_element_size"]
    assert "Traceback" not in output.err


def test_missing_evidence_never_becomes_a_pass(valid_spec_path):
    spec, _ = load_spec(valid_spec_path)
    summary = {"results": {"total_deformation": {"unit": "m"}}}
    checks = {item.name: item.status for item in post_solve_checks(spec, summary)}
    assert checks["requested_results"] is CheckStatus.FAIL
    assert checks["small_deformation"] is CheckStatus.NOT_RUN
    assert checks["mechanical_messages"] is CheckStatus.NOT_RUN


def test_scoped_displacement_cannot_certify_global_small_deformation(valid_document):
    document = copy.deepcopy(valid_document)
    document["requested_results"][0]["scope"] = "fixed_face"
    spec = SimulationSpec.model_validate(document)
    summary = {"results": {"total_deformation": {"maximum": 0.0, "unit": "m"}}}
    check = next(
        item for item in post_solve_checks(spec, summary) if item.name == "small_deformation"
    )
    assert check.status is CheckStatus.NOT_RUN


def test_compiled_spec_keeps_a_portable_input_snapshot(valid_spec_path, tmp_path):
    spec, _ = load_spec(valid_spec_path)
    run_dir = tmp_path / "different output"
    artifacts = compile_simulation(spec, valid_spec_path, run_dir)
    normalized = Path(artifacts["normalized_spec"])
    saved, _ = load_spec(normalized)
    input_check = next(
        item for item in preflight_checks(saved, normalized) if item.name == "input_file"
    )
    assert input_check.status is CheckStatus.PASS
    assert not Path(saved.inputs.geometry_file).is_absolute()
    assert (run_dir / saved.inputs.geometry_file).read_bytes() == (
        valid_spec_path.parent / "cantilever.step"
    ).read_bytes()


def test_inspection_does_not_require_the_source_cad(valid_spec_path, tmp_path, monkeypatch, capsys):
    spec, _ = load_spec(valid_spec_path)
    run_dir = tmp_path / "history"
    compile_simulation(spec, valid_spec_path, run_dir)
    (run_dir / "result.rst").write_bytes(b"offline fixture")
    summary = {
        "status": "POSTPROCESSED",
        "synthetic": False,
        "result_file": "result.rst",
        "node_count": 10,
        "element_count": 5,
        "results": {},
    }
    monkeypatch.setattr(cli, "inspect_result_file", lambda *_: summary)
    cli.command_inspect(Namespace(run_directory=str(run_dir), json=True))
    capsys.readouterr()
    verification = json.loads((run_dir / "verification.json").read_text())
    checks = {item["name"]: item["status"] for item in verification["checks"]}
    assert checks["input_file"] == "NOT_RUN"
    assert checks["mechanical_messages"] == "NOT_RUN"


def test_dry_run_environment_never_probes_a_network_port(valid_spec_path, monkeypatch):
    spec, _ = load_spec(valid_spec_path)
    spec.execution.port = 10000
    monkeypatch.setattr(
        environment, "_port_state", lambda *_: pytest.fail("Network access in dry-run")
    )
    report = environment.doctor_report(spec, probe_port=False)
    assert report["checks"]["port"]["status"] == "NOT_RUN"
