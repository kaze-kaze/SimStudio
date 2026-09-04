"""PyMechanical gRPC backend with centralized version compatibility handling."""

from __future__ import annotations

import inspect
import json
import ntpath
import posixpath
import shutil
import threading
from collections.abc import Callable
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import suppress
from pathlib import Path
from typing import Any

from ansys_skill.backends.base import BackendOutcome, MechanicalBackend
from ansys_skill.backends.environment import LOCAL_HOSTS, _find_mechanical_executable, doctor_report
from ansys_skill.backends.timing import call_with_timeout
from ansys_skill.errors import EnvironmentUnavailableError, MechanicalExecutionError
from ansys_skill.paths import safe_join
from ansys_skill.schema import SimulationSpec

_MECHANICAL_LOCK = threading.Lock()
REMOTE_WORKDIR_SENTINEL = "TEXT_TO_ANSYS_WORKDIR:"


def _remote_basename(path: str) -> str:
    if "\\" in path or ntpath.splitdrive(path)[0]:
        return ntpath.basename(path)
    return posixpath.basename(path)




class PyMechanicalCompat:
    """Only location for PyMechanical signature/version adaptation."""

    def __init__(self) -> None:
        try:
            from ansys.mechanical.core import connect_to_mechanical, launch_mechanical
        except ImportError as exc:
            raise EnvironmentUnavailableError(
                "ansys-mechanical-core is not installed; install the 'ansys' extra"
            ) from exc
        self.connect_to_mechanical = connect_to_mechanical
        self.launch_mechanical = launch_mechanical

    @staticmethod
    def _supported_call(function: Callable[..., Any], kwargs: dict[str, object]) -> Any:
        parameters = inspect.signature(function).parameters
        missing = [key for key, value in kwargs.items() if value is not None and key not in parameters]
        if missing:
            raise EnvironmentUnavailableError(
                f"Installed PyMechanical does not support required arguments: {', '.join(missing)}"
            )
        filtered = {
            key: value for key, value in kwargs.items() if key in parameters and value is not None
        }
        return function(**filtered)

    def launch(self, spec: SimulationSpec) -> Any:
        return self._supported_call(
            self.launch_mechanical,
            {
                "batch": True,
                "exec_file": _find_mechanical_executable(),
                "start_instance": True,
                "port": spec.execution.port,
                "host": spec.execution.host,
                "start_timeout": min(spec.execution.timeout_seconds, 600),
                "cleanup_on_exit": False,
                "transport_mode": spec.execution.transport_mode,
                "certs_dir": spec.execution.certs_dir,
            },
        )

    def connect(self, spec: SimulationSpec) -> Any:
        return self._supported_call(
            self.connect_to_mechanical,
            {
                "ip": spec.execution.host,
                "port": spec.execution.port,
                "connect_timeout": min(spec.execution.timeout_seconds, 600),
                "cleanup_on_exit": False,
                "transport_mode": spec.execution.transport_mode,
                "certs_dir": spec.execution.certs_dir,
            },
        )


class PyMechanicalRemoteBackend(MechanicalBackend):
    def execute(
        self, spec: SimulationSpec, spec_path: Path, run_dir: Path, script_path: Path
    ) -> BackendOutcome:
        report = doctor_report(spec)
        if not report["can_execute"]:
            raise EnvironmentUnavailableError(
                "A compatible Mechanical product, PyMechanical, PyDPF, connection, and license path are required",
                details=report,
            )
        spec.assert_execution_ready()
        compat = PyMechanicalCompat()
        mechanical = None
        owned = False
        remote = False
        remote_workdir: str | None = None
        remote_job_active = False
        cleanup_error: str | None = None
        downloaded: list[Path] = []
        outcome: BackendOutcome | None = None
        try:
            with _MECHANICAL_LOCK:
                try:
                    start = spec.execution.start_instance
                    should_launch = start == "yes" or (
                        start == "auto"
                        and spec.execution.host in LOCAL_HOSTS
                        and spec.execution.port is None
                    )
                    try:
                        mechanical = compat.launch(spec) if should_launch else compat.connect(spec)
                        owned = should_launch
                    except Exception as exc:
                        raise MechanicalExecutionError(
                            f"Mechanical startup/connection failed: {exc}"
                        ) from exc
                    try:
                        product_version = str(mechanical.version)
                    except Exception as exc:
                        raise MechanicalExecutionError(
                            f"Connected Mechanical version could not be determined: {exc}"
                        ) from exc

                    plan = json.loads((run_dir / "mechanical-plan.json").read_text(encoding="utf-8"))
                    input_path = safe_join(run_dir, Path("inputs") / plan["input"]["basename"])
                    if not input_path.is_file():
                        raise MechanicalExecutionError("The compiled input snapshot is missing")
                    remote = spec.execution.host not in LOCAL_HOSTS
                    workdir = str(run_dir)
                    if remote:
                        remote_workdir, prepare_path = self._create_remote_workdir(
                            mechanical, run_dir
                        )
                        downloaded.append(prepare_path)
                        try:
                            mechanical.upload(
                                str(input_path),
                                file_location_destination=remote_workdir, progress_bar=False,
                            )
                        except Exception as exc:
                            raise MechanicalExecutionError(f"Input upload failed: {exc}") from exc
                        workdir = remote_workdir

                    bootstrap_path = run_dir / "mechanical-bootstrap.py"
                    bootstrap_path.write_text(
                        f"import os\nos.chdir(u{json.dumps(workdir)})\n",
                        encoding="utf-8",
                    )
                    mechanical.run_python_script_from_file(str(bootstrap_path))

                    remote_job_active = remote
                    try:
                        response = call_with_timeout(
                            lambda: mechanical.run_python_script_from_file(str(script_path), True),
                            spec.execution.timeout_seconds,
                        )
                        remote_job_active = False
                    except FutureTimeoutError as exc:
                        if owned:
                            with suppress(Exception):
                                call_with_timeout(lambda: mechanical.exit(force=True), 5)
                        raise MechanicalExecutionError(
                            f"Mechanical execution exceeded {spec.execution.timeout_seconds} seconds",
                            details={
                                "remote_workdir": remote_workdir,
                                "remote_cleanup": "skipped because the timed-out job may still be active"
                                if remote_workdir
                                else "not applicable",
                            },
                        ) from exc
                    except Exception as exc:
                        remote_job_active = False
                        raise MechanicalExecutionError(
                            f"Mechanical script or solve failed: {exc}"
                        ) from exc

                    marker = "TEXT_TO_ANSYS_RESULT:"
                    if not str(response).startswith(marker):
                        raise MechanicalExecutionError("Mechanical did not return the structured result protocol")
                    payload = json.loads(str(response)[len(marker):])
                    artifact_path = run_dir / "mechanical-artifacts.json"
                    artifact_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                    self._download_known_artifacts(mechanical, run_dir, remote, downloaded)
                    if payload.get("status") != "SOLVED":
                        raise MechanicalExecutionError(
                            "Mechanical reported a failed solve", details={"mechanical": payload}
                        )
                    outcome = BackendOutcome(
                        status="SOLVED",
                        synthetic=False,
                        artifacts=[artifact_path, bootstrap_path],
                        metadata={
                            "mechanical_response": str(response),
                            "owned_instance": owned,
                            "mechanical_product_version": product_version,
                            "remote_workdir": remote_workdir,
                        },
                    )
                finally:
                    if mechanical is not None and remote_workdir and not remote_job_active and outcome is not None:
                        try:
                            cleanup_path = self._cleanup_remote_workdir(
                                mechanical, run_dir, remote_workdir
                            )
                            downloaded.append(cleanup_path)
                        except Exception as exc:
                            cleanup_error = str(exc)
        finally:
            if mechanical is not None and owned and spec.execution.cleanup_owned_instance:
                with suppress(Exception):
                    call_with_timeout(lambda: mechanical.exit(), 5)
        if outcome is None:
            raise MechanicalExecutionError("Mechanical execution ended without an outcome")
        outcome.artifacts = sorted(set([*outcome.artifacts, *downloaded]))
        if cleanup_error:
            outcome.metadata["remote_cleanup_warning"] = cleanup_error
        return outcome

    @staticmethod
    def _create_remote_workdir(mechanical: Any, run_dir: Path) -> tuple[str, Path]:
        prepare_path = run_dir / "mechanical-prepare-workdir.py"
        prepare_path.write_text(
            "import tempfile\n"
            f"path = tempfile.mkdtemp(prefix={json.dumps('text-to-ansys-')})\n"
            f"{json.dumps(REMOTE_WORKDIR_SENTINEL)} + path\n",
            encoding="utf-8",
        )
        response = str(mechanical.run_python_script_from_file(str(prepare_path)))
        if REMOTE_WORKDIR_SENTINEL not in response:
            raise MechanicalExecutionError(
                "Mechanical did not return the isolated remote work directory sentinel"
            )
        remote_workdir = response.split(REMOTE_WORKDIR_SENTINEL, 1)[1].splitlines()[0].strip()
        parser = ntpath if ntpath.splitdrive(remote_workdir)[0] or "\\" in remote_workdir else posixpath
        if not parser.isabs(remote_workdir) or not parser.basename(remote_workdir).startswith("text-to-ansys-"):
            raise MechanicalExecutionError("Mechanical returned an unsafe remote work directory")
        return remote_workdir, prepare_path

    @staticmethod
    def _cleanup_remote_workdir(mechanical: Any, run_dir: Path, remote_workdir: str) -> Path:
        cleanup_path = run_dir / "mechanical-cleanup-workdir.py"
        cleanup_path.write_text(
            "import os\nimport shutil\nimport tempfile\n"
            f"target = u{json.dumps(remote_workdir)}\n"
            "target = os.path.realpath(target)\n"
            "if os.path.dirname(target) != os.path.realpath(tempfile.gettempdir()) or not os.path.basename(target).startswith('text-to-ansys-'):\n"
            "    raise RuntimeError('Refusing unsafe remote cleanup target')\n"
            "os.chdir(tempfile.gettempdir())\n"
            "if os.path.isdir(target):\n"
            "    shutil.rmtree(target)\n",
            encoding="utf-8",
        )
        mechanical.run_python_script_from_file(str(cleanup_path))
        return cleanup_path

    @staticmethod
    def _download_known_artifacts(
        mechanical: Any, run_dir: Path, remote: bool, downloaded: list[Path]
    ) -> None:
        manifest = run_dir / "mechanical-artifacts.json"
        if not manifest.is_file():
            raise MechanicalExecutionError("Structured Mechanical artifacts are missing")
        downloaded.append(manifest)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if not remote:
            for key in ("result_files", "solve_logs"):
                payload[key] = [Path(path).resolve().relative_to(run_dir.resolve()).as_posix()
                                for path in payload.get(key, [])]
            downloaded.extend(path for path in run_dir.rglob("*") if path.is_file())
        else:
            root = payload["run_directory"]
            join = ntpath.join if "\\" in root or ntpath.splitdrive(root)[0] else posixpath.join

            def download(source: str, relative: str) -> str:
                target = safe_join(run_dir, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    paths = mechanical.download([source], target_dir=str(target.parent), progress_bar=False)
                    if len(paths) != 1 or not Path(paths[0]).is_file():
                        raise OSError("The server returned no complete file")
                    received = Path(paths[0]).resolve()
                    received.relative_to(run_dir.resolve())
                    if received != target:
                        shutil.move(str(received), str(target))
                except Exception as exc:
                    raise MechanicalExecutionError(
                        f"Required Mechanical artifact download failed: {source}: {exc}",
                        details={"remote_workdir": root, "remote_path": source,
                                 "remote_cleanup": "preserved for recovery"},
                    ) from exc
                downloaded.append(target)
                return target.relative_to(run_dir).as_posix()

            for key in ("result_files", "solve_logs"):
                payload[key] = [download(path, "solver/" + _remote_basename(path))
                                for path in payload.get(key, [])]
            face_path = run_dir / "face-selection-report.json"
            face_path.write_text(json.dumps(payload.get("face_selections", []), indent=2) + "\n", encoding="utf-8")
            downloaded.append(face_path)
            if payload.get("project_file"):
                payload["project_file"] = download(payload["project_file"], "text-to-ansys.mechdb")
            for item in payload.get("visual_review", []):
                if item.get("status") == "PASS":
                    try:
                        download(join(root, item["name"]), item["name"])
                    except MechanicalExecutionError as exc:
                        item.update(status="NOT_RUN", reason=str(exc))
        manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
