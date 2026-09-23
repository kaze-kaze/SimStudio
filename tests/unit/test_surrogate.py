from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest
from ansys_skill.errors import EnvironmentUnavailableError
from ansys_skill.surrogate import (
    SurrogateValidationError,
    evaluate_model,
    load_model,
    models,
    predict_model,
    train_model,
)
from ansys_skill.surrogate.metrics import regression_metrics


def analytic_dataset() -> dict:
    rows = []
    for index in range(16):
        x = index / 15
        rows.append(
            {
                "sample_id": f"train-{index:02d}",
                "design_id": f"train-design-{index:02d}",
                "split": "train",
                "parameters": {"x": x},
                "targets": {"deflection": 2.0 + 3.0 * x + 4.0 * x * x},
                "accepted_targets": ["deflection"],
                "source": {"synthetic": True, "kind": "analytic_test"},
            }
        )
    for index, x in enumerate((0.13, 0.39, 0.71, 0.91)):
        rows.append(
            {
                "sample_id": f"test-{index:02d}",
                "design_id": f"test-design-{index:02d}",
                "split": "test",
                "parameters": {"x": x},
                "targets": {"deflection": 2.0 + 3.0 * x + 4.0 * x * x},
                "accepted_targets": ["deflection"],
                "source": {"synthetic": True, "kind": "analytic_test"},
            }
        )
    return {
        "schema_version": "1.0",
        "dataset_id": "analytic-fixture-v1",
        "study_fingerprint": "study-fixture-v1",
        "evidence_kind": "analytic_test",
        "feature_names": ["x"],
        "feature_units": {"x": "meter"},
        "bounds": {"x": [0.0, 1.0]},
        "frozen_test_designs": [f"test-design-{index:02d}" for index in range(4)],
        "targets": {
            "deflection": {
                "unit": "meter",
                "dimension": "length",
                "absolute_tolerance": 1e-5,
                "relative_tolerance": 1e-5,
                "reference_scale": 1.0,
                "limit": 8.0,
            }
        },
        "rows": rows,
    }


def train_analytic(
    tmp_path: Path, dataset: dict | None = None, options: dict | None = None
) -> tuple[dict, Path]:
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    output = tmp_path / "model"
    source = dataset or analytic_dataset()
    result = models._train_analytic_test_model(source, output, options)
    return result, output


def test_public_training_rejects_analytic_fixtures(tmp_path):
    with pytest.raises(SurrogateValidationError, match="requires evidence_kind='solver'"):
        train_model(analytic_dataset(), tmp_path / "model")
    assert not (tmp_path / "model").exists()


@pytest.mark.parametrize("missing_dependency", ["numpy", "scipy"])
def test_missing_numerical_dependency_raises_environment_unavailable(
    monkeypatch, missing_dependency
):
    if missing_dependency == "scipy":
        pytest.importorskip("numpy")
    real_import = __import__

    def without_dependency(name, *args, **kwargs):
        if name == missing_dependency:
            raise ImportError(f"{missing_dependency} unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", without_dependency)
    operation = models._numpy if missing_dependency == "numpy" else models._runtime_versions
    with pytest.raises(EnvironmentUnavailableError) as caught:
        operation()
    assert caught.value.exit_code == 3




def test_quadratic_response_surface_fits_known_response_and_records_grouped_cv(tmp_path):
    result, directory = train_analytic(tmp_path)
    assert result["status"] == "TRAINED"
    assert result["model_directory"] == str(directory)
    model = load_model(directory)
    target = model["target_models"]["deflection"]
    assert target["cv"]["folds"] == 4
    assert target["cv"]["group_count"] == 16
    assert len(target["cv"]["candidates"]) == 18
    fold_designs = [
        design_id
        for fold in target["cv"]["candidates"][0]["folds"]
        for design_id in fold["validation_design_ids"]
    ]
    assert sorted(fold_designs) == sorted(f"train-design-{i:02d}" for i in range(16))
    card = json.loads((directory / "model-card.json").read_text(encoding="utf-8"))
    assert load_model(directory)["schema_version"] == "1.1"
    assert load_model(directory)["frozen_test_designs"] == [
        f"test-design-{index:02d}" for index in range(4)
    ]
    assert card["evidence_kind"] == "analytic_test"
    assert "not engineering evidence" in card["evidence_label"]
    assert card["model_selection"]["deflection"]["cross_validation"]["selected_metrics"]["rmse"] < 1e-5
    assert card["options"] == {
        "seed": 42,
        "cv_folds": 4,
        "max_normalized_distance": 0.4,
        "max_relative_std": 0.15,
    }
    assert card["training_algorithm_version"] == models.TRAINING_ALGORITHM_VERSION
    assert set(card["numeric_runtime"]) == {"python", "numpy", "scipy"}
    assert all(card["numeric_runtime"].values())


def test_test_split_changes_do_not_change_model_or_training_hash(tmp_path):
    original = analytic_dataset()
    changed = copy.deepcopy(original)
    changed["dataset_id"] = "different-dataset-id"
    for row in changed["rows"]:
        if row["split"] == "test":
            row["targets"]["deflection"] += 100.0
    first, first_dir = train_analytic(tmp_path / "first", original)
    second, second_dir = train_analytic(tmp_path / "second", changed)
    first_model = load_model(first_dir)
    second_model = load_model(second_dir)
    assert first["model_id"] == second["model_id"]
    assert first_model["training_data_hash"] == second_model["training_data_hash"]
    assert first_model["target_models"] == second_model["target_models"]

    different_frozen_ids = copy.deepcopy(original)
    different_frozen_ids["frozen_test_designs"] = ["alternate-test-design"]
    different_frozen_ids["rows"] = [row for row in different_frozen_ids["rows"] if row["split"] == "train"]
    _, third_dir = train_analytic(tmp_path / "third", different_frozen_ids)
    third_model = load_model(third_dir)
    assert first_model["training_data_hash"] == third_model["training_data_hash"]
    assert first_model["model_id"] != third_model["model_id"]


def test_evaluation_rejects_changed_frozen_test_design_ids(tmp_path):
    dataset = analytic_dataset()
    _, directory = train_analytic(tmp_path, dataset)
    changed = copy.deepcopy(dataset)
    changed["frozen_test_designs"] = ["replacement-design"]

    with pytest.raises(SurrogateValidationError, match="frozen_test_designs"):
        models._evaluate_analytic_test_model(directory, changed)


def test_dataset_rejects_frozen_test_design_in_non_test_split():
    dataset = analytic_dataset()
    dataset["rows"][0]["design_id"] = dataset["frozen_test_designs"][0]

    with pytest.raises(SurrogateValidationError, match="frozen for test"):
        models._validate_dataset(dataset)


def test_evaluation_rejects_extra_unplanned_test_rows(tmp_path):
    dataset = analytic_dataset()
    _, directory = train_analytic(tmp_path, dataset)
    extra = copy.deepcopy(dataset["rows"][-1])
    extra.update(sample_id="unplanned-test", design_id="unplanned-design")
    dataset["rows"].append(extra)
    with pytest.raises(SurrogateValidationError, match="not declared in frozen_test_designs"):
        models._evaluate_analytic_test_model(directory, dataset)


def test_model_json_round_trip_preserves_predictions(tmp_path):
    _, directory = train_analytic(tmp_path)
    model = load_model(directory)
    np = models._numpy()
    target = model["target_models"]["deflection"]
    query = models._normalize_row(np, {"x": 0.47}, ["x"], {"x": [0.0, 1.0]}).reshape(1, -1)
    value_before, std_before = models._predict_numeric_model(np, target, query)
    restored = load_model(directory / ".")
    value_after, std_after = models._predict_numeric_model(
        np, restored["target_models"]["deflection"], query
    )
    assert value_after[0] == pytest.approx(value_before[0], rel=1e-12, abs=1e-12)
    assert std_after[0] == pytest.approx(std_before[0], rel=1e-12, abs=1e-12)
    serialized = (directory / "model.json").read_text(encoding="utf-8")
    assert "pickle" not in serialized.lower()
    assert "cholesky_lower" in serialized or "coefficients" in serialized


def test_gpr_safe_artifact_round_trip_and_empirical_interval_report(tmp_path):
    dataset = analytic_dataset()
    for row in dataset["rows"]:
        x = row["parameters"]["x"]
        row["targets"]["deflection"] = 2.0 + math.sin(4.0 * math.pi * x)
    _, directory = train_analytic(tmp_path, dataset)
    model = load_model(directory)
    target = model["target_models"]["deflection"]
    assert target["family"] == "gpr"
    assert target["kernel"] in {"rbf", "matern32", "matern52"}

    np = models._numpy()
    query = models._normalize_row(np, {"x": 0.43}, ["x"], {"x": [0.0, 1.0]}).reshape(1, -1)
    value_before, std_before = models._predict_numeric_model(np, target, query)
    restored = load_model(directory)
    value_after, std_after = models._predict_numeric_model(
        np, restored["target_models"]["deflection"], query
    )
    assert value_after[0] == pytest.approx(value_before[0], rel=1e-12, abs=1e-12)
    assert std_after[0] == pytest.approx(std_before[0], rel=1e-12, abs=1e-12)

    evaluation = models._evaluate_analytic_test_model(directory, dataset)
    interval = evaluation["targets"]["deflection"]["interval_coverage"]
    assert interval["sample_count"] == 4
    assert 0.0 <= interval["empirical_coverage"] <= 1.0
    assert interval["confidence_probability_guaranteed"] is False


def test_dataset_validation_rejects_cross_split_design_leakage(tmp_path):
    dataset = analytic_dataset()
    dataset["rows"][-1]["design_id"] = dataset["rows"][0]["design_id"]
    with pytest.raises(SurrogateValidationError, match="multiple splits"):
        models._train_analytic_test_model(dataset, tmp_path / "model")


def test_dataset_validation_checks_unselected_rows_before_fit(tmp_path):
    dataset = analytic_dataset()
    dataset["rows"][-1]["parameters"]["x"] = math.nan
    with pytest.raises(SurrogateValidationError, match="must be finite"):
        models._train_analytic_test_model(dataset, tmp_path / "model")


def test_training_uses_only_accepted_finite_training_rows_for_each_target(tmp_path):
    dataset = analytic_dataset()
    dataset["rows"][0]["accepted_targets"] = []
    dataset["rows"][1]["targets"]["deflection"] = None
    dataset["rows"][2]["split"] = "baseline"
    dataset["rows"][2]["design_id"] = "baseline-design"
    _, directory = train_analytic(tmp_path, dataset)
    target = load_model(directory)["target_models"]["deflection"]
    assert target["training_sample_ids"] == [
        f"train-{index:02d}" for index in range(3, 16)
    ]


def test_prediction_domain_and_uncertainty_keep_needs_solve_values(tmp_path):
    _, directory = train_analytic(tmp_path)
    model = load_model(directory)
    inside = models._predict_model_document(model, {"x": 0.5})
    assert inside["status"] == "PREDICTED"
    assert inside["evidence_kind"] == "analytic_test"
    assert inside["predictions"]["deflection"]["value"] == pytest.approx(4.5, abs=1e-4)
    assert inside["domain"]["inside_bounds"] is True

    outside = models._predict_model_document(model, {"x": 1.2})
    assert outside["status"] == "NEEDS_SOLVE"
    assert outside["predictions"]["deflection"]["value"] == pytest.approx(11.36, abs=0.1)
    assert "outside_bounds" in outside["domain"]["reasons"]

    conservative_result, conservative_dir = train_analytic(
        tmp_path / "conservative", options={"max_normalized_distance": 0.01}
    )
    assert conservative_result["status"] == "TRAINED"
    conservative_model = load_model(conservative_dir)
    sparse_support = models._predict_model_document(conservative_model, {"x": 0.5})
    assert sparse_support["status"] == "NEEDS_SOLVE"
    assert sparse_support["predictions"]["deflection"]["value"] == pytest.approx(4.5, abs=1e-4)
    assert "outside_sampling_coverage" in sparse_support["domain"]["reasons"]


def test_prediction_rejects_missing_or_nonfinite_parameters(tmp_path):
    _, directory = train_analytic(tmp_path)
    model = load_model(directory)
    with pytest.raises(SurrogateValidationError, match="every model feature"):
        models._predict_model_document(model, {})
    with pytest.raises(SurrogateValidationError, match="must be finite"):
        models._predict_model_document(model, {"x": math.inf})


def test_prediction_is_independent_of_parameter_mapping_key_order(tmp_path):
    dataset = analytic_dataset()
    dataset["feature_names"] = ["x", "z"]
    dataset["feature_units"]["z"] = "meter"
    dataset["bounds"]["z"] = [0.0, 1.0]
    for index, row in enumerate(dataset["rows"]):
        row["parameters"]["z"] = (index * 7 % 16) / 15
    _, directory = train_analytic(tmp_path, dataset)
    model = load_model(directory)
    x_first = models._predict_model_document(model, {"x": 0.5, "z": 0.4})
    z_first = models._predict_model_document(model, {"z": 0.4, "x": 0.5})
    assert x_first["predictions"] == z_first["predictions"]
    assert x_first["domain"] == z_first["domain"]


def test_model_loader_rejects_tampered_json(tmp_path):
    _, directory = train_analytic(tmp_path)
    path = directory / "model.json"
    model = json.loads(path.read_text(encoding="utf-8"))
    model["target_models"]["deflection"]["y_center"] += 1.0
    path.write_text(json.dumps(model), encoding="utf-8")
    with pytest.raises(SurrogateValidationError, match="model_id does not match"):
        load_model(directory)


def test_metrics_report_error_scales_and_undefined_r2():
    metrics = regression_metrics([2.0, 2.0], [1.0, 3.0], 2.0)
    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["rmse"] == pytest.approx(1.0)
    assert metrics["max_absolute_error"] == pytest.approx(1.0)
    assert metrics["normalized_error"] == pytest.approx(0.5)
    assert metrics["r2"] is None


def test_evaluation_and_prediction_reject_non_solver_model(tmp_path):
    _, directory = train_analytic(tmp_path)
    with pytest.raises(SurrogateValidationError, match="requires a solver-trained model"):
        predict_model(directory, {"x": 0.5})
    with pytest.raises(SurrogateValidationError, match="requires evidence_kind='solver'"):
        evaluate_model(directory, analytic_dataset())


def test_evaluation_consumes_only_test_rows_and_reports_target_quality(tmp_path):
    dataset = analytic_dataset()
    _, directory = train_analytic(tmp_path, dataset)
    result = models._evaluate_analytic_test_model(directory, dataset)
    target = result["targets"]["deflection"]
    assert result["status"] == "PASS"
    assert result["sample_count"] == 4
    assert target["status"] == "PASS"
    assert target["metrics"]["rmse"] < 1e-5
    assert target["tolerance_failures"] == 0
    assert result["test_only"] is True
    assert len(target["points"]) == 4
    assert set(target["points"][0]) == {
        "sample_id", "design_id", "truth", "prediction", "std", "unit"
    }
    boundary = target["error_slices"]["design_space_boundary"]
    assert boundary["status"] == "EVALUATED"
    assert boundary["sample_ids"] == ["test-03"]
    assert boundary["sample_count"] == 1
    assert boundary["selection"]["threshold_fraction"] == 0.1
    assert boundary["metrics"]["mae"] < 1e-5
    assert boundary["metrics"]["rmse"] < 1e-5
    assert boundary["metrics"]["max_absolute_error"] < 1e-5
    assert boundary["false_safe_count"] == 0

    changed_test = copy.deepcopy(dataset)
    for row in changed_test["rows"]:
        if row["split"] == "test":
            row["targets"]["deflection"] += 2.0
    failed = models._evaluate_analytic_test_model(directory, changed_test)
    assert failed["status"] == "FAIL"
    assert failed["targets"]["deflection"]["metrics"]["rmse"] > 1.0


def test_evaluation_returns_not_run_when_no_test_targets_are_accepted(tmp_path):
    dataset = analytic_dataset()
    dataset["rows"][-1]["accepted_targets"] = []
    _, directory = train_analytic(tmp_path, dataset)
    result = models._evaluate_analytic_test_model(directory, dataset)
    assert result["status"] == "NOT_RUN"
    assert result["targets"]["deflection"]["status"] == "NOT_RUN"
    assert result["sample_count"] == 3
    target = result["targets"]["deflection"]
    assert target["expected_design_count"] == 4
    assert target["evaluated_design_count"] == 3
    assert target["missing_design_ids"] == ["test-design-03"]
    assert target["ineligible_designs"]["test-design-03"] == ["target_not_accepted"]
    assert len(target["points"]) == 3


def test_evaluation_allows_test_quality_backfill_with_frozen_design_ids(tmp_path):
    incomplete = analytic_dataset()
    incomplete["rows"][-1]["accepted_targets"] = []
    incomplete["rows"][-1]["targets"]["deflection"] = None
    _, directory = train_analytic(tmp_path, incomplete)

    completed = copy.deepcopy(incomplete)
    completed["rows"][-1]["accepted_targets"] = ["deflection"]
    completed["rows"][-1]["targets"]["deflection"] = 2.0 + 3.0 * 0.91 + 4.0 * 0.91**2
    result = models._evaluate_analytic_test_model(directory, completed)

    assert result["status"] == "PASS"
    assert result["sample_count"] == 4


def test_evaluation_requires_every_frozen_test_design_row(tmp_path):
    dataset = analytic_dataset()
    dataset["frozen_test_designs"].append("frozen-design-not-in-dataset")
    _, directory = train_analytic(tmp_path, dataset)
    result = models._evaluate_analytic_test_model(directory, dataset)
    target = result["targets"]["deflection"]
    assert result["status"] == "NOT_RUN"
    assert target["status"] == "NOT_RUN"
    assert target["expected_design_count"] == 5
    assert target["missing_design_ids"] == ["frozen-design-not-in-dataset"]


def test_evaluation_reports_constraint_near_slice_using_declared_error_tolerance(tmp_path):
    dataset = analytic_dataset()
    dataset["targets"]["deflection"]["limit"] = 2.0 + 3.0 * 0.39 + 4.0 * 0.39**2
    _, directory = train_analytic(tmp_path, dataset)

    result = models._evaluate_analytic_test_model(directory, dataset)
    target = result["targets"]["deflection"]
    constraint = target["error_slices"]["constraint_near"]

    assert constraint["status"] == "EVALUATED"
    assert constraint["sample_ids"] == ["test-01"]
    assert constraint["sample_count"] == 1
    assert constraint["selection"]["criterion"] == "abs(truth - limit) <= error_tolerance"
    assert constraint["selection"]["error_tolerance"] == (
        "absolute_tolerance + relative_tolerance * max(abs(truth), reference_scale)"
    )
    assert constraint["metrics"]["mae"] < 1e-5
    assert constraint["metrics"]["rmse"] < 1e-5
    assert constraint["metrics"]["max_absolute_error"] < 1e-5
    assert constraint["false_safe_count"] == 0
    assert result["status"] == "PASS"


def test_false_safe_fails_even_when_prediction_error_is_inside_tolerance(tmp_path, monkeypatch):
    dataset = analytic_dataset()
    dataset["targets"]["deflection"]["limit"] = 4.5
    dataset["targets"]["deflection"]["absolute_tolerance"] = 0.01
    sample = next(row for row in dataset["rows"] if row["sample_id"] == "test-00")
    sample["parameters"]["x"] = 0.5
    sample["targets"]["deflection"] = 4.500001
    _, directory = train_analytic(tmp_path, dataset)

    def near_limit_prediction(np, model, values):
        x = float(values[0, 0])
        if abs(x - 0.5) < 1e-12:
            return np.asarray([4.5 - 5e-7]), np.asarray([0.01])
        return np.asarray([2.0 + 3.0 * x + 4.0 * x * x]), np.asarray([0.01])

    monkeypatch.setattr(models, "_predict_numeric_model", near_limit_prediction)
    result = models._evaluate_analytic_test_model(directory, dataset)
    target = result["targets"]["deflection"]
    point = next(item for item in target["points"] if item["sample_id"] == "test-00")
    assert abs(point["prediction"] - point["truth"]) < 0.01
    assert target["tolerance_failures"] == 0
    assert target["false_safe_count"] == 1
    classification = target["constraint_classification"]
    assert classification["false_safe_count"] == 1
    assert classification["false_unsafe_count"] == 0
    assert classification["sample_ids"] == ["test-00", "test-01", "test-02", "test-03"]
    assert classification["confusion_matrix"] == {
        "true_feasible_predicted_feasible": 1,
        "true_feasible_predicted_infeasible": 0,
        "true_infeasible_predicted_feasible": 1,
        "true_infeasible_predicted_infeasible": 2,
    }
    constraint = target["error_slices"]["constraint_near"]
    assert constraint["sample_ids"] == ["test-00"]
    assert constraint["false_safe_count"] == 1
    assert target["status"] == "FAIL"
    assert result["status"] == "FAIL"


def test_constraint_classification_reports_false_unsafe_without_changing_gate(
    tmp_path, monkeypatch
):
    dataset = analytic_dataset()
    metadata = dataset["targets"]["deflection"]
    metadata["limit"] = 5.0
    metadata["absolute_tolerance"] = 10.0
    metadata["relative_tolerance"] = 0.0
    _, directory = train_analytic(tmp_path, dataset)

    predicted_values = {0.13: 4.0, 0.39: 6.0, 0.71: 6.0, 0.91: 8.1}

    def prediction_with_one_false_unsafe(np, model, values):
        x = float(values[0, 0])
        estimate = next(value for location, value in predicted_values.items() if abs(x - location) < 1e-12)
        return np.asarray([estimate]), np.asarray([0.01])

    monkeypatch.setattr(models, "_predict_numeric_model", prediction_with_one_false_unsafe)
    result = models._evaluate_analytic_test_model(directory, dataset)
    target = result["targets"]["deflection"]
    classification = target["constraint_classification"]

    assert classification["status"] == "EVALUATED"
    assert classification["sample_count"] == 4
    assert classification["sample_ids"] == ["test-00", "test-01", "test-02", "test-03"]
    assert classification["confusion_matrix"] == {
        "true_feasible_predicted_feasible": 1,
        "true_feasible_predicted_infeasible": 1,
        "true_infeasible_predicted_feasible": 0,
        "true_infeasible_predicted_infeasible": 2,
    }
    assert classification["false_safe_count"] == 0
    assert classification["false_unsafe_count"] == 1
    assert target["status"] == "PASS"
    assert result["status"] == "PASS"


def test_evaluation_marks_empty_slices_not_run_without_metrics(tmp_path):
    dataset = analytic_dataset()
    test_parameters = (0.25, 0.39, 0.55, 0.70)
    test_rows = [row for row in dataset["rows"] if row["split"] == "test"]
    for row, x in zip(test_rows, test_parameters, strict=True):
        row["parameters"]["x"] = x
        row["targets"]["deflection"] = 2.0 + 3.0 * x + 4.0 * x * x
    dataset["targets"]["deflection"]["limit"] = 100.0
    _, directory = train_analytic(tmp_path, dataset)

    result = models._evaluate_analytic_test_model(directory, dataset)
    slices = result["targets"]["deflection"]["error_slices"]
    for evaluation_slice in slices.values():
        assert evaluation_slice["status"] == "NOT_RUN"
        assert evaluation_slice["sample_ids"] == []
        assert evaluation_slice["sample_count"] == 0
        assert evaluation_slice["metrics"] is None
        assert evaluation_slice["false_safe_count"] is None


def test_constraint_classification_is_not_run_without_declared_limit(tmp_path):
    dataset = analytic_dataset()
    dataset["targets"]["deflection"]["limit"] = None
    _, directory = train_analytic(tmp_path, dataset)

    result = models._evaluate_analytic_test_model(directory, dataset)
    classification = result["targets"]["deflection"]["constraint_classification"]

    assert classification["status"] == "NOT_RUN"
    assert classification["reason"] == "target_limit_not_declared"
    assert classification["sample_count"] == 4
    assert classification["confusion_matrix"] is None
    assert classification["false_safe_count"] is None
    assert classification["false_unsafe_count"] is None
    constraint_slice = result["targets"]["deflection"]["error_slices"]["constraint_near"]
    assert constraint_slice["status"] == "NOT_RUN"
    assert constraint_slice["reason"] == "target_limit_not_declared"
    assert constraint_slice["false_safe_count"] is None
    assert result["status"] == "PASS"
