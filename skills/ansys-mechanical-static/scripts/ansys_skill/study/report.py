"""Generate a deterministic, self-contained report for a design study."""

from __future__ import annotations

import html
import json
import math
from collections.abc import Mapping
from numbers import Real
from pathlib import Path, PureWindowsPath
from typing import Any

from ansys_skill.errors import SpecValidationError
from ansys_skill.paths import PathSafetyError, safe_join
from ansys_skill.study import project
from ansys_skill.study.report_assets import REPORT_CSS, REPORT_JS
from ansys_skill.study.storage import atomic_text
from ansys_skill.units import convert_canonical_value

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_MISSING = object()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _fmt(value: object, digits: int = 6) -> str:
    parsed = _number(value)
    return "NOT_RUN" if parsed is None else format(parsed, f".{digits}g")


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else "NOT_RUN"), quote=True)


def _display_number(value: float, dimension: str, unit: str) -> float | None:
    try:
        return _number(convert_canonical_value(value, dimension, unit))
    except (KeyError, TypeError, ValueError, SpecValidationError):
        return None


def _quantity(value: object, dimension: str, unit: str) -> str:
    parsed = _number(value)
    if parsed is None:
        return "NOT_RUN"
    converted = _display_number(parsed, dimension, unit)
    return "INVALID_UNIT" if converted is None else f"{_fmt(converted)} {unit}".strip()


def _state(value: object) -> str:
    state = str(value or "NOT_RUN").upper()
    if state in {"PASS", "SOLVED", "REPORTED", "VERIFIED"}:
        return "pass"
    if state in {"FAIL", "FAILED", "INFEASIBLE"}:
        return "fail"
    if state == "REVIEW_REQUIRED":
        return "warn"
    if state in {"WARN", "PARTIAL", "NOT_RUN", "UNKNOWN"}:
        return state.lower()
    return ""


def _status(value: object) -> str:
    return str(value or "NOT_RUN").upper()


def _safe_path(root: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    windows_path = PureWindowsPath(value)
    if windows_path.is_absolute() or windows_path.drive or value.startswith(("/", "\\")):
        return None
    normalized = value.replace("\\", "/")
    try:
        path = safe_join(root, normalized)
        cursor = root
        for part in Path(normalized).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return None
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            return None
        return path
    except (OSError, PathSafetyError, RuntimeError, ValueError):
        return None


def _read_json(root: Path, relative: object) -> dict[str, Any] | None:
    path = _safe_path(root, relative)
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _target_specs(study: object) -> dict[str, Any]:
    return dict(getattr(study, "targets", {}) or {})


def _target_names(study: object, dataset: Mapping[str, Any]) -> list[str]:
    names = list(_target_specs(study)) or list(_mapping(dataset.get("targets")))
    return [str(name) for name in names]


def _target_unit(name: str, study: object, dataset: Mapping[str, Any]) -> tuple[str, str]:
    spec = _target_specs(study).get(name)
    if spec is not None:
        return str(getattr(spec, "dimension", "")), str(getattr(spec, "unit", ""))
    metadata = _mapping(_mapping(dataset.get("targets")).get(name))
    return (str(metadata.get("dimension", "")),
            str(metadata.get("display_unit", metadata.get("unit", ""))))


def _feature_unit(name: str, study: object, dataset: Mapping[str, Any]) -> str:
    features = getattr(study, "parameters", {}) or {}
    feature = features.get(name) if isinstance(features, Mapping) else None
    baseline = getattr(feature, "baseline", None)
    if isinstance(baseline, str) and baseline.split():
        return baseline.split()[-1]
    return str(_mapping(dataset.get("feature_units")).get(name, ""))


def _target_value(values: object, target: str, result_id: str | None = None) -> object:
    data = _mapping(values)
    return data.get(target, data.get(result_id, _MISSING) if result_id else _MISSING)


def _value_number(value: object) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("value", value.get("mean", value.get("maximum")))
    return _number(value)


def _sample_rows(dataset: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in _list(dataset.get("rows")) if isinstance(row, Mapping)]


def _accepted(row: Mapping[str, Any]) -> set[str]:
    return {str(value) for value in _list(row.get("accepted_targets")) if isinstance(value, str)}


def _attempts(sample: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = []
    for job_value in _list(sample.get("jobs")):
        job = _mapping(job_value)
        for kind, items in (("attempt", _list(job.get("attempts"))),
                            ("preview", _list(job.get("previews")))):
            for item in items:
                if isinstance(item, Mapping):
                    records.append({"kind": kind, "mesh_index": job.get("mesh_index"),
                                    "mesh_size": job.get("mesh_size"), **dict(item)})
    return records


def _sample_status(sample: Mapping[str, Any]) -> str:
    status = _status(sample.get("status"))
    jobs = [_mapping(job) for job in _list(sample.get("jobs"))]
    if jobs:
        latest = [_status(_mapping(_list(job.get("attempts"))[-1]).get("status"))
                  if _list(job.get("attempts")) else None for job in jobs]
        recorded = [value for value in latest if value is not None]
        if recorded and len(recorded) == len(jobs) and all(value == "SOLVED" for value in recorded):
            return "SOLVED"
        if "INTERRUPTED" in recorded:
            return "INTERRUPTED"
        if "RUNNING" in recorded:
            return "RUNNING"
        if "FAILED" in recorded:
            return "FAILED"
        if "DRY_RUN" in recorded:
            return "DRY_RUN"
        if "SOLVED" in recorded:
            return "PARTIAL"
    return status


def _quality_status(row: Mapping[str, Any]) -> str:
    levels = _list(row.get("quality"))
    if levels:
        return _status(_mapping(levels[-1]).get("status"))
    return "NOT_RUN"


def _mesh_records(rows: list[dict[str, Any]], targets: list[str], study: object) -> dict[str, list[dict[str, Any]]]:
    result = {target: [] for target in targets}
    result_ids = {name: str(getattr(spec, "result_id", name))
                  for name, spec in _target_specs(study).items()}
    for row in rows:
        qualities = _list(row.get("quality"))
        sources = _list(_mapping(row.get("source")).get("runs"))
        convergence = _mapping(_mapping(row.get("mesh_convergence")).get("targets"))
        for target in targets:
            target_convergence = _mapping(convergence.get(target))
            levels = _list(target_convergence.get("levels"))
            adjacent = _list(target_convergence.get("adjacent_changes"))
            for index, level_value in enumerate(qualities):
                level = _mapping(level_value)
                source = _mapping(sources[index]) if index < len(sources) else {}
                raw = _target_value(level.get("values"), target, result_ids.get(target))
                if raw is _MISSING:
                    raw = _target_value(level.get("targets"), target, result_ids.get(target))
                value = _value_number(raw)
                check_statuses = [_status(_mapping(check).get("status"))
                                  for check in _list(_mapping(level.get("target_checks")).get(target))]
                if check_statuses and all(status == "PASS" for status in check_statuses):
                    level_status = "PASS"
                elif "FAIL" in check_statuses:
                    level_status = "FAIL"
                else:
                    level_status = "NOT_RUN"
                change = _number(_mapping(adjacent[index - 1]).get("relative_change")) if index else None
                if change is None and index == len(qualities) - 1:
                    change = _number(target_convergence.get("relative_change"))
                result[target].append({
                    "sample_id": row.get("sample_id", "NOT_RUN"),
                    "mesh_size": source.get("mesh_size", _mapping(level.get("evidence")).get("mesh_size_m")),
                    "value": value,
                    "relative_change": change,
                    "status": level_status,
                    "overall_status": _status(level.get("status")),
                })
            if not qualities:
                for value in levels:
                    level = _mapping(value)
                    result[target].append({
                        "sample_id": row.get("sample_id", "NOT_RUN"),
                        "mesh_size": level.get("mesh_size"),
                        "value": _value_number(level.get("value", level)),
                        "relative_change": _number(level.get(
                            "relative_change", level.get("relative_error"))),
                        "status": level.get("status", target_convergence.get("status", "NOT_RUN")),
                    })
    return result


def _evaluation_points(evaluation: Mapping[str, Any], target: str) -> list[tuple[float, float]]:
    target_data = _mapping(_mapping(evaluation.get("targets", evaluation.get("results"))).get(target))
    records: list[Any] = []
    for key in ("points", "samples", "observations", "predictions", "rows"):
        records.extend(_list(target_data.get(key)))
        records.extend(_list(evaluation.get(key)))
    points = []
    for value in records:
        item = _mapping(value)
        actual = next((item[key] for key in ("actual", "truth", "observed", "true", "measured")
                       if key in item), _MISSING)
        predicted = next((item[key] for key in
                          ("predicted", "prediction", "estimate", "predicted_value")
                          if key in item), _MISSING)
        if actual is _MISSING:
            actual = _target_value(item.get("targets", item.get("actuals")), target)
        if predicted is _MISSING:
            predicted = _target_value(item.get("predictions", item.get("estimates")), target)
        actual_number, predicted_number = _value_number(actual), _value_number(predicted)
        if actual_number is not None and predicted_number is not None:
            points.append((actual_number, predicted_number))
    return points


def _evaluation_records(evaluation: Mapping[str, Any], target: str,
                        dimension: str, unit: str) -> list[dict[str, float]]:
    target_data = _mapping(_mapping(evaluation.get("targets", evaluation.get("results"))).get(target))
    records = []
    for point_value in _list(target_data.get("points")):
        point = _mapping(point_value)
        values = {name: _number(point.get(name)) for name in ("truth", "prediction", "std")}
        if values["truth"] is None or values["prediction"] is None:
            continue
        values = {name: _display_number(value, dimension, unit)
                  for name, value in values.items() if value is not None}
        if values.get("truth") is None or values.get("prediction") is None:
            continue
        records.append({name: value for name, value in values.items() if value is not None})
    return records


def _scatter_svg(points: list[dict[str, float]], target: str, unit: str) -> str:
    width, height = 560, 330
    left, right, top, bottom = 65.0, 18.0, 20.0, 52.0
    values = [value for point in points for value in (point["truth"], point["prediction"])]
    low, high = min(values), max(values)
    padding = (high - low) * 0.08 if high > low else max(abs(low) * 0.08, 1.0)
    low, high = low - padding, high + padding
    plot_width, plot_height = width - left - right, height - top - bottom

    def xmap(value: float) -> float:
        return left + (value - low) / (high - low) * plot_width

    def ymap(value: float) -> float:
        return top + (high - value) / (high - low) * plot_height

    grid = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        x, y = left + fraction * plot_width, top + fraction * plot_height
        tick = low + fraction * (high - low)
        grid.append(
            f'<line x1="{x:.2f}" y1="{top:.2f}" x2="{x:.2f}" y2="{top + plot_height:.2f}" stroke="#e0e5e8"/>'
            f'<line x1="{left:.2f}" y1="{y:.2f}" x2="{left + plot_width:.2f}" y2="{y:.2f}" stroke="#e0e5e8"/>'
            f'<text x="{x:.2f}" y="{top + plot_height + 18:.2f}" text-anchor="middle" fill="#65717d" font-size="10">{_e(_fmt(tick, 3))}</text>'
            f'<text x="{left - 9:.2f}" y="{y + 3:.2f}" text-anchor="end" fill="#65717d" font-size="10">{_e(_fmt(high - fraction * (high - low), 3))}</text>'
        )
    circles = "".join(
        (f'<line x1="{xmap(point["truth"]):.2f}" y1="{ymap(point["prediction"] + point["std"]):.2f}" '
         f'x2="{xmap(point["truth"]):.2f}" y2="{ymap(point["prediction"] - point["std"]):.2f}" stroke="#245f98" stroke-opacity=".45"/>'
         if point.get("std") is not None else "")
        + f'<circle cx="{xmap(point["truth"]):.2f}" cy="{ymap(point["prediction"]):.2f}" r="4" fill="#245f98" fill-opacity=".78"/>'
        for point in points
    )
    identity = (f'<line x1="{xmap(low):.2f}" y1="{ymap(low):.2f}" '
                f'x2="{xmap(high):.2f}" y2="{ymap(high):.2f}" '
                'stroke="#65717d" stroke-dasharray="5 4"/>')
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{_e(target)} predicted versus true scatter">'
        + "".join(grid) + identity + circles
        + f'<text x="{left + plot_width / 2:.2f}" y="{height - 8}" text-anchor="middle" fill="#34414c" font-size="11">Truth ({_e(unit)})</text>'
        + f'<text transform="translate(15 {top + plot_height / 2:.2f}) rotate(-90)" text-anchor="middle" fill="#34414c" font-size="11">Prediction ({_e(unit)})</text></svg>'
    )


def _attempt_image_evidence(root: Path, samples: list[dict[str, Any]]) -> list[dict[str, str]]:
    images, seen = [], set()
    for sample in samples:
        for attempt in _attempts(sample):
            run_path = attempt.get("path")
            if not isinstance(run_path, str) or PureWindowsPath(run_path).is_absolute():
                continue
            run_path = run_path.replace("\\", "/").rstrip("/")
            artifacts = _read_json(root, f"{run_path}/mechanical-artifacts.json")
            for item_value in _list(_mapping(artifacts).get("visual_review")):
                item = _mapping(item_value)
                name = item.get("name")
                if item.get("status") != "PASS" or not isinstance(name, str):
                    continue
                relative = f"{run_path}/{name.replace(chr(92), '/').lstrip('/')}"
                path = _safe_path(root, relative)
                if path is None or path.suffix.lower() not in _IMAGE_SUFFIXES:
                    continue
                canonical = path.relative_to(root).as_posix()
                if canonical not in seen:
                    seen.add(canonical)
                    images.append({"path": canonical,
                                   "sample_id": str(sample.get("sample_id", "NOT_RUN"))})
    return images


def _phase_rows(manifest: Mapping[str, Any], samples: list[dict[str, Any]],
                models: list[dict[str, Any]], rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    attempts = [attempt for sample in samples for attempt in _attempts(sample)]
    real = [item for item in attempts if item["kind"] == "attempt"]
    previews = [item for item in attempts if item["kind"] == "preview"]
    phases = _mapping(manifest.get("phase_timings", manifest.get("phases")))

    def durations(records: list[Mapping[str, Any]], field: str = "elapsed_seconds") -> float | None:
        values = [_number(item.get(field)) for item in records]
        if not values or any(value is None or value < 0 for value in values):
            return None
        return sum(values)

    def recorded_phase(key: str, label: str, records: list[Mapping[str, Any]],
                       field: str = "elapsed_seconds") -> dict[str, Any]:
        phase = _mapping(phases.get(key))
        if phase and phase.get("status") == "RECORDED" and key in _mapping(manifest.get("phase_timings")):
            return {"name": label, "status": phase.get("status", "NOT_RUN"),
                    "seconds": _number(phase.get("elapsed_seconds", phase.get("seconds"))),
                    "calls": _number(phase.get("calls", phase.get("call_count")))}
        if records:
            return {"name": label, "status": "RECORDED",
                    "seconds": durations(records, field), "calls": len(records)}
        phase = _mapping(phases.get(key))
        return {"name": label, "status": phase.get("status", "NOT_RUN"),
                "seconds": _number(phase.get("elapsed_seconds", phase.get("seconds"))),
                "calls": _number(phase.get("calls", phase.get("call_count")))}

    rows = [
        {"name": "Solver attempts", "status": "RECORDED" if real else "NOT_RUN",
         "seconds": durations(real),
         "calls": _number(manifest.get("solver_calls")) if _number(manifest.get("solver_calls")) is not None else len(real)},
        {"name": "Dry-run / preview", "status": "RECORDED" if previews else "NOT_RUN",
         "seconds": durations(previews), "calls": len(previews) if previews else None},
    ]
    geometry = [{"elapsed_seconds": sample.get("geometry_seconds",
                    _mapping(sample.get("geometry")).get("geometry_seconds"))}
                for sample in samples if sample.get("geometry") or "geometry_seconds" in sample]
    geometry_phase = recorded_phase("geometry", "Geometry preparation", geometry)
    if _number(manifest.get("geometry_seconds")) is not None:
        geometry_phase.update(status="RECORDED", seconds=_number(manifest["geometry_seconds"]))
    rows.append(geometry_phase)
    rows.append(recorded_phase("collection", "Data collection and quality checks", []))
    rows.append(recorded_phase("model_training", "Surrogate training",
                [_mapping(model) for model in _list(manifest.get("models"))], "training_seconds"))
    evaluations = [_mapping(model.get("evaluation")) for model in models
                   if model.get("evaluation_present") or model.get("evaluation")]
    rows.append(recorded_phase("evaluation", "Holdout evaluation", evaluations, "evaluation_seconds"))
    plans = [_mapping(record.get("plan_data")) for record in rounds if record.get("plan_data")]
    rows.append(recorded_phase("optimization", "Candidate search", plans, "search_seconds"))
    rows.append(recorded_phase("round_execution", "Optimization rounds",
                [record for record in rounds if "elapsed_seconds" in record]))
    for split, label in (("verification", "Candidate verification"), ("comparison", "Direct comparison")):
        records = [attempt for sample in samples if sample.get("split") == split
                   for attempt in _attempts(sample) if attempt["kind"] == "attempt"]
        rows.append(recorded_phase(split, label, records))
    total = _number(manifest.get("elapsed_seconds"))
    rows.append({"name": "Study elapsed time", "status": "RECORDED" if total is not None else "NOT_RUN",
                 "seconds": total, "calls": None})
    return rows


def _render_metrics(models: list[dict[str, Any]], targets: list[str], study: object,
                    dataset: Mapping[str, Any]) -> tuple[str, str]:
    tables, charts = [], []
    for model in models:
        card, evaluation = _mapping(model.get("card")), _mapping(model.get("evaluation"))
        eval_targets = _mapping(evaluation.get("targets", evaluation.get("results")))
        training_counts = _mapping(card.get("training_sample_count_by_target"))
        model_selection = _mapping(card.get("model_selection"))
        body = []
        for target in targets:
            result = _mapping(eval_targets.get(target))
            metrics = _mapping(result.get("metrics"))
            selection = _mapping(model_selection.get(target))
            cross_validation = _mapping(selection.get("cross_validation"))
            cv_metrics = _mapping(cross_validation.get("selected_metrics"))
            dimension, unit = _target_unit(target, study, dataset)
            cells = [target, selection.get("selected_model", "NOT_RUN"),
                     _quantity(cv_metrics.get("rmse"), dimension, unit), _status(result.get("status")), training_counts.get(target, "NOT_RUN"),
                     result.get("sample_count", "NOT_RUN")]
            for metric_name in ("mae", "rmse"):
                cells.append(_quantity(metrics.get(metric_name), dimension, unit))
            cells.extend((_fmt(metrics.get("normalized_error")), _fmt(metrics.get("r2"))))
            body.append("<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in cells) + "</tr>")
            point_records = _evaluation_records(evaluation, target, dimension, unit)
            if _display_number(1.0, dimension, unit) is None:
                charts.append(f'<p class="chart-empty">{_e(target)}: INVALID_UNIT. Display unit conversion failed.</p>')
            elif point_records:
                charts.append(
                    f'<figure class="chart">{_scatter_svg(point_records, target, unit)}'
                    f'<figcaption>{_e(target)}: {len(point_records)} measured and predicted pairs with recorded standard deviation; dashed line is y = x.</figcaption></figure>'
                )
            else:
                charts.append(f'<p class="chart-empty">{_e(target)}: NOT_RUN. Evaluation has no paired truth and prediction values.</p>')
        tables.append(
            f'<p class="muted">Model <code>{_e(model.get("model_id"))}</code> · evaluation: {_e(_status(evaluation.get("status")))} · training dataset: <code>{_e(model.get("dataset_id"))}</code></p>'
            '<div class="table-wrap"><table><thead><tr><th>Target</th><th>Selected model</th><th>CV RMSE</th><th>Evaluation status</th><th>Training samples</th><th>Test samples</th><th>MAE</th><th>RMSE</th><th>Normalized error</th><th>R²</th></tr></thead><tbody>'
            + "".join(body) + "</tbody></table></div>"
        )
    if not models:
        tables.append('<p class="chart-empty">NOT_RUN: no model card or evaluation file is available. The test split remains held out.</p>')
    return "".join(tables), '<h3>Predicted versus truth</h3>' + "".join(charts)


def _candidate_status(candidate: Mapping[str, Any], *, confirmed: bool = False) -> str:
    if not confirmed and "feasible" not in candidate and candidate.get("verified") is not True:
        return _status(candidate.get("status"))
    if candidate.get("verified") is not True:
        return "REVIEW_REQUIRED"
    if candidate.get("feasible") is True:
        return "VERIFIED"
    if candidate.get("feasible") is False:
        return "INFEASIBLE"
    return "REVIEW_REQUIRED"


def _candidate_table(candidates: list[Any], targets: list[str], study: object,
                     dataset: Mapping[str, Any], truth_by_id: Mapping[str, Any] | None = None,
                     *, confirmed: bool = False) -> str:
    body = []
    for candidate_value in candidates:
        candidate = _mapping(candidate_value)
        status = _candidate_status(candidate, confirmed=confirmed)
        identifier = str(candidate.get("sample_id", candidate.get("candidate_id", "candidate")))
        parameters = _mapping(candidate.get("parameters"))
        parameter_text = "; ".join(
            f"{_e(key)} {_e(_quantity(value, 'length', _feature_unit(str(key), study, dataset)))}"
            for key, value in parameters.items()
        ) or "NOT_RUN"
        predicted = _mapping(candidate.get("predictions"))
        actual = _mapping(candidate.get("targets"))
        if not actual and truth_by_id:
            actual = _mapping(truth_by_id.get(identifier))
        errors = _mapping(candidate.get("prediction_errors"))
        target_text = []
        for target in targets:
            dimension, unit = _target_unit(target, study, dataset)
            pred = _target_value(predicted, target)
            true = _target_value(actual, target)
            error = _target_value(errors, target)
            pred_text = _quantity(_value_number(pred), dimension, unit) if pred is not _MISSING and unit else "NOT_RUN"
            true_text = _quantity(_value_number(true), dimension, unit) if true is not _MISSING and unit else "NOT_RUN"
            error_text = _quantity(_value_number(error), dimension, unit) if error is not _MISSING and unit else "NOT_RUN"
            feasible = candidate.get("feasible", "NOT_RUN")
            if isinstance(feasible, Mapping):
                feasible = feasible.get(target, "NOT_RUN")
            constraint = _status(feasible) if isinstance(feasible, str) else "PASS" if feasible else "FAIL"
            if status == "REVIEW_REQUIRED":
                constraint = "REVIEW_REQUIRED"
            target_text.append(f"<span class=\"candidate-target\">{_e(target)}: predicted {_e(pred_text)} · truth {_e(true_text)} · error {_e(error_text)} · constraint {_e(constraint)}</span>")
        mass = _number(candidate.get("mass_kg"))
        body.append(
            f'<tr class="candidate-row"><td><code>{_e(identifier)}</code></td><td>{parameter_text}</td>'
            f'<td>{_e(_fmt(mass) + " kg" if mass is not None else "NOT_RUN")}</td>'
            f'<td>{"".join(target_text) or "NOT_RUN"}</td>'
            f'<td><span class="inline-state" data-state="{_e(_state(status))}">{_e(status)}</span></td></tr>'
        )
    if not body:
        body.append('<tr><td colspan="5" class="muted">NOT_RUN: no candidate records.</td></tr>')
    return (
        '<div class="table-wrap"><table><thead><tr><th>Candidate</th><th>Parameters</th><th>Mass</th>'
        '<th>Prediction, truth, error, and constraints</th><th>Status</th></tr></thead><tbody>'
        + "".join(body) + "</tbody></table></div>"
    )


def _rounds_html(root: Path, rounds: list[dict[str, Any]], targets: list[str],
                 study: object, dataset: Mapping[str, Any]) -> str:
    if not rounds:
        return '<h3>Optimization rounds</h3><p class="muted">NOT_RUN: no optimization rounds are recorded in the manifest.</p>'
    output = []
    for record_value in rounds:
        record = _mapping(record_value)
        plan_ref = record.get("plan")
        plan = _read_json(root, plan_ref) if plan_ref else None
        heading = f'Round {_e(record.get("round", "?"))}'
        if plan is None:
            output.append(f'<h3>{heading}</h3><p class="muted">NOT_RUN: plan file is missing or its path is unsafe.</p>')
            continue
        output.append(f'<h3>{heading} · {_e(_status(plan.get("status", "RECORDED")))}</h3>')
        output.append(_candidate_table(_list(plan.get("candidates")), targets, study, dataset))
        output.append(f'<p class="muted">Plan evidence: <code>{_e(plan_ref)}</code></p>')
    return "".join(output)


def _detail_html(sample: Mapping[str, Any], row: Mapping[str, Any], targets: list[str],
                 features: list[str], study: object, dataset: Mapping[str, Any]) -> str:
    sample_id = str(sample.get("sample_id", "NOT_RUN"))
    parameters = _mapping(sample.get("parameters", row.get("parameters")))
    items = [
        f'<li><strong>{_e(name)}</strong> {_e(_quantity(parameters.get(name), "length", _feature_unit(name, study, dataset)))}</li>'
        for name in features
    ]
    target_specs = _target_specs(study)
    for target in targets:
        dimension, unit = _target_unit(target, study, dataset)
        spec = target_specs.get(target)
        raw = _target_value(row.get("targets"), target, str(getattr(spec, "result_id", target)))
        value = _quantity(raw, dimension, unit) if raw is not _MISSING and unit else "NOT_RUN"
        quality = "PASS" if target in _accepted(row) else "WARN" if row else "NOT_RUN"
        quality_text = f" · {_e(quality)}" if quality != "NOT_RUN" or value != "NOT_RUN" else ""
        items.append(f"<li><strong>{_e(target)}</strong> {_e(value)}{quality_text}</li>")
    evidence = []
    for attempt in _attempts(sample):
        evidence.append(
            "<li>{} · mesh {} · {} · {} s · <code>{}</code></li>".format(
                _e(attempt.get("kind")), _e(attempt.get("mesh_index")),
                _e(_status(attempt.get("status"))), _e(_fmt(attempt.get("elapsed_seconds"))),
                _e(attempt.get("path", "NOT_RUN")),
            )
        )
    content = '<ul class="evidence-list">' + "".join(items) + "</ul>"
    if evidence:
        content += '<h3>Solver and preview records</h3><ul class="evidence-list">' + "".join(evidence) + "</ul>"
    return (
        f'<tr class="detail-row" data-detail-for="{_e(sample_id)}"><td colspan="{4 + len(features) + len(targets)}">'
        f'<details><summary>Expand parameters and evidence</summary>{content}</details></td></tr>'
    )


def _sample_section(samples: list[dict[str, Any]], rows: list[dict[str, Any]], targets: list[str],
                    features: list[str], study: object, dataset: Mapping[str, Any],
                    dataset_path: str | None) -> str:
    by_id = {str(row.get("sample_id")): row for row in rows}
    status_options = sorted({_sample_status(sample) for sample in samples})
    headers = [
        '<th><button type="button" data-sort="sample">Sample</button></th>',
        '<th><button type="button" data-sort="split">Split</button></th>',
        '<th><button type="button" data-sort="status">Status</button></th>',
        '<th><button type="button" data-sort="mass">Mass (kg)</button></th>',
    ]
    headers.append("<th>Overall quality</th>")
    headers.extend(f"<th>{_e(name)} ({_e(_feature_unit(name, study, dataset))})</th>" for name in features)
    headers.extend(f"<th>{_e(name)} ({_e(_target_unit(name, study, dataset)[1] or 'unit unavailable')})</th>" for name in targets)
    body = []
    for sample in samples:
        sample_id = str(sample.get("sample_id", "NOT_RUN"))
        row = by_id.get(sample_id, {})
        params = _mapping(sample.get("parameters", row.get("parameters")))
        target_values = _mapping(row.get("targets"))
        mass = _number(row.get("mass_kg", _mapping(sample.get("geometry")).get("mass_kg")))
        state, split = _sample_status(sample), str(sample.get("split", "NOT_RUN"))
        search_text = " ".join([sample_id, split, *(f"{key} {value}" for key, value in params.items())])
        row_quality = _quality_status(row)
        cells = [
            f"<td><code>{_e(sample_id)}</code></td>", f"<td>{_e(split)}</td>",
            f'<td><span class="inline-state" data-state="{_e(_state(state))}">{_e(state)}</span></td>',
            f"<td>{_e(_fmt(mass) + ' kg' if mass is not None else 'NOT_RUN')}</td>",
            f'<td><span class="inline-state" data-state="{_e(_state(row_quality))}">{_e(row_quality)}</span></td>',
        ]
        for name in features:
            unit = _feature_unit(name, study, dataset)
            cells.append(f"<td>{_e(_quantity(params.get(name), 'length', unit) if unit else _fmt(params.get(name)))}</td>")
        for target in targets:
            dimension, unit = _target_unit(target, study, dataset)
            spec = _target_specs(study).get(target)
            raw = _target_value(target_values, target, str(getattr(spec, "result_id", target)))
            value = _quantity(raw, dimension, unit) if raw is not _MISSING and unit else "NOT_RUN"
            quality = "PASS" if target in _accepted(row) else "WARN" if row else "NOT_RUN"
            quality_text = (f'<br><span class="inline-state" data-state="{_e(_state(quality))}">{quality}</span>'
                            if quality != "NOT_RUN" or value != "NOT_RUN" else "")
            cells.append(f"<td>{_e(value)}{quality_text}</td>")
        body.append(
            f'<tr class="sample-row" data-sample="{_e(sample_id)}" data-split="{_e(split)}" '
            f'data-status="{_e(state)}" data-search="{_e(search_text)}" '
            f'data-mass="{_e(mass if mass is not None else "")}">' + "".join(cells) + "</tr>"
            + _detail_html(sample, row, targets, features, study, dataset)
        )
    reference = f' · <code>{_e(dataset_path)}</code>' if dataset_path else ""
    state = "AVAILABLE" if dataset else "NOT_RUN"
    return (
        '<div class="section-head"><h2>Sample distribution and quality</h2>'
        f'<span class="section-note">Dataset: <span class="inline-state" data-state="{_e(_state(state))}">{state}</span>{reference}</span></div>'
        '<div class="controls">'
        '<label class="control" for="filter-split">Sample split<select id="filter-split" aria-label="Sample split"><option value="all">All</option><option value="baseline">baseline</option><option value="train">train</option><option value="test">test</option></select></label>'
        '<label class="control" for="filter-status">Sample status<select id="filter-status" aria-label="Sample status"><option value="all">All</option>'
        + "".join(f'<option value="{_e(value)}">{_e(value)}</option>' for value in status_options)
        + '</select></label><label class="control" for="filter-query">Find sample<input id="filter-query" type="search" autocomplete="off" placeholder="ID or parameter"></label>'
        f'<span class="filter-count" id="filter-count">{len(samples)} / {len(samples)} samples</span></div>'
        '<div class="table-wrap"><table id="sample-table"><thead><tr>' + "".join(headers)
        + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
    )


def _mesh_html(mesh: Mapping[str, list[dict[str, Any]]], targets: list[str], study: object,
               dataset: Mapping[str, Any]) -> str:
    sections = []
    for target in targets:
        dimension, unit = _target_unit(target, study, dataset)
        rows = []
        for item in mesh.get(target, []):
            value = _quantity(item.get("value"), dimension, unit) if unit else "NOT_RUN"
            change = _number(item.get("relative_change"))
            change_text = f"{_fmt(change * 100)}%" if change is not None else "NOT_RUN"
            status = item.get("status", "NOT_RUN")
            rows.append(
                f'<tr class="mesh-row"><td><code>{_e(item.get("sample_id"))}</code></td>'
                f'<td>{_e(item.get("mesh_size"))}</td><td>{_e(value)}</td><td>{_e(change_text)}</td>'
                f'<td><span class="inline-state" data-state="{_e(_state(status))}">{_e(status)}</span></td></tr>'
            )
        if not rows:
            rows.append('<tr><td colspan="5" class="muted">NOT_RUN: No per-mesh target values are available.</td></tr>')
        sections.append(
            f'<h3>{_e(target)} · {_e(unit or "unit unavailable")}</h3><div class="table-wrap"><table><thead>'
            '<tr><th>Sample</th><th>Mesh size</th><th>Target value</th><th>Relative change</th><th>Convergence status</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div>"
        )
    return "".join(sections) if sections else '<p class="muted">NOT_RUN</p>'


def _verification_html(verification: Mapping[str, Any] | None, targets: list[str], study: object,
                       dataset: Mapping[str, Any]) -> str:
    if verification is None:
        return '<h3>Candidate verification · NOT_RUN</h3><p class="muted">verification.json was not found.</p>'
    return (
        f'<h3>Candidate verification · <span class="inline-state" data-state="{_e(_state(verification.get("status")))}">{_e(_status(verification.get("status")))}</span></h3>'
        + _candidate_table(_list(verification.get("candidates")), targets, study, dataset, confirmed=True)
        + f'<p>Best sample: <code>{_e(verification.get("best_sample_id"))}</code></p>'
    )


def _rounds_html_with_evidence(root: Path, rounds: list[dict[str, Any]], targets: list[str],
                               study: object, dataset: Mapping[str, Any]) -> str:
    if not rounds:
        return '<h3>Optimization rounds</h3><p class="muted">NOT_RUN: no optimization rounds are recorded in the manifest.</p>'
    pieces = []
    for record_value in rounds:
        record = _mapping(record_value)
        reference = record.get("plan")
        plan = _read_json(root, reference) if reference else None
        heading = f'Round {_e(record.get("round", "?"))}'
        if plan is None:
            pieces.append(f'<h3>{heading}</h3><p class="muted">NOT_RUN: plan file is missing or its path is unsafe.</p>')
        else:
            pieces.append(f'<h3>{heading} · {_e(_status(plan.get("status", "RECORDED")))}</h3>')
            pieces.append(_candidate_table(_list(plan.get("candidates")), targets, study, dataset))
            pieces.append(f'<p class="muted">Plan evidence: <code>{_e(reference)}</code></p>')
    return "".join(pieces)


def _phases_html(phases: list[dict[str, Any]]) -> str:
    body = []
    for phase in phases:
        seconds, calls = _number(phase.get("seconds")), _number(phase.get("calls"))
        body.append(
            f'<tr><td>{_e(phase.get("name"))}</td><td><span class="inline-state" data-state="{_e(_state(phase.get("status")))}">{_e(_status(phase.get("status")))}</span></td>'
            f'<td>{_e(_fmt(seconds) + " s" if seconds is not None else "NOT_RUN")}</td>'
            f'<td>{_e(_fmt(calls) if calls is not None else "NOT_RUN")}</td></tr>'
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>Phase</th><th>Record status</th><th>Duration</th><th>Calls</th></tr></thead><tbody>'
        + "".join(body) + "</tbody></table></div>"
    )


def _images_html(images: list[dict[str, str]]) -> str:
    if not images:
        return '<p class="muted">NOT_RUN: No existing image is recorded as successfully exported.</p>'
    figures = []
    for item in images:
        path = _e(item["path"])
        figures.append(
            f'<figure class="image-evidence"><a href="{path}"><img loading="lazy" src="{path}" alt="Mechanical result image from {_e(item["sample_id"])}"></a>'
            f'<figcaption>Mechanical export · sample <code>{_e(item["sample_id"])}</code> · <code>{path}</code></figcaption></figure>'
        )
    return '<div class="image-strip">' + "".join(figures) + "</div>"


def _comparison_html(comparison: Mapping[str, Any] | None) -> str:
    if comparison is None:
        return '<p class="muted">comparison.json: NOT_RUN.</p>'
    items = [f"<li><strong>{_e(key)}</strong> {_e(value)}</li>"
             for key, value in comparison.items()
             if key in {"status", "sample_count", "compared_count", "message", "reason"}]
    return '<ul class="evidence-list">' + "".join(items) + "</ul>" if items else '<p class="muted">Comparison file exists without summary fields.</p>'


def _markdown(study: object, manifest: Mapping[str, Any], dataset: Mapping[str, Any],
              dataset_path: str | None, rows: list[dict[str, Any]], models: list[dict[str, Any]],
              rounds: list[dict[str, Any]], verification: Mapping[str, Any] | None,
              comparison: Mapping[str, Any] | None, mesh: Mapping[str, list[dict[str, Any]]],
              images: list[dict[str, str]], phases: list[dict[str, Any]]) -> str:
    name = getattr(study, "name", manifest.get("name", "Design study"))
    samples = [dict(item) for item in _list(manifest.get("samples")) if isinstance(item, Mapping)]
    targets = _target_names(study, dataset)
    by_id = {str(row.get("sample_id")): row for row in rows}
    completed = sum(_sample_status(item) == "SOLVED" for item in samples)
    accepted = sum(bool(targets) and set(targets).issubset(_accepted(by_id.get(str(item.get("sample_id")), {}))) for item in samples)
    overall = _status(manifest.get("overall", manifest.get("engineering_validation", manifest.get("overall_status", "NOT_RUN"))))
    lines = [f"# {name} — Study report", "",
             f"- Study status: {_status(manifest.get('status'))}",
             f"- Recorded overall verification status: {overall}",
             f"- Study ID: {manifest.get('study_id', 'NOT_RUN')}",
             f"- Planned samples: {len(samples)}; real solves completed: {completed}; quality accepted (all targets): {accepted}",
             f"- Dataset: {dataset_path or 'NOT_RUN'}", "",
             "The test split is held out from training and used only for independent evaluation.", "", "## Sample target values", ""]
    for target in targets:
        dimension, unit = _target_unit(target, study, dataset)
        lines.extend([f"### {target} ({unit or 'unit unavailable'})", "",
                      "| Sample | Split | Status | Value | Quality accepted |", "|---|---|---|---:|---|"])
        for sample in samples:
            row = by_id.get(str(sample.get("sample_id")), {})
            spec = _target_specs(study).get(target)
            raw = _target_value(row.get("targets"), target, str(getattr(spec, "result_id", target)))
            value = _quantity(raw, dimension, unit) if raw is not _MISSING and unit else "NOT_RUN"
            quality = "PASS" if target in _accepted(row) else "WARN" if row else "NOT_RUN"
            lines.append(f"| {sample.get('sample_id', 'NOT_RUN')} | {sample.get('split', 'NOT_RUN')} | {_sample_status(sample)} | {value} | {quality} |")
        lines.append("")
    lines.extend(["## Mesh convergence values", ""])
    for target in targets:
        dimension, unit = _target_unit(target, study, dataset)
        lines.extend([f"### {target} ({unit or 'unit unavailable'})", "",
                      "| Sample | Mesh size (mm) | Target value | Relative change | Status |", "|---|---:|---:|---:|---|"])
        records = mesh.get(target, [])
        for item in records:
            value = _quantity(item.get("value"), dimension, unit) if unit else "NOT_RUN"
            change = _number(item.get("relative_change"))
            delta = f"{_fmt(change * 100)}%" if change is not None else "NOT_RUN"
            lines.append(f"| {item.get('sample_id', 'NOT_RUN')} | {item.get('mesh_size', 'NOT_RUN')} | {value} | {delta} | {_status(item.get('status'))} |")
        if not records:
            lines.append("| NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |")
        lines.append("")
    lines.extend(["## Model evaluation", ""])
    if not models:
        lines.extend(["NOT_RUN: no model or evaluation.json is available.", ""])
    for model in models:
        card, evaluation = _mapping(model.get("card")), _mapping(model.get("evaluation"))
        eval_targets = _mapping(evaluation.get("targets", evaluation.get("results")))
        train_counts = _mapping(card.get("training_sample_count_by_target"))
        lines.extend([f"Model {model.get('model_id', 'NOT_RUN')}", "",
                      "| Target | Status | Training samples | Test samples | CV RMSE | MAE | RMSE | Normalized error | R² |",
                      "|---|---|---:|---:|---:|---:|---:|---:|---:|"])
        for target in targets:
            result = _mapping(eval_targets.get(target))
            metrics = _mapping(result.get("metrics"))
            dimension, unit = _target_unit(target, study, dataset)
            selection = _mapping(_mapping(card.get("model_selection")).get(target))
            cv_metrics = _mapping(_mapping(selection.get("cross_validation")).get("selected_metrics"))
            cv_rmse = _quantity(cv_metrics.get("rmse"), dimension, unit)
            mae = _quantity(metrics.get("mae"), dimension, unit)
            rmse = _quantity(metrics.get("rmse"), dimension, unit)
            lines.append(f"| {target} | {_status(result.get('status'))} | {train_counts.get(target, 'NOT_RUN')} | {result.get('sample_count', 'NOT_RUN')} | {cv_rmse} | {mae} | {rmse} | {_fmt(metrics.get('normalized_error'))} | {_fmt(metrics.get('r2'))} |")
            points = _evaluation_points(evaluation, target)
            lines.append(f"{target} Scatter points: {len(points)} paired truth/prediction values" if points else f"{target} Scatter points: NOT_RUN")
        lines.append("")
    lines.extend(["## Optimization candidates", ""])
    if not rounds:
        lines.extend(["NOT_RUN: no optimization rounds are recorded in the manifest.", ""])
    for info in rounds:
        plan = _mapping(info.get("plan_data"))
        lines.extend([f"### Round {info.get('round', '?')}", "",
                      "| Candidate | Status | Mass | Parameters | Predictions |", "|---|---|---:|---|---|"])
        candidates = _list(plan.get("candidates"))
        if not candidates:
            lines.append("| NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |")
        for value in candidates:
            candidate = _mapping(value)
            parameters = "; ".join(f"{key}={item}" for key, item in _mapping(candidate.get("parameters")).items()) or "NOT_RUN"
            predictions = "; ".join(f"{key}={_fmt(_mapping(item).get('value'))} {_mapping(item).get('unit', '')}" for key, item in _mapping(candidate.get("predictions")).items()) or "NOT_RUN"
            lines.append(f"| {candidate.get('candidate_id', candidate.get('sample_id', 'candidate'))} | {_candidate_status(candidate)} | {_fmt(candidate.get('mass_kg'))} kg | {parameters} | {predictions} |")
        lines.append("")
    lines.extend(["## Real verification", "", f"Status: {_status(_mapping(verification).get('status')) if verification else 'NOT_RUN'}", ""])
    if verification:
        lines.extend(["| Sample | Status | Mass | Feasible | Target truth | Prediction error |", "|---|---|---:|---|---|---|"])
        for value in _list(verification.get("candidates")):
            item = _mapping(value)
            lines.append(f"| {item.get('sample_id', 'NOT_RUN')} | {_candidate_status(item, confirmed=True)} | {_fmt(item.get('mass_kg'))} kg | {item.get('feasible', 'NOT_RUN')} | {json.dumps(item.get('targets', {}), ensure_ascii=False, sort_keys=True)} | {json.dumps(item.get('prediction_errors', {}), ensure_ascii=False, sort_keys=True)} |")
        lines.append(f"Best sample: {verification.get('best_sample_id') or 'NOT_RUN'}")
    else:
        lines.append("NOT_RUN: verification.json was not found.")
    lines.extend(["", "## Phase duration and calls", "",
                  "| Phase | Status | Duration | Calls |", "|---|---|---:|---:|"])
    for phase in phases:
        seconds, calls = _number(phase.get("seconds")), _number(phase.get("calls"))
        lines.append(f"| {phase.get('name')} | {_status(phase.get('status'))} | {_fmt(seconds) + ' s' if seconds is not None else 'NOT_RUN'} | {_fmt(calls) if calls is not None else 'NOT_RUN'} |")
    lines.extend(["", "## Additional evidence", "",
                  f"- comparison.json: {_status(_mapping(comparison).get('status')) if comparison else 'NOT_RUN'}"])
    lines.extend(f"- Result image: {item['path']} (sample {item['sample_id']})" for item in images)
    if not images:
        lines.append("- Result image: NOT_RUN")
    lines.extend(["", "This report is an auditable automation artifact, not engineering certification.", ""])
    return "\n".join(lines)


def _html_report(root: Path, study: object, manifest: Mapping[str, Any],
                 dataset: Mapping[str, Any], dataset_path: str | None,
                 rows: list[dict[str, Any]], models: list[dict[str, Any]],
                 rounds: list[dict[str, Any]], verification: Mapping[str, Any] | None,
                 comparison: Mapping[str, Any] | None,
                 mesh: Mapping[str, list[dict[str, Any]]], images: list[dict[str, str]],
                 phases: list[dict[str, Any]]) -> str:
    name = getattr(study, "name", manifest.get("name", "Design study"))
    description = getattr(study, "description", "")
    samples = [dict(item) for item in _list(manifest.get("samples")) if isinstance(item, Mapping)]
    targets = _target_names(study, dataset)
    features = [str(name) for name in _list(dataset.get("feature_names"))]
    if not features:
        features = list(getattr(study, "parameters", {}) or {})
    by_id = {str(row.get("sample_id")): row for row in rows}
    completed = sum(_sample_status(sample) == "SOLVED" for sample in samples)
    accepted = sum(bool(targets) and set(targets).issubset(_accepted(by_id.get(str(sample.get("sample_id")), {}))) for sample in samples)
    overall = manifest.get("overall", manifest.get("engineering_validation", manifest.get("overall_status", "NOT_RUN")))
    test_count = sum(sample.get("split") == "test" for sample in samples)
    model_html, chart_html = _render_metrics(models, targets, study, dataset)
    sample_html = _sample_section(samples, rows, targets, features, study, dataset, dataset_path)
    mesh_html = _mesh_html(mesh, targets, study, dataset)
    rounds_html = _rounds_html_with_evidence(root, rounds, targets, study, dataset)
    verify_html = _verification_html(verification, targets, study, dataset)
    phase_html = _phases_html(phases)
    compare_status = _status(_mapping(comparison).get("status")) if comparison else "NOT_RUN"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light"><title>' + _e(name) + ' · Study report</title>'
        + f"<style>{REPORT_CSS}</style></head><body><div class=\"page\">"
        + '<header class="masthead"><p class="eyebrow">ANSYS Mechanical · Design study</p>'
        + f'<div class="title-row"><h1>{_e(name)}</h1><span class="status" data-state="{_e(_state(manifest.get("status")))}">{_e(_status(manifest.get("status")))}</span></div>'
        + (f'<p class="description">{_e(description)}</p>' if description else "")
        + f'<div class="identity"><span>Study ID <code>{_e(manifest.get("study_id"))}</code></span><span>Overall verification <strong class="inline-state" data-state="{_e(_state(overall))}">{_e(_status(overall))}</strong></span></div></header>'
        + '<main><section><div class="section-head"><h2>Study overview</h2><span class="section-note">Planned, real solve completion, and quality acceptance are counted separately</span></div><div class="metrics">'
        + f'<div class="metric"><span class="metric-value">{len(samples)}</span><span class="metric-label">Planned samples</span></div>'
        + f'<div class="metric"><span class="metric-value">{completed}</span><span class="metric-label">Real solves completed</span></div>'
        + f'<div class="metric"><span class="metric-value">{accepted}</span><span class="metric-label">Quality accepted (all targets)</span></div>'
        + f'</div><p class="callout">Recorded overall verification status: <strong>{_e(_status(overall))}</strong>. Test split: {test_count} samples, reserved for holdout evaluation and excluded from training.</p></section>'
        + f'<section>{sample_html}</section>'
        + f'<section><div class="section-head"><h2>Model error</h2><span class="section-note">Per-target values come from evaluation.json; missing values remain NOT_RUN</span></div>{model_html}{chart_html}</section>'
        + f'<section><div class="section-head"><h2>Mesh convergence</h2><span class="section-note">Per-sample, per-target numerical evidence</span></div>{mesh_html}</section>'
        + f'<section><div class="section-head"><h2>Candidates and real verification</h2><span class="section-note">Predictions and re-solved values are shown separately</span></div>{rounds_html}{verify_html}</section>'
        + f'<section><div class="section-head"><h2>Run phases</h2><span class="section-note">Unrecorded duration and call counts are shown as NOT_RUN</span></div>{phase_html}</section>'
        + f'<section><div class="section-head"><h2>Evidence files</h2><span class="section-note">Links point only to existing files inside the study root</span></div>{_images_html(images)}{_comparison_html(comparison)}<p>Direct comparison: <span class="inline-state" data-state="{_e(_state(compare_status))}">{_e(compare_status)}</span></p></section>'
        + '</main><footer>Offline report · Values and states come from study evidence · Report generation does not start a solver</footer></div>'
        + f"<script>{REPORT_JS}</script></body></html>\n"
    )


def generate_study_report(root: Path) -> dict[str, Any]:
    """Write offline HTML and Markdown reports from a study's recorded evidence."""
    root = Path(root).expanduser().resolve()
    study, _base, raw_manifest = project.load_project(root)
    manifest = _mapping(raw_manifest)
    dataset, dataset_path = {}, None
    for reference in reversed(_list(manifest.get("datasets"))):
        candidate = _read_json(root, reference)
        if candidate is not None:
            dataset, dataset_path = candidate, str(reference)
            break
    rows = _sample_rows(dataset)
    targets = _target_names(study, dataset)
    mesh = _mesh_records(rows, targets, study)
    models = []
    for value in _list(manifest.get("models")):
        record = _mapping(value)
        path = record.get("path")
        if not isinstance(path, str):
            continue
        prefix = path.replace("\\", "/").rstrip("/")
        card = _read_json(root, f"{prefix}/model-card.json")
        evaluation = _read_json(root, f"{prefix}/evaluation.json")
        provenance = _read_json(root, f"{prefix}/training-provenance.json")
        models.append({"model_id": record.get("model_id", (card or {}).get("model_id", "NOT_RUN")),
                       "dataset_id": record.get("dataset_id", (provenance or {}).get("dataset_id", "NOT_RUN")),
                       "card": card or {}, "evaluation": evaluation or {},
                       "evaluation_present": evaluation is not None})
    rounds = []
    for value in _list(manifest.get("rounds")):
        record = _mapping(value)
        plan = _read_json(root, record.get("plan")) if record.get("plan") else None
        rounds.append({**dict(record), "plan_data": plan or {}})
    verification = _read_json(root, "verification.json")
    comparison = _read_json(root, "comparison.json")
    samples = [dict(item) for item in _list(manifest.get("samples")) if isinstance(item, Mapping)]
    images = _attempt_image_evidence(root, samples)
    phases = _phase_rows(manifest, samples, models, rounds)
    html_text = _html_report(root, study, manifest, dataset, dataset_path, rows, models,
                             rounds, verification, comparison, mesh, images, phases)
    markdown = _markdown(study, manifest, dataset, dataset_path, rows, models, rounds,
                         verification, comparison, mesh, images, phases)
    html_path, markdown_path = root / "study-report.html", root / "study-report.md"
    atomic_text(html_path, html_text)
    atomic_text(markdown_path, markdown)
    return {"status": "REPORTED", "html": str(html_path), "markdown": str(markdown_path),
            "dataset": dataset_path, "sample_count": len(samples)}
