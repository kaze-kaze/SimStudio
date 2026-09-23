"""Recovery protocol tests; fixtures are not Mechanical acceptance evidence."""
from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest
from ansys_skill.errors import SpecValidationError
from ansys_skill.manifest import utc_now
from ansys_skill.study import project, recovery, storage
from ansys_skill.study.sampling import sample_record
from ansys_skill.study.storage import atomic_json, read_json
from ansys_skill.study.templates import init_study


@pytest.fixture
def interrupted_study(tmp_path, monkeypatch):
    monkeypatch.setattr(
        project,
        "plan_samples",
        lambda spec: ([sample_record(spec.baseline(), "baseline")], []),
    )
    init_study(tmp_path / "inputs")
    root = tmp_path / "study"
    project.create_plan(tmp_path / "inputs" / "study.yaml", root)
    manifest = read_json(root / "study-manifest.json")
    sample = manifest["samples"][0]
    job = sample["jobs"][0]
    attempt_dir = root / "samples" / sample["sample_id"] / "mesh-0" / "attempt-001"
    run_dir = attempt_dir / "run"
    run_dir.mkdir(parents=True)
    attempt = {
        "attempt": 1,
        "path": run_dir.relative_to(root).as_posix(),
        "status": "RUNNING",
        "started_at": utc_now(),
        "ended_at": None,
        "elapsed_seconds": None,
        "hashes": {},
    }
    job["attempts"].append(attempt)
    job["status"] = "RUNNING"
    sample["status"] = "RUNNING"
    manifest["solver_calls"] = 1
    manifest["status"] = "RUNNING"
    atomic_json(root / "study-manifest.json", manifest)
    atomic_json(root / ".study.lock", {"pid": 910001, "host": socket.gethostname(), "token": "stale"})
    return root, attempt, attempt_dir


def write_owner(attempt_dir: Path, *, ended_at=None):
    owner = {
        "pid": 910002,
        "host": socket.gethostname(),
        "started_at": utc_now(),
        "ended_at": ended_at,
        "process_tree": "windows-parent-tree" if os.name == "nt" else "posix-session",
        "process_group_id": None if os.name == "nt" else 910002,
        "tree_verified": False,
    }
    atomic_json(attempt_dir / "owned-process.json", owner)
    return owner


def test_missing_owner_evidence_keeps_lock_and_explains_manual_recovery(
    interrupted_study, monkeypatch
):
    root, _, _ = interrupted_study
    monkeypatch.setattr(storage, "process_alive", lambda _pid: False)

    with pytest.raises(
        SpecValidationError, match=r"ownership evidence.*cannot automatically recover"
    ):
        recovery.recover_study(root)

    assert (root / ".study.lock").exists()
    assert not (root / ".study.recovery.lock").exists()


def test_recovery_checks_owned_process_tree_even_if_owner_says_ended(
    interrupted_study, monkeypatch
):
    root, _, attempt_dir = interrupted_study
    write_owner(attempt_dir, ended_at=utc_now())
    monkeypatch.setattr(storage, "process_alive", lambda _pid: False)
    monkeypatch.setattr(storage, "process_group_alive", lambda _pgid: True)
    monkeypatch.setattr(storage, "windows_process_tree_alive", lambda _pid: True)

    with pytest.raises(SpecValidationError, match="owned process tree is still running"):
        recovery.recover_study(root)

    assert (root / ".study.lock").exists()
    assert read_json(root / "study-manifest.json")["samples"][0]["jobs"][0]["attempts"][0]["status"] == "RUNNING"


def test_recovery_marks_only_proven_stopped_attempt_interrupted(interrupted_study, monkeypatch):
    root, attempt, attempt_dir = interrupted_study
    write_owner(attempt_dir)
    (attempt_dir / "run" / "partial.txt").write_text("protocol fixture")
    monkeypatch.setattr(storage, "process_alive", lambda _pid: False)
    monkeypatch.setattr(storage, "process_group_alive", lambda _pgid: False)
    monkeypatch.setattr(storage, "windows_process_tree_alive", lambda _pid: False)

    result = recovery.recover_study(root)

    manifest = read_json(root / "study-manifest.json")
    recovered = manifest["samples"][0]["jobs"][0]["attempts"][0]
    assert result["status"] == "RECOVERED"
    assert recovered["path"] == attempt["path"]
    assert recovered["status"] == "INTERRUPTED"
    assert recovered["hashes"]["partial.txt"]
    assert not (root / ".study.lock").exists()


def test_windows_liveness_uses_windows_query_without_os_kill(monkeypatch):
    monkeypatch.setattr(storage.os, "name", "nt")
    monkeypatch.setattr(storage, "_windows_process_alive", lambda _pid: False)
    monkeypatch.setattr(storage.os, "kill", lambda *_args: pytest.fail("os.kill is not a Windows liveness API"))

    assert storage.process_alive(910003) is False


def test_recovery_checks_nested_solver_tree_after_both_parents_exited(
    interrupted_study, monkeypatch
):
    root, _, attempt_dir = interrupted_study
    parent = write_owner(attempt_dir, ended_at=utc_now())
    parent["tree_verified"] = True
    atomic_json(attempt_dir / "owned-process.json", parent)
    child = {**parent, "pid": 910004, "process_group_id": 910004,
             "tree_verified": False}
    atomic_json(attempt_dir / "run" / "owned-process.json", child)
    monkeypatch.setattr(storage, "process_alive", lambda _pid: False)
    monkeypatch.setattr(storage, "process_group_alive", lambda pid: pid == 910004)
    monkeypatch.setattr(storage, "windows_process_tree_alive", lambda pid: pid == 910004)

    with pytest.raises(SpecValidationError, match="solver child process tree is still running"):
        recovery.recover_study(root)

    assert (root / ".study.lock").exists()
    assert read_json(root / "study-manifest.json")["solver_calls"] == 1
