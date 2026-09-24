"""Shared text tables for offline engineering, evaluation and comparison evidence."""

from __future__ import annotations

import html
from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass
class ReportTable:
    title: str
    headers: list[str]
    rows: list[list[object]]


def _mapping(value: object) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _field(value: object, name: str) -> object:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _text(value: object) -> str:
    if value is None or value == "":
        return "NOT_RUN"
    if isinstance(value, Mapping):
        return "; ".join(f"{key}: {_text(item)}" for key, item in value.items()) or "NOT_RUN"
    if isinstance(value, (list, tuple)):
        return "; ".join(_text(item) for item in value) or "NOT_RUN"
    return str(value)


def render_tables(tables: list[ReportTable]) -> tuple[str, str]:
    """Render the same evidence cells with HTML and Markdown escaping."""
    html_parts, markdown_parts = [], []

    def md(value: object) -> str:
        return html.escape(_text(value), quote=True).replace("|", "&#124;").replace("\n", "<br>")

    for table in tables:
        rows = table.rows or [["NOT_RUN"] * len(table.headers)]
        header = "".join(f"<th>{html.escape(label, quote=True)}</th>" for label in table.headers)
        body = "".join("<tr>" + "".join(
            f"<td>{html.escape(_text(value), quote=True)}</td>" for value in row
        ) + "</tr>" for row in rows)
        html_parts.append(f'<h3>{html.escape(table.title, quote=True)}</h3>'
                          f'<div class="table-wrap"><table><thead><tr>{header}</tr></thead>'
                          f'<tbody>{body}</tbody></table></div>')
        markdown_parts.extend([f"### {md(table.title)}", "",
                               "| " + " | ".join(md(label) for label in table.headers) + " |",
                               "|" + "---|" * len(table.headers)])
        markdown_parts.extend("| " + " | ".join(md(value) for value in row) + " |" for row in rows)
        markdown_parts.append("")
    return "".join(html_parts), "\n".join(markdown_parts)


def engineering_tables(study: object, context: Mapping, dataset: Mapping,
                       quantity: Callable[[object, str, str], str]) -> list[ReportTable]:
    """Read the portable project.engineering_context contract and study design bounds."""
    simulation = _mapping(context.get("simulation"))
    material = _mapping(context.get("material_evidence"))
    geometry = _mapping(context.get("geometry"))
    analysis = _mapping(simulation.get("analysis"))
    mesh = _mapping(context.get("mesh_study"))
    tables = [ReportTable("Study conditions", ["Condition", "Recorded value"], [
        ["Geometry generator", geometry.get("generator")],
        ["Generator version", geometry.get("generator_version")],
        ["Analysis", analysis.get("type")],
        ["Deformation assumption", analysis.get("deformation")],
        ["Material", material.get("engineering_data_name")],
        ["Density", material.get("density")],
        ["Material property source", material.get("property_source")],
        ["Material definitions", simulation.get("materials")],
        ["Bodies and material assignments", simulation.get("bodies")],
        ["Mesh sizes", mesh.get("sizes")],
        ["Element order", mesh.get("element_order")],
        ["Target statistic", context.get("target_statistic")],
    ])]

    parameters = _mapping(getattr(study, "parameters", None))
    bounds = _mapping(dataset.get("bounds"))
    parameter_rows = []
    for name in dict.fromkeys([*parameters, *bounds]):
        spec = parameters.get(name)
        limits = bounds.get(name)
        unit = _mapping(dataset.get("feature_units")).get(name, "meter")
        cells = []
        for index, key in enumerate(("lower", "upper", "baseline")):
            value = _field(spec, key)
            if value is None and index < 2 and isinstance(limits, list) and len(limits) == 2:
                value = quantity(limits[index], "length", str(unit))
            cells.append(value)
        parameter_rows.append([name, *cells])
    tables.append(ReportTable("Design space", ["Parameter", "Lower bound", "Upper bound", "Baseline"], parameter_rows))

    definitions = _mapping(context.get("target_definitions"))
    specifications = _mapping(getattr(study, "targets", None))
    target_metadata = _mapping(dataset.get("targets"))
    target_rows = []
    for name in dict.fromkeys([*specifications, *definitions, *target_metadata]):
        spec = definitions.get(name, specifications.get(name))
        meta = _mapping(target_metadata.get(name))
        limit = _field(spec, "limit")
        if limit is None and meta.get("limit") is not None:
            limit = quantity(meta["limit"], str(meta.get("dimension", "")),
                             str(meta.get("display_unit", meta.get("unit", ""))))
        target_rows.append([name, _field(spec, "result_id") or meta.get("result_id"),
                            limit, _field(spec, "acceptance_source") or meta.get("acceptance_source"),
                            _field(spec, "require_stress_review")])
    tables.append(ReportTable("Target constraints", ["Target", "Requested result", "Upper limit", "Acceptance source", "Stress review required"], target_rows))

    for key, title in (("loads", "Loads"), ("supports", "Supports"), ("scopes", "Scopes")):
        rows = []
        records = simulation.get(key)
        for value in records if isinstance(records, list) else []:
            record = _mapping(value)
            details = {name: item for name, item in record.items()
                       if name not in {"id", "type", "kind", "scope"}}
            rows.append([record.get("id"), record.get("type", record.get("kind")),
                         record.get("scope"), details])
        tables.append(ReportTable(title, ["ID", "Type", "Scope", "Definition"], rows))
    assumptions = simulation.get("assumptions")
    tables.append(ReportTable("Physical assumptions", ["Assumption", "Source"], [
        [_mapping(item).get("text"), _mapping(item).get("source")]
        for item in assumptions if isinstance(item, Mapping)
    ] if isinstance(assumptions, list) else []))
    return tables


def comparison_tables(comparison: Mapping | None, targets: Mapping[str, tuple[str, str]],
                      quantity: Callable[[object, str, str], str],
                      number: Callable[[object], str]) -> list[ReportTable]:
    """Present measured outcomes and costs from comparison.json without assuming speedup."""
    data = _mapping(comparison)
    best_rows = []
    candidates = (("direct_best", "Direct search best"),
                  ("surrogate_best", "Surrogate search best (observed)"),
                  ("best_observed_training", "Observed training best"),
                  ("verified_candidate", "Independently verified candidate"))
    for key, label in candidates:
        best = _mapping(data.get(key))
        values = _mapping(best.get("targets"))
        best_rows.append([label, best.get("sample_id"), quantity(best.get("mass_kg"), "mass", "kg"),
                          *[quantity(values.get(target), dimension, unit)
                            for target, (dimension, unit) in targets.items()]])
    improvement = data.get("mass_improvement_vs_direct")
    if isinstance(improvement, (float, int)) and not isinstance(improvement, bool):
        improvement = number(improvement * 100)
        if improvement != "NOT_RUN":
            improvement += "%"
    else:
        improvement = "NOT_RUN"
    tables = [ReportTable("Comparison outcome", ["Measure", "Recorded value"], [
        ["Comparison status", data.get("status")],
        ["Execution status", data.get("execution_status")],
        ["Completion status", data.get("completion_status")],
        ["Equal solver-call allowance", data.get("allowance_equal")],
        ["Equal actual solver calls", data.get("actual_calls_equal")],
        ["Recommendation status", data.get("recommendation_status")],
        ["Independent verification evidence", data.get("verification_evidence_status")],
        ["Mass reduction relative to direct search", improvement],
    ]), ReportTable("Best feasible designs", ["Method", "Sample", "Mass", *targets], best_rows)]
    groups = _mapping(data.get("target_margins"))
    margin_rows = []
    for key, label in (("baseline", "Baseline"), *candidates):
        values = _mapping(groups.get(key))
        for target, (dimension, unit) in targets.items():
            evidence = _mapping(values.get(target))
            margin_rows.append([label, target,
                                *[quantity(evidence.get(field), dimension, unit)
                                  for field in ("value", "limit", "margin")],
                                evidence.get("status"), evidence.get("feasibility")])
    tables.append(ReportTable("Constraint margins", ["Evidence", "Target", "Value", "Upper limit", "Margin (limit - value)", "Status", "Feasibility"], margin_rows))
    baseline_changes = _mapping(data.get("baseline_comparison"))
    delta_rows = []
    for key, label in candidates:
        changes = _mapping(baseline_changes.get(key))
        values = _mapping(changes.get("target_value_delta"))
        delta_rows.append([label, quantity(changes.get("mass_delta_kg"), "mass", "kg"),
                           *[quantity(_mapping(values.get(target)).get("value_delta"), dimension, unit)
                             for target, (dimension, unit) in targets.items()], changes.get("status")])
    tables.append(ReportTable("Changes from baseline (candidate - baseline)",
                             ["Evidence", "Mass change", *targets, "Status"], delta_rows))
    call_labels = {
        "direct_search_allowance": "Direct search allowance",
        "shared_solver_calls": "Shared baseline and holdout solver calls",
        "actual_shared_solver_calls": "Actual shared solver calls",
        "direct_search_calls_used": "Direct search calls used",
        "surrogate_search_calls_used": "Surrogate search calls used",
        "direct_total_solver_calls": "Direct total solver calls (including shared)",
        "surrogate_total_solver_calls": "Surrogate total solver calls (including shared)",
    }
    call_rows = [
        [label, number(data.get(key))] for key, label in call_labels.items()
    ]
    budget = _mapping(data.get("budget"))
    call_rows.extend([label, number(budget.get(key))] for key, label in (
        ("max_solver_calls", "Study solver-call budget"),
        ("solver_calls_used", "Study solver calls used"),
        ("solver_calls_remaining", "Study solver calls remaining"),
        ("direct_search_calls_remaining", "Direct search calls remaining"),
    ))
    tables.append(ReportTable("Solver-call accounting", ["Measure", "Calls"], call_rows))
    seconds = _mapping(data.get("solver_command_seconds"))
    costs = _mapping(data.get("solver_costs_by_split"))
    cost_rows = []
    for split in ("baseline", "train", "test", "verification", "comparison"):
        cost = _mapping(costs.get(split))
        cost_rows.append([split, number(cost.get("calls")),
                          quantity(cost.get("seconds", seconds.get(split)), "time", "s"),
                          quantity(cost.get("known_seconds"), "time", "s"),
                          number(cost.get("timed_calls")), number(cost.get("unknown_time_calls")),
                          number(cost.get("failed_calls")), number(cost.get("running_calls")), cost.get("status")])
    total = _mapping(data.get("solver_costs_total"))
    cost_rows.append(["All recorded attempts", number(total.get("calls")),
                      quantity(total.get("seconds"), "time", "s"), quantity(total.get("known_seconds"), "time", "s"),
                      number(total.get("timed_calls")), number(total.get("unknown_time_calls")),
                      number(total.get("failed_calls")), number(total.get("running_calls")), total.get("status")])
    tables.append(ReportTable("Solver ledger costs", ["Split", "Calls", "Total duration", "Recorded duration", "Timed calls", "Missing timings", "Failed / interrupted calls", "Running calls", "Status"], cost_rows))
    tables.append(ReportTable("Recorded comparison costs", ["Activity", "Duration"], [
        ["Model training", quantity(data.get("training_seconds"), "time", "s")],
        ["Study active elapsed time", quantity(data.get("study_elapsed_seconds"), "time", "s")],
    ]))
    geometries = _mapping(data.get("geometry_seconds_per_sample"))
    tables.append(ReportTable("Geometry preparation costs", ["Split", "Samples", "Timed samples", "Missing timings", "Recorded duration", "Mean per timed sample", "Status"], [
        [split, number(_mapping(record).get("sample_count")),
         number(_mapping(record).get("timed_samples")), number(_mapping(record).get("unknown_samples")),
         quantity(_mapping(record).get("known_seconds"), "time", "s"),
         quantity(_mapping(record).get("seconds_per_sample"), "time", "s"),
         _mapping(record).get("status")]
        for split, record in geometries.items()
    ]))
    phases = _mapping(data.get("phase_timings"))
    tables.append(ReportTable("Non-solver phase costs", ["Phase", "Duration", "Recorded calls", "Status"], [
        [phase, quantity(_mapping(record).get("elapsed_seconds"), "time", "s"),
         number(_mapping(record).get("calls")), _mapping(record).get("status")]
        for phase, record in phases.items()
    ]))
    split_phases = _mapping(data.get("phase_timings_by_split"))
    tables.append(ReportTable("Attempt phase costs by split", ["Split", "Phase", "Recorded duration", "Timed attempts", "Missing timings", "Status"], [
        [split, phase, quantity(_mapping(record).get("known_seconds"), "time", "s"),
         number(_mapping(record).get("recorded_attempts")), number(_mapping(record).get("unknown_attempts")),
         _mapping(record).get("status")]
        for split, records in split_phases.items() for phase, record in _mapping(records).items()
    ]))
    rounds = data.get("round_search_seconds")
    tables.append(ReportTable("Search round costs", ["Round", "Purpose", "Round status", "Search time", "Timing status"], [
        [_mapping(record).get("round"), _mapping(record).get("purpose"),
         _mapping(record).get("round_status"),
         quantity(_mapping(record).get("search_seconds"), "time", "s"), _mapping(record).get("status")]
        for record in rounds
    ] if isinstance(rounds, list) else []))
    return tables


def evaluation_tables(models: list[dict], targets: Mapping[str, tuple[str, str]],
                      quantity: Callable[[object, str, str], str],
                      number: Callable[[object], str]) -> list[ReportTable]:
    """Display producer-selected holdout slices without recomputing membership or gates."""
    tables = []
    for model in models:
        evaluation = _mapping(model.get("evaluation"))
        results = _mapping(evaluation.get("targets"))
        metrics_rows, selection_rows, classification_rows = [], [], []
        for target, (dimension, unit) in targets.items():
            result = _mapping(results.get(target))
            slices = _mapping(result.get("error_slices"))
            for key, label in (("design_space_boundary", "Design space boundary"),
                               ("constraint_near", "Near constraint")):
                record = _mapping(slices.get(key))
                metrics = _mapping(record.get("metrics"))
                metrics_rows.append([target, label, record.get("status"), number(record.get("sample_count")),
                                     *[quantity(metrics.get(name), dimension, unit)
                                       for name in ("mae", "rmse", "max_absolute_error")],
                                     number(record.get("false_safe_count"))])
                selection = dict(_mapping(record.get("selection")))
                for name in ("absolute_tolerance", "reference_scale", "limit"):
                    if name in selection:
                        selection[name] = quantity(selection[name], dimension, unit)
                selection_rows.append([target, label, selection, record.get("sample_ids"), record.get("reason")])
            classification = _mapping(result.get("constraint_classification"))
            counts = _mapping(classification.get("confusion_matrix"))
            classification_rows.append([target, classification.get("status"),
                quantity(classification.get("limit"), dimension, unit), number(classification.get("sample_count")),
                *[number(counts.get(key)) for key in (
                    "true_feasible_predicted_feasible", "true_feasible_predicted_infeasible",
                    "true_infeasible_predicted_feasible", "true_infeasible_predicted_infeasible")],
                number(classification.get("false_safe_count")), number(classification.get("false_unsafe_count")),
                classification.get("reason")])
        model_id = _text(model.get("model_id"))
        tables.extend([
            ReportTable(f"Holdout error slices: {model_id}",
                        ["Target", "Slice", "Status", "Samples", "MAE", "RMSE", "Maximum absolute error", "False-safe count"], metrics_rows),
            ReportTable(f"Slice selection and membership: {model_id}",
                        ["Target", "Slice", "Recorded selection", "Sample IDs", "Reason if not evaluated"], selection_rows),
            ReportTable(f"Constraint classification: {model_id}",
                        ["Target", "Status", "Upper limit", "Samples", "True feasible / predicted feasible",
                         "True feasible / predicted infeasible", "True infeasible / predicted feasible",
                         "True infeasible / predicted infeasible", "False-safe count", "False-unsafe count", "Reason if not evaluated"], classification_rows),
        ])
    return tables
