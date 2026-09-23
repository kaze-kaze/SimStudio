"""Small deterministic regression metrics for surrogate validation."""

from __future__ import annotations

import math
from collections.abc import Sequence


def regression_metrics(
    truth: Sequence[float], prediction: Sequence[float], reference_scale: float
) -> dict[str, float | None]:
    """Return regression errors, with R2 omitted when it is undefined."""
    if len(truth) != len(prediction) or not truth:
        raise ValueError("truth and prediction must have the same non-zero length")
    errors = [
        float(estimate) - float(actual)
        for actual, estimate in zip(truth, prediction, strict=True)
    ]
    absolute = [abs(error) for error in errors]
    mae = math.fsum(absolute) / len(absolute)
    rmse = math.sqrt(math.fsum(error * error for error in errors) / len(errors))
    mean_truth = math.fsum(float(value) for value in truth) / len(truth)
    total = math.fsum((float(value) - mean_truth) ** 2 for value in truth)
    residual = math.fsum(error * error for error in errors)
    r2 = 1.0 - residual / total if total > 0.0 else None
    scale = abs(float(reference_scale))
    normalized = rmse / scale if scale > 0.0 else (0.0 if rmse == 0.0 else None)
    return {
        "mae": mae,
        "rmse": rmse,
        "max_absolute_error": max(absolute),
        "normalized_error": normalized,
        "r2": r2,
    }
