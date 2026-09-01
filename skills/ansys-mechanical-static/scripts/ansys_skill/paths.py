"""Path normalization and output containment helpers."""

from __future__ import annotations

import os
from pathlib import Path

from ansys_skill.errors import PathSafetyError, SpecValidationError


def resolve_spec_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise SpecValidationError(f"Simulation specification does not exist: {resolved}")
    return resolved


def resolve_input_path(spec_path: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = spec_path.parent / candidate
    return candidate.resolve()


def prepare_output_dir(path: str | Path) -> Path:
    raw = Path(path).expanduser()
    if raw.exists() and raw.is_symlink():
        raise PathSafetyError(f"Output directory cannot be a symbolic link: {raw}")
    candidate = raw.resolve()
    forbidden = {Path("/").resolve(), Path.home().resolve()}
    if candidate in forbidden:
        raise PathSafetyError(f"Refusing unsafe output directory: {candidate}")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def require_fresh_run_dir(path: str | Path) -> None:
    candidate = Path(path).expanduser()
    if not candidate.exists():
        return
    if candidate.is_symlink():
        raise PathSafetyError(f"Run directory cannot be a symbolic link: {candidate}")
    if not candidate.is_dir():
        raise PathSafetyError(f"Run output path is not a directory: {candidate}")
    entries = sorted(item.name for item in candidate.iterdir())
    if entries:
        raise PathSafetyError(
            "Run directory must be new or empty to prevent stale solver artifacts",
            details={"directory": str(candidate.resolve()), "existing_entries": entries},
        )


def safe_join(root: Path, relative: str | Path) -> Path:
    rel = Path(relative)
    if rel.is_absolute():
        raise PathSafetyError(f"Artifact path must be relative: {relative}")
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PathSafetyError(f"Artifact path escapes the run directory: {relative}") from exc
    return target


def display_path(path: Path, root: Path | None = None) -> str:
    if root is not None:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return os.fspath(path.resolve())
