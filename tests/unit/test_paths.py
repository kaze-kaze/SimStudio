from __future__ import annotations

from pathlib import Path

import pytest
from ansys_skill.errors import PathSafetyError
from ansys_skill.paths import prepare_output_dir, require_fresh_run_dir, safe_join


def test_safe_join_blocks_escape(tmp_path: Path) -> None:
    with pytest.raises(PathSafetyError, match="escapes"):
        safe_join(tmp_path, "../outside.txt")


def test_output_directory_symlink_is_rejected(tmp_path: Path, create_symlink) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    create_symlink(link, real, is_directory=True)
    with pytest.raises(PathSafetyError, match="symbolic link"):
        prepare_output_dir(link)


def test_nonempty_run_directory_is_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "old.rst").write_bytes(b"stale")
    with pytest.raises(PathSafetyError, match="new or empty"):
        require_fresh_run_dir(run_dir)
