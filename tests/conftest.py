from __future__ import annotations

import copy
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from ansys_skill.compiler.mechanical import render_script

ROOT = Path(__file__).resolve().parents[1]
CANTILEVER = ROOT / "examples" / "cantilever"


@pytest.fixture
def create_symlink():
    """Retain real symlink assertions; report a missing Windows privilege explicitly."""
    def create(link: Path, target: Path, *, is_directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=is_directory)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                pytest.skip("NOT_RUN: Windows does not grant symbolic-link creation (WinError 1314)")
            raise
    return create


@pytest.fixture
def valid_document() -> dict[str, object]:
    return yaml.safe_load((CANTILEVER / "simulation.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def valid_spec_path(tmp_path: Path, valid_document: dict[str, object]) -> Path:
    shutil.copy2(CANTILEVER / "cantilever.step", tmp_path / "cantilever.step")
    path = tmp_path / "simulation.yaml"
    path.write_text(
        yaml.safe_dump(copy.deepcopy(valid_document), sort_keys=False), encoding="utf-8"
    )
    return path


@pytest.fixture
def mechanical_runtime(monkeypatch):
    """Load only the fixed generated definitions, never the solver entry point."""
    monkeypatch.setitem(sys.modules, "units", ModuleType("units"))

    def load(plan):
        namespace = {}
        definitions = render_script(plan).split("outcome = None", 1)[0]
        exec(compile(definitions, "generated-definitions.py", "exec"), namespace)
        return namespace

    return load
