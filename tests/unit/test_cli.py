from __future__ import annotations

import copy
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import ansys_skill.cli as cli_module
import yaml
from ansys_skill.errors import ExitCode, MechanicalExecutionError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "cantilever" / "simulation.yaml"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ansys_skill.cli", *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_doctor_json_is_stable() -> None:
    result = _run("doctor", "--json")
    payload = json.loads(result.stdout)
    assert result.returncode == ExitCode.SUCCESS
    assert set(payload) == {"status", "can_start_local", "can_execute", "checks"}
    assert result.stderr == ""


def test_doctor_strict_exit_code(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_module, "doctor_report", lambda: {"can_execute": False})
    code = cli_module.command_doctor(Namespace(json=True, strict=True))
    assert code == ExitCode.ENVIRONMENT_UNAVAILABLE
    assert json.loads(capsys.readouterr().out)["can_execute"] is False


def test_validate_json() -> None:
    result = _run("validate", str(EXAMPLE), "--json")
    payload = json.loads(result.stdout)
    assert result.returncode == ExitCode.SUCCESS
    assert payload["ok"] is True
    assert payload["execution_ready"] is True


def test_compile_and_dry_run_json(tmp_path: Path) -> None:
    compile_dir = tmp_path / "compile"
    compiled = _run("compile", str(EXAMPLE), "--out", str(compile_dir), "--json")
    compiled_payload = json.loads(compiled.stdout)
    assert compiled.returncode == ExitCode.SUCCESS
    assert compiled_payload["status"] == "COMPILED"
    assert (compile_dir / "generated-mechanical.py").is_file()

    run_dir = tmp_path / "dry"
    run = _run("run", str(EXAMPLE), "--out", str(run_dir), "--json")
    payload = json.loads(run.stdout)
    assert run.returncode == ExitCode.SUCCESS
    assert payload["status"] == "DRY_RUN"
    assert (run_dir / "report.md").is_file()
    assert (run_dir / "verification.json").is_file()
    assert json.loads((run_dir / "results-summary.json").read_text())["status"] == "NOT_RUN"
    manifest_path = run_dir / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["commands_and_checks"] == [
        "schema validation",
        "deterministic Mechanical compilation",
        "doctor environment check",
        "dry-run execution plan",
        "engineering verification",
        "visual review status recording",
        "report generation",
    ]

    reported = _run("report", str(run_dir), "--json")
    assert reported.returncode == ExitCode.SUCCESS
    assert json.loads(reported.stdout)["status"] == "REPORTED"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["commands_and_checks"][-1] == "report regeneration"


def test_invalid_spec_exit_code(tmp_path: Path, valid_document: dict[str, object]) -> None:
    document = copy.deepcopy(valid_document)
    document["mesh"]["global_element_size"] = "10"  # type: ignore[index]
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    result = _run("validate", str(path), "--json")
    payload = json.loads(result.stdout)
    assert result.returncode == ExitCode.VALIDATION_FAILED
    assert payload["status"] == "ERROR"
    assert payload["error"]["type"] == "spec_validation_error"


def test_run_rejects_nonempty_output_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "existing"
    run_dir.mkdir()
    (run_dir / "stale.rst").write_bytes(b"stale")
    result = _run("run", str(EXAMPLE), "--out", str(run_dir), "--json")
    payload = json.loads(result.stdout)
    assert result.returncode == ExitCode.VALIDATION_FAILED
    assert payload["error"]["type"] == "path_safety_error"


def test_manifest_failure_preserves_structured_details(tmp_path: Path) -> None:
    run_dir = tmp_path / "compiled"
    compiled = _run("compile", str(EXAMPLE), "--out", str(run_dir), "--json")
    assert compiled.returncode == ExitCode.SUCCESS
    error = MechanicalExecutionError(
        "timed out", details={"remote_workdir": r"C:\Temp\text-to-ansys-1"}
    )
    cli_module._mark_failure(run_dir, "MECHANICAL_FAILED", "mechanical_execution", error)
    manifest = json.loads((run_dir / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["error"]["details"]["remote_workdir"].endswith(
        "text-to-ansys-1"
    )


def test_raw_rst_inspection_without_spec(monkeypatch, capsys, tmp_path: Path) -> None:
    rst = tmp_path / "existing.rst"
    rst.write_bytes(b"fixture")
    monkeypatch.setattr(
        cli_module,
        "inspect_result_file",
        lambda _path: {
            "status": "POSTPROCESSED",
            "inspection_mode": "raw_rst",
            "result_file": str(rst),
            "node_count": 10,
            "element_count": 5,
            "results": {
                "total_deformation": {
                    "maximum": 0.001,
                    "unit": "m",
                    "location": "Nodal",
                    "scoping_id": 1,
                }
            },
            "unavailable_results": {},
        },
    )
    code = cli_module.command_inspect(Namespace(run_directory=str(rst), json=True))
    payload = json.loads(capsys.readouterr().out)
    assert code == ExitCode.SUCCESS
    assert payload["inspection_mode"] == "raw_rst"
    assert (tmp_path / "report.md").is_file()
    assert (tmp_path / "verification.json").is_file()
