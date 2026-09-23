"""Offline study report tests using explicit evidence fixtures."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from ansys_skill.study import report


class _ReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: dict[str, dict[str, object]] = {}
        self.table_rows: list[list[str]] = []
        self.labels: dict[str, str] = {}
        self._row: dict[str, object] | None = None
        self._cell: list[str] | None = None
        self._label_for: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self._row = {**attributes, "cells": []}
        elif tag == "td" and self._row is not None:
            self._cell = []
        elif tag == "label":
            self._label_for = attributes.get("for")
        elif tag == "select" and attributes.get("id"):
            self.labels[str(attributes["id"])] = str(
                attributes.get("aria-label") or self._label_for or ""
            )

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cell is not None and self._row is not None:
            cells = self._row["cells"]
            assert isinstance(cells, list)
            cells.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.table_rows.append(self._row["cells"])
            if "data-sample" in self._row:
                self.rows[str(self._row["data-sample"])] = self._row
            self._row = None
        elif tag == "label":
            self._label_for = None


def _study() -> SimpleNamespace:
    return SimpleNamespace(
        name="bracket-study",
        description="Fixture study for report rendering.",
        parameters={
            "plate_thickness": SimpleNamespace(baseline="20 mm"),
            "hole_diameter": SimpleNamespace(baseline="14 mm"),
            "fillet_radius": SimpleNamespace(baseline="10 mm"),
        },
        targets={
            "displacement": SimpleNamespace(
                result_id="total_deformation", dimension="length", unit="mm"
            ),
            "stress": SimpleNamespace(
                result_id="equivalent_stress", dimension="pressure", unit="MPa"
            ),
        },
    )


def _sample(sample_id: str, split: str, status: str, *, attempt_status: str | None = None) -> dict:
    parameters = {
        "plate_thickness": 0.02,
        "hole_diameter": 0.014,
        "fillet_radius": 0.01,
    }
    if split == "train":
        parameters["plate_thickness"] = 0.023
    if split == "test":
        parameters["hole_diameter"] = 0.016
    attempts = [{"status": attempt_status}] if attempt_status else []
    return {
        "sample_id": sample_id,
        "split": split,
        "status": status,
        "parameters": parameters,
        "geometry": {"mass_kg": 1.25},
        "jobs": [
            {"mesh_index": 0, "mesh_size": "12 mm", "attempts": attempts}
        ],
    }


def _context(
    tmp_path: Path,
    monkeypatch,
    *,
    samples: list[dict] | None = None,
    study: SimpleNamespace | None = None,
) -> tuple[Path, SimpleNamespace, dict]:
    root = tmp_path / "study"
    root.mkdir()
    study = study or _study()
    manifest = {
        "name": study.name,
        "study_id": "fixture-study",
        "status": "PLANNED",
        "overall": "WARN",
        "samples": samples if samples is not None else [
            _sample("baseline-001", "baseline", "SOLVED", attempt_status="SOLVED"),
            _sample("train-001", "train", "PLANNED"),
            _sample("test-001", "test", "DRY_RUN"),
        ],
        "datasets": [],
        "models": [],
        "rounds": [],
        "solver_calls": 1,
        "elapsed_seconds": 1.5,
    }
    monkeypatch.setattr(report.project, "load_project", lambda _root: (study, None, manifest))
    return root, study, manifest


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _dataset(study: SimpleNamespace) -> dict:
    return {
        "dataset_id": "dataset-001",
        "feature_names": list(study.parameters),
        "feature_units": {name: "meter" for name in study.parameters},
        "targets": {
            "displacement": {"dimension": "length", "unit": "meter",
                               "display_unit": "mm"},
            "stress": {"dimension": "pressure", "unit": "pascal",
                         "display_unit": "MPa"},
        },
        "rows": [
            {
                "sample_id": "baseline-001",
                "split": "baseline",
                "parameters": {
                    "plate_thickness": 0.02,
                    "hole_diameter": 0.014,
                    "fillet_radius": 0.01,
                },
                "mass_kg": 1.25,
                "targets": {"displacement": 0.001, "stress": 25_000_000},
                "accepted_targets": ["displacement", "stress"],
                "quality": [
                    {
                        "status": "WARN",
                        "values": {"displacement": 0.001, "stress": 25_000_000},
                        "evidence": {"mesh_size_m": 0.012},
                        "target_checks": {
                            "displacement": [{"status": "PASS"}],
                            "stress": [{"status": "PASS"}],
                        },
                    }
                ],
                "source": {"runs": [{"mesh_size": "12 mm"}]},
                "mesh_convergence": {
                    "targets": {
                        "displacement": {"relative_change": 0.01},
                        "stress": {"relative_change": 0.02},
                    }
                },
            }
        ],
    }


def test_empty_report_is_offline_and_returns_json_serializable_paths(tmp_path, monkeypatch):
    root, _, _ = _context(tmp_path, monkeypatch, samples=[])

    result = report.generate_study_report(root)
    document = json.dumps(result)
    html_text = Path(result["html"]).read_text(encoding="utf-8")

    assert result["status"] == "REPORTED"
    assert isinstance(result["html"], str)
    assert isinstance(result["markdown"], str)
    assert json.loads(document) == result
    assert "verification.json was not found" in html_text
    assert "comparison.json: NOT_RUN" in html_text
    assert "<html lang=\"en\">" in html_text
    assert "https://" not in html_text


def test_real_fields_preserve_execution_quality_units_and_evaluation_evidence(
    tmp_path, monkeypatch
):
    root, study, manifest = _context(tmp_path, monkeypatch)
    dataset = _dataset(study)
    _write_json(root / "datasets/dataset-001/dataset.json", dataset)
    manifest["datasets"] = ["datasets/dataset-001/dataset.json"]

    model_path = root / "models/model-001"
    _write_json(model_path / "model-card.json", {
        "model_id": "model-001",
        "training_sample_count_by_target": {"displacement": 4},
        "model_selection": {
            "displacement": {
                "selected_model": "random_forest",
                "cross_validation": {"selected_metrics": {"rmse": 0.0002}},
            }
        },
    })
    _write_json(model_path / "training-provenance.json", {"dataset_id": "dataset-001"})
    _write_json(model_path / "evaluation.json", {
        "status": "PASS",
        "targets": {
            "displacement": {
                "status": "PASS",
                "sample_count": 1,
                "metrics": {"mae": 0.0001, "rmse": 0.0002,
                             "normalized_error": 0.1, "r2": 0.9},
                "points": [{
                    "truth": 0.001, "prediction": 0.0012, "std": 0.0001,
                    "unit": "meter",
                }],
            }
        },
    })
    manifest["models"] = [{"model_id": "model-001", "path": "models/model-001"}]
    _write_json(root / "verification.json", {
        "status": "PASS",
        "best_sample_id": "verification-001",
        "candidates": [{
            "sample_id": "verification-001",
            "status": "SOLVED",
            "mass_kg": 1.1,
            "parameters": {"plate_thickness": 0.019},
            "targets": {"displacement": 0.0011},
            "accepted_targets": ["displacement"],
            "feasible": True,
        }],
    })

    result = report.generate_study_report(root)
    html_text = Path(result["html"]).read_text(encoding="utf-8")
    parser = _ReportParser()
    parser.feed(html_text)
    train_cells = parser.rows["train-001"]["cells"]

    assert "Overall verification" in html_text and "WARN" in html_text
    assert "Real solves completed" in html_text and "Quality accepted (all targets)" in html_text
    assert train_cells[2] == "PLANNED"
    assert train_cells[3] == "1.25 kg"
    assert train_cells[4] == "NOT_RUN"
    assert "1 mm" in html_text
    assert "25 MPa" in html_text
    assert "12 mm" in html_text
    assert "training dataset: <code>dataset-001</code>" in html_text
    assert "Truth (mm)" in html_text
    assert "0.2 mm" in html_text
    assert "Predictions and re-solved values are shown separately" in html_text
    assert "comparison.json: NOT_RUN" in html_text
    assert train_cells[-1] == "NOT_RUN"
    assert "NOT_RUN<br><span" not in html_text


def test_untrusted_labels_and_sample_ids_are_escaped(tmp_path, monkeypatch):
    payload = '</script><img src=x onerror="alert(1)">'
    study = _study()
    study.name = payload
    study.description = payload
    sample = _sample(payload, "test", "PLANNED")
    root, _, _ = _context(tmp_path, monkeypatch, samples=[sample], study=study)

    result = report.generate_study_report(root)
    html_text = Path(result["html"]).read_text(encoding="utf-8")

    assert payload not in html_text
    assert "&lt;/script&gt;&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html_text
    assert '<img src=x onerror="alert(1)">' not in html_text


def test_split_filters_match_labels_and_keep_sample_rows_searchable(tmp_path, monkeypatch):
    root, _, _ = _context(tmp_path, monkeypatch)

    result = report.generate_study_report(root)
    html_text = Path(result["html"]).read_text(encoding="utf-8")
    parser = _ReportParser()
    parser.feed(html_text)

    train = parser.rows["train-001"]
    test = parser.rows["test-001"]
    assert train["data-split"] == "train"
    assert "0.023" in str(train["data-search"])
    assert test["data-split"] == "test"
    assert "dataset.split === split.value" in html_text
    assert "dataset.search || ''" in html_text
    assert parser.labels["filter-split"] == "Sample split"
    assert 'for="filter-split"' in html_text
    assert "min-width: max-content" in html_text
    assert "overflow-x: auto" in html_text
    assert "white-space: nowrap" in html_text


def test_only_existing_passed_image_evidence_is_linked(tmp_path, monkeypatch):
    sample = _sample("solved-001", "baseline", "SOLVED")
    run_relative = "samples/solved-001/mesh-0/attempt-001/run"
    sample["jobs"][0]["attempts"] = [{"status": "SOLVED", "path": run_relative}]
    root, _, _ = _context(tmp_path, monkeypatch, samples=[sample])
    run_directory = root / run_relative
    run_directory.mkdir(parents=True)
    (run_directory / "deformation.png").write_bytes(b"fixture image bytes")
    (run_directory / "failed.png").write_bytes(b"fixture image bytes")
    _write_json(run_directory / "mechanical-artifacts.json", {
        "visual_review": [
            {"name": "deformation.png", "status": "PASS"},
            {"name": "missing.png", "status": "PASS"},
            {"name": "failed.png", "status": "FAIL"},
            {"name": "../../../../../outside.png", "status": "PASS"},
        ]
    })
    (tmp_path / "outside.png").write_bytes(b"outside fixture")

    result = report.generate_study_report(root)
    html_text = Path(result["html"]).read_text(encoding="utf-8")

    assert f'href="{run_relative}/deformation.png"' in html_text
    assert f'src="{run_relative}/deformation.png"' in html_text
    assert "missing.png" not in html_text
    assert "failed.png" not in html_text
    assert "outside.png" not in html_text


def test_repeated_report_generation_is_deterministic(tmp_path, monkeypatch):
    root, _, _ = _context(tmp_path, monkeypatch)

    first = report.generate_study_report(root)
    first_html = Path(first["html"]).read_bytes()
    first_markdown = Path(first["markdown"]).read_bytes()
    second = report.generate_study_report(root)

    assert first == second
    assert Path(second["html"]).read_bytes() == first_html
    assert Path(second["markdown"]).read_bytes() == first_markdown


@pytest.mark.parametrize("dimension,unit", [
    ("unknown_dimension", "mm"), ("length", "MPa"), ("length", "invalid_length_unit"),
])
def test_invalid_units_never_relabel_si_values_or_scatter_points(
    tmp_path, monkeypatch, dimension, unit
):
    root, study, manifest = _context(tmp_path, monkeypatch)
    study.targets["displacement"].dimension = dimension
    study.targets["displacement"].unit = unit
    _write_json(root / "datasets/data/dataset.json", _dataset(study))
    manifest["datasets"] = ["datasets/data/dataset.json"]
    manifest["models"] = [{"model_id": "model", "path": "models/model"}]
    _write_json(root / "models/model/evaluation.json", {
        "targets": {"displacement": {"points": [
            {"truth": 0.001, "prediction": 0.002, "std": 0.0001, "unit": "meter"},
        ]}},
    })

    result = report.generate_study_report(root)
    html_text = Path(result["html"]).read_text()
    parser = _ReportParser()
    parser.feed(html_text)
    assert "INVALID_UNIT" in parser.rows["baseline-001"]["cells"][-2]
    assert "INVALID_UNIT" in Path(result["markdown"]).read_text()
    assert f"0.001 {unit}" not in html_text
    assert "<svg" not in html_text


def test_cv_rmse_uses_display_units_in_html_and_markdown(tmp_path, monkeypatch):
    root, _, manifest = _context(tmp_path, monkeypatch)
    manifest["models"] = [{"model_id": "model", "path": "models/model"}]
    _write_json(root / "models/model/model-card.json", {
        "model_selection": {
            target: {"selected_model": "gpr", "cross_validation": {
                "selected_metrics": {"rmse": value},
            }} for target, value in (("displacement", 0.00025), ("stress", 2_500_000))
        },
    })
    result = report.generate_study_report(root)
    parser = _ReportParser()
    parser.feed(Path(result["html"]).read_text())
    metrics = {row[0]: row for row in parser.table_rows if len(row) == 10 and row[1] == "gpr"}
    assert metrics["displacement"][2] == "0.25 mm"
    assert metrics["stress"][2] == "2.5 MPa"
    assert metrics["stress"][6:8] == ["NOT_RUN", "NOT_RUN"]
    markdown = Path(result["markdown"]).read_text()
    assert "CV RMSE" in markdown and "0.25 mm" in markdown and "2.5 MPa" in markdown


def test_phase_timings_use_recorded_producer_fields(tmp_path, monkeypatch):
    root, _, manifest = _context(tmp_path, monkeypatch)
    for sample, seconds in zip(manifest["samples"], (2.0, 3.0, 0.0), strict=True):
        sample["geometry_seconds"] = seconds
    manifest["models"] = [
        {"model_id": "first", "path": "models/first", "training_seconds": 4.0},
        {"model_id": "second", "path": "models/second", "training_seconds": 6.0},
    ]
    _write_json(root / "models/first/evaluation.json", {"status": "FAIL", "evaluation_seconds": 0.75})
    manifest["rounds"] = [{"round": 0, "plan": "optimization/round-000/plan.json", "elapsed_seconds": 12.0}]
    _write_json(root / manifest["rounds"][0]["plan"], {"status": "PROPOSED", "search_seconds": 1.5, "candidates": []})
    manifest["phases"] = {"model_training": {"elapsed_seconds": 999, "calls": 99}}
    result = report.generate_study_report(root)
    parser = _ReportParser()
    parser.feed(Path(result["html"]).read_text())
    rows = {row[0]: row for row in parser.table_rows if row}
    expected = {
        "Geometry preparation": ("5 s", "3"),
        "Surrogate training": ("10 s", "2"),
        "Holdout evaluation": ("0.75 s", "1"),
        "Candidate search": ("1.5 s", "1"),
        "Optimization rounds": ("12 s", "1"),
    }
    markdown = Path(result["markdown"]).read_text()
    for phase, (duration, calls) in expected.items():
        assert rows[phase][1:] == ["RECORDED", duration, calls]
        assert f"| {phase} | RECORDED | {duration} | {calls} |" in markdown
    assert rows["Candidate verification"][1:] == ["NOT_RUN", "NOT_RUN", "NOT_RUN"]

    del manifest["models"][1]["training_seconds"]
    _write_json(root / "models/first/evaluation.json", {"status": "PASS"})
    parser = _ReportParser()
    parser.feed(Path(report.generate_study_report(root)["html"]).read_text())
    rows = {row[0]: row for row in parser.table_rows if row}
    assert rows["Surrogate training"][2:] == ["NOT_RUN", "2"]
    assert rows["Holdout evaluation"][2:] == ["NOT_RUN", "1"]


@pytest.mark.parametrize("verified,feasible,status", [
    (True, True, "VERIFIED"), (True, False, "INFEASIBLE"),
    (False, False, "REVIEW_REQUIRED"), (None, True, "REVIEW_REQUIRED"),
])
def test_confirmed_candidate_status_overrides_inherited_prediction_status(
    tmp_path, monkeypatch, verified, feasible, status
):
    root, _, manifest = _context(tmp_path, monkeypatch)
    proposed = {"candidate_id": "proposal", "status": "PREDICTED_CANDIDATE", "verified": False}
    manifest["rounds"] = [{"round": 0, "plan": "optimization/round-000/plan.json"}]
    _write_json(root / manifest["rounds"][0]["plan"], {"candidates": [proposed]})
    confirmed = {**proposed, "sample_id": "verification-001", "verified": verified, "feasible": feasible}
    _write_json(root / "verification.json", {"status": "REVIEW_REQUIRED", "candidates": [confirmed]})
    result = report.generate_study_report(root)
    parser = _ReportParser()
    parser.feed(Path(result["html"]).read_text())
    rows = {row[0]: row for row in parser.table_rows if row}
    assert rows["proposal"][-1] == "PREDICTED_CANDIDATE"
    assert rows["verification-001"][-1] == status
    if verified is not True:
        assert "constraint FAIL" not in rows["verification-001"][3]
    assert f"| verification-001 | {status} |" in Path(result["markdown"]).read_text()


@pytest.mark.parametrize("dataset_context", [False, True])
def test_engineering_context_uses_real_producer_without_machine_paths(tmp_path, monkeypatch, dataset_context):
    from ansys_skill.schema import SimulationSpec
    from ansys_skill.study.schema import StudySpec
    from ansys_skill.study.templates import example_simulation, example_study

    study = StudySpec.model_validate(example_study())
    document = example_simulation()
    document["inputs"]["geometry_file"] = "C:/private-machine-path/geometry.step"
    document["assumptions"][0]["text"] = 'Authored fixture <script>alert("context")</script>'
    base = SimulationSpec.model_validate(document)
    context = report.project.engineering_context(study, base)
    root, _, manifest = _context(tmp_path, monkeypatch, study=study)
    _write_json(root / "datasets/context/dataset.json", {
        "engineering_context": context if dataset_context else {"material_evidence": {"density": "STALE_DENSITY"}},
    })
    manifest["datasets"] = ["datasets/context/dataset.json"]
    monkeypatch.setattr(report.project, "load_project",
                        lambda _: (study, None if dataset_context else base, manifest))
    result = report.generate_study_report(root)
    html_text = Path(result["html"]).read_text()
    markdown = Path(result["markdown"]).read_text()
    for output in (html_text, markdown):
        for value in ("Structural Steel", "7850 kg/m^3", "1000 N", "0.8 MPa", "fixed_support",
                      "mounting_face", "14 mm", "24 mm", "0.025 mm", "10 MPa", "quadratic",
                      "linear_static_structural", "Acceptance source", "small-deformation"):
            assert value in output
        assert "private-machine-path" not in output
        assert "STALE_DENSITY" not in output
        assert '<script>alert("context")</script>' not in output
        assert "&lt;script&gt;" in output
    parser = _ReportParser()
    parser.feed(html_text)
    assert ["Density", "7850 kg/m^3"] in parser.table_rows
    assert ["plate_thickness", "14 mm", "24 mm", "20 mm"] in parser.table_rows


def test_missing_base_context_is_explicitly_not_run(tmp_path, monkeypatch):
    root, _, _ = _context(tmp_path, monkeypatch)
    result = report.generate_study_report(root)
    parser = _ReportParser()
    parser.feed(Path(result["html"]).read_text())
    assert ["Material", "NOT_RUN"] in parser.table_rows
    assert ["Density", "NOT_RUN"] in parser.table_rows
    assert ["Mesh sizes", "NOT_RUN"] in parser.table_rows
    assert ["plate_thickness", "NOT_RUN", "NOT_RUN", "20 mm"] in parser.table_rows
    assert ["displacement", "total_deformation", "NOT_RUN", "NOT_RUN", "NOT_RUN"] in parser.table_rows
    assert "| Density | NOT_RUN |" in Path(result["markdown"]).read_text()


def test_comparison_renders_measured_best_margins_and_full_cost_contract(tmp_path, monkeypatch):
    from ansys_skill.study import comparison
    from ansys_skill.study.schema import StudySpec
    from ansys_skill.study.templates import example_study

    root, _, _ = _context(tmp_path, monkeypatch)
    study = StudySpec.model_validate(example_study())
    best = {"sample_id": "direct-observed", "mass_kg": 2.0,
            "targets": {"displacement": 1.2e-5, "stress": 9e6},
            "feasibility": {target: "FEASIBLE" for target in study.targets}}
    attempts = {split: [{"status": "FAILED" if index < failed else "SOLVED", "elapsed_seconds": seconds / calls}
                       for index in range(calls)]
             for split, calls, seconds, failed in (("baseline", 3, 6, 0), ("train", 5, 10, 1),
                 ("test", 3, 6, 0), ("verification", 2, 4, 0), ("comparison", 4, 12, 2))}
    costs = {split: comparison._cost_summary(records) for split, records in attempts.items()}
    margins = comparison._target_margins(best, study)
    _write_json(root / "comparison.json", {
        "status": "PASS", "execution_status": "SOLVED", "allowance_equal": True,
        "direct_best": best,
        "surrogate_best": {**best, "sample_id": "training-observed", "mass_kg": 1.5},
        "best_observed_training": {**best, "sample_id": "training-observed", "mass_kg": 1.5},
        "verified_candidate": None,
        "recommendation_status": "OBSERVED_TRAINING_NOT_INDEPENDENTLY_VERIFIED",
        "mass_improvement_vs_direct": 0.25,
        "target_margins": {"baseline": margins, "direct_best": margins, "surrogate_best": margins},
        "direct_search_allowance": 7, "shared_solver_calls": 6,
        "surrogate_total_solver_calls": 13, "direct_total_solver_calls": 10,
        "solver_costs_by_split": costs,
        "solver_costs_total": comparison._cost_summary([attempt for records in attempts.values() for attempt in records]),
        "solver_command_seconds": {split: row["seconds"] for split, row in costs.items()},
        "training_seconds": 2, "study_elapsed_seconds": 45.75,
        "geometry_seconds_per_sample": comparison._geometry_costs({"samples": [
            {"split": "train", "geometry_seconds": 2}, {"split": "train", "geometry_seconds": 3}]}),
        "phase_timings": {"evaluation": {"status": "RECORDED", "elapsed_seconds": 0.5, "calls": 1}},
        "round_search_seconds": [{"round": 0, "purpose": "adaptive", "round_status": "SOLVED", "status": "RECORDED", "search_seconds": 0.25}],
    })
    result = report.generate_study_report(root)
    parser = _ReportParser()
    parser.feed(Path(result["html"]).read_text())
    rows = parser.table_rows
    assert ["Direct search best", "direct-observed", "2 kg", "0.012 mm", "9 MPa"] in rows
    assert ["Observed training best", "training-observed", "1.5 kg", "0.012 mm", "9 MPa"] in rows
    assert ["Independently verified candidate", "NOT_RUN", "NOT_RUN", "NOT_RUN", "NOT_RUN"] in rows
    assert ["Baseline", "displacement", "0.012 mm", "0.025 mm", "0.013 mm", "RECORDED", "FEASIBLE"] in rows
    assert ["Mass reduction relative to direct search", "25%"] in rows
    assert ["Shared baseline and holdout solver calls", "6"] in rows
    assert ["Direct search allowance", "7"] in rows
    assert ["Surrogate total solver calls (including shared)", "13"] in rows
    assert ["comparison", "4", "12 s", "12 s", "4", "0", "2", "0", "RECORDED"] in rows
    assert ["All recorded attempts", "17", "38 s", "38 s", "17", "0", "3", "0", "RECORDED"] in rows
    assert ["train", "2", "2", "0", "5 s", "2.5 s", "RECORDED"] in rows
    assert ["evaluation", "0.5 s", "1", "RECORDED"] in rows
    assert ["0", "adaptive", "SOLVED", "0.25 s", "RECORDED"] in rows
    assert ["Model training", "2 s"] in rows
    assert ["Study active elapsed time", "45.75 s"] in rows
    markdown = Path(result["markdown"]).read_text()
    for value in ("OBSERVED_TRAINING_NOT_INDEPENDENTLY_VERIFIED", "1.5 kg", "0.013 mm", "25%",
                  "| All recorded attempts | 17 | 38 s | 38 s | 17 | 0 | 3 | 0 | RECORDED |",
                  "| evaluation | 0.5 s | 1 | RECORDED |"):
        assert value in markdown


def test_partial_comparison_costs_preserve_missing_timings_from_producer(tmp_path, monkeypatch):
    from ansys_skill.study import comparison

    root, _, manifest = _context(tmp_path, monkeypatch)
    attempts = [{"status": "FAILED", "elapsed_seconds": 3.0,
                 "phase_timings": {"backend_total": {"status": "RECORDED", "elapsed_seconds": 2.5},
                                   "mesh": {"status": "RECORDED", "elapsed_seconds": 0.5},
                                   "solve": {"status": "RECORDED", "elapsed_seconds": 2.0}}},
                {"status": "INTERRUPTED", "elapsed_seconds": None}]
    samples = [{"split": "train", "geometry_seconds": 4, "jobs": [{"attempts": attempts}]},
               {"split": "train", "jobs": []}]
    evidence = {"samples": samples, "rounds": [{"round": 1, "purpose": "adaptive", "status": "PARTIAL",
                                               "plan": "optimization/round-001/plan.json"}]}
    _write_json(root / "optimization/round-001/plan.json", {"search_seconds": 0.125})
    _write_json(root / "comparison.json", {
        "status": "NOT_RUN", "solver_costs_by_split": {"train": comparison._cost_summary(attempts)},
        "solver_costs_total": comparison._cost_summary(attempts),
        "geometry_seconds_per_sample": comparison._geometry_costs(evidence),
        "phase_timings_by_split": comparison._phase_costs(evidence),
        "round_search_seconds": comparison._round_search_costs(root, evidence),
    })
    manifest["rounds"] = evidence["rounds"]
    result = report.generate_study_report(root)
    parser = _ReportParser()
    parser.feed(Path(result["html"]).read_text())
    assert ["train", "2", "NOT_RUN", "3 s", "1", "1", "2", "0", "PARTIAL"] in parser.table_rows
    assert ["train", "2", "1", "1", "4 s", "4 s", "PARTIAL"] in parser.table_rows
    assert ["train", "backend_total", "2.5 s", "1", "1", "PARTIAL"] in parser.table_rows
    assert ["train", "postprocessing", "NOT_RUN", "0", "2", "NOT_RUN"] in parser.table_rows
    assert ["1", "adaptive", "PARTIAL", "0.125 s", "RECORDED"] in parser.table_rows
    markdown = Path(result["markdown"]).read_text()
    assert "| train | 2 | NOT_RUN | 3 s | 1 | 1 | 2 | 0 | PARTIAL |" in markdown
    assert "backend_total includes mesh and solve" in markdown


def test_error_slices_and_classification_follow_model_producer(tmp_path, monkeypatch):
    from ansys_skill.surrogate.models import _constraint_classification, _evaluation_slices

    root, _, manifest = _context(tmp_path, monkeypatch)
    metadata = {"limit": 0.002, "absolute_tolerance": 0.0001, "relative_tolerance": 0.0, "reference_scale": 0.002}
    samples = [{"sample_id": name, "parameters": {"plate_thickness": parameter},
                "truth": truth, "prediction": prediction, "error_tolerance": 0.0001, "false_safe": false_safe}
               for name, parameter, truth, prediction, false_safe in (
                   ("heldout-boundary", 0.011, 0.00205, 0.00195, True),
                   ("heldout-interior", 0.02, 0.001, 0.0012, False),
                   ("heldout-near", 0.02, 0.00195, 0.0021, False))]
    slices = _evaluation_slices(samples, ["plate_thickness"], {"plate_thickness": [0.01, 0.03]}, metadata)
    classification = _constraint_classification(samples, metadata)
    manifest["models"] = [{"model_id": "slice-model", "path": "models/slice-model"}]
    _write_json(root / "models/slice-model/evaluation.json", {"status": "FAIL", "targets": {
        "displacement": {"status": "FAIL", "error_slices": slices, "constraint_classification": classification}}})
    result = report.generate_study_report(root)
    parser = _ReportParser()
    parser.feed(Path(result["html"]).read_text())
    assert ["displacement", "Design space boundary", "EVALUATED", "1", "0.1 mm", "0.1 mm", "0.1 mm", "1"] in parser.table_rows
    assert ["displacement", "Near constraint", "EVALUATED", "2", "0.125 mm", "0.127475 mm", "0.15 mm", "1"] in parser.table_rows
    assert ["displacement", "EVALUATED", "2 mm", "3", "1", "1", "1", "0", "1", "1", "NOT_RUN"] in parser.table_rows
    selection = next(row for row in parser.table_rows if len(row) == 5 and row[:2] == ["displacement", "Design space boundary"])
    assert "threshold_fraction: 0.1" in selection[2]
    assert selection[3] == "heldout-boundary"
    markdown = Path(result["markdown"]).read_text()
    assert "| displacement | Near constraint | EVALUATED | 2 | 0.125 mm | 0.127475 mm | 0.15 mm | 1 |" in markdown
    assert "heldout-boundary; heldout-near" in markdown


@pytest.mark.parametrize("limit", [None, 0.002])
def test_unevaluated_slices_and_classification_never_fill_unknowns_with_zero(tmp_path, monkeypatch, limit):
    from ansys_skill.surrogate.models import _constraint_classification, _evaluation_slices

    root, _, manifest = _context(tmp_path, monkeypatch)
    metadata = {"limit": limit, "absolute_tolerance": 0.0001, "relative_tolerance": 0.0, "reference_scale": 0.002}
    slices = _evaluation_slices([], ["plate_thickness"], {"plate_thickness": [0.01, 0.03]}, metadata)
    classification = _constraint_classification([], metadata)
    manifest["models"] = [{"model_id": "empty-slices", "path": "models/empty-slices"}]
    _write_json(root / "models/empty-slices/evaluation.json", {"targets": {"displacement": {
        "error_slices": slices, "constraint_classification": classification}}})
    result = report.generate_study_report(root)
    parser = _ReportParser()
    parser.feed(Path(result["html"]).read_text())
    assert ["displacement", "Near constraint", "NOT_RUN", "0", "NOT_RUN", "NOT_RUN", "NOT_RUN", "NOT_RUN"] in parser.table_rows
    row = next(row for row in parser.table_rows if len(row) == 11 and row[0] == "displacement")
    assert row[1:4] == ["NOT_RUN", "NOT_RUN" if limit is None else "2 mm", "0"]
    assert row[4:10] == ["NOT_RUN"] * 6
    assert row[10] == ("target_limit_not_declared" if limit is None else "no_eligible_test_samples")
    assert "| displacement | Near constraint | NOT_RUN | 0 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |" in Path(result["markdown"]).read_text()


@pytest.mark.parametrize("changed", ["ledger", "dataset", "model", "verification", "comparison"])
def test_recorded_overall_uses_bound_workflow_status_and_rejects_stale_results(tmp_path, monkeypatch, changed):
    from ansys_skill.study import workflow

    root, study, manifest = _context(tmp_path, monkeypatch)
    paths = {"dataset": "datasets/current/dataset.json", "model": "models/current/model-card.json",
             "verification": "verification.json", "comparison": "comparison.json"}
    for path in paths.values():
        _write_json(root / path, {})
    manifest["datasets"] = [paths["dataset"]]
    manifest["models"] = [{"model_id": "current", "path": "models/current"}]
    monkeypatch.setattr(workflow, "load_project", lambda _: (study, None, manifest))
    outcome = workflow._finish(root, {"status": "REVIEW_REQUIRED", "engineering_validation": "PASS"})
    bound = outcome["report"]
    assert "Recorded overall verification status: <strong>REVIEW_REQUIRED</strong>" in Path(bound["html"]).read_text()
    assert "- Recorded overall verification status: REVIEW_REQUIRED" in Path(bound["markdown"]).read_text()

    if changed == "ledger":
        manifest["samples"][0]["jobs"][0]["attempts"].append({"status": "FAILED"})
        manifest["solver_calls"] += 1
    else:
        _write_json(root / paths[changed], {"changed_evidence": True})
    stale = report.generate_study_report(root)
    assert "Recorded overall verification status: <strong>NOT_RUN</strong>" in Path(stale["html"]).read_text()
    assert "- Recorded overall verification status: NOT_RUN" in Path(stale["markdown"]).read_text()


def test_legacy_unbound_workflow_pass_is_not_trusted(tmp_path, monkeypatch):
    root, _, _ = _context(tmp_path, monkeypatch)
    _write_json(root / "workflow-result.json", {"status": "PASS", "engineering_validation": "PASS"})
    result = report.generate_study_report(root)
    assert "Recorded overall verification status: <strong>NOT_RUN</strong>" in Path(result["html"]).read_text()
