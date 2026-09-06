from __future__ import annotations

import json
import math
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from ansys_skill.cli import _find_result_file
from ansys_skill.manifest import sha256_file

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "cantilever" / "simulation.yaml"
REAL_BACKENDS = ("pymechanical_remote", "mechanical_batch")
EXECUTION_TIMEOUT_SECONDS = 300

pytestmark = [
    pytest.mark.ansys_integration,
    pytest.mark.skipif(
        os.getenv("ANSYS_AVAILABLE") != "1",
        reason="Set ANSYS_AVAILABLE=1 only on a licensed compatible Mechanical host",
    ),
]


def _require_ansys_available() -> None:
    if os.getenv("ANSYS_AVAILABLE") != "1":
        pytest.skip("Real ANSYS execution requires ANSYS_AVAILABLE=1")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_cli(*arguments: str) -> dict[str, Any]:
    _require_ansys_available()
    result = subprocess.run(
        [sys.executable, "-m", "ansys_skill.cli", *arguments],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=EXECUTION_TIMEOUT_SECONDS + 120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _example_document(backend: str) -> dict[str, Any]:
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    geometry = EXAMPLE.parent / document["inputs"]["geometry_file"]
    document["inputs"]["geometry_file"] = str(geometry.resolve(strict=True))
    document["execution"]["backend"] = backend
    document["execution"]["timeout_seconds"] = EXECUTION_TIMEOUT_SECONDS
    return document


def _assert_checks(run_dir: Path, **expected: str) -> None:
    verification = _read_json(run_dir / "verification.json")
    checks = {item["name"]: item["status"] for item in verification["checks"]}
    for name, status in expected.items():
        assert checks[name] == status, verification


def _solve(case_dir: Path, document: dict[str, Any]) -> Path:
    _require_ansys_available()
    assert document["execution"]["backend"] in REAL_BACKENDS, "Only real backends are allowed"
    spec_path = case_dir / "simulation.yaml"
    spec_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    run_dir = case_dir / "run"
    assert not run_dir.exists(), "Each real solve requires a fresh run directory"
    payload = _run_cli(
        "run", str(spec_path), "--out", str(run_dir), "--execute", "--json"
    )
    assert payload["status"] == "SOLVED", payload
    assert payload["synthetic"] is False
    for filename in ("results-summary.json", "verification.json", "report.md"):
        assert (run_dir / filename).is_file()
    summary = _read_json(run_dir / "results-summary.json")
    assert summary["synthetic"] is False
    assert summary["node_count"] > 0
    assert summary["element_count"] > 0
    _assert_checks(run_dir, requested_results="PASS", small_deformation="PASS")
    return run_dir


@pytest.fixture(scope="module")
def real_backend(request: pytest.FixtureRequest) -> str:
    _require_ansys_available()
    if hasattr(request.config, "workerinput") or os.getenv("PYTEST_XDIST_WORKER"):
        pytest.fail("Real ANSYS solves must run serially; disable pytest-xdist with -n 0", pytrace=False)
    backend = os.getenv("ANSYS_TEST_BACKEND", "pymechanical_remote")
    if backend not in REAL_BACKENDS:
        pytest.fail(
            f"ANSYS_TEST_BACKEND must be one of {REAL_BACKENDS}; got {backend!r}", pytrace=False
        )
    # The standalone doctor uses the remote backend; batch is checked by run.
    if backend == "pymechanical_remote":
        _run_cli("doctor", "--strict", "--json")
    return backend


@pytest.fixture(scope="module")
def real_cantilever(real_backend: str, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Reuse one solve for numerical, image, and raw-RST acceptance checks."""
    _require_ansys_available()
    return _solve(tmp_path_factory.mktemp("real-cantilever"), _example_document(real_backend))


def test_real_cantilever(real_cantilever: Path) -> None:
    _assert_checks(
        real_cantilever,
        requested_results="PASS",
        reaction_balance="PASS",
        small_deformation="PASS",
        cantilever_analytical="PASS",
    )
    summary = _read_json(real_cantilever / "results-summary.json")
    assert summary["results"]["tip_z"]["canonical_maximum"] == pytest.approx(-0.000125, rel=0.15)


@pytest.mark.parametrize(
    "filename", ["mesh.png", "total-deformation.png", "equivalent-stress.png"]
)
def test_real_image_export(real_cantilever: Path, filename: str) -> None:
    artifacts = _read_json(real_cantilever / "mechanical-artifacts.json")
    records = [item for item in artifacts["visual_review"] if item["name"] == filename]
    assert len(records) == 1, artifacts
    assert records[0]["status"] == "PASS", records[0]
    data = (real_cantilever / filename).read_bytes()
    assert len(data) > 33, "PNG must contain image data beyond its header"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[8:16] == b"\x00\x00\x00\x0dIHDR"
    width, height = struct.unpack(">II", data[16:24])
    assert width > 0 and height > 0, (width, height)
    _assert_checks(real_cantilever, image_export="PASS", visual_review="NOT_RUN")


def test_real_raw_rst_inspect_and_report(real_cantilever: Path, tmp_path: Path) -> None:
    baseline = _read_json(real_cantilever / "results-summary.json")
    source_rst = _find_result_file(real_cantilever)
    source_hash = sha256_file(source_rst)
    raw_dir = tmp_path / "raw-rst"
    raw_dir.mkdir()
    raw_rst = raw_dir / source_rst.name
    shutil.copy2(source_rst, raw_rst)
    assert sha256_file(raw_rst) == source_hash

    inspected = _run_cli("inspect", str(raw_rst), "--json")
    assert inspected["status"] == "INSPECTED", inspected
    assert inspected["inspection_mode"] == "raw_rst"
    summary = _read_json(raw_dir / "results-summary.json")
    assert summary["synthetic"] is False
    assert summary["inspection_mode"] == "raw_rst"
    assert Path(summary["result_file"]) == raw_rst.resolve()
    assert summary["unavailable_results"] == {}, summary
    for count in ("node_count", "element_count"):
        assert summary[count] == baseline[count]

    result_ids = {
        "total_deformation": "total_deformation",
        "equivalent_stress": "equivalent_stress",
        "reaction_force": "fixed_reaction",
    }
    assert result_ids.keys() <= summary["results"].keys(), summary
    for raw_id, baseline_id in result_ids.items():
        actual = summary["results"][raw_id]
        expected = baseline["results"][baseline_id]
        assert actual["value_count"] > 0, actual
        assert actual["location"] == expected["location"] == "Nodal"
        assert actual["canonical_unit"] == expected["canonical_unit"]
        assert actual["canonical_maximum"] == pytest.approx(
            expected["canonical_maximum"], rel=1e-8, abs=1e-12
        ), actual
    reaction = summary["results"]["reaction_force"]
    expected_reaction = baseline["results"]["fixed_reaction"]
    assert reaction["canonical_sum_vector_unit"] == expected_reaction["canonical_sum_vector_unit"]
    assert reaction["canonical_sum_vector"] == pytest.approx(
        expected_reaction["canonical_sum_vector"], rel=1e-8, abs=1e-6
    )
    _assert_checks(
        raw_dir,
        dpf_result_file="PASS",
        mesh_counts="PASS",
        simulation_specification="NOT_RUN",
        engineering_validation="NOT_RUN",
        visual_review="NOT_RUN",
    )

    (raw_dir / "report.md").unlink()
    reported = _run_cli("report", str(raw_dir), "--json")
    assert reported["status"] == "REPORTED", reported
    for filename in ("report.md", "results.csv", "verification.json", "results-summary.json"):
        assert (raw_dir / filename).stat().st_size > 0
    assert "raw RST inspection" in (raw_dir / "report.md").read_text(encoding="utf-8")
    assert not (raw_dir / "normalized-simulation.yaml").exists()
    assert _read_json(raw_dir / "results-summary.json") == summary
    assert _read_json(real_cantilever / "results-summary.json") == baseline
    assert sha256_file(raw_rst) == sha256_file(source_rst) == source_hash


def test_real_pressure(real_backend: str, tmp_path: Path) -> None:
    document = _example_document(real_backend)
    document["loads"] = [
        {"id": "surface_pressure", "type": "pressure", "scope": "load_face", "magnitude": "1 MPa"}
    ]
    for result in document["requested_results"]:
        if result["id"] == "tip_z":
            result.update(id="tip_x", direction="x")
    document["validation"]["cantilever"] = {"enabled": False}
    run_dir = _solve(tmp_path, document)
    summary = _read_json(run_dir / "results-summary.json")
    reaction = summary["results"]["fixed_reaction"]["canonical_sum_vector"]
    # Positive pressure on the X-max face compresses the 20 mm by 40 mm section.
    expected_force = 1e6 * 0.02 * 0.04
    assert math.dist(reaction, [expected_force, 0.0, 0.0]) <= 0.05 * expected_force, reaction
    tip = summary["results"]["tip_x"]
    assert tip["canonical_unit"] == "meter"
    assert tip["canonical_maximum"] == pytest.approx(-1e-6, rel=0.05)
    _assert_checks(run_dir, reaction_balance="NOT_RUN", cantilever_analytical="NOT_RUN")


def test_real_gravity(real_backend: str, tmp_path: Path) -> None:
    document = _example_document(real_backend)
    document["loads"] = [
        {
            "id": "gravity",
            "type": "gravity",
            "magnitude": "9.80665 m/s^2",
            "direction": [0.0, 0.0, -1.0],
        }
    ]
    document["validation"]["cantilever"] = {"enabled": False}
    run_dir = _solve(tmp_path, document)
    summary = _read_json(run_dir / "results-summary.json")
    reaction = summary["results"]["fixed_reaction"]["canonical_sum_vector"]
    # Structural Steel density was verified as 7850 kg/m^3 in Mechanical.
    expected_weight = 7850.0 * (0.2 * 0.02 * 0.04) * 9.80665
    assert math.dist(reaction, [0.0, 0.0, expected_weight]) <= 0.05 * expected_weight, reaction
    tip = summary["results"]["tip_z"]
    assert tip["canonical_unit"] == "meter"
    assert math.isfinite(tip["canonical_maximum"]) and tip["canonical_maximum"] < 0
    _assert_checks(run_dir, reaction_balance="NOT_RUN", cantilever_analytical="NOT_RUN")


def _template_script(directory: Path, source: Path, destination: Path | None = None) -> dict[str, Any]:
    from ansys_skill.backends.environment import _find_mechanical_executable

    _require_ansys_available()
    if sys.platform != "win32":
        pytest.skip("Template preparation/readback fixture requires local Windows Mechanical")
    executable = _find_mechanical_executable()
    assert executable, "Template preparation requires a local Mechanical installation"
    evidence = directory / ("seed.json" if destination else "readback.json")
    environment = {**os.environ, "TTA_TEMPLATE_SOURCE": str(source),
                   "TTA_TEMPLATE_EVIDENCE": str(evidence),
                   "TTA_TEMPLATE_SEED": "1" if destination else "0"}
    if destination:
        environment["TTA_TEMPLATE_DESTINATION"] = str(destination)
    script = Path(__file__).parent / "fixtures" / "mechanical_template.py"
    result = subprocess.run(
        [executable, "-DSApplet", "-AppModeMech", "-b", "-script", str(script), "-x"],
        cwd=directory, env=environment, capture_output=True, check=False, timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    (directory / (evidence.stem + "-stdout.log")).write_bytes(result.stdout)
    (directory / (evidence.stem + "-stderr.log")).write_bytes(result.stderr)
    assert result.returncode == 0 and evidence.is_file(), result.stdout + result.stderr
    return _read_json(evidence)


@pytest.mark.parametrize("suffix", [".mechdat", ".mechdb"])
def test_real_template_synchronization(
    real_cantilever: Path, real_backend: str, tmp_path: Path, suffix: str
) -> None:
    baseline_project = real_cantilever / "text-to-ansys.mechdb"
    baseline_hash = sha256_file(baseline_project)
    seed = tmp_path / ("rotated-template" + suffix)
    before = _template_script(tmp_path, baseline_project, seed)
    assert before["extra_coordinate_state"] != "UnderDefined"
    assert before["force_coordinate_system"] != 0
    assert before["force_components_N"] == [100.0, 0.0, 0.0]
    assert before["direction_axis"] == "XAxis"
    assert before["direction_scope"] == "TTA_SCOPE_FIXED_FACE"
    assert before["reaction_support"] == "Acceptance unused support"
    seed_hash = sha256_file(seed)

    document = _example_document(real_backend)
    document["mode"] = "template"
    document["inputs"] = {"project_file": str(seed)}
    document["analysis"]["object_name"] = "text-to-ansys static structural"
    document["scopes"] = [
        {"id": "fixed_face", "kind": "named_selection", "name": "TTA_SCOPE_FIXED_FACE"},
        {"id": "load_face", "kind": "named_selection", "name": "TTA_SCOPE_LOAD_FACE"},
    ]
    for item in document["supports"] + document["loads"] + document["requested_results"]:
        if item["type"] not in {"solver_messages", "node_count", "element_count"}:
            item["object_name"] = item["id"]
    run_dir = _solve(tmp_path, document)
    _assert_checks(run_dir, reaction_balance="PASS", cantilever_analytical="PASS")
    after = _template_script(tmp_path, run_dir / "text-to-ansys.mechdb")
    assert after["force_coordinate_system"] == 0
    assert after["force_components_N"] == [0.0, 0.0, -1000.0]
    assert after["direction_coordinate_system"] == 0
    assert after["direction_axis"] == "ZAxis"
    assert after["direction_scope"] == "TTA_SCOPE_LOAD_FACE"
    assert after["direction_scoping_method"] == "Component"
    assert after["reaction_support"] == "fixed_support"
    assert after["reaction_coordinate_system"] == 0
    assert after["reaction_location_method"] == "BoundaryCondition"
    assert sha256_file(seed) == sha256_file(run_dir / "inputs" / seed.name) == seed_hash
    assert sha256_file(baseline_project) == baseline_hash
