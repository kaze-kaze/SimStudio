from __future__ import annotations

import json
from pathlib import Path

from ansys_skill.reporting import generate_reports
from ansys_skill.schema import load_spec


def test_report_generation(valid_spec_path: Path, tmp_path: Path) -> None:
    spec, _ = load_spec(valid_spec_path)
    summary = {
        "status": "NOT_RUN",
        "synthetic": False,
        "results": {},
        "solver_messages": [],
    }
    verification = {
        "status": "NOT_RUN",
        "checks": [
            {
                "name": "mechanical_solve",
                "status": "NOT_RUN",
                "message": "dry-run",
            }
        ],
    }
    paths = generate_reports(tmp_path, spec, summary, verification)
    assert Path(paths["report"]).is_file()
    assert "No numerical solver result" in Path(paths["report"]).read_text(encoding="utf-8")
    assert (
        json.loads(Path(paths["results_summary"]).read_text(encoding="utf-8"))["status"]
        == "NOT_RUN"
    )
    assert Path(paths["results_csv"]).read_text(encoding="utf-8").startswith("result_id")


def test_synthetic_report_has_warning(valid_spec_path: Path, tmp_path: Path) -> None:
    spec, _ = load_spec(valid_spec_path)
    paths = generate_reports(
        tmp_path,
        spec,
        {"status": "SYNTHETIC", "synthetic": True, "results": {}},
        {"status": "NOT_RUN", "checks": []},
    )
    report = Path(paths["report"]).read_text(encoding="utf-8")
    assert "SYNTHETIC TEST DATA" in report
    assert "Do not treat them as engineering results" in report
    assert "Normalized input quantities" in report
    assert "10 mm | 0.01 meter" in report
