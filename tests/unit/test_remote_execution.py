from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from ansys_skill.backends import pymechanical
from ansys_skill.compiler.mechanical import compile_simulation
from ansys_skill.errors import MechanicalExecutionError
from ansys_skill.schema import SimulationSpec, load_spec


def test_remote_workdir_is_a_return_value(tmp_path):
    class Server:
        def run_python_script_from_file(self, path):
            module = ast.parse(Path(path).read_text())
            assert isinstance(module.body[-1], ast.Expr)
            assert isinstance(module.body[-1].value, ast.BinOp)
            return pymechanical.REMOTE_WORKDIR_SENTINEL + r"C:\Temp\text-to-ansys-job"

    directory, _ = pymechanical.PyMechanicalRemoteBackend._create_remote_workdir(Server(), tmp_path)
    assert directory == r"C:\Temp\text-to-ansys-job"


@pytest.mark.parametrize("directory", ["/", r"C:\\", "relative-path"])
def test_remote_cleanup_never_accepts_a_broad_directory(tmp_path, directory):
    class Server:
        def run_python_script_from_file(self, _path):
            return pymechanical.REMOTE_WORKDIR_SENTINEL + directory

    with pytest.raises(MechanicalExecutionError, match="unsafe"):
        pymechanical.PyMechanicalRemoteBackend._create_remote_workdir(Server(), tmp_path)


@pytest.mark.parametrize("fail_download", [False, True])
def test_remote_execution_uses_snapshots_and_preserves_failed_downloads(
    valid_spec_path, tmp_path, monkeypatch, fail_download
):
    spec, _ = load_spec(valid_spec_path)
    document = spec.model_dump(mode="json")
    document["execution"].update(
        host="test.invalid",
        allow_remote=True,
        transport_mode="mtls",
        certs_dir=str(tmp_path),
        port=10000,
    )
    spec = SimulationSpec.model_validate(document)
    artifacts = compile_simulation(spec, valid_spec_path, tmp_path / "run")
    run_dir = Path(artifacts["run_directory"])
    server_root = r"C:\Users\测试 User\Temp\text-to-ansys-job"
    events = []

    class Server:
        version = "261"

        def run_python_script_from_file(self, path, *_args):
            name = Path(path).name
            if name == "mechanical-prepare-workdir.py":
                return pymechanical.REMOTE_WORKDIR_SENTINEL + server_root
            if name == "mechanical-bootstrap.py":
                assert 'os.chdir(u"' in Path(path).read_text()
                return ""
            if name == "mechanical-cleanup-workdir.py":
                events.append("cleanup")
                return ""
            return "TEXT_TO_ANSYS_RESULT:" + json.dumps(
                {
                    "status": "SOLVED",
                    "run_directory": server_root,
                    "result_files": [server_root + r"\solver\file.rst"],
                    "solve_logs": [],
                    "visual_review": [],
                }
            )

        def upload(self, path, **kwargs):
            assert Path(path).parent == run_dir / "inputs"
            assert kwargs["progress_bar"] is False
            events.append("upload")

        def download(self, paths, target_dir, **kwargs):
            assert isinstance(paths, list) and paths[0].startswith(server_root)
            if fail_download:
                raise OSError("download interrupted")
            # The official client may keep Windows backslashes in a POSIX filename.
            target = Path(target_dir) / Path(paths[0]).name
            target.write_bytes(b"offline RST stand-in")
            events.append("download")
            return [str(target)]

        def exit(self, **_kwargs):
            pytest.fail("A pre-existing server must not be closed")

    class Compat:
        def connect(self, _spec):
            return Server()

    monkeypatch.setattr(pymechanical, "doctor_report", lambda *_: {"can_execute": True})
    monkeypatch.setattr(pymechanical, "PyMechanicalCompat", Compat)
    backend = pymechanical.PyMechanicalRemoteBackend()
    if fail_download:
        with pytest.raises(MechanicalExecutionError, match="download failed") as caught:
            backend.execute(spec, valid_spec_path, run_dir, Path(artifacts["generated_script"]))
        assert caught.value.details["remote_workdir"] == server_root
        assert "cleanup" not in events
    else:
        outcome = backend.execute(
            spec, valid_spec_path, run_dir, Path(artifacts["generated_script"])
        )
        assert outcome.status == "SOLVED"
        assert (run_dir / "solver/file.rst").read_bytes() == b"offline RST stand-in"
        payload = json.loads((run_dir / "mechanical-artifacts.json").read_text())
        assert payload["result_files"] == ["solver/file.rst"]
        assert events == ["upload", "download", "cleanup"]


def test_blocked_rpc_does_not_hold_the_cli_process_open():
    code = """
from threading import Event
from ansys_skill.backends.timing import call_with_timeout
try:
    call_with_timeout(Event().wait, 0.01)
except TimeoutError:
    print('timed out')
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=5, check=False
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "timed out"
