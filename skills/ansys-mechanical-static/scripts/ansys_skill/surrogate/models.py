"""Auditable numerical surrogate training and prediction."""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from collections.abc import Mapping, Sequence
from numbers import Real
from pathlib import Path
from typing import Any

from ansys_skill.errors import AnsysSimError, EnvironmentUnavailableError

from .metrics import absolute_error_metrics, regression_metrics

MODEL_SCHEMA_VERSION = "1.1"
TRAINING_ALGORITHM_VERSION = "1.0.0"
MODEL_FILENAME = "model.json"
MODEL_CARD_FILENAME = "model-card.json"
_SPLITS = {"train", "test", "baseline", "verification", "comparison"}
_KERNELS = {"rbf", "matern32", "matern52"}
_RIDGE_ALPHAS = (1e-8, 1e-5, 1e-3, 0.1, 1.0, 10.0)
_GPR_LENGTH_SCALES = (0.25, 0.5, 1.0, 2.0)
_BOUNDARY_REGION_FRACTION = 0.1
_DEFAULT_OPTIONS: dict[str, object] = {
    "seed": 42,
    "cv_folds": 4,
    "max_normalized_distance": 0.4,
    "max_relative_std": 0.15,
}
_OPTION_NAMES = frozenset(_DEFAULT_OPTIONS)


class SurrogateError(AnsysSimError):
    """Base error for surrogate operations."""

    error_type = "surrogate_error"


class SurrogateValidationError(SurrogateError):
    """Raised when a dataset, model, or prediction request is invalid."""

    error_type = "surrogate_validation_error"


def _numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise EnvironmentUnavailableError(
            "Surrogate numerics require NumPy; install the optional numerical runtime."
        ) from exc
    return np


def _runtime_versions() -> dict[str, str]:
    try:
        import numpy
        import scipy
    except ImportError as exc:
        raise EnvironmentUnavailableError(
            "Surrogate training requires NumPy and SciPy in the numerical runtime."
        ) from exc
    return {
        "python": sys.version.split()[0],
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
    }


def _invalid(message: str) -> None:
    raise SurrogateValidationError(message)


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid(f"{label} must be a non-empty string")
    return value


def _finite_number(value: object, label: str, *, nullable: bool = False) -> float | None:
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        _invalid(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        _invalid(f"{label} must be finite")
    return result


def _nonnegative_number(value: object, label: str) -> float:
    result = _finite_number(value, label)
    assert result is not None
    if result < 0.0:
        _invalid(f"{label} must be non-negative")
    return result


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        _invalid(f"{label} must be an object with string keys")
    return value


def _validate_context(
    feature_names_value: object,
    feature_units_value: object,
    bounds_value: object,
    targets_value: object,
) -> tuple[list[str], dict[str, str], dict[str, list[float]], dict[str, dict[str, object]]]:
    if not isinstance(feature_names_value, list) or not feature_names_value:
        _invalid("feature_names must be a non-empty list")
    feature_names = [_nonempty_string(item, "feature name") for item in feature_names_value]
    if len(set(feature_names)) != len(feature_names):
        _invalid("feature_names must be unique")

    units_raw = _mapping(feature_units_value, "feature_units")
    if set(units_raw) != set(feature_names):
        _invalid("feature_units keys must exactly match feature_names")
    feature_units = {name: _nonempty_string(units_raw[name], f"unit for {name}") for name in feature_names}

    bounds_raw = _mapping(bounds_value, "bounds")
    if set(bounds_raw) != set(feature_names):
        _invalid("bounds keys must exactly match feature_names")
    bounds: dict[str, list[float]] = {}
    for name in feature_names:
        pair = bounds_raw[name]
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            _invalid(f"bounds for {name} must contain a lower and upper value")
        lower = _finite_number(pair[0], f"lower bound for {name}")
        upper = _finite_number(pair[1], f"upper bound for {name}")
        assert lower is not None and upper is not None
        if lower >= upper:
            _invalid(f"bounds for {name} must be strictly increasing")
        bounds[name] = [lower, upper]

    targets_raw = _mapping(targets_value, "targets")
    if not targets_raw:
        _invalid("targets must define at least one output")
    targets: dict[str, dict[str, object]] = {}
    for target_name, target_value in targets_raw.items():
        name = _nonempty_string(target_name, "target name")
        target = _mapping(target_value, f"target metadata for {name}")
        required_target_fields = {
            "unit",
            "dimension",
            "absolute_tolerance",
            "relative_tolerance",
            "reference_scale",
            "limit",
        }
        missing_target_fields = required_target_fields - set(target)
        if missing_target_fields:
            _invalid(f"target {name} is missing metadata: {sorted(missing_target_fields)}")
        unit = _nonempty_string(target.get("unit"), f"unit for target {name}")
        dimension = target.get("dimension")
        if dimension not in {"length", "pressure"}:
            _invalid(f"target {name} dimension must be 'length' or 'pressure'")
        absolute_tolerance = _nonnegative_number(
            target.get("absolute_tolerance"), f"absolute_tolerance for {name}"
        )
        relative_tolerance = _nonnegative_number(
            target.get("relative_tolerance"), f"relative_tolerance for {name}"
        )
        reference_scale = _finite_number(target.get("reference_scale"), f"reference_scale for {name}")
        assert reference_scale is not None
        if reference_scale <= 0.0:
            _invalid(f"reference_scale for {name} must be positive")
        limit = _finite_number(target.get("limit"), f"limit for {name}", nullable=True)
        targets[name] = {
            "unit": unit,
            "dimension": dimension,
            "absolute_tolerance": absolute_tolerance,
            "relative_tolerance": relative_tolerance,
            "reference_scale": reference_scale,
            "limit": limit,
        }
    return feature_names, feature_units, bounds, targets


def _validate_dataset(dataset: object) -> dict[str, object]:
    root = _mapping(dataset, "dataset")
    if root.get("schema_version") != "1.0":
        _invalid("dataset schema_version must be '1.0'")
    dataset_id = _nonempty_string(root.get("dataset_id"), "dataset_id")
    fingerprint = _nonempty_string(root.get("study_fingerprint"), "study_fingerprint")
    evidence_kind = root.get("evidence_kind")
    if evidence_kind not in {"solver", "analytic_test"}:
        _invalid("evidence_kind must be 'solver' or 'analytic_test'")
    feature_names, feature_units, bounds, targets = _validate_context(
        root.get("feature_names"), root.get("feature_units"), root.get("bounds"), root.get("targets")
    )
    frozen_test_designs = root.get("frozen_test_designs", [])
    if not isinstance(frozen_test_designs, list) or any(
        not isinstance(design_id, str) or not design_id for design_id in frozen_test_designs
    ):
        _invalid("frozen_test_designs must be a list of non-empty design IDs")
    if len(set(frozen_test_designs)) != len(frozen_test_designs):
        _invalid("frozen_test_designs must not contain duplicates")
    frozen_test_design_set = set(frozen_test_designs)
    rows_value = root.get("rows")
    if not isinstance(rows_value, list) or not rows_value:
        _invalid("rows must be a non-empty list")
    rows: list[dict[str, object]] = []
    seen_sample_ids: set[str] = set()
    design_splits: dict[str, str] = {}
    design_parameters: dict[str, dict[str, float]] = {}
    target_names = set(targets)
    for row_index, row_value in enumerate(rows_value):
        label = f"rows[{row_index}]"
        row = _mapping(row_value, label)
        sample_id = _nonempty_string(row.get("sample_id"), f"{label}.sample_id")
        design_id = _nonempty_string(row.get("design_id"), f"{label}.design_id")
        if sample_id in seen_sample_ids:
            _invalid(f"duplicate sample_id {sample_id!r}")
        seen_sample_ids.add(sample_id)
        split = row.get("split")
        if split not in _SPLITS:
            _invalid(f"{label}.split must be one of {sorted(_SPLITS)}")
        prior_split = design_splits.setdefault(design_id, str(split))
        if prior_split != split:
            _invalid(f"design_id {design_id!r} occurs in multiple splits")
        if design_id in frozen_test_design_set and split != "test":
            _invalid(f"{label}.design_id is frozen for test but its split is {split!r}")
        if split == "test" and design_id not in frozen_test_design_set:
            _invalid(f"{label}.design_id is not declared in frozen_test_designs")

        parameters_raw = _mapping(row.get("parameters"), f"{label}.parameters")
        if set(parameters_raw) != set(feature_names):
            _invalid(f"{label}.parameters keys must exactly match feature_names")
        parameters: dict[str, float] = {}
        for name in feature_names:
            value = _finite_number(parameters_raw[name], f"{label}.parameters.{name}")
            assert value is not None
            lower, upper = bounds[name]
            if value < lower or value > upper:
                _invalid(f"{label}.parameters.{name} lies outside declared bounds")
            parameters[name] = value
        prior_parameters = design_parameters.setdefault(design_id, parameters)
        if prior_parameters != parameters:
            _invalid(f"rows sharing design_id {design_id!r} must have identical parameters")

        targets_raw = _mapping(row.get("targets"), f"{label}.targets")
        unknown_targets = set(targets_raw) - target_names
        if unknown_targets:
            _invalid(f"{label}.targets contains undeclared target(s): {sorted(unknown_targets)}")
        target_values: dict[str, float | None] = {}
        for name, value in targets_raw.items():
            parsed = _finite_number(value, f"{label}.targets.{name}", nullable=True)
            target_values[name] = parsed
        accepted_value = row.get("accepted_targets")
        if not isinstance(accepted_value, list) or any(not isinstance(name, str) for name in accepted_value):
            _invalid(f"{label}.accepted_targets must be a list of target names")
        if len(set(accepted_value)) != len(accepted_value):
            _invalid(f"{label}.accepted_targets must not contain duplicates")
        unknown_accepted = set(accepted_value) - target_names
        if unknown_accepted:
            _invalid(f"{label}.accepted_targets contains undeclared target(s): {sorted(unknown_accepted)}")
        source_raw = _mapping(row.get("source"), f"{label}.source")
        synthetic = source_raw.get("synthetic")
        if not isinstance(synthetic, bool):
            _invalid(f"{label}.source.synthetic must be boolean")
        source_kind = source_raw.get("kind")
        if source_kind not in {"solver", "analytic_test"}:
            _invalid(f"{label}.source.kind must be 'solver' or 'analytic_test'")
        normalized = dict(row)
        normalized.update(
            {
                "sample_id": sample_id,
                "design_id": design_id,
                "split": split,
                "parameters": parameters,
                "targets": target_values,
                "accepted_targets": list(accepted_value),
                "source": {**source_raw, "synthetic": synthetic, "kind": source_kind},
            }
        )
        rows.append(normalized)
    return {
        "schema_version": "1.0",
        "dataset_id": dataset_id,
        "study_fingerprint": fingerprint,
        "evidence_kind": evidence_kind,
        "feature_names": feature_names,
        "feature_units": feature_units,
        "bounds": bounds,
        "targets": targets,
        "frozen_test_designs": sorted(frozen_test_designs),
        "rows": rows,
    }


def _resolve_options(options: object) -> dict[str, object]:
    if options is None:
        supplied: Mapping[str, object] = {}
    else:
        supplied = _mapping(options, "options")
    unknown = set(supplied) - _OPTION_NAMES
    if unknown:
        _invalid(f"unknown surrogate option(s): {sorted(unknown)}")
    result = {**_DEFAULT_OPTIONS, **supplied}
    folds = result["cv_folds"]
    if isinstance(folds, bool) or not isinstance(folds, int) or not 3 <= folds <= 10:
        _invalid("cv_folds must be an integer from 3 through 10")
    seed = result["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        _invalid("seed must be an integer from 0 through 2**32 - 1")
    max_distance = _finite_number(result["max_normalized_distance"], "max_normalized_distance")
    assert max_distance is not None
    if not 0.0 < max_distance <= 1.0:
        _invalid("max_normalized_distance must be greater than 0 and at most 1")
    result["max_normalized_distance"] = max_distance
    max_relative_std = _finite_number(result["max_relative_std"], "max_relative_std")
    assert max_relative_std is not None
    if not 0.0 < max_relative_std <= 1.0:
        _invalid("max_relative_std must be greater than 0 and at most 1")
    result["max_relative_std"] = max_relative_std
    return result


def _normalize_row(np: Any, parameters: Mapping[str, float], feature_names: list[str], bounds: dict[str, list[float]]):
    return np.asarray(
        [(parameters[name] - bounds[name][0]) / (bounds[name][1] - bounds[name][0]) for name in feature_names],
        dtype=float,
    )


def _quadratic_features(np: Any, values: Any):
    columns = [np.ones(values.shape[0], dtype=float)]
    columns.extend(values[:, index] for index in range(values.shape[1]))
    columns.extend(
        values[:, left] * values[:, right]
        for left in range(values.shape[1])
        for right in range(left, values.shape[1])
    )
    return np.column_stack(columns)


def _fit_ridge(np: Any, values: Any, truth: Any, alpha: float) -> dict[str, object]:
    design = _quadratic_features(np, values)
    center = float(np.mean(truth))
    scale = float(np.std(truth))
    if scale <= np.finfo(float).eps * max(1.0, abs(center)):
        scale = 1.0
    normalized_truth = (truth - center) / scale
    gram = design.T @ design
    penalty = np.eye(gram.shape[0], dtype=float) * alpha
    penalty[0, 0] = 0.0
    try:
        coefficients = np.linalg.solve(gram + penalty, design.T @ normalized_truth)
    except np.linalg.LinAlgError:
        coefficients = np.linalg.lstsq(gram + penalty, design.T @ normalized_truth, rcond=None)[0]
    return {
        "family": "quadratic_ridge",
        "alpha": float(alpha),
        "y_center": center,
        "y_scale": scale,
        "coefficients": coefficients,
    }


def _kernel_matrix(np: Any, left: Any, right: Any, kernel: str, length_scale: float):
    difference = (left[:, None, :] - right[None, :, :]) / length_scale
    squared_distance = np.sum(difference * difference, axis=2)
    radius = np.sqrt(np.maximum(squared_distance, 0.0))
    if kernel == "rbf":
        return np.exp(-0.5 * squared_distance)
    if kernel == "matern32":
        scaled = math.sqrt(3.0) * radius
        return (1.0 + scaled) * np.exp(-scaled)
    scaled = math.sqrt(5.0) * radius
    return (1.0 + scaled + (5.0 / 3.0) * squared_distance) * np.exp(-scaled)


def _fit_gpr(np: Any, values: Any, truth: Any, kernel: str, length_scale: float) -> dict[str, object]:
    center = float(np.mean(truth))
    scale = float(np.std(truth))
    if scale <= np.finfo(float).eps * max(1.0, abs(center)):
        scale = 1.0
    normalized_truth = (truth - center) / scale
    covariance = _kernel_matrix(np, values, values, kernel, length_scale)
    jitter = 1e-10
    identity = np.eye(values.shape[0], dtype=float)
    for _ in range(6):
        try:
            lower = np.linalg.cholesky(covariance + jitter * identity)
            break
        except np.linalg.LinAlgError:
            jitter *= 10.0
    else:
        raise SurrogateValidationError("GPR covariance matrix could not be factorized")
    dual = np.linalg.solve(lower.T, np.linalg.solve(lower, normalized_truth))
    return {
        "family": "gpr",
        "kernel": kernel,
        "length_scale": float(length_scale),
        "jitter": float(jitter),
        "y_center": center,
        "y_scale": scale,
        "training_x": values,
        "cholesky_lower": lower,
        "dual_coefficients": dual,
    }


def _predict_numeric_model(np: Any, model: Mapping[str, object], values: Any) -> tuple[Any, Any]:
    if model.get("family") == "quadratic_ridge":
        design = _quadratic_features(np, values)
        coefficients = np.asarray(model["coefficients"], dtype=float)
        prediction = float(model["y_center"]) + float(model["y_scale"]) * (design @ coefficients)
        standard_deviation = np.full(values.shape[0], float(model.get("cv_rmse", 0.0)), dtype=float)
    else:
        train_x = np.asarray(model["training_x"], dtype=float)
        lower = np.asarray(model["cholesky_lower"], dtype=float)
        dual = np.asarray(model["dual_coefficients"], dtype=float)
        kernel = str(model["kernel"])
        length_scale = float(model["length_scale"])
        cross = _kernel_matrix(np, values, train_x, kernel, length_scale)
        normalized_mean = cross @ dual
        solved = np.linalg.solve(lower, cross.T)
        variance = np.maximum(0.0, 1.0 - np.sum(solved * solved, axis=0))
        center = float(model["y_center"])
        scale = float(model["y_scale"])
        prediction = center + scale * normalized_mean
        standard_deviation = scale * np.sqrt(variance)
    if not np.all(np.isfinite(prediction)) or not np.all(np.isfinite(standard_deviation)):
        raise SurrogateValidationError("surrogate prediction produced a non-finite result")
    return prediction, standard_deviation


def _group_splits(groups: Sequence[str], fold_count: int, seed: int) -> list[tuple[list[int], list[int], list[str]]]:
    unique_groups = sorted(set(groups))
    if len(unique_groups) < 3:
        raise SurrogateValidationError("each target needs at least three distinct training design_id groups")
    actual_folds = min(fold_count, len(unique_groups))
    shuffled = list(unique_groups)
    random.Random(seed).shuffle(shuffled)
    buckets = [shuffled[index::actual_folds] for index in range(actual_folds)]
    result = []
    for validation_groups in buckets:
        validation_set = set(validation_groups)
        train_indices = [index for index, group in enumerate(groups) if group not in validation_set]
        validation_indices = [index for index, group in enumerate(groups) if group in validation_set]
        result.append((train_indices, validation_indices, sorted(validation_groups)))
    return result


def _fit_numeric_target(
    np: Any,
    values: Any,
    truth: Any,
    groups: list[str],
    reference_scale: float,
    options: dict[str, object],
) -> dict[str, object]:
    fold_count = min(int(options["cv_folds"]), len(set(groups)))
    folds = _group_splits(groups, fold_count, int(options["seed"]))
    candidates: list[dict[str, object]] = [
        {"family": "quadratic_ridge", "alpha": float(alpha)}
        for alpha in _RIDGE_ALPHAS
    ]
    candidates.extend(
        {"family": "gpr", "kernel": str(kernel), "length_scale": float(length_scale)}
        for kernel in ("rbf", "matern32", "matern52")
        for length_scale in _GPR_LENGTH_SCALES
    )
    candidate_reports: list[dict[str, object]] = []
    for candidate in candidates:
        out_of_fold = np.empty(truth.shape[0], dtype=float)
        fold_reports = []
        for train_indices, validation_indices, validation_groups in folds:
            train_x = values[train_indices]
            train_y = truth[train_indices]
            if candidate["family"] == "quadratic_ridge":
                fitted = _fit_ridge(np, train_x, train_y, float(candidate["alpha"]))
            else:
                fitted = _fit_gpr(
                    np, train_x, train_y, str(candidate["kernel"]), float(candidate["length_scale"])
                )
            prediction, _ = _predict_numeric_model(np, fitted, values[validation_indices])
            out_of_fold[validation_indices] = prediction
            fold_reports.append(
                {
                    "validation_design_ids": validation_groups,
                    "metrics": regression_metrics(
                        truth[validation_indices].tolist(), prediction.tolist(), reference_scale
                    ),
                }
            )
        metrics = regression_metrics(truth.tolist(), out_of_fold.tolist(), reference_scale)
        candidate_reports.append(
            {
                **candidate,
                "metrics": metrics,
                "folds": fold_reports,
                "out_of_fold_prediction": out_of_fold,
            }
        )

    def score(report: Mapping[str, object]) -> tuple[float, int, float, str]:
        metrics = report["metrics"]
        assert isinstance(metrics, Mapping)
        normalized = metrics["normalized_error"]
        normalized_score = float(normalized) if normalized is not None else math.inf
        family_rank = 0 if report["family"] == "quadratic_ridge" else 1
        parameter_key = json.dumps(
            {key: report[key] for key in ("alpha", "kernel", "length_scale") if key in report},
            sort_keys=True,
        )
        return normalized_score, family_rank, float(metrics["rmse"]), parameter_key

    selected = min(candidate_reports, key=score)
    selected_metrics = selected["metrics"]
    assert isinstance(selected_metrics, dict)
    if selected["family"] == "quadratic_ridge":
        fitted_model = _fit_ridge(np, values, truth, float(selected["alpha"]))
        persisted = {
            **fitted_model,
            "coefficients": fitted_model["coefficients"].tolist(),
            "cv_rmse": float(selected_metrics["rmse"]),
        }
    else:
        fitted_model = _fit_gpr(
            np, values, truth, str(selected["kernel"]), float(selected["length_scale"])
        )
        persisted = {
            **fitted_model,
            "training_x": fitted_model["training_x"].tolist(),
            "cholesky_lower": fitted_model["cholesky_lower"].tolist(),
            "dual_coefficients": fitted_model["dual_coefficients"].tolist(),
            "cv_rmse": float(selected_metrics["rmse"]),
        }
    public_candidate_reports = [
        {key: value for key, value in report.items() if key != "out_of_fold_prediction"}
        for report in candidate_reports
    ]
    return {
        **persisted,
        "cv_metrics": selected_metrics,
        "cv": {
            "requested_folds": int(options["cv_folds"]),
            "folds": len(folds),
            "seed": int(options["seed"]),
            "group_count": len(set(groups)),
            "selection_metric": "normalized_error",
            "selected_candidate": {
                key: selected[key]
                for key in ("family", "alpha", "kernel", "length_scale")
                if key in selected
            },
            "selected_metrics": selected_metrics,
            "candidates": public_candidate_reports,
        },
    }


def _support_summary(np: Any, values: Any, groups: list[str], max_distance: float) -> dict[str, object]:
    grouped: dict[str, list[Any]] = {}
    for value, group in zip(values, groups, strict=True):
        grouped.setdefault(group, []).append(value)
    design_ids = sorted(grouped)
    points = np.asarray([np.mean(grouped[group], axis=0) for group in design_ids], dtype=float)
    return {
        "support_design_ids": design_ids,
        "support_points": points.tolist(),
        "coverage_distance_limit": max_distance,
    }


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SurrogateValidationError("surrogate data must contain JSON-safe finite values") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _training_projection(
    dataset: dict[str, object], eligible_by_target: dict[str, list[dict[str, object]]]
) -> tuple[str, dict[str, list[str]], dict[str, int]]:
    target_rows: dict[str, list[dict[str, object]]] = {}
    sample_ids: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for target_name, rows in eligible_by_target.items():
        ordered = sorted(rows, key=lambda row: str(row["sample_id"]))
        target_rows[target_name] = [
            {
                "sample_id": row["sample_id"],
                "design_id": row["design_id"],
                "parameters": row["parameters"],
                "target_value": row["targets"][target_name],
                "source": row["source"],
            }
            for row in ordered
        ]
        sample_ids[target_name] = [str(row["sample_id"]) for row in ordered]
        counts[target_name] = len(ordered)
    context = {
        "schema_version": dataset["schema_version"],
        "study_fingerprint": dataset["study_fingerprint"],
        "feature_names": dataset["feature_names"],
        "feature_units": dataset["feature_units"],
        "bounds": dataset["bounds"],
        "targets": dataset["targets"],
        "training_rows_by_target": target_rows,
    }
    return _sha256(context), sample_ids, counts


def _assemble_model_document(
    dataset: dict[str, object],
    training_data_hash: str,
    target_models: dict[str, dict[str, object]],
    options: dict[str, object],
) -> dict[str, object]:
    document: dict[str, object] = {
        "artifact_type": "ansys_skill_surrogate_model",
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_id": "",
        "evidence_kind": dataset["evidence_kind"],
        "study_fingerprint": dataset["study_fingerprint"],
        "frozen_test_designs": sorted(dataset["frozen_test_designs"]),
        "training_data_hash": training_data_hash,
        "feature_names": dataset["feature_names"],
        "feature_units": dataset["feature_units"],
        "bounds": dataset["bounds"],
        "targets": dataset["targets"],
        "options": options,
        "target_models": target_models,
    }
    document["model_id"] = _sha256({key: value for key, value in document.items() if key != "model_id"})
    return document


def _write_json(path: Path, value: object) -> None:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def _fit_validated_dataset(
    dataset: dict[str, object], out_dir: Path, options_value: object
) -> dict[str, object]:
    options = _resolve_options(options_value)
    np = _numpy()
    runtime_versions = _runtime_versions()
    feature_names = dataset["feature_names"]
    bounds = dataset["bounds"]
    target_info = dataset["targets"]
    assert isinstance(feature_names, list) and isinstance(bounds, dict) and isinstance(target_info, dict)
    rows = dataset["rows"]
    assert isinstance(rows, list)
    evidence_kind = dataset["evidence_kind"]
    def eligible_source(row: dict[str, object]) -> bool:
        source = row["source"]
        if evidence_kind == "solver":
            return source["synthetic"] is False and source["kind"] == "solver"
        return source["synthetic"] is True and source["kind"] == "analytic_test"

    target_models: dict[str, dict[str, object]] = {}
    eligible_by_target: dict[str, list[dict[str, object]]] = {}
    for target_name, metadata in target_info.items():
        eligible = [
            row
            for row in rows
            if row["split"] == "train"
            and eligible_source(row)
            and target_name in row["accepted_targets"]
            and row["targets"].get(target_name) is not None
        ]
        design_ids = {str(row["design_id"]) for row in eligible}
        if len(design_ids) < 3:
            _invalid(f"target {target_name!r} needs at least three eligible training design_id groups")
        eligible_by_target[target_name] = eligible
        values = np.asarray(
            [_normalize_row(np, row["parameters"], feature_names, bounds) for row in eligible], dtype=float
        )
        truth = np.asarray([row["targets"][target_name] for row in eligible], dtype=float)
        groups = [str(row["design_id"]) for row in eligible]
        core = _fit_numeric_target(np, values, truth, groups, float(metadata["reference_scale"]), options)
        core.update(_support_summary(np, values, groups, float(options["max_normalized_distance"])))
        core["unit"] = metadata["unit"]
        core["reference_scale"] = metadata["reference_scale"]
        core["absolute_tolerance"] = metadata["absolute_tolerance"]
        core["relative_tolerance"] = metadata["relative_tolerance"]
        core["limit"] = metadata["limit"]
        core["training_sample_ids"] = sorted(str(row["sample_id"]) for row in eligible)
        target_models[target_name] = core

    training_hash, sample_ids, sample_counts = _training_projection(dataset, eligible_by_target)
    model = _assemble_model_document(dataset, training_hash, target_models, options)
    evidence_label = (
        "Non-synthetic solver results; predictions are not solver evidence or certification."
        if evidence_kind == "solver"
        else "Synthetic analytic test data; not engineering evidence."
    )
    card = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "training_algorithm_version": TRAINING_ALGORITHM_VERSION,
        "numeric_runtime": runtime_versions,
        "model_id": model["model_id"],
        "training_data_id": f"sha256:{training_hash}",
        "study_fingerprint": dataset["study_fingerprint"],
        "training_data_hash": training_hash,
        "evidence_kind": evidence_kind,
        "evidence_label": evidence_label,
        "feature_names": feature_names,
        "feature_units": dataset["feature_units"],
        "bounds": bounds,
        "targets": dataset["targets"],
        "training_sample_ids_by_target": sample_ids,
        "training_sample_count_by_target": sample_counts,
        "model_selection": {
            name: {
                "selected_model": target_model["family"],
                "selected_parameters": target_model["cv"]["selected_candidate"],
                "cross_validation": target_model["cv"],
            }
            for name, target_model in target_models.items()
        },
        "options": options,
        "selection_metric": "normalized_error (out-of-fold RMSE / reference_scale)",
        "validation_split": "Grouped by design_id; only split=train rows participate.",
        "prediction_uncertainty_note": (
            "GPR intervals and all surrogate uncertainty estimates are descriptive; no confidence probability is guaranteed."
        ),
    }
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    model_path = destination / MODEL_FILENAME
    card_path = destination / MODEL_CARD_FILENAME
    _write_json(model_path, model)
    _write_json(card_path, card)
    return {
        "status": "TRAINED",
        "model_id": model["model_id"],
        "model_directory": str(destination),
        "model_path": str(model_path),
        "model_card_path": str(card_path),
        "evidence_kind": evidence_kind,
        "training_data_hash": training_hash,
        "targets": {
            name: {
                "selected_model": target_model["family"],
                "cv_metrics": target_model["cv_metrics"],
                "cv_folds": target_model["cv"]["folds"],
            }
            for name, target_model in target_models.items()
        },
    }


def train_model(dataset: dict, out_dir: Path, options: dict | None = None) -> dict:
    """Train solver-backed response surfaces using training rows only."""
    validated = _validate_dataset(dataset)
    if validated["evidence_kind"] != "solver":
        _invalid("engineering surrogate training requires evidence_kind='solver'")
    return _fit_validated_dataset(validated, Path(out_dir), options)


def _train_analytic_test_model(dataset: dict, out_dir: Path, options: dict | None = None) -> dict:
    """Explicit test helper that only accepts synthetic analytic-test evidence."""
    validated = _validate_dataset(dataset)
    if validated["evidence_kind"] != "analytic_test":
        _invalid("the analytic test helper requires evidence_kind='analytic_test'")
    if any(
        row["split"] == "train"
        and (row["source"]["synthetic"] is not True or row["source"]["kind"] != "analytic_test")
        for row in validated["rows"]
    ):
        _invalid("analytic test training rows must be marked synthetic analytic_test")
    return _fit_validated_dataset(validated, Path(out_dir), options)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def _validate_model_document(model: object) -> dict[str, object]:
    root = _mapping(model, "model")
    if root.get("artifact_type") != "ansys_skill_surrogate_model":
        _invalid("unsupported surrogate model artifact_type")
    if root.get("schema_version") != MODEL_SCHEMA_VERSION:
        _invalid("unsupported surrogate model schema_version")
    evidence_kind = root.get("evidence_kind")
    if evidence_kind not in {"solver", "analytic_test"}:
        _invalid("model evidence_kind is invalid")
    _nonempty_string(root.get("study_fingerprint"), "model study_fingerprint")
    frozen_test_designs = root.get("frozen_test_designs")
    if not isinstance(frozen_test_designs, list) or any(
        not isinstance(design_id, str) or not design_id for design_id in frozen_test_designs
    ):
        _invalid("model frozen_test_designs must be a list of non-empty design IDs")
    if len(set(frozen_test_designs)) != len(frozen_test_designs):
        _invalid("model frozen_test_designs must not contain duplicates")
    if frozen_test_designs != sorted(frozen_test_designs):
        _invalid("model frozen_test_designs must be sorted")
    training_hash = root.get("training_data_hash")
    if not isinstance(training_hash, str) or len(training_hash) != 64:
        _invalid("model training_data_hash must be a SHA-256 digest")
    feature_names, _feature_units, _bounds, targets = _validate_context(
        root.get("feature_names"), root.get("feature_units"), root.get("bounds"), root.get("targets")
    )
    _resolve_options(root.get("options"))
    target_models = _mapping(root.get("target_models"), "model target_models")
    if set(target_models) != set(targets):
        _invalid("model target_models must exactly match target metadata")
    feature_count = len(feature_names)
    coefficient_count = 1 + feature_count + feature_count * (feature_count + 1) // 2
    for target_name, model_value in target_models.items():
        item = _mapping(model_value, f"model for {target_name}")
        family = item.get("family")
        if family not in {"quadratic_ridge", "gpr"}:
            _invalid(f"model for {target_name} has an unsupported family")
        _nonempty_string(item.get("unit"), f"model unit for {target_name}")
        if item.get("unit") != targets[target_name]["unit"]:
            _invalid(f"model unit mismatch for {target_name}")
        _finite_number(item.get("y_center"), f"model y_center for {target_name}")
        scale = _finite_number(item.get("y_scale"), f"model y_scale for {target_name}")
        cv_rmse = _nonnegative_number(item.get("cv_rmse"), f"model cv_rmse for {target_name}")
        if scale is None or scale <= 0.0:
            _invalid(f"model y_scale for {target_name} must be positive")
        support_ids = item.get("support_design_ids")
        support_points = item.get("support_points")
        if not isinstance(support_ids, list) or len(support_ids) < 3 or any(not isinstance(x, str) for x in support_ids):
            _invalid(f"model support_design_ids for {target_name} must contain at least three groups")
        if len(set(support_ids)) != len(support_ids):
            _invalid(f"model support_design_ids for {target_name} must be unique")
        if not isinstance(support_points, list) or len(support_points) != len(support_ids):
            _invalid(f"model support_points for {target_name} are invalid")
        for point in support_points:
            _validated_vector(point, feature_count, f"support point for {target_name}")
        _nonnegative_number(item.get("coverage_distance_limit"), f"coverage_distance_limit for {target_name}")
        if family == "quadratic_ridge":
            _finite_number(item.get("alpha"), f"ridge alpha for {target_name}")
            _validated_vector(item.get("coefficients"), coefficient_count, f"ridge coefficients for {target_name}")
        else:
            kernel = item.get("kernel")
            if kernel not in _KERNELS:
                _invalid(f"GPR kernel for {target_name} is not in the supported whitelist")
            length_scale = _finite_number(item.get("length_scale"), f"GPR length_scale for {target_name}")
            jitter = _finite_number(item.get("jitter"), f"GPR jitter for {target_name}")
            if length_scale is None or length_scale <= 0.0 or jitter is None or jitter <= 0.0:
                _invalid(f"GPR kernel parameters for {target_name} must be positive")
            training_x = item.get("training_x")
            dual = item.get("dual_coefficients")
            cholesky = item.get("cholesky_lower")
            if not isinstance(training_x, list) or not training_x:
                _invalid(f"GPR training_x for {target_name} is empty")
            for point in training_x:
                _validated_vector(point, feature_count, f"GPR training point for {target_name}")
            row_count = len(training_x)
            _validated_vector(dual, row_count, f"GPR dual coefficients for {target_name}")
            if not isinstance(cholesky, list) or len(cholesky) != row_count:
                _invalid(f"GPR Cholesky matrix for {target_name} has an invalid shape")
            for row_index, row in enumerate(cholesky):
                values = _validated_vector(row, row_count, f"GPR Cholesky row for {target_name}")
                if values[row_index] <= 0.0 or any(abs(values[col]) > 1e-12 for col in range(row_index + 1, row_count)):
                    _invalid(f"GPR Cholesky matrix for {target_name} must be lower triangular with positive diagonal")
        if not isinstance(item.get("cv"), Mapping) or not isinstance(item.get("cv_metrics"), Mapping):
            _invalid(f"model CV summary for {target_name} is missing")
        _ = cv_rmse
    model_id = root.get("model_id")
    expected_id = _sha256({key: value for key, value in root.items() if key != "model_id"})
    if model_id != expected_id:
        _invalid("surrogate model_id does not match model content")
    return dict(root)


def _validated_vector(value: object, length: int, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        _invalid(f"{label} must contain exactly {length} numbers")
    result = []
    for index, item in enumerate(value):
        parsed = _finite_number(item, f"{label}[{index}]")
        assert parsed is not None
        result.append(parsed)
    return result


def load_model(model_dir: Path) -> dict:
    """Load and validate a JSON-only surrogate model."""
    path = Path(model_dir) / MODEL_FILENAME
    try:
        model = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SurrogateValidationError(f"unable to read a valid surrogate model: {exc}") from exc
    return _validate_model_document(model)


def _assert_compatible(model: dict[str, object], dataset: dict[str, object]) -> None:
    if dataset["evidence_kind"] != "solver":
        _invalid("engineering surrogate evaluation requires evidence_kind='solver'")
    if model["evidence_kind"] != "solver":
        _invalid("engineering surrogate evaluation requires a solver-trained model")
    _assert_context_matches(model, dataset)


def _assert_context_matches(model: dict[str, object], dataset: dict[str, object]) -> None:
    for key in (
        "study_fingerprint",
        "frozen_test_designs",
        "feature_names",
        "feature_units",
        "bounds",
        "targets",
    ):
        if dataset[key] != model[key]:
            _invalid(f"evaluation dataset {key} does not match the trained model")


def evaluate_model(model_dir: Path, dataset: dict) -> dict:
    """Evaluate a compatible solver dataset using only split=test rows."""
    model = load_model(model_dir)
    validated = _validate_dataset(dataset)
    _assert_compatible(model, validated)
    return _evaluate_validated_dataset(model, validated)


def _evaluate_analytic_test_model(model_dir: Path, dataset: dict) -> dict:
    """Test-helper for numerical evaluation that preserves analytic-test labels."""
    model = load_model(model_dir)
    validated = _validate_dataset(dataset)
    if model["evidence_kind"] != "analytic_test" or validated["evidence_kind"] != "analytic_test":
        _invalid("the analytic evaluation helper only accepts analytic_test artifacts")
    _assert_context_matches(model, validated)
    return _evaluate_validated_dataset(model, validated)


def _target_error_tolerance(actual: float, metadata: Mapping[str, object]) -> float:
    return float(metadata["absolute_tolerance"]) + float(metadata["relative_tolerance"]) * max(
        abs(actual), float(metadata["reference_scale"])
    )


def _slice_result(
    selected: list[dict[str, object]],
    selection: dict[str, object],
    *,
    empty_reason: str,
    false_safe_available: bool,
) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "EVALUATED" if selected else "NOT_RUN",
        "selection": selection,
        "sample_ids": sorted(str(sample["sample_id"]) for sample in selected),
        "sample_count": len(selected),
    }
    if not selected:
        result.update(
            {
                "reason": empty_reason,
                "metrics": None,
                "false_safe_count": None,
            }
        )
        return result

    result["metrics"] = absolute_error_metrics(
        [float(sample["truth"]) for sample in selected],
        [float(sample["prediction"]) for sample in selected],
    )
    result["false_safe_count"] = (
        sum(bool(sample["false_safe"]) for sample in selected) if false_safe_available else None
    )
    return result


def _evaluation_slices(
    samples: list[dict[str, object]],
    feature_names: list[str],
    bounds: dict[str, list[float]],
    metadata: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    boundary_selection: dict[str, object] = {
        "criterion": (
            "Any feature's normalized distance to its nearest declared bound is <= threshold."
        ),
        "normalized_distance": (
            "min((value - lower) / (upper - lower), (upper - value) / (upper - lower))"
        ),
        "combine_features": "any",
        "threshold_fraction": _BOUNDARY_REGION_FRACTION,
        "feature_names": feature_names,
    }
    boundary_samples = []
    for sample in samples:
        parameters = sample["parameters"]
        assert isinstance(parameters, Mapping)
        if any(
            min(
                (float(parameters[name]) - bounds[name][0]) / (bounds[name][1] - bounds[name][0]),
                (bounds[name][1] - float(parameters[name])) / (bounds[name][1] - bounds[name][0]),
            )
            <= _BOUNDARY_REGION_FRACTION
            for name in feature_names
        ):
            boundary_samples.append(sample)

    limit = metadata["limit"]
    constraint_selection: dict[str, object] = {
        "criterion": "abs(truth - limit) <= error_tolerance",
        "error_tolerance": (
            "absolute_tolerance + relative_tolerance * max(abs(truth), reference_scale)"
        ),
        "absolute_tolerance": float(metadata["absolute_tolerance"]),
        "relative_tolerance": float(metadata["relative_tolerance"]),
        "reference_scale": float(metadata["reference_scale"]),
        "limit": float(limit) if limit is not None else None,
    }
    constraint_samples = (
        [
            sample
            for sample in samples
            if abs(float(sample["truth"]) - float(limit))
            <= float(sample["error_tolerance"])
        ]
        if limit is not None
        else []
    )
    constraint_empty_reason = (
        "target_limit_not_declared" if limit is None else "no_samples_match_selection"
    )
    return {
        "design_space_boundary": _slice_result(
            boundary_samples,
            boundary_selection,
            empty_reason="no_samples_match_selection",
            false_safe_available=limit is not None,
        ),
        "constraint_near": _slice_result(
            constraint_samples,
            constraint_selection,
            empty_reason=constraint_empty_reason,
            false_safe_available=limit is not None,
        ),
    }


def _constraint_classification(
    samples: list[dict[str, object]], metadata: Mapping[str, object]
) -> dict[str, object]:
    limit = metadata["limit"]
    if limit is None:
        return {
            "status": "NOT_RUN",
            "reason": "target_limit_not_declared",
            "limit": None,
            "sample_count": len(samples),
            "sample_ids": sorted(str(sample["sample_id"]) for sample in samples),
            "confusion_matrix": None,
            "false_safe_count": None,
            "false_unsafe_count": None,
        }
    if not samples:
        return {
            "status": "NOT_RUN",
            "reason": "no_eligible_test_samples",
            "limit": float(limit),
            "sample_count": 0,
            "sample_ids": [],
            "confusion_matrix": None,
            "false_safe_count": None,
            "false_unsafe_count": None,
        }

    counts = {
        "true_feasible_predicted_feasible": 0,
        "true_feasible_predicted_infeasible": 0,
        "true_infeasible_predicted_feasible": 0,
        "true_infeasible_predicted_infeasible": 0,
    }
    threshold = float(limit)
    for sample in samples:
        true_feasible = float(sample["truth"]) <= threshold
        predicted_feasible = float(sample["prediction"]) <= threshold
        if true_feasible and predicted_feasible:
            cell = "true_feasible_predicted_feasible"
        elif true_feasible:
            cell = "true_feasible_predicted_infeasible"
        elif predicted_feasible:
            cell = "true_infeasible_predicted_feasible"
        else:
            cell = "true_infeasible_predicted_infeasible"
        counts[cell] += 1

    return {
        "status": "EVALUATED",
        "feasibility_rule": "truth <= limit; prediction <= limit",
        "limit": threshold,
        "sample_count": len(samples),
        "sample_ids": sorted(str(sample["sample_id"]) for sample in samples),
        "confusion_matrix": counts,
        "false_safe_count": counts["true_infeasible_predicted_feasible"],
        "false_unsafe_count": counts["true_feasible_predicted_infeasible"],
    }


def _evaluate_validated_dataset(model: dict[str, object], validated: dict[str, object]) -> dict:
    rows = validated["rows"]
    evidence_kind = validated["evidence_kind"]
    feature_names = model["feature_names"]
    bounds = model["bounds"]
    target_info = model["targets"]
    target_models = model["target_models"]
    assert isinstance(rows, list) and isinstance(feature_names, list)
    assert isinstance(bounds, dict) and isinstance(target_info, dict) and isinstance(target_models, dict)
    np = _numpy()
    results: dict[str, object] = {}
    total_false_safe = 0
    eligible_test_count = 0
    has_failure = False
    all_targets_evaluated = True
    frozen_test_designs = validated["frozen_test_designs"]
    test_rows = [row for row in rows if row["split"] == "test"]
    expected_design_ids = sorted(
        set(frozen_test_designs) | {str(row["design_id"]) for row in test_rows}
    )
    for target_name, metadata in target_info.items():
        target_model = target_models[target_name]
        assert isinstance(metadata, dict) and isinstance(target_model, dict)
        rows_by_design: dict[str, list[dict[str, object]]] = {}
        for row in test_rows:
            rows_by_design.setdefault(str(row["design_id"]), []).append(row)
        samples: list[dict[str, object]] = []
        missing_design_ids: list[str] = []
        ineligible_designs: dict[str, list[str]] = {}
        for design_id in expected_design_ids:
            design_rows = rows_by_design.get(design_id, [])
            if len(design_rows) != 1:
                missing_design_ids.append(design_id)
                ineligible_designs[design_id] = [
                    "missing_test_row" if not design_rows else "duplicate_test_rows"
                ]
                continue
            row = design_rows[0]
            reasons = []
            if row["source"]["synthetic"] is not (evidence_kind == "analytic_test"):
                reasons.append("source_synthetic_mismatch")
            if row["source"]["kind"] != evidence_kind:
                reasons.append("source_kind_mismatch")
            if target_name not in row["accepted_targets"]:
                reasons.append("target_not_accepted")
            if row["targets"].get(target_name) is None:
                reasons.append("target_value_missing")
            if reasons:
                missing_design_ids.append(design_id)
                ineligible_designs[design_id] = reasons
            else:
                samples.append(row)
        if not samples:
            all_targets_evaluated = False
            results[target_name] = {
                "status": "NOT_RUN",
                "sample_count": 0,
                "expected_design_count": len(expected_design_ids),
                "evaluated_design_count": 0,
                "missing_design_ids": missing_design_ids,
                "ineligible_designs": ineligible_designs,
                "points": [],
                "error_slices": _evaluation_slices([], feature_names, bounds, metadata),
                "constraint_classification": _constraint_classification([], metadata),
            }
            continue
        training_ids = set(target_model["support_design_ids"])
        overlapping = sorted({str(row["design_id"]) for row in samples} & training_ids)
        if overlapping:
            _invalid(f"test design_id leaks into training for target {target_name!r}: {overlapping}")
        truth: list[float] = []
        prediction: list[float] = []
        deviations: list[float] = []
        false_safe = 0
        tolerance_failures = 0
        points: list[dict[str, object]] = []
        evaluation_samples: list[dict[str, object]] = []
        for row in samples:
            x = _normalize_row(np, row["parameters"], feature_names, bounds).reshape(1, -1)
            mean, std = _predict_numeric_model(np, target_model, x)
            actual = float(row["targets"][target_name])
            estimate = float(mean[0])
            standard_deviation = float(std[0])
            truth.append(actual)
            prediction.append(estimate)
            deviations.append(standard_deviation)
            tolerance = _target_error_tolerance(actual, metadata)
            if abs(estimate - actual) > tolerance:
                tolerance_failures += 1
            limit = metadata["limit"]
            is_false_safe = limit is not None and actual > float(limit) and estimate <= float(limit)
            if is_false_safe:
                false_safe += 1
            evaluation_samples.append(
                {
                    "sample_id": row["sample_id"],
                    "parameters": row["parameters"],
                    "truth": actual,
                    "prediction": estimate,
                    "error_tolerance": tolerance,
                    "false_safe": is_false_safe,
                }
            )
            points.append(
                {
                    "sample_id": row["sample_id"],
                    "design_id": row["design_id"],
                    "truth": actual,
                    "prediction": estimate,
                    "std": standard_deviation,
                    "unit": metadata["unit"],
                }
            )
        eligible_test_count += len(samples)
        total_false_safe += false_safe
        status = "FAIL" if tolerance_failures > 0 or false_safe > 0 else (
            "NOT_RUN" if missing_design_ids else "PASS"
        )
        has_failure = has_failure or status == "FAIL"
        all_targets_evaluated = all_targets_evaluated and not missing_design_ids
        target_result: dict[str, object] = {
            "status": status,
            "sample_count": len(samples),
            "expected_design_count": len(expected_design_ids),
            "evaluated_design_count": len(samples),
            "missing_design_ids": missing_design_ids,
            "ineligible_designs": ineligible_designs,
            "points": points,
            "metrics": regression_metrics(truth, prediction, float(metadata["reference_scale"])),
            "error_slices": _evaluation_slices(
                evaluation_samples, feature_names, bounds, metadata
            ),
            "constraint_classification": _constraint_classification(evaluation_samples, metadata),
            "tolerance_failures": tolerance_failures,
            "false_safe_count": false_safe,
            "unit": metadata["unit"],
            "model_family": target_model["family"],
        }
        if target_model["family"] == "gpr":
            covered = sum(
                abs(actual - estimate) <= deviation
                for actual, estimate, deviation in zip(truth, prediction, deviations, strict=True)
            )
            target_result["interval_coverage"] = {
                "interval": "prediction +/- 1 posterior standard deviation",
                "covered_count": covered,
                "sample_count": len(samples),
                "empirical_coverage": covered / len(samples),
                "confidence_probability_guaranteed": False,
            }
        results[target_name] = target_result
    overall = "FAIL" if has_failure else ("PASS" if all_targets_evaluated else "NOT_RUN")
    return {
        "status": overall,
        "model_id": model["model_id"],
        "evidence_kind": evidence_kind,
        "evidence_label": (
            "solver" if evidence_kind == "solver" else "analytic_test; not engineering evidence"
        ),
        "test_only": True,
        "sample_count": eligible_test_count,
        "false_safe_count": total_false_safe,
        "targets": results,
    }


def predict_model(model_dir: Path, parameters: dict[str, float]) -> dict:
    """Predict at one complete, ordered parameter point and flag unsupported queries."""
    model = load_model(model_dir)
    if model["evidence_kind"] != "solver":
        _invalid("engineering prediction requires a solver-trained model")
    return _predict_model_document(model, parameters)


def _predict_model_document(model: dict[str, object], parameters: dict[str, float]) -> dict:
    """Numerical prediction core, also used with explicitly labeled analytic fixtures."""
    feature_names = model["feature_names"]
    bounds = model["bounds"]
    target_info = model["targets"]
    target_models = model["target_models"]
    assert isinstance(feature_names, list) and isinstance(bounds, dict)
    assert isinstance(target_info, dict) and isinstance(target_models, dict)
    values = _mapping(parameters, "parameters")
    if set(values) != set(feature_names):
        missing = sorted(set(feature_names) - set(values))
        extra = sorted(set(values) - set(feature_names))
        _invalid(f"parameters must contain every model feature exactly once; missing={missing}, extra={extra}")
    parsed = {name: _finite_number(values[name], f"parameters.{name}") for name in feature_names}
    point = {name: float(parsed[name]) for name in feature_names}
    inside_bounds = all(bounds[name][0] <= point[name] <= bounds[name][1] for name in feature_names)
    np = _numpy()
    normalized = _normalize_row(np, point, feature_names, bounds).reshape(1, -1)
    predictions: dict[str, object] = {}
    relative_uncertainty: dict[str, float] = {}
    coverage_by_target: dict[str, object] = {}
    reasons = []
    if not inside_bounds:
        reasons.append("outside_bounds")
    uncertainty_limit = float(model["options"]["max_relative_std"])
    global_nearest = math.inf
    global_nearest_id: str | None = None
    any_unsupported_coverage = False
    for target_name, target_model in target_models.items():
        metadata = target_info[target_name]
        mean, std = _predict_numeric_model(np, target_model, normalized)
        value = float(mean[0])
        deviation = max(0.0, float(std[0]))
        scale = max(abs(value), float(metadata["reference_scale"]))
        relative = deviation / scale
        relative_uncertainty[target_name] = relative
        predictions[target_name] = {
            "value": value,
            "std": deviation,
            "unit": metadata["unit"],
        }
        support = np.asarray(target_model["support_points"], dtype=float)
        distances = np.linalg.norm(support - normalized[0], axis=1) / math.sqrt(len(feature_names))
        nearest_index = int(np.argmin(distances))
        nearest_distance = float(distances[nearest_index])
        coverage_limit = float(target_model["coverage_distance_limit"])
        covered = nearest_distance <= coverage_limit + 1e-15
        if nearest_distance < global_nearest:
            global_nearest = nearest_distance
            global_nearest_id = str(target_model["support_design_ids"][nearest_index])
        if not covered:
            any_unsupported_coverage = True
        coverage_by_target[target_name] = {
            "nearest_distance": nearest_distance,
            "nearest_design_id": target_model["support_design_ids"][nearest_index],
            "coverage_distance_limit": coverage_limit,
            "covered": covered,
        }
        if relative > uncertainty_limit:
            reasons.append(f"relative_uncertainty_exceeded:{target_name}")
    if any_unsupported_coverage:
        reasons.append("outside_sampling_coverage")
    status = "PREDICTED" if not reasons else "NEEDS_SOLVE"
    return {
        "status": status,
        "model_id": model["model_id"],
        "evidence_kind": model["evidence_kind"],
        "predictions": predictions,
        "domain": {
            "inside_bounds": inside_bounds,
            "nearest_distance": global_nearest,
            "nearest_design_id": global_nearest_id,
            "distance_metric": "root-mean-square Euclidean distance after scaling features to declared bounds",
            "coverage_by_target": coverage_by_target,
            "max_relative_std": uncertainty_limit,
            "relative_uncertainty": relative_uncertainty,
            "reasons": reasons,
            "reliability_note": "Being inside parameter bounds does not establish surrogate reliability.",
        },
    }
