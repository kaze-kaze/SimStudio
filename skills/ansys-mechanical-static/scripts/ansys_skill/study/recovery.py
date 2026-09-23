"""Recover interrupted attempts only after proving owned processes stopped."""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from pathlib import Path

from ansys_skill.errors import SpecValidationError
from ansys_skill.manifest import utc_now
from ansys_skill.paths import safe_join
from ansys_skill.study.project import load_project, save_project
from ansys_skill.study.storage import (
    artifact_hashes,
    owned_process_alive,
    process_alive,
    read_json,
    recover_lock,
    recovery_guard,
    study_lock,
)


def _running_attempts(manifest: dict) -> list[tuple[dict, dict, dict]]:
    running = []
    for sample in manifest["samples"]:
        for job in sample["jobs"]:
            for index, attempt in enumerate(job["attempts"]):
                if attempt["status"] == "RUNNING":
                    if index != len(job["attempts"]) - 1:
                        raise SpecValidationError("A running attempt is not the latest attempt; inspect the ledger manually")
                    running.append((sample, job, attempt))
    return running


def _prove_attempt_stopped(root: Path, attempt: dict) -> Path:
    run_dir = safe_join(root, attempt["path"])
    owner_path = run_dir.parent / "owned-process.json"
    if not owner_path.is_file() or owner_path.is_symlink():
        raise SpecValidationError(
            "Interrupted attempt has no ownership evidence; cannot automatically recover; inspect processes manually"
        )
    owner = read_json(owner_path)
    if owned_process_alive(owner):
        raise SpecValidationError("Interrupted attempt's owned process tree is still running")

    backend_owner = run_dir / "owned-process.json"
    if backend_owner.is_file():
        child = read_json(backend_owner)
        if child.get("host") != socket.gethostname():
            raise SpecValidationError("Cannot verify a solver process from another host")
        pid = child.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            raise SpecValidationError("Nested process ownership evidence has no valid PID; inspect it manually")
        if process_alive(pid):
            raise SpecValidationError("An owned solver child process is still running")
    return run_dir


def _interrupted_elapsed(attempt: dict, now: datetime) -> float:
    started_at = attempt.get("started_at")
    if not isinstance(started_at, str):
        raise SpecValidationError("Interrupted attempt has no valid start time; cannot account for its wall budget")
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError as exc:
        raise SpecValidationError("Interrupted attempt has an invalid start time") from exc
    if started.tzinfo is None:
        raise SpecValidationError("Interrupted attempt start time has no timezone")
    return max(0.0, (now - started.astimezone(UTC)).total_seconds())


def recover_study(root: Path) -> dict:
    root = root.resolve()
    lock = root / ".study.lock"
    with recovery_guard(root) as recovery_token:
        _, _, manifest = load_project(root)
        pending = _running_attempts(manifest)
        run_directories = [_prove_attempt_stopped(root, attempt) for _, _, attempt in pending]
        lock_result = recover_lock(root, recovery_token=recovery_token) if lock.exists() else None
        with study_lock(root, recovery_token=recovery_token):
            _, _, manifest = load_project(root)
            pending = _running_attempts(manifest)
            now = datetime.now(UTC)
            recovered = []
            elapsed = 0.0
            for (sample, job, attempt), run_dir in zip(pending, run_directories, strict=True):
                _prove_attempt_stopped(root, attempt)
                duration = _interrupted_elapsed(attempt, now)
                elapsed += duration
                attempt.update(
                    status="INTERRUPTED",
                    ended_at=utc_now(),
                    elapsed_seconds=duration,
                    failure={
                        "type": "RecoveredInterruption",
                        "message": "All recorded local owners are stopped; a new attempt is required.",
                    },
                )
                if run_dir.is_dir():
                    attempt["hashes"] = artifact_hashes(run_dir)
                job["status"] = "INTERRUPTED"
                sample["status"] = "INTERRUPTED"
                recovered.append(attempt["path"])
            if recovered:
                manifest["elapsed_seconds"] += elapsed
                manifest["status"] = "INTERRUPTED"
                save_project(root, manifest)
            return {
                "status": "RECOVERED",
                "attempts": recovered,
                "lock": lock_result,
                "message": "Use --execute --resume to retry within the original budget.",
            }
