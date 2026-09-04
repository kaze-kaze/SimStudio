from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "cantilever" / "simulation.yaml"


@pytest.mark.ansys_integration
@pytest.mark.skipif(
    os.getenv("ANSYS_AVAILABLE") != "1",
    reason="Set ANSYS_AVAILABLE=1 only on a licensed compatible Mechanical host",
)
def test_real_cantilever(tmp_path: Path) -> None:
    doctor = subprocess.run(
        [sys.executable, "-m", "ansys_skill.cli", "doctor", "--strict", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    run_dir = tmp_path / "cantilever-real"
    result = subprocess.run(
        [
            sys.executable, "-m", "ansys_skill.cli",
            "run",
            str(EXAMPLE),
            "--out",
            str(run_dir),
            "--execute",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["synthetic"] is False
    assert (run_dir / "results-summary.json").is_file()
    assert (run_dir / "verification.json").is_file()
    assert (run_dir / "report.md").is_file()
    verification = json.loads((run_dir / "verification.json").read_text(encoding="utf-8"))
    checks = {item["name"]: item["status"] for item in verification["checks"]}
    for name in ("requested_results", "reaction_balance", "small_deformation", "cantilever_analytical"):
        assert checks[name] == "PASS", verification
    summary = json.loads((run_dir / "results-summary.json").read_text(encoding="utf-8"))
    assert summary["synthetic"] is False
    assert summary["results"]["tip_z"]["canonical_maximum"] == pytest.approx(-0.000125, rel=0.15)
