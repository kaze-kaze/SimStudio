"""Backend protocol and result model."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ansys_skill.schema import SimulationSpec


@dataclass
class BackendOutcome:
    status: str
    synthetic: bool
    artifacts: list[Path] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


class MechanicalBackend(ABC):
    @abstractmethod
    def execute(
        self, spec: SimulationSpec, spec_path: Path, run_dir: Path, script_path: Path
    ) -> BackendOutcome:
        raise NotImplementedError
