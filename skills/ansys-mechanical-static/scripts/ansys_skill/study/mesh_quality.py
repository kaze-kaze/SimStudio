"""Strict evidence checks for the controlled tetrahedral mesh-quality gate."""

from __future__ import annotations

import math
import re
from typing import Any

from ansys_skill.study.storage import canonical_hash
from ansys_skill.validation.statuses import CheckStatus

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

# Direction describes which side of the limit is poor quality. Edge metrics and
# WarpingAngle are retained as diagnostics but do not govern this tetra study.
_METRIC_RULES = {
    "AspectRatio": ("higher", ""),
    "ElementQuality": ("lower", ""),
    "JacobianRatioCornerNodes": ("lower", ""),
    "JacobianRatioGaussPoints": ("lower", ""),
    "MaxEdgeLength": ("higher", "m"),
    "MaximumCornerAngle": ("higher", "deg"),
    "MinEdgeLength": ("lower", "m"),
    "Skewness": ("higher", ""),
    "TetCollapse": ("lower", ""),
    "WarpingAngle": ("higher", "deg"),
}
_REQUIRED_SHAPE_METRICS = frozenset({
    "AspectRatio",
    "ElementQuality",
    "JacobianRatioCornerNodes",
    "JacobianRatioGaussPoints",
    "MaximumCornerAngle",
    "Skewness",
    "TetCollapse",
})
_NUMERIC_FIELDS = ("worst", "average", "error_limit", "warning_limit")


def _finite_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("mesh quality values must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("mesh quality values must be finite")
    return number


def _outside_limit(value: float, limit: float, direction: str) -> bool:
    return value > limit if direction == "higher" else value < limit


def _result(status: CheckStatus, message: str, evidence: dict[str, Any],
            quality_sha256: str | None = None) -> dict[str, Any]:
    return {"status": status.value, "message": message, "evidence": evidence,
            "quality_sha256": quality_sha256}


def assess_mesh_quality(quality: Any) -> dict[str, Any]:
    """Validate the complete metric record while gating on seven shape metrics."""
    if quality is None:
        return _result(CheckStatus.NOT_RUN, "Mesh quality evidence is unavailable", {})
    if not isinstance(quality, dict):
        return _result(CheckStatus.FAIL, "Mesh quality record is malformed",
                       {"error": "mesh_quality must be an object"})
    record_status = quality.get("status")
    if record_status not in {"RECORDED", "NOT_RUN"}:
        return _result(CheckStatus.FAIL, "Mesh quality record has an invalid status",
                       {"status": record_status, "record": quality})
    if "worksheet_active" in quality and not isinstance(quality["worksheet_active"], bool):
        return _result(CheckStatus.FAIL, "Mesh worksheet state is malformed",
                       {"error": "worksheet_active must be boolean when present",
                        "record": quality})

    metrics = quality.get("metrics")
    if metrics is None and record_status == "NOT_RUN":
        return _result(CheckStatus.NOT_RUN, "Mesh quality measurement was not recorded",
                       {"record": quality})
    if not isinstance(metrics, list):
        return _result(CheckStatus.FAIL, "Mesh quality metrics are malformed",
                       {"error": "metrics must be a list", "record": quality})
    names: set[str] = set()
    by_name: dict[str, dict[str, Any]] = {}
    unsupported: list[str] = []
    diagnostic_contradictions: list[str] = []
    try:
        for metric in metrics:
            if not isinstance(metric, dict):
                raise ValueError("each metric must be an object")
            name = metric.get("metric")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("metric identities must be non-empty strings")
            if name in names:
                raise ValueError(f"duplicate metric identity: {name}")
            names.add(name)
            if name not in _METRIC_RULES:
                unsupported.append(name)
            for field in _NUMERIC_FIELDS:
                statistic = metric.get(field)
                if not isinstance(statistic, dict):
                    raise ValueError(f"{name}.{field} must contain value and unit")
                _finite_number(statistic.get("value"))
                if not isinstance(statistic.get("unit"), str):
                    raise ValueError(f"{name}.{field}.unit must be a string")
            direction, expected_unit = _METRIC_RULES.get(name, (None, None))
            if direction is not None:
                wrong_units = [field for field in _NUMERIC_FIELDS
                               if metric[field]["unit"] != expected_unit]
                if wrong_units:
                    raise ValueError(
                        f"{name} requires unit {expected_unit!r} for {', '.join(wrong_units)}")
            for field in ("error_count", "warning_count"):
                count = metric.get(field)
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise ValueError(f"{name}.{field} must be a non-negative integer")
            by_name[name] = metric
        quality_sha256 = canonical_hash(quality)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return _result(CheckStatus.FAIL, "Mesh quality evidence is malformed",
                       {"error": str(exc), "record": quality})

    missing = sorted(_REQUIRED_SHAPE_METRICS - names)
    if missing:
        return _result(CheckStatus.NOT_RUN, "Required mesh shape metrics are missing",
                       {"missing_metrics": missing, "record": quality}, quality_sha256)
    if unsupported:
        return _result(CheckStatus.NOT_RUN, "Mesh quality contains unsupported metric identities",
                       {"unsupported_metrics": sorted(unsupported), "record": quality},
                       quality_sha256)

    if record_status == "NOT_RUN":
        return _result(CheckStatus.NOT_RUN, "Mesh quality measurement was not recorded",
                       {"record": quality}, quality_sha256)

    errors: list[str] = []
    warnings: list[str] = []
    contradictions: list[str] = []
    for name, metric in by_name.items():
        if name not in _METRIC_RULES:
            continue
        direction, _ = _METRIC_RULES[name]
        worst, average, error_limit, warning_limit = (
            float(metric[field]["value"]) for field in _NUMERIC_FIELDS
        )
        error_count, warning_count = metric["error_count"], metric["warning_count"]
        limits_ordered = (warning_limit <= error_limit if direction == "higher"
                          else error_limit <= warning_limit)
        if not limits_ordered:
            message = f"{name}: warning and error limits are reversed"
            (contradictions if name in _REQUIRED_SHAPE_METRICS else diagnostic_contradictions).append(message)
            continue

        worst_is_error = _outside_limit(worst, error_limit, direction)
        worst_is_warning = _outside_limit(worst, warning_limit, direction)
        if ((worst < average and direction == "higher")
                or (worst > average and direction == "lower")):
            message = f"{name}: worst and average contradict the metric direction"
            (contradictions if name in _REQUIRED_SHAPE_METRICS else diagnostic_contradictions).append(message)
        metric_contradictions = []
        if (error_count > 0) != worst_is_error:
            metric_contradictions.append(f"{name}: error_count contradicts worst and error_limit")
        if (warning_count > 0 and not worst_is_warning) or (
                error_count == 0 and (warning_count > 0) != worst_is_warning):
            metric_contradictions.append(f"{name}: warning_count contradicts worst and warning_limit")
        if name in _REQUIRED_SHAPE_METRICS:
            contradictions.extend(metric_contradictions)
            if error_count > 0:
                errors.append(name)
            elif warning_count > 0:
                warnings.append(name)
        else:
            diagnostic_contradictions.extend(metric_contradictions)

    if contradictions:
        return _result(CheckStatus.NOT_RUN, "Mesh quality evidence is internally inconsistent",
                       {"contradictions": contradictions, "record": quality}, quality_sha256)
    status = CheckStatus.FAIL if errors else CheckStatus.WARN if warnings else CheckStatus.PASS
    message = {
        CheckStatus.FAIL: "Required mesh shape metrics report error-limit failures",
        CheckStatus.WARN: "Required mesh shape metrics report warning-limit failures",
        CheckStatus.PASS: "All required mesh shape metrics pass their recorded limits",
    }[status]
    return _result(status, message, {"error_metrics": errors, "warning_metrics": warnings,
                                     "diagnostic_count_contradictions": diagnostic_contradictions,
                                     "record": quality}, quality_sha256)


def mesh_quality_review_check(
    target_name: str, result_file_sha256: str | None, quality_sha256: str | None,
    reviews: Any, raw_status: str,
) -> dict[str, Any]:
    """Validate an explicit review bound to both evidence hashes and one target."""
    evidence = {"result_file_sha256": result_file_sha256,
                "quality_sha256": quality_sha256}
    if raw_status != CheckStatus.WARN.value:
        status = CheckStatus.FAIL if raw_status == CheckStatus.FAIL.value else CheckStatus.NOT_RUN
        return {"status": status.value, "message": "Only raw mesh WARN may be reviewed",
                "evidence": {**evidence, "raw_status": raw_status,
                               "review_status": "NOT_APPLICABLE"}}
    if not isinstance(result_file_sha256, str) or not _SHA256.fullmatch(result_file_sha256):
        return {"status": CheckStatus.NOT_RUN.value, "message": "A verified RST hash is required for mesh review",
                "evidence": {**evidence, "review_status": "REVIEW_REQUIRED"}}
    if not isinstance(quality_sha256, str) or not _SHA256.fullmatch(quality_sha256):
        return {"status": CheckStatus.NOT_RUN.value, "message": "A canonical mesh quality hash is required for review",
                "evidence": {**evidence, "review_status": "REVIEW_REQUIRED"}}
    if reviews is None:
        reviews = {}
    if not isinstance(reviews, dict):
        return {"status": CheckStatus.FAIL.value, "message": "Mesh review records are malformed",
                "evidence": {**evidence, "error": "reviews must be an object"}}
    root = reviews.get(result_file_sha256)
    if root is None:
        return {"status": CheckStatus.NOT_RUN.value, "message": "An explicit mesh quality review is required",
                "evidence": {**evidence, "review_status": "REVIEW_REQUIRED"}}
    if not isinstance(root, dict):
        return {"status": CheckStatus.FAIL.value, "message": "RST review record is malformed",
                "evidence": {**evidence, "error": "RST review record must be an object"}}
    review = root.get("mesh_quality_review")
    if review is None:
        return {"status": CheckStatus.NOT_RUN.value, "message": "RST record has no mesh quality review",
                "evidence": {**evidence, "review_status": "REVIEW_REQUIRED"}}
    if not isinstance(review, dict):
        return {"status": CheckStatus.FAIL.value, "message": "Mesh quality review is malformed",
                "evidence": {**evidence, "error": "mesh_quality_review must be an object"}}
    targets = review.get("targets")
    if (not isinstance(targets, list) or not targets
            or any(not isinstance(item, str) or not item.strip() for item in targets)
            or len(set(targets)) != len(targets)):
        return {"status": CheckStatus.FAIL.value, "message": "Mesh review requires a unique explicit targets list",
                "evidence": {**evidence, "error": "mesh_quality_review.targets must be a non-empty list of unique labels"}}
    if target_name not in targets:
        return {"status": CheckStatus.NOT_RUN.value, "message": "Mesh review does not include this target",
                "evidence": {**evidence, "review_targets": targets,
                               "target_name": target_name, "review_status": "WRONG_TARGET"}}
    reviewer, rationale, citations = (review.get("reviewer"), review.get("rationale"),
                                      review.get("evidence"))
    if (review.get("status") != "PASS" or not isinstance(reviewer, str) or not reviewer.strip()
            or not isinstance(rationale, str) or not rationale.strip()
            or not isinstance(citations, list) or not citations
            or any(not isinstance(item, str) or not item.strip() for item in citations)):
        return {"status": CheckStatus.FAIL.value, "message": "Mesh review requires PASS, reviewer, rationale, and evidence",
                "evidence": {**evidence, "review_targets": targets,
                               "review_status": review.get("status")}}
    if review.get("quality_sha256") != quality_sha256:
        return {"status": CheckStatus.FAIL.value, "message": "Mesh review quality hash does not match the raw record",
                "evidence": {**evidence, "review_targets": targets,
                               "review_quality_sha256": review.get("quality_sha256"),
                               "review_status": "HASH_MISMATCH"}}
    return {"status": CheckStatus.PASS.value, "message": "Mesh warning review matches the current RST and raw quality evidence",
            "evidence": {**evidence, "review_targets": targets, "review_status": "PASS",
                           "reviewer": reviewer, "rationale": rationale, "evidence": citations}}


def mesh_target_gate(raw_status: str, review_status: str | None = None) -> CheckStatus:
    """Permit only clean evidence or an explicitly reviewed raw warning."""
    if raw_status == CheckStatus.PASS.value:
        return CheckStatus.PASS
    if raw_status == CheckStatus.FAIL.value:
        return CheckStatus.FAIL
    if raw_status == CheckStatus.WARN.value:
        if review_status == CheckStatus.PASS.value:
            return CheckStatus.PASS
        if review_status == CheckStatus.FAIL.value:
            return CheckStatus.FAIL
        return CheckStatus.NOT_RUN
    return CheckStatus.NOT_RUN


def mesh_review_matches_target(
    review_check: dict[str, Any] | None, target_name: str,
    result_file_sha256: str | None, quality_sha256: str | None,
) -> bool:
    """Require an evaluated review record to carry both hashes and its target."""
    if not isinstance(review_check, dict) or review_check.get("status") != CheckStatus.PASS.value:
        return False
    evidence = review_check.get("evidence")
    return (isinstance(evidence, dict)
            and isinstance(result_file_sha256, str)
            and _SHA256.fullmatch(result_file_sha256) is not None
            and isinstance(quality_sha256, str)
            and _SHA256.fullmatch(quality_sha256) is not None
            and evidence.get("result_file_sha256") == result_file_sha256
            and evidence.get("quality_sha256") == quality_sha256
            and isinstance(evidence.get("review_targets"), list)
            and target_name in evidence["review_targets"]
            and evidence.get("review_status") == "PASS"
            and isinstance(evidence.get("reviewer"), str)
            and bool(evidence["reviewer"].strip())
            and isinstance(evidence.get("rationale"), str)
            and bool(evidence["rationale"].strip())
            and isinstance(evidence.get("evidence"), list)
            and bool(evidence["evidence"])
            and all(isinstance(item, str) and item.strip() for item in evidence["evidence"]))
