"""Read-only execution environment and product discovery."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import socket
from pathlib import Path

from ansys_skill.manifest import package_version
from ansys_skill.schema import SimulationSpec
from ansys_skill.validation.statuses import CheckStatus

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _find_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _find_mechanical_executable() -> str | None:
    if platform.system() not in {"Windows", "Linux"}:
        return None
    try:
        from ansys.mechanical.core import find_mechanical
    except ImportError:
        pass
    else:
        path, _version = find_mechanical()
        if path and Path(path).is_file():
            return path
    commands = ["AnsysWBU.exe", "AnsysWBU"]
    for command in commands:
        path = shutil.which(command)
        if path:
            return path
    for key, root in sorted(os.environ.items(), reverse=True):
        if not key.startswith("AWP_ROOT"):
            continue
        base = Path(root)
        candidates = [
            base / "aisol" / ".workbench",
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


def doctor_report(spec: SimulationSpec | None = None, *, probe_port: bool = True) -> dict[str, object]:
    execution = spec.execution if spec else None
    batch = bool(execution and execution.backend == "mechanical_batch")
    host = execution.host if execution else "127.0.0.1"
    port = execution.port if execution else None
    system = platform.system()
    mechanical_path = _find_mechanical_executable()
    pymechanical = _find_module("ansys.mechanical.core")
    dpf = _find_module("ansys.dpf.core")
    supported_os = system == "Windows" if batch else system in {"Windows", "Linux"}
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
    port_check = _port_state(host, port) if probe_port and not batch else {
        "status": CheckStatus.NOT_RUN.value, "message": "Dry-run does not contact Mechanical"
    }
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
    batch_policy_error = None
    if batch:
        try:
            execution.validate_connection()
        except ValueError as exc:
            batch_policy_error = str(exc)
        can_start = supported_os and mechanical_path is not None and batch_policy_error is None
        can_execute = can_start and dpf
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
    if batch:
        checks["operating_system"]["message"] = "mechanical_batch supports local Windows execution only"
        checks["pymechanical"].update(
            status=CheckStatus.NOT_RUN.value, message="mechanical_batch does not use PyMechanical gRPC"
        )
        checks["connection_policy"].update(
            status=CheckStatus.FAIL.value if batch_policy_error else CheckStatus.PASS.value,
            message=batch_policy_error or "A new task-owned local batch process is required",
        )
        checks["mechanical_executable"].update(
            status=CheckStatus.PASS.value if mechanical_path else CheckStatus.FAIL.value,
            message="mechanical_batch requires a local Mechanical executable",
        )
        for name in ("transport", "port"):
            checks[name].update(
                status=CheckStatus.NOT_RUN.value, message="mechanical_batch does not use a gRPC connection"
            )
    return {
        "status": CheckStatus.PASS.value if can_execute else CheckStatus.NOT_RUN.value,
        "can_start_local": can_start,
        "can_execute": can_execute,
        "checks": checks,
    }
