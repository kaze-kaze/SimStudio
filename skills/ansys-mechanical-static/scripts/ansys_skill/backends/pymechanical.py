"""PyMechanical gRPC backend with centralized version compatibility handling."""

from __future__ import annotations

import importlib.util
import inspect
import json
import ntpath
import os
import platform
import posixpath
import shutil
import socket
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import suppress
from pathlib import Path
from typing import Any

from ansys_skill.backends.base import BackendOutcome, MechanicalBackend
from ansys_skill.errors import EnvironmentUnavailableError, MechanicalExecutionError
from ansys_skill.manifest import package_version
from ansys_skill.paths import resolve_input_path
from ansys_skill.schema import Mode, SimulationSpec
from ansys_skill.validation.statuses import CheckStatus

_MECHANICAL_LOCK = threading.Lock()
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
REMOTE_WORKDIR_SENTINEL = "TEXT_TO_ANSYS_WORKDIR:"


def _remote_basename(path: str) -> str:
    if "\\" in path or ntpath.splitdrive(path)[0]:
        return ntpath.basename(path)
    return posixpath.basename(path)


def _find_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _find_mechanical_executable() -> str | None:
    commands = ["AnsysWBU.exe", "runwb2", "ansys-mechanical", "mechanical"]
    for command in commands:
        path = shutil.which(command)
        if path:
            return path
    for key, root in sorted(os.environ.items(), reverse=True):
        if not key.startswith("AWP_ROOT"):
            continue
        base = Path(root)
        candidates = [
            base / "aisol" / "bin" / "winx64" / "AnsysWBU.exe",
            base / "aisol" / "bin" / "linx64" / "AnsysWBU",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


def _port_state(host: str, port: int | None) -> dict[str, object]:
    if port is None:
        return {"status": CheckStatus.NOT_RUN.value, "message": "No port configured"}
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return {"status": CheckStatus.PASS.value, "message": "TCP port is reachable"}
    except OSError as exc:
        return {
            "status": CheckStatus.FAIL.value,
            "message": f"TCP port is unreachable: {exc}",
        }


def doctor_report(spec: SimulationSpec | None = None) -> dict[str, object]:
    execution = spec.execution if spec else None
    host = execution.host if execution else "127.0.0.1"
    port = execution.port if execution else None
    system = platform.system()
    mechanical_path = _find_mechanical_executable()
    pymechanical = _find_module("ansys.mechanical.core")
    dpf = _find_module("ansys.dpf.core")
    supported_os = system in {"Windows", "Linux"}
    local = host in LOCAL_HOSTS
    remote_allowed = bool(execution and execution.allow_remote)
    transport = execution.transport_mode if execution else "insecure"
    certs_path = (
        Path(execution.certs_dir).expanduser()
        if execution and execution.certs_dir
        else None
    )
    certs_ok = transport != "mtls" or bool(certs_path and certs_path.is_dir())
    transport_os_ok = transport != "wnua" or system == "Windows"
    remote_transport_ok = local or transport in {"wnua", "mtls"}
    port_check = _port_state(host, port)
    start_mode = execution.start_instance if execution else "auto"
    should_launch = start_mode == "yes" or (start_mode == "auto" and local and port is None)
    can_connect = (
        pymechanical
        and (local or remote_allowed)
        and certs_ok
        and transport_os_ok
        and remote_transport_ok
    )
    can_start = (
        can_connect
        and should_launch
        and local
        and supported_os
        and mechanical_path is not None
    )
    can_use_existing = (
        can_connect
        and not should_launch
        and port is not None
        and port_check["status"] == CheckStatus.PASS.value
    )
    can_execute = can_connect and (can_start or can_use_existing) and dpf
    checks = {
        "operating_system": {
            "status": CheckStatus.PASS.value if supported_os else CheckStatus.WARN.value,
            "value": system,
            "message": "Mechanical product execution is supported on Windows/Linux"
            if supported_os
            else "PyMechanical client can install here, but Mechanical product execution is not supported on macOS",
        },
        "python": {
            "status": CheckStatus.PASS.value,
            "value": platform.python_version(),
        },
        "pymechanical": {
            "status": CheckStatus.PASS.value if pymechanical else CheckStatus.FAIL.value,
            "version": package_version("ansys-mechanical-core"),
        },
        "pydpf": {
            "status": CheckStatus.PASS.value if dpf else CheckStatus.FAIL.value,
            "version": package_version("ansys-dpf-core"),
        },
        "mechanical_executable": {
            "status": (
                CheckStatus.PASS.value
                if mechanical_path
                else CheckStatus.FAIL.value
                if should_launch
                else CheckStatus.NOT_RUN.value
            ),
            "path": mechanical_path,
            "message": (
                "A local executable is required for the selected start mode"
                if should_launch
                else "Connecting to an existing service does not require a local executable"
            ),
        },
        "connection_policy": {
            "status": CheckStatus.PASS.value if local or remote_allowed else CheckStatus.FAIL.value,
            "host": host,
            "allow_remote": remote_allowed,
        },
        "transport": {
            "status": (
                CheckStatus.PASS.value
                if certs_ok and transport_os_ok and remote_transport_ok
                else CheckStatus.FAIL.value
            ),
            "mode": transport,
            "certs_dir": execution.certs_dir if execution else None,
            "message": (
                "Transport configuration is compatible with the host and client OS"
                if certs_ok and transport_os_ok and remote_transport_ok
                else "Transport requires a valid mTLS certificate directory, Windows for WNUA, "
                "and authenticated transport for non-local hosts"
            ),
        },
        "port": port_check,
        "license": {
            "status": CheckStatus.NOT_RUN.value,
            "message": "A license is consumed and verified only during an explicitly requested real execution",
        },
    }
    return {
        "status": CheckStatus.PASS.value if can_execute else CheckStatus.NOT_RUN.value,
        "can_start_local": can_start,
        "can_execute": can_execute,
        "checks": checks,
    }


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
        filtered = {
            key: value for key, value in kwargs.items() if key in parameters and value is not None
        }
        return function(**filtered)

    def launch(self, spec: SimulationSpec) -> Any:
        return self._supported_call(
            self.launch_mechanical,
            {
                "batch": True,
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

                    input_value = (
                        spec.inputs.project_file
                        if spec.mode is Mode.TEMPLATE
                        else spec.inputs.geometry_file
                    )
                    input_path = resolve_input_path(spec_path, input_value)
                    assert input_path is not None
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
                                file_location_destination=remote_workdir,
                            )
                        except Exception as exc:
                            raise MechanicalExecutionError(f"Input upload failed: {exc}") from exc
                        workdir = remote_workdir

                    bootstrap_path = run_dir / "mechanical-bootstrap.py"
                    bootstrap_path.write_text(
                        f"import os\nos.chdir({json.dumps(workdir)})\n",
                        encoding="utf-8",
                    )
                    mechanical.run_python_script_from_file(str(bootstrap_path))

                    executor = ThreadPoolExecutor(max_workers=1)
                    future = executor.submit(
                        mechanical.run_python_script_from_file,
                        str(script_path),
                        True,
                    )
                    remote_job_active = remote
                    try:
                        response = future.result(timeout=spec.execution.timeout_seconds)
                        remote_job_active = False
                    except FutureTimeoutError as exc:
                        future.cancel()
                        if owned:
                            mechanical.exit(force=True)
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
                        self._download_known_artifacts(mechanical, run_dir, remote, downloaded)
                        raise MechanicalExecutionError(
                            f"Mechanical script or solve failed: {exc}"
                        ) from exc
                    finally:
                        executor.shutdown(wait=False, cancel_futures=True)

                    self._download_known_artifacts(mechanical, run_dir, remote, downloaded)
                    artifact_path = run_dir / "mechanical-artifacts.json"
                    if not artifact_path.is_file():
                        raise MechanicalExecutionError(
                            "Mechanical did not produce mechanical-artifacts.json"
                        )
                    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                    if payload.get("status") != "SOLVED":
                        raise MechanicalExecutionError(
                            "Mechanical reported a failed solve", details={"mechanical": payload}
                        )
                    if "TEXT_TO_ANSYS_RESULT:" not in str(response):
                        payload["sentinel_warning"] = (
                            "Result sentinel was not present in the API response"
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
                    if mechanical is not None and remote_workdir and not remote_job_active:
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
                    mechanical.exit()
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
            f"print({json.dumps(REMOTE_WORKDIR_SENTINEL)} + path)\n",
            encoding="utf-8",
        )
        response = str(mechanical.run_python_script_from_file(str(prepare_path)))
        if REMOTE_WORKDIR_SENTINEL not in response:
            raise MechanicalExecutionError(
                "Mechanical did not return the isolated remote work directory sentinel"
            )
        remote_workdir = response.split(REMOTE_WORKDIR_SENTINEL, 1)[1].splitlines()[0].strip()
        if not remote_workdir:
            raise MechanicalExecutionError("Mechanical returned an empty remote work directory")
        return remote_workdir, prepare_path

    @staticmethod
    def _cleanup_remote_workdir(mechanical: Any, run_dir: Path, remote_workdir: str) -> Path:
        cleanup_path = run_dir / "mechanical-cleanup-workdir.py"
        cleanup_path.write_text(
            "import os\nimport shutil\nimport tempfile\n"
            f"target = {json.dumps(remote_workdir)}\n"
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
        if not remote:
            downloaded.extend(path for path in run_dir.iterdir() if path.is_file())
            return
        try:
            mechanical.download("mechanical-artifacts.json", target_dir=str(run_dir))
        except Exception:
            return
        manifest = run_dir / "mechanical-artifacts.json"
        if not manifest.is_file():
            return
        downloaded.append(manifest)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        remote_files = list(payload.get("result_files", [])) + list(payload.get("solve_logs", []))
        remote_files.extend(
            [
                "face-selection-report.json",
                "text-to-ansys.mechdb",
                "mesh.png",
                "total-deformation.png",
                "equivalent-stress.png",
            ]
        )
        for remote_path in remote_files:
            try:
                mechanical.download(remote_path, target_dir=str(run_dir))
                downloaded.append(run_dir / _remote_basename(str(remote_path)))
            except Exception:
                continue
