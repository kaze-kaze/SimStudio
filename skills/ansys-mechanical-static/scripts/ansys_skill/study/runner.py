"""Serial, budgeted execution with immutable attempts and checked resume."""

from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import io
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import yaml

from ansys_skill.backends.environment import doctor_report
from ansys_skill.errors import AnsysSimError, EnvironmentUnavailableError, SpecValidationError
from ansys_skill.logging import progress
from ansys_skill.manifest import environment_snapshot, sha256_file, utc_now
from ansys_skill.paths import safe_join
from ansys_skill.study.project import load_project, prepare_sample, save_project
from ansys_skill.study.storage import (
    artifact_hashes,
    atomic_json,
    atomic_text,
    owned_process_alive,
    process_group_alive,
    read_json,
    study_lock,
    verify_hashes,
)


def _call_single_run(specification: Path, directory: Path, execute: bool,
                     *, wall_timeout_seconds: float | None = None) -> tuple[int, dict]:
    if execute:
        return _run_isolated(specification, directory, wall_timeout_seconds=wall_timeout_seconds)
    # Reuse the real command's validation, explicit execution and error handling.
    from ansys_skill.cli import command_run

    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            code = command_run(argparse.Namespace(simulation=str(specification), out=str(directory),
                                                 execute=execute, json=True))
    except AnsysSimError as exc:
        return int(exc.exit_code), {"status": "ERROR", "error": str(exc), "details": exc.details}
    try:
        payload = json.loads(output.getvalue())
    except ValueError as exc:
        raise SpecValidationError("Single-run command returned invalid structured output") from exc
    return int(code), payload


def _stop_owned_cli(process: subprocess.Popen, owner: dict, *, immediate: bool = False) -> None:
    if os.name == "nt":
        if process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=10, check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        if process.poll() is None:
            process.wait(timeout=5)
        if owned_process_alive(owner):
            raise SpecValidationError("Cannot prove that the owned Windows process tree stopped")
        return

    process_group_id = owner.get("process_group_id")
    if not isinstance(process_group_id, int) or process_group_id <= 0:
        raise SpecValidationError("Owned CLI process has no recorded process group")
    if process_group_alive(process_group_id):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process_group_id, signal.SIGKILL if immediate else signal.SIGTERM)
    if process.poll() is None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
    if process_group_alive(process_group_id):
        os.killpg(process_group_id, signal.SIGKILL)
        if process.poll() is None:
            process.wait(timeout=5)
    if process_group_alive(process_group_id):
        raise SpecValidationError("Cannot prove that the owned POSIX process group stopped")


def _run_cli_child(command: list[str], parent: Path, *, timeout: float) -> tuple[int, dict]:
    """Run one owned CLI child and capture its structured output and process evidence."""
    stdout_path, stderr_path = parent / "command-output.json", parent / "command-stderr.log"
    owner_path = parent / "owned-process.json"
    started = time.monotonic()
    owner = {
        "pid": None,
        "host": socket.gethostname(),
        "started_at": utc_now(),
        "ended_at": None,
        "process_tree": "windows-parent-tree" if os.name == "nt" else "posix-session",
        "process_group_id": None,
        "tree_verified": False,
        "launch_status": "PENDING",
    }
    atomic_json(owner_path, owner)
    process = None
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, cwd=parent,
                env=dict(os.environ),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
        except OSError:
            owner.update(launch_status="FAILED", ended_at=utc_now(), tree_verified=True)
            atomic_json(owner_path, owner)
            raise
        owner.update(pid=process.pid, launch_status="STARTED")
        if os.name != "nt":
            owner["process_group_id"] = process.pid
        try:
            atomic_json(owner_path, owner)
        except BaseException as exc:
            try:
                _stop_owned_cli(process, owner, immediate=True)
                owner.update(ended_at=utc_now(), exit_code=process.returncode, tree_verified=True)
                atomic_json(owner_path, owner)
            except BaseException as cleanup_error:
                raise cleanup_error from exc
            raise
        try:
            remaining = max(0.0, timeout - (time.monotonic() - started))
            code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            _stop_owned_cli(process, owner, immediate=True)
            owner.update(ended_at=utc_now(), exit_code=process.returncode, tree_verified=True)
            atomic_json(owner_path, owner)
            return 4, {"status": "ERROR",
                       "error": "Mechanical/DPF command exceeded the remaining time budget"}
        except BaseException:
            _stop_owned_cli(process, owner)
            owner.update(ended_at=utc_now(), exit_code=process.returncode, tree_verified=True)
            atomic_json(owner_path, owner)
            raise
        if owned_process_alive(owner):
            _stop_owned_cli(process, owner)
            owner.update(ended_at=utc_now(), exit_code=process.returncode, tree_verified=True)
            atomic_json(owner_path, owner)
            return 4, {"status": "ERROR",
                       "error": "CLI exited while an owned child process was still running"}
        owner.update(ended_at=utc_now(), exit_code=code, tree_verified=True)
        atomic_json(owner_path, owner)
    try:
        payload = json.loads(stdout_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return 4, {"status": "ERROR", "error": "CLI returned no valid JSON; inspect command-stderr.log"}
    return code, payload


def _run_isolated(specification: Path, directory: Path,
                  *, wall_timeout_seconds: float | None = None) -> tuple[int, dict]:
    """Contain DPF's native environment changes within one CLI child process."""
    started = time.monotonic()
    document = yaml.safe_load(specification.read_text(encoding="utf-8"))
    timeout = document["execution"]["timeout_seconds"] + 30
    parent = directory.parent
    command = [sys.executable, "-m", "ansys_skill.cli", "run", str(specification),
               "--out", str(directory), "--execute", "--json"]
    if wall_timeout_seconds is not None:
        timeout = min(timeout, max(0.0, wall_timeout_seconds - (time.monotonic() - started)))
    return _run_cli_child(command, parent, timeout=timeout)


def _execution_context(base) -> dict:
    report = doctor_report(base, probe_port=True)
    if not report["can_execute"]:
        raise EnvironmentUnavailableError("No usable Mechanical environment for this study", details=report)
    environment = environment_snapshot()
    context = {key: environment[key] for key in
               ("system", "python_version", "ansys_mechanical_core_version", "ansys_dpf_core_version")}
    context["backend"] = base.execution.backend
    for name in ("build123d", "numpy", "scipy"):
        context[name] = importlib.metadata.version(name)
    executable = report.get("checks", {}).get("mechanical_executable", {}).get("path")
    if executable and Path(executable).is_file():
        stat = Path(executable).stat()
        context["mechanical_executable"] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return context


def _completed_attempt(root: Path, job: dict) -> dict | None:
    attempts = job["attempts"]
    if not attempts or attempts[-1]["status"] != "SOLVED":
        return None
    attempt = attempts[-1]
    inputs = attempt.get("input_hashes")
    if not isinstance(inputs, dict) or not inputs:
        raise SpecValidationError("Attempt input integrity record is missing; cannot reuse result")
    for name, expected in inputs.items():
        path = safe_join(root, name)
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise SpecValidationError(f"Attempt input missing or changed: {name}")
    verify_hashes(safe_join(root, attempt["path"]), attempt["hashes"])
    directory_hashes = attempt.get("directory_hashes")
    if not isinstance(directory_hashes, dict) or not directory_hashes:
        raise SpecValidationError("Attempt directory integrity record is missing; cannot reuse result")
    verify_hashes(safe_join(root, attempt["path"]).parent, directory_hashes)
    return attempt


def _attempt(root, manifest, sample, job, *, execute, timeout_seconds, wall_timeout_seconds=None):
    attempt_started = time.monotonic()
    ordinal = len(job["attempts"]) + 1 if execute else len(job.get("previews", [])) + 1
    kind = "attempt" if execute else "preview"
    relative = f"samples/{sample['sample_id']}/mesh-{job['mesh_index']}/{kind}-{ordinal:03d}"
    directory = safe_join(root, relative)
    if directory.exists():
        raise SpecValidationError("Attempt directory already exists; inspect interrupted state")
    directory.mkdir(parents=True)
    document = yaml.safe_load(safe_join(root, job["specification"]).read_text(encoding="utf-8"))
    document["inputs"]["geometry_file"] = "../../geometry.step"
    remaining_wall = (None if wall_timeout_seconds is None else
                      max(0.0, wall_timeout_seconds - (time.monotonic() - attempt_started)))
    if remaining_wall is not None and remaining_wall > 30:
        timeout_seconds = min(timeout_seconds, int(remaining_wall) - 30)
    document["execution"]["timeout_seconds"] = timeout_seconds
    spec_path = directory / "simulation.yaml"
    atomic_text(spec_path, yaml.safe_dump(document, sort_keys=False))
    geometry_path = safe_join(root, f"samples/{sample['sample_id']}/geometry.step")
    input_hashes = {
        spec_path.relative_to(root).as_posix(): sha256_file(spec_path),
        geometry_path.relative_to(root).as_posix(): sha256_file(geometry_path),
    }
    attempt = {"attempt": ordinal, "path": relative + "/run", "status": "RUNNING",
               "started_at": utc_now(), "ended_at": None, "elapsed_seconds": None,
               "specification_sha256": input_hashes[spec_path.relative_to(root).as_posix()],
               "input_hashes": input_hashes, "hashes": {}}
    records = job["attempts"] if execute else job.setdefault("previews", [])
    records.append(attempt)
    job["status"] = "RUNNING" if execute else job["status"]
    if execute:
        manifest["solver_calls"] += 1
    save_project(root, manifest)
    try:
        code, payload = _call_single_run(
            spec_path, directory / "run", execute, wall_timeout_seconds=remaining_wall
        )
        attempt["exit_code"] = code
        attempt["command_result"] = payload
        solved = execute and code in {0, 6} and payload.get("status") == "SOLVED" and payload.get("synthetic") is False
        attempt["status"] = "SOLVED" if solved else "DRY_RUN" if not execute and code == 0 else "FAILED"
        if solved:
            evidence = read_json(directory / "run" / "run-manifest.json")
            version = evidence.get("mechanical_product_version")
            if not version:
                raise SpecValidationError("Real run did not identify the Mechanical product version")
            old_version = manifest.setdefault("mechanical_product_version", version)
            if old_version != version:
                raise SpecValidationError("Mechanical product version changed during the study")
    except BaseException as exc:
        attempt["status"] = "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "FAILED"
        attempt["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        finalization_error = None
        try:
            if (directory / "run").is_dir():
                attempt["hashes"] = artifact_hashes(directory / "run")
            attempt["directory_hashes"] = artifact_hashes(directory)
        except BaseException as exc:
            finalization_error = exc
            attempt["status"] = "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "FAILED"
            attempt["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        attempt["elapsed_seconds"] = time.monotonic() - attempt_started
        attempt["ended_at"] = utc_now()
        if execute:
            job["status"] = attempt["status"]
        try:
            save_project(root, manifest)
        except BaseException as exc:
            if attempt["status"] == "SOLVED":
                attempt["status"] = "FAILED"
                attempt["failure"] = {"type": type(exc).__name__, "message": str(exc)}
                if execute:
                    job["status"] = "FAILED"
            raise
        if finalization_error is not None:
            raise finalization_error
    return attempt


def run_study(root: Path, *, execute: bool = False, resume: bool = False,
              limit: int | None = None, splits: tuple[str, ...] | None = None,
              solver_call_limit: int | None = None) -> dict:
    root = root.resolve()
    with study_lock(root):
        started = time.monotonic()
        study, base, manifest = load_project(root, check_code=True)
        prior_elapsed = manifest["elapsed_seconds"]
        if execute:
            context = _execution_context(base)
            if manifest["execution_context"] not in (None, context):
                raise SpecValidationError("Execution environment changed; cannot reuse this study")
            manifest["execution_context"] = context
        if execute and manifest["solver_calls"] and not resume:
            raise SpecValidationError("Study already has attempts; use explicit --resume")
        if limit is not None and limit <= 0:
            raise SpecValidationError("Sample limit must be positive")
        if solver_call_limit is not None and solver_call_limit <= 0:
            raise SpecValidationError("Solver call limit must be positive")
        starting_calls = manifest["solver_calls"]
        starting_split_calls = sum(
            len(job["attempts"]) for sample in manifest["samples"]
            if not splits or sample["split"] in splits for job in sample["jobs"]
        )
        processed = 0
        has_execution_history = any(
            job["attempts"] for sample in manifest["samples"] for job in sample["jobs"]
        )
        if execute:
            manifest["status"] = "RUNNING"
        elif not has_execution_history:
            manifest["status"] = "PREPARING"
        try:
            for sample in manifest["samples"]:
                if splits and sample["split"] not in splits:
                    continue
                if limit is not None and processed >= limit:
                    break
                if execute and all(_completed_attempt(root, job) for job in sample["jobs"]):
                    continue
                if execute:
                    elapsed = prior_elapsed + time.monotonic() - started
                    calls_in_scope = starting_split_calls + manifest["solver_calls"] - starting_calls
                    if (manifest["solver_calls"] >= study.budget.max_solver_calls
                            or study.budget.max_wall_seconds - elapsed < 60
                            or (solver_call_limit is not None
                                and calls_in_scope >= solver_call_limit)):
                        manifest["status"] = "BUDGET_EXHAUSTED"
                        manifest["elapsed_seconds"] = elapsed
                        return status_payload(manifest)
                progress(f"Study {study.name}: {sample['sample_id']}")
                previous_status = sample["status"]
                had_attempts = any(job["attempts"] for job in sample["jobs"])
                try:
                    prepare_sample(root, sample, study, base)
                except EnvironmentUnavailableError:
                    raise
                except AnsysSimError as exc:
                    sample.update(status="GEOMETRY_FAILED", failure=str(exc))
                    save_project(root, manifest)
                    processed += 1
                    continue
                if not execute and had_attempts:
                    sample["status"] = previous_status
                save_project(root, manifest)
                for job in sample["jobs"]:
                    if execute and _completed_attempt(root, job):
                        continue
                    if execute and any(a["status"] == "RUNNING" for a in job["attempts"]):
                        raise SpecValidationError("Unresolved running attempt; inspect and recover before retrying")
                    allowed = study.budget.retries_per_job + 1
                    while not execute or len(job["attempts"]) < allowed:
                        remaining = study.budget.max_wall_seconds - prior_elapsed - (time.monotonic() - started)
                        calls_in_scope = starting_split_calls + manifest["solver_calls"] - starting_calls
                        split_exhausted = (solver_call_limit is not None
                                           and calls_in_scope >= solver_call_limit)
                        if execute and (manifest["solver_calls"] >= study.budget.max_solver_calls
                                        or remaining < 60 or split_exhausted):
                            manifest["status"] = "BUDGET_EXHAUSTED"
                            manifest["elapsed_seconds"] = (
                                prior_elapsed + max(0.0, time.monotonic() - started)
                            )
                            return status_payload(manifest)
                        timeout = (min(base.execution.timeout_seconds, int(remaining) - 30)
                                   if execute else base.execution.timeout_seconds)
                        attempt = _attempt(
                            root, manifest, sample, job, execute=execute, timeout_seconds=timeout,
                            wall_timeout_seconds=remaining if execute else None,
                        )
                        if not execute or attempt["status"] == "SOLVED":
                            break
                        progress(f"Attempt failed: {sample['sample_id']} / mesh {job['mesh_index']}")
                    if execute and job["status"] != "SOLVED":
                        sample["status"] = "FAILED"
                        break
                else:
                    if execute:
                        sample["status"] = "SOLVED"
                    elif had_attempts:
                        sample["status"] = previous_status
                    else:
                        sample["status"] = "DRY_RUN"
                processed += 1
                save_project(root, manifest)
            states = {sample["status"] for sample in manifest["samples"]}
            if execute or has_execution_history:
                manifest["status"] = "SOLVED" if states == {"SOLVED"} else "PARTIAL"
            else:
                manifest["status"] = "DRY_RUN"
        except KeyboardInterrupt:
            manifest["status"] = "INTERRUPTED"
            raise
        except BaseException:
            manifest["status"] = "FAILED"
            raise
        finally:
            manifest["elapsed_seconds"] = prior_elapsed + max(0.0, time.monotonic() - started)
            save_project(root, manifest)
        return status_payload(manifest)


def status_payload(manifest: dict) -> dict:
    states = {}
    for sample in manifest["samples"]:
        states[sample["status"]] = states.get(sample["status"], 0) + 1
    return {"status": manifest["status"], "study_id": manifest["study_id"],
            "samples": states, "solver_calls": manifest["solver_calls"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "engineering_validation": "NOT_RUN"}
