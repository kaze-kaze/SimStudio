"""Deterministic JSON, CSV, and Markdown report generation."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ansys_skill.paths import safe_join
from ansys_skill.reporting.quantities import normalized_input_quantities
from ansys_skill.schema import SimulationSpec


def _write_results_csv(path: Path, summary: dict[str, Any]) -> None:
    results = summary.get("results", {})
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "result_id",
                "maximum",
                "unit",
                "canonical_maximum",
                "canonical_unit",
                "reported_maximum",
                "reported_unit",
                "location",
                "scoping_id",
            ]
        )
        if isinstance(results, dict):
            for result_id, item in sorted(results.items()):
                if not isinstance(item, dict):
                    continue
                writer.writerow(
                    [
                        result_id,
                        item.get("maximum", ""),
                        item.get("unit", ""),
                        item.get("canonical_maximum", ""),
                        item.get("canonical_unit", ""),
                        item.get("reported_maximum", ""),
                        item.get("reported_unit", ""),
                        item.get("location", ""),
                        item.get("scoping_id", ""),
                    ]
                )


def _report_markdown(
    spec: SimulationSpec, summary: dict[str, Any], verification: dict[str, Any]
) -> str:
    synthetic = bool(summary.get("synthetic"))
    lines = [
        f"# {spec.project.name} — ANSYS Mechanical static analysis report",
        "",
        f"- Run status: **{summary.get('status', 'UNKNOWN')}**",
        f"- Verification status: **{verification.get('status', 'NOT_RUN')}**",
        f"- Execution source: **{'SYNTHETIC TEST DATA' if synthetic else 'ANSYS/DPF OR NOT RUN'}**",
        f"- Mode: `{spec.mode.value}`",
        f"- Analysis: `{spec.analysis.type}` / `{spec.analysis.deformation}` deformation",
        "",
    ]
    if synthetic:
        lines.extend(
            [
                "> **Warning:** These values were produced by `FakeMechanicalBackend`. No ANSYS ",
                "> solver or commercial license was used. Do not treat them as engineering results.",
                "",
            ]
        )
    lines.extend(
        [
            "## Inputs and assumptions",
            "",
            f"- Bodies: {', '.join(body.name for body in spec.bodies)}",
            f"- Loads: {', '.join(load.id for load in spec.loads)}",
            f"- Supports: {', '.join(item.id for item in spec.supports)}",
        ]
    )
    if spec.assumptions:
        lines.append("- Assumptions:")
        for assumption in spec.assumptions:
            lines.append(f"  - [{assumption.source.value}] {assumption.text}")
    if spec.open_questions:
        lines.append("- Open questions (real execution blocked):")
        for question in spec.open_questions:
            lines.append(f"  - {question}")
    quantities = normalized_input_quantities(spec)
    if quantities:
        lines.extend(
            [
                "",
                "## Normalized input quantities",
                "",
                "| Field | Original | Canonical |",
                "|---|---:|---:|",
            ]
        )
        for quantity in quantities:
            lines.append(
                "| {} | {} | {} {} |".format(
                    quantity["label"],
                    quantity["raw"],
                    quantity["canonical_value"],
                    quantity["canonical_unit"],
                )
            )
    lines.extend(["", "## Results", ""])
    results = summary.get("results", {})
    if isinstance(results, dict) and results:
        lines.extend(
            [
                "| Result | Original maximum | Canonical maximum | Reported maximum | Location | Entity |",
                "|---|---:|---:|---:|---|---:|",
            ]
        )
        for result_id, item in sorted(results.items()):
            if isinstance(item, dict):
                lines.append(
                    "| {} | {} {} | {} {} | {} {} | {} | {} |".format(
                        result_id,
                        item.get("maximum", ""),
                        item.get("unit", ""),
                        item.get("canonical_maximum", ""),
                        item.get("canonical_unit", ""),
                        item.get("reported_maximum", ""),
                        item.get("reported_unit", ""),
                        item.get("location", ""),
                        item.get("scoping_id", ""),
                    )
                )
    else:
        lines.append("No numerical solver result was produced.")
    lines.extend(["", "## Verification", ""])
    for check in verification.get("checks", []):
        if isinstance(check, dict):
            lines.append(
                f"- **{check.get('status', 'NOT_RUN')}** `{check.get('name')}` — {check.get('message')}"
            )
    lines.extend(
        [
            "",
            "## Engineering limitation",
            "",
            "This report is an auditable automation artifact, not an engineering certification. "
            "A qualified engineer must review model scope, material data, mesh adequacy, boundary "
            "conditions, solver messages, numerical results, and visual plots.",
            "",
        ]
    )
    return "\n".join(lines)


def generate_reports(
    run_dir: Path,
    spec: SimulationSpec,
    summary: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, str]:
    summary_path = safe_join(run_dir, "results-summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verification_path = safe_join(run_dir, "verification.json")
    verification_path.write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    csv_path = safe_join(run_dir, "results.csv")
    _write_results_csv(csv_path, summary)
    report_path = safe_join(run_dir, "report.md")
    report_path.write_text(_report_markdown(spec, summary, verification), encoding="utf-8")
    return {
        "results_summary": str(summary_path),
        "results_csv": str(csv_path),
        "verification": str(verification_path),
        "report": str(report_path),
    }


def generate_inspection_reports(
    run_dir: Path,
    summary: dict[str, Any],
    verification: dict[str, Any],
    *,
    title: str,
) -> dict[str, str]:
    summary_path = safe_join(run_dir, "results-summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verification_path = safe_join(run_dir, "verification.json")
    verification_path.write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    csv_path = safe_join(run_dir, "results.csv")
    _write_results_csv(csv_path, summary)
    report_path = safe_join(run_dir, "report.md")
    lines = [
        f"# {title} — raw RST inspection",
        "",
        f"- DPF status: **{summary.get('status', 'UNKNOWN')}**",
        f"- Verification status: **{verification.get('status', 'NOT_RUN')}**",
        f"- Nodes: {summary.get('node_count', 0)}",
        f"- Elements: {summary.get('element_count', 0)}",
        "",
        "## Extracted results",
        "",
    ]
    results = summary.get("results", {})
    if isinstance(results, dict) and results:
        for result_id, item in sorted(results.items()):
            if isinstance(item, dict):
                lines.append(
                    f"- {result_id}: {item.get('maximum')} {item.get('unit', '')}; canonical "
                    f"{item.get('canonical_maximum', '')} {item.get('canonical_unit', '')} "
                    f"reported {item.get('reported_maximum', '')} "
                    f"{item.get('reported_unit', '')} "
                    f"at {item.get('location', 'unknown')} / "
                    f"{item.get('scoping_id', 'unknown')}"
                )
    else:
        lines.append("No common numerical result provider could be extracted.")
    unavailable = summary.get("unavailable_results", {})
    if isinstance(unavailable, dict) and unavailable:
        lines.extend(["", "## Unavailable providers", ""])
        for name, reason in sorted(unavailable.items()):
            lines.append(f"- {name}: {reason}")
    lines.extend(["", "## Verification", ""])
    for check in verification.get("checks", []):
        if isinstance(check, dict):
            lines.append(
                f"- **{check.get('status', 'NOT_RUN')}** {check.get('name')} — "
                f"{check.get('message')}"
            )
    lines.extend(
        [
            "",
            "## Limitation",
            "",
            "No simulation specification was available. Material intent, load/support scopes, "
            "reaction balance, analytical acceptance criteria, small-deformation limits, and "
            "visual review therefore remain NOT_RUN and require engineering context.",
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "results_summary": str(summary_path),
        "results_csv": str(csv_path),
        "verification": str(verification_path),
        "report": str(report_path),
    }
