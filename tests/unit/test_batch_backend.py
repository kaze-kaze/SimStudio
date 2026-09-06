from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import ansys_skill.backends.batch as batch
import ansys_skill.backends.environment as environment
import ansys_skill.backends.pymechanical as pymechanical
import ansys_skill.cli as cli
import pytest
import yaml
from ansys_skill.backends import MechanicalBatchBackend
from ansys_skill.compiler.mechanical import compile_simulation
from ansys_skill.errors import (
    EnvironmentUnavailableError,
    ExitCode,
    MechanicalExecutionError,
    PathSafetyError,
    SpecValidationError,
)
from ansys_skill.schema import ExecutionSpec, dump_normalized_yaml, load_spec


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No test in this module may start Mechanical, kill real processes, or use gRPC."""
    executable = tmp_path / "ANSYS Student" / "AnsysWBU.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"offline executable placeholder")
    monkeypatch.setattr(environment.platform, "system", lambda: "Windows")
    monkeypatch.setattr(environment, "_find_mechanical_executable", lambda: str(executable))
    monkeypatch.setattr(environment, "_find_module", lambda name: name == "ansys.dpf.core")
    monkeypatch.setattr(
        environment, "_port_state", Mock(side_effect=AssertionError("Network probe"))
    )
    monkeypatch.setattr(
        pymechanical, "PyMechanicalCompat", Mock(side_effect=AssertionError("gRPC access"))
    )
    commands = SimpleNamespace(
        Popen=Mock(side_effect=AssertionError("Unexpected process launch")),
        run=Mock(side_effect=AssertionError("Unexpected process cleanup")),
        DEVNULL=subprocess.DEVNULL,
        CREATE_NO_WINDOW=0x08000000,
        TimeoutExpired=subprocess.TimeoutExpired,
        SubprocessError=subprocess.SubprocessError,
    )
    monkeypatch.setattr(batch, "subprocess", commands)
    return commands


@pytest.fixture
def batch_spec_path(valid_spec_path):
    spec, _ = load_spec(valid_spec_path)
    spec.execution.backend = "mechanical_batch"
    valid_spec_path.write_text(dump_normalized_yaml(spec), encoding="utf-8")
    return valid_spec_path


@pytest.fixture
def compiled_run(batch_spec_path, tmp_path):
    spec, _ = load_spec(batch_spec_path)
    artifacts = compile_simulation(spec, batch_spec_path, tmp_path / "batch run 测试")
    return SimpleNamespace(
        spec=spec,
        spec_path=batch_spec_path,
        run_dir=Path(artifacts["run_directory"]),
        script_path=Path(artifacts["generated_script"]),
    )


def _execute(job):
    return MechanicalBatchBackend().execute(job.spec, job.spec_path, job.run_dir, job.script_path)


def _runtime_payload(run_dir, *, status="SOLVED", relative=False):
    solver = run_dir / "solver"
    solver.mkdir(exist_ok=True)
    for name in ("file.rst", "solve.out", "extra.log"):
        (solver / name).write_bytes(b"offline solver artifact")
    (run_dir / "text-to-ansys.mechdb").write_bytes(b"offline project")
    (run_dir / "mesh.png").write_bytes(b"offline image")
    (run_dir / "face-selection-report.json").write_text("[]\n", encoding="utf-8")

    def path(name):
        return name if relative else str(run_dir / name)

    return {
        "status": status,
        "mechanical_product_version": "2026 R1",
        "error": None
        if status == "SOLVED"
        else {"type": "RuntimeError", "message": "Model check failed"},
        "face_selections": [],
        "analysis": {},
        "object_types": {},
        "run_directory": str(run_dir),
        "project_file": path("text-to-ansys.mechdb"),
        "solver_messages": [],
        "result_files": [path("solver/file.rst")],
        "solve_logs": [path("solver/solve.out")],
        "visual_review": [{"status": "PASS", "name": "mesh.png"}],
    }


def _process(offline, produce, *, exit_code=0):
    process = Mock(pid=7312, returncode=None)

    def start(command, **kwargs):
        kwargs["stdout"].write(b"batch stdout\n")
        kwargs["stderr"].write(b"batch stderr\n\x80")

        def wait(*, timeout):
            produce(Path(kwargs["cwd"]))
            process.returncode = exit_code
            return exit_code

        process.wait.side_effect = wait
        return process

    offline.Popen.side_effect = start
    return process


def _save_payload(run_dir, payload):
    (run_dir / "mechanical-artifacts.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize("relative", [False, True])
def test_batch_runs_saved_script_and_collects_all_local_files(compiled_run, offline, relative):
    job = compiled_run
    script_before = job.script_path.read_bytes()
    process = _process(
        offline, lambda root: _save_payload(root, _runtime_payload(root, relative=relative))
    )

    outcome = _execute(job)

    command = offline.Popen.call_args.args[0]
    assert command == [
        environment._find_mechanical_executable(),
        "-DSApplet",
        "-AppModeMech",
        "-b",
        "-script",
        str(job.script_path),
        "-x",
    ]
    assert offline.Popen.call_args.kwargs["cwd"] == job.run_dir
    assert offline.Popen.call_args.kwargs["creationflags"] == offline.CREATE_NO_WINDOW
    assert offline.Popen.call_args.kwargs["stdin"] == subprocess.DEVNULL
    assert not offline.Popen.call_args.kwargs.get("shell", False)
    process.wait.assert_called_once_with(timeout=job.spec.execution.timeout_seconds)
    offline.run.assert_not_called()
    assert job.script_path.read_bytes() == script_before
    assert (job.run_dir / "mechanical-batch-stdout.log").read_bytes() == b"batch stdout\n"
    assert (job.run_dir / "mechanical-batch-stderr.log").read_bytes() == b"batch stderr\n\x80"
    payload = json.loads((job.run_dir / "mechanical-artifacts.json").read_text())
    assert payload["result_files"] == ["solver/file.rst"]
    assert payload["solve_logs"] == ["solver/solve.out"]
    assert payload["project_file"] == "text-to-ansys.mechdb"
    assert set(outcome.artifacts) == {path for path in job.run_dir.rglob("*") if path.is_file()}
    assert outcome.status == "SOLVED"
    assert outcome.synthetic is False
    assert outcome.metadata["owned_instance"] is True
    assert outcome.metadata["mechanical_product_version"] == "2026 R1"
    assert outcome.metadata["process_id"] == process.pid


@pytest.mark.parametrize("exit_code", [0, 7])
def test_batch_structured_failure_is_preserved(compiled_run, offline, exit_code):
    _process(
        offline,
        lambda root: _save_payload(root, _runtime_payload(root, status="FAILED")),
        exit_code=exit_code,
    )
    with pytest.raises(MechanicalExecutionError, match="failed solve") as error:
        _execute(compiled_run)
    assert error.value.exit_code == ExitCode.MECHANICAL_FAILED
    assert error.value.details["mechanical"]["error"]["message"] == "Model check failed"
    assert error.value.details["mechanical"]["status"] == "FAILED"
    assert error.value.details["process_exit_code"] == exit_code
    offline.run.assert_not_called()


def test_batch_nonzero_exit_retains_solved_payload(compiled_run, offline):
    _process(offline, lambda root: _save_payload(root, _runtime_payload(root)), exit_code=7)
    with pytest.raises(MechanicalExecutionError, match="exited with code 7") as error:
        _execute(compiled_run)
    assert error.value.details["mechanical"]["status"] == "SOLVED"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "{",
        "[]",
        "{}",
        '{"status": false}',
        '{"status": "SOLVED", "result_files": "file.rst"}',
    ],
)
def test_batch_requires_structured_payload_even_with_zero_exit(compiled_run, offline, payload):
    def produce(root):
        if payload is not None:
            (root / "mechanical-artifacts.json").write_text(payload, encoding="utf-8")

    _process(offline, produce)
    with pytest.raises(MechanicalExecutionError) as error:
        _execute(compiled_run)
    assert error.value.exit_code == ExitCode.MECHANICAL_FAILED
    assert error.value.details["process_exit_code"] == 0
    assert (compiled_run.run_dir / error.value.details["stderr_log"]).is_file()


def test_batch_rejects_solved_payload_with_missing_result(compiled_run, offline):
    def produce(root):
        payload = _runtime_payload(root)
        (root / "solver/file.rst").unlink()
        _save_payload(root, payload)

    _process(offline, produce)
    with pytest.raises(MechanicalExecutionError, match="complete result files"):
        _execute(compiled_run)


@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_batch_timeout_only_terminates_its_owned_process_tree(
    compiled_run, offline, cleanup_failure
):
    job = compiled_run
    process = Mock(pid=7312, returncode=None)
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("Mechanical", 30), 1]
    offline.Popen.side_effect = None
    offline.Popen.return_value = process

    def terminate(command, **kwargs):
        if cleanup_failure:
            raise subprocess.CalledProcessError(1, command, stderr="Access denied")
        process.returncode = 1
        return subprocess.CompletedProcess(command, 0)

    offline.run.side_effect = terminate
    with pytest.raises(MechanicalExecutionError, match="exceeded") as error:
        _execute(job)

    assert offline.Popen.call_count == 1
    assert offline.run.call_args.args[0] == ["taskkill", "/PID", "7312", "/T", "/F"]
    assert offline.run.call_args.kwargs["timeout"] == 10
    assert offline.run.call_count == 1
    process.kill.assert_not_called()
    process.terminate.assert_not_called()
    assert error.value.details["owned_instance"] is True
    assert error.value.details["process_id"] == process.pid
    assert ("cleanup_error" in error.value.details) is cleanup_failure
    assert (job.run_dir / "mechanical-batch-stdout.log").is_file()
    assert (job.run_dir / "mechanical-batch-stderr.log").is_file()


def test_batch_cleanup_does_not_target_an_already_exited_process(offline):
    process = Mock(pid=7312)
    process.poll.return_value = 0
    assert batch._terminate_owned_tree(process) is None
    offline.run.assert_not_called()


@pytest.mark.parametrize(
    "key", ["result_files", "solve_logs", "project_file", "visual_review", "run_directory"]
)
@pytest.mark.parametrize("absolute", [False, True])
def test_batch_rejects_payload_paths_outside_run(compiled_run, offline, key, absolute):
    def produce(root):
        payload = _runtime_payload(root)
        outside = str(root.parent / "outside.rst") if absolute else "../outside.rst"
        if key in {"result_files", "solve_logs"}:
            payload[key] = [outside]
        elif key == "visual_review":
            payload[key] = [{"status": "PASS", "name": outside}]
        else:
            payload[key] = outside
        _save_payload(root, payload)

    _process(offline, produce)
    with pytest.raises(PathSafetyError, match="run directory"):
        _execute(compiled_run)


def test_batch_rejects_result_symlink_outside_run(compiled_run, offline, create_symlink):
    outside = compiled_run.run_dir.parent / "outside.rst"
    outside.write_bytes(b"must not be collected")
    link = compiled_run.run_dir / "linked.rst"
    create_symlink(link, outside)

    def produce(root):
        payload = _runtime_payload(root)
        payload["result_files"] = ["linked.rst"]
        _save_payload(root, payload)

    _process(offline, produce)
    with pytest.raises(PathSafetyError, match="run directory"):
        _execute(compiled_run)
    assert outside.read_bytes() == b"must not be collected"


@pytest.mark.parametrize("problem", ["missing_script", "outside_script", "stale_payload"])
def test_batch_rejects_invalid_saved_inputs_before_spawn(compiled_run, offline, problem):
    job = compiled_run
    if problem == "missing_script":
        job.script_path.unlink()
    elif problem == "outside_script":
        job.script_path = job.run_dir.parent / "outside.py"
        job.script_path.write_text("raise AssertionError('must not execute')", encoding="utf-8")
    else:
        _save_payload(job.run_dir, {"status": "SOLVED"})
    with pytest.raises((MechanicalExecutionError, PathSafetyError)):
        _execute(job)
    offline.Popen.assert_not_called()


@pytest.mark.parametrize(
    "options",
    [
        {"host": "remote.example.test"},
        {
            "host": "remote.example.test",
            "allow_remote": True,
            "transport_mode": "mtls",
            "certs_dir": "certs",
        },
        {"allow_remote": True},
        {"port": 10000},
        {"start_instance": "no"},
        {"transport_mode": "wnua"},
        {"transport_mode": "mtls", "certs_dir": "certs"},
        {"certs_dir": "certs"},
        {"cleanup_owned_instance": False},
    ],
)
def test_batch_cli_rejects_connection_options_before_spawn(
    valid_spec_path, valid_document, tmp_path, offline, capsys, options
):
    valid_document["execution"] = {"backend": "mechanical_batch", **options}
    valid_spec_path.write_text(yaml.safe_dump(valid_document), encoding="utf-8")
    run_dir = tmp_path / "rejected"
    code = cli.main(["run", str(valid_spec_path), "--out", str(run_dir), "--execute", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == ExitCode.VALIDATION_FAILED
    assert payload["error"]["type"] == "spec_validation_error"
    assert "mechanical_batch" in str(payload["error"]["details"])
    assert not run_dir.exists()
    offline.Popen.assert_not_called()


def test_batch_direct_execution_revalidates_existing_instance_request(compiled_run, offline):
    job = compiled_run
    job.spec = job.spec.model_copy(
        update={"execution": job.spec.execution.model_copy(update={"start_instance": "no"})}
    )
    report = environment.doctor_report(job.spec)
    assert report["can_start_local"] is False
    with pytest.raises(SpecValidationError, match="start_instance"):
        _execute(job)
    offline.Popen.assert_not_called()


@pytest.mark.parametrize("system", ["Linux", "Darwin"])
def test_batch_requires_windows(compiled_run, offline, monkeypatch, system):
    monkeypatch.setattr(environment.platform, "system", lambda: system)
    with pytest.raises(EnvironmentUnavailableError) as error:
        _execute(compiled_run)
    assert error.value.exit_code == ExitCode.ENVIRONMENT_UNAVAILABLE
    assert error.value.details["can_execute"] is False
    offline.Popen.assert_not_called()


def test_batch_doctor_does_not_require_grpc(compiled_run):
    report = environment.doctor_report(compiled_run.spec)
    assert set(report) == {"status", "can_start_local", "can_execute", "checks"}
    assert report["can_execute"] is True
    assert report["can_start_local"] is True
    for name in ("pymechanical", "transport", "port"):
        assert report["checks"][name]["status"] == "NOT_RUN"


@pytest.mark.parametrize("missing", ["executable", "dpf"])
def test_batch_unavailable_environment_does_not_spawn(compiled_run, offline, monkeypatch, missing):
    if missing == "executable":
        monkeypatch.setattr(environment, "_find_mechanical_executable", lambda: None)
    else:
        monkeypatch.setattr(environment, "_find_module", lambda name: False)
    with pytest.raises(EnvironmentUnavailableError):
        _execute(compiled_run)
    offline.Popen.assert_not_called()


def test_batch_cli_stays_dry_run_without_execute(batch_spec_path, tmp_path, offline, capsys):
    run_dir = tmp_path / "dry"
    code = cli.main(["run", str(batch_spec_path), "--out", str(run_dir), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == ExitCode.SUCCESS
    assert payload["status"] == "DRY_RUN"
    plan = json.loads((run_dir / "execution-plan.json").read_text())
    assert plan["backend"] == "mechanical_batch"
    assert plan["execute_requested"] is False
    assert ExecutionSpec().backend == "pymechanical_remote"
    offline.Popen.assert_not_called()
    offline.run.assert_not_called()


def test_batch_cli_records_structured_failure_and_logs(batch_spec_path, tmp_path, offline, capsys):
    _process(offline, lambda root: _save_payload(root, _runtime_payload(root, status="FAILED")))
    run_dir = tmp_path / "failed"
    code = cli.main(["run", str(batch_spec_path), "--out", str(run_dir), "--execute", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == ExitCode.MECHANICAL_FAILED
    assert payload["error"]["type"] == "mechanical_execution_error"
    assert payload["error"]["details"]["mechanical"]["status"] == "FAILED"
    manifest = json.loads((run_dir / "run-manifest.json").read_text())
    assert manifest["status"] == "MECHANICAL_FAILED"
    assert manifest["failure_stage"] == "mechanical_execution"
    assert {
        "mechanical-batch-stdout.log",
        "mechanical-batch-stderr.log",
        "mechanical-artifacts.json",
    } <= set(manifest["artifacts"])


def test_batch_cli_records_product_version_and_ownership(
    batch_spec_path, tmp_path, offline, monkeypatch, capsys
):
    _process(offline, lambda root: _save_payload(root, _runtime_payload(root)))
    monkeypatch.setattr(
        cli,
        "_real_postprocess",
        lambda *_: (
            {"status": "POSTPROCESSED", "synthetic": False, "results": {}},
            {"status": "NOT_RUN", "checks": []},
        ),
    )
    run_dir = tmp_path / "versioned"
    code = cli.main(["run", str(batch_spec_path), "--out", str(run_dir), "--execute", "--json"])
    assert code == ExitCode.SUCCESS, capsys.readouterr().out
    manifest = json.loads((run_dir / "run-manifest.json").read_text())
    assert manifest["execution_mode"] == "mechanical_batch"
    assert manifest["mechanical_product_version"] == "2026 R1"
    assert manifest["instance_owned_by_run"] is True
    assert manifest["remote_workdir"] is None


def test_batch_startup_failure_never_uses_grpc(compiled_run, offline):
    offline.Popen.side_effect = OSError("Cannot start executable")
    with pytest.raises(MechanicalExecutionError, match="Cannot start executable") as error:
        _execute(compiled_run)
    assert error.value.details["owned_instance"] is False
    offline.run.assert_not_called()


def test_grpc_failure_never_spawns_batch(valid_spec_path, tmp_path, monkeypatch, offline, capsys):
    monkeypatch.setattr(environment, "_find_module", lambda name: True)
    monkeypatch.setattr(environment, "_port_state", lambda host, port: {"status": "NOT_RUN"})
    compat = Mock()
    compat.launch.side_effect = RuntimeError("gRPC handshake failed")
    monkeypatch.setattr(pymechanical, "PyMechanicalCompat", lambda: compat)
    code = cli.main(
        ["run", str(valid_spec_path), "--out", str(tmp_path / "grpc"), "--execute", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == ExitCode.MECHANICAL_FAILED
    assert "gRPC handshake failed" in payload["error"]["message"]
    offline.Popen.assert_not_called()
