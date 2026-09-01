from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CANTILEVER = ROOT / "examples" / "cantilever"


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
