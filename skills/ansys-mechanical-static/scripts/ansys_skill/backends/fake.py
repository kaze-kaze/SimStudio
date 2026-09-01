"""Explicitly synthetic backend for offline state-machine tests."""

from __future__ import annotations

import json
from pathlib import Path

from ansys_skill.backends.base import BackendOutcome, MechanicalBackend
from ansys_skill.errors import MechanicalExecutionError
from ansys_skill.schema import ResultType, SimulationSpec


class FakeMechanicalBackend(MechanicalBackend):
    def __init__(self, fail_stage: str | None = None) -> None:
        self.fail_stage = fail_stage

    def execute(
        self, spec: SimulationSpec, spec_path: Path, run_dir: Path, script_path: Path
    ) -> BackendOutcome:
        del spec_path, script_path
        if self.fail_stage == "startup":
            raise MechanicalExecutionError("Synthetic Mechanical startup failure")
        solve_log = run_dir / "solve.out"
        solve_log.write_text("SYNTHETIC TEST OUTPUT - NOT AN ANSYS SOLVE\n", encoding="utf-8")
        if self.fail_stage == "solve":
            raise MechanicalExecutionError("Synthetic solver failure")

        results: dict[str, object] = {}
        for request in spec.requested_results:
            if request.type in {ResultType.TOTAL_DEFORMATION, ResultType.DIRECTIONAL_DEFORMATION}:
                results[request.id] = {
                    "maximum": 0.001,
                    "unit": "m",
                    "location": "Nodal",
                    "scoping_id": 1,
                }
            elif request.type is ResultType.EQUIVALENT_VON_MISES_STRESS:
                results[request.id] = {
                    "maximum": 100_000_000.0,
                    "unit": "Pa",
                    "location": "ElementalNodal",
                    "scoping_id": 1,
                }
            elif request.type is ResultType.REACTION_FORCE:
                results[request.id] = {
                    "maximum": 1000.0,
                    "unit": "N",
                    "location": "Nodal",
                    "sum_vector": [-1000.0, 0.0, 0.0],
                }
        summary = {
            "status": "SYNTHETIC",
            "synthetic": True,
            "result_file": None,
            "node_count": 8,
            "element_count": 1,
            "solver_messages": [
                {
                    "severity": "INFO",
                    "text": "Synthetic backend result; no ANSYS solver was invoked",
                }
            ],
            "results": results,
        }
        summary_path = run_dir / "results-summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        messages_path = run_dir / "solver-messages.json"
        messages_path.write_text(
            json.dumps(summary["solver_messages"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return BackendOutcome(
            status="SYNTHETIC",
            synthetic=True,
            artifacts=[solve_log, summary_path, messages_path],
            metadata={"warning": "No commercial solver was invoked"},
        )
