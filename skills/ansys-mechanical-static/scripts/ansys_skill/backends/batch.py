"""Explicit local Windows Mechanical batch execution of a saved compiler script."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ansys_skill.backends.base import BackendOutcome, MechanicalBackend
from ansys_skill.backends.environment import doctor_report
from ansys_skill.errors import (
    EnvironmentUnavailableError,
    MechanicalExecutionError,
    PathSafetyError,
    SpecValidationError,
)
from ansys_skill.paths import safe_join
from ansys_skill.schema import SimulationSpec


def _contained_path(run_dir: Path, value: str | Path) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise MechanicalExecutionError("Mechanical artifact paths must be non-empty strings")
    path = Path(value)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(run_dir)
        except ValueError as exc:
            raise PathSafetyError(f"Artifact path escapes the run directory: {value}") from exc
    return safe_join(run_dir, path)


def _read_artifacts(run_dir: Path) -> dict[str, Any]:
    """Keep the runtime protocol, normalizing local file paths to run-relative paths."""
    manifest = safe_join(run_dir, "mechanical-artifacts.json")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise MechanicalExecutionError(
            "Structured Mechanical artifacts are missing or invalid"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
        raise MechanicalExecutionError("Mechanical did not write a structured result status")
    if "run_directory" in payload and _contained_path(run_dir, payload["run_directory"]) != run_dir:
        raise PathSafetyError("Mechanical reported a different run directory")
    for key in ("result_files", "solve_logs"):
        paths = payload.get(key, [])
        if not isinstance(paths, list):
            raise MechanicalExecutionError(f"Mechanical {key} must be a list of paths")
        payload[key] = [
            _contained_path(run_dir, path).relative_to(run_dir).as_posix() for path in paths
        ]
    if payload.get("project_file") is not None:
        payload["project_file"] = (
            _contained_path(run_dir, payload["project_file"]).relative_to(run_dir).as_posix()
        )
    visual_review = payload.get("visual_review", [])
    if not isinstance(visual_review, list) or any(
        not isinstance(item, dict) for item in visual_review
    ):
        raise MechanicalExecutionError("Mechanical visual_review must be a list of records")
    for item in visual_review:
        if item.get("status") == "PASS":
            item["name"] = (
                _contained_path(run_dir, item.get("name")).relative_to(run_dir).as_posix()
            )
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _terminate_owned_tree(process: subprocess.Popen) -> str | None:
    """Target only the PID returned by this run's Popen, never an image name or service."""
    if process.poll() is not None:
        return None
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10,
            check=True,
        )
        process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    return None


class MechanicalBatchBackend(MechanicalBackend):
    def execute(
        self, spec: SimulationSpec, spec_path: Path, run_dir: Path, script_path: Path
    ) -> BackendOutcome:
        if spec.execution.backend != "mechanical_batch":
            raise SpecValidationError(
                "Mechanical batch execution requires backend: mechanical_batch"
            )
        try:
            spec.execution.validate_connection()
        except ValueError as exc:
            raise SpecValidationError(str(exc)) from exc
        spec.assert_execution_ready()
        report = doctor_report(spec, probe_port=False)
        if not report["can_execute"]:
            raise EnvironmentUnavailableError(
                "mechanical_batch requires a local Windows Mechanical executable and PyDPF",
                details=report,
            )
        run_dir = run_dir.resolve()
        script_path = _contained_path(run_dir, script_path)
        if not script_path.is_file():
            raise MechanicalExecutionError("The saved generated Mechanical script is missing")
        if safe_join(run_dir, "mechanical-artifacts.json").exists():
            raise MechanicalExecutionError(
                "Mechanical artifacts already exist; use a fresh run directory"
            )
        command = [
            report["checks"]["mechanical_executable"]["path"],
            "-DSApplet",
            "-AppModeMech",
            "-b",
            "-script",
            str(script_path),
            "-x",
        ]
        stdout_path = safe_join(run_dir, "mechanical-batch-stdout.log")
        stderr_path = safe_join(run_dir, "mechanical-batch-stderr.log")
        metadata: dict[str, object] = {
            "owned_instance": False,
            "mechanical_product_version": None,
            "remote_workdir": None,
            "command": command,
            "stdout_log": stdout_path.name,
            "stderr_log": stderr_path.name,
        }
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.Popen(
                    command,
                    cwd=run_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                metadata.update(owned_instance=True, process_id=process.pid)
                try:
                    metadata["process_exit_code"] = process.wait(
                        timeout=spec.execution.timeout_seconds
                    )
                except subprocess.TimeoutExpired as exc:
                    cleanup_error = _terminate_owned_tree(process)
                    metadata["process_exit_code"] = process.returncode
                    if cleanup_error:
                        metadata["cleanup_error"] = cleanup_error
                    raise MechanicalExecutionError(
                        f"Mechanical execution exceeded {spec.execution.timeout_seconds} seconds",
                        details=metadata,
                    ) from exc
                except BaseException:
                    _terminate_owned_tree(process)
                    raise
        except OSError as exc:
            raise MechanicalExecutionError(
                f"Mechanical batch process failed: {exc}", details=metadata
            ) from exc
        try:
            payload = _read_artifacts(run_dir)
        except MechanicalExecutionError as exc:
            exc.details.update(metadata)
            raise
        metadata["mechanical_product_version"] = payload.get("mechanical_product_version")
        details = {**metadata, "mechanical": payload}
        if payload["status"] != "SOLVED":
            raise MechanicalExecutionError("Mechanical reported a failed solve", details=details)
        if metadata["process_exit_code"] != 0:
            raise MechanicalExecutionError(
                f"Mechanical batch process exited with code {metadata['process_exit_code']}",
                details=details,
            )
        if not payload["result_files"] or any(
            not safe_join(run_dir, path).is_file() for path in payload["result_files"]
        ):
            raise MechanicalExecutionError(
                "Mechanical reported SOLVED without complete result files", details=details
            )
        return BackendOutcome(
            status="SOLVED",
            synthetic=False,
            artifacts=sorted(
                {_contained_path(run_dir, path) for path in run_dir.rglob("*") if path.is_file()}
            ),
            metadata=metadata,
        )
