"""Small deterministic regression metrics for surrogate validation."""

from __future__ import annotations

import math
from collections.abc import Sequence


def absolute_error_metrics(
    truth: Sequence[float], prediction: Sequence[float]
) -> dict[str, float]:
    """Return absolute regression errors for a non-empty evaluation slice."""
    if len(truth) != len(prediction) or not truth:
        raise ValueError("truth and prediction must have the same non-zero length")
    errors = [
        float(estimate) - float(actual)
        for actual, estimate in zip(truth, prediction, strict=True)
    ]
    absolute = [abs(error) for error in errors]
    mae = math.fsum(absolute) / len(absolute)
    rmse = math.sqrt(math.fsum(error * error for error in errors) / len(errors))
    return {
        "mae": mae,
        "rmse": rmse,
        "max_absolute_error": max(absolute),
    }


def regression_metrics(
    truth: Sequence[float], prediction: Sequence[float], reference_scale: float
) -> dict[str, float | None]:
    """Return regression errors, with R2 omitted when it is undefined."""
    if len(truth) != len(prediction) or not truth:
        raise ValueError("truth and prediction must have the same non-zero length")
    metrics = absolute_error_metrics(truth, prediction)
    errors = [
        float(estimate) - float(actual)
        for actual, estimate in zip(truth, prediction, strict=True)
    ]
    mean_truth = math.fsum(float(value) for value in truth) / len(truth)
    total = math.fsum((float(value) - mean_truth) ** 2 for value in truth)
    residual = math.fsum(error * error for error in errors)
    r2 = 1.0 - residual / total if total > 0.0 else None
    scale = abs(float(reference_scale))
    normalized = metrics["rmse"] / scale if scale > 0.0 else (0.0 if metrics["rmse"] == 0.0 else None)
    return {
        **metrics,
        "normalized_error": normalized,
        "r2": r2,
    }
