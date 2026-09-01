"""Run manifest creation, hashing, and artifact tracking."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ansys_skill.paths import display_path


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def environment_snapshot() -> dict[str, Any]:
    return {
        "os": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "ansys_mechanical_core_version": package_version("ansys-mechanical-core"),
        "ansys_dpf_core_version": package_version("ansys-dpf-core"),
    }


def initial_manifest(
    *,
    run_dir: Path,
    input_path: Path,
    spec_path: Path,
    normalized_path: Path,
    script_path: Path,
    execution_mode: str,
    transport_mode: str,
) -> dict[str, Any]:
    environment = environment_snapshot()
    return {
        "manifest_version": "1.0",
        "status": "COMPILED",
        "synthetic": False,
        "started_at": utc_now(),
        "ended_at": None,
        "failure_stage": None,
        "execution_mode": execution_mode,
        "transport_mode": transport_mode,
        "mechanical_product_version": None,
        "instance_owned_by_run": None,
        "remote_workdir": None,
        "remote_cleanup_warning": None,
        "environment": environment,
        "hashes": {
            "input_sha256": sha256_file(input_path),
            "source_spec_sha256": sha256_file(spec_path),
            "normalized_spec_sha256": sha256_file(normalized_path),
            "generated_script_sha256": sha256_file(script_path),
        },
        "commands_and_checks": [],
        "artifacts": [
            display_path(normalized_path, run_dir),
            display_path(script_path, run_dir),
        ],
    }


def add_artifact(manifest: dict[str, Any], run_dir: Path, path: Path) -> None:
    relative = display_path(path, run_dir)
    artifacts = manifest.setdefault("artifacts", [])
    if relative not in artifacts:
        artifacts.append(relative)
        artifacts.sort()


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
