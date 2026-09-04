"""ansys-sim deterministic command-line interface."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ansys_skill.backends import FakeMechanicalBackend, PyMechanicalRemoteBackend
from ansys_skill.backends.pymechanical import doctor_report
from ansys_skill.compiler import compile_simulation
from ansys_skill.errors import (
    AnsysSimError,
    EnvironmentUnavailableError,
    ExitCode,
    PostprocessingError,
    SpecValidationError,
)
from ansys_skill.logging import progress
from ansys_skill.manifest import add_artifact, utc_now, write_manifest
from ansys_skill.paths import (
    prepare_output_dir,
    require_fresh_run_dir,
    resolve_spec_path,
    safe_join,
)
from ansys_skill.postprocessing import inspect_result_file
from ansys_skill.reporting import generate_inspection_reports, generate_reports
from ansys_skill.schema import (
    SimulationSpec,
    load_spec,
    write_json_schema,
)
from ansys_skill.validation.preflight import preflight_checks
from ansys_skill.validation.results import post_solve_checks
from ansys_skill.validation.statuses import (
    Check,
    CheckStatus,
    checks_payload,
)

INIT_SIMULATION = """schema_version: "1.0"
project:
  name: replace-me
  description: Review and replace every placeholder before execution.
mode: from_geometry
inputs:
  geometry_file: ./geometry.step
units:
  length: m
  force: N
  stress: Pa
  mass: kg
  time: s
coordinate_systems:
  - name: Global Coordinate System
    kind: global
bodies:
  - name: ExactBodyName
    material: steel
materials:
  - name: steel
    source: engineering_data
    engineering_data_name: Structural Steel
scopes:
  - id: fixed_face
    kind: axis_extreme_face
    body: ExactBodyName
    axis: x
    extreme: min
    tolerance: 0.001 mm
  - id: load_face
    kind: axis_extreme_face
    body: ExactBodyName
    axis: x
    extreme: max
    tolerance: 0.001 mm
analysis:
  type: linear_static_structural
  deformation: small
mesh:
  global_element_size: 5 mm
  element_order: program_controlled
supports:
  - id: fixed_support
    type: fixed_support
    scope: fixed_face
loads:
  - id: applied_force
    type: force
    scope: load_face
    components:
      x: 0 N
      y: -1000 N
      z: 0 N
requested_results:
  - id: total_deformation
    type: total_deformation
  - id: equivalent_stress
    type: equivalent_von_mises_stress
  - id: fixed_reaction
    type: reaction_force
    support: fixed_support
  - id: solver_messages
    type: solver_messages
  - id: node_count
    type: node_count
  - id: element_count
    type: element_count
validation:
  reaction_balance_relative_tolerance: 0.05
  small_deformation_warn_ratio: 0.02
  small_deformation_fail_ratio: 0.1
  characteristic_length: 100 mm
assumptions: []
open_questions:
  - Replace placeholder names, geometry, material, load, and acceptance values.
output:
  export_images: true
  save_project: true
execution:
  backend: pymechanical_remote
  host: 127.0.0.1
  allow_remote: false
  transport_mode: insecure
  start_instance: auto
  timeout_seconds: 1800
  cleanup_owned_instance: true
"""

INIT_BRIEF = """# Simulation brief

## Objective

State the engineering question and the decision this analysis informs.

## Inputs

- Template or geometry path:
- Exact Mechanical object names or body name:
- Unit system:

## Physics

- Material source and exact Engineering Data name:
- Fixed support scope:
- Load type, scope, components or magnitude/direction:
- Small-deformation justification:

## Mesh and requested results

- Global element size:
- Required result quantities and scopes:

## Acceptance criteria

- Reaction balance tolerance:
- Analytical benchmark, if any:
- Small-deformation warning/failure ratios:

## Assumptions

Record each assumption and whether it came from the user, template, program, or an engineering default.

## Open questions

List only questions that block a safe, unique execution. A non-empty list blocks `--execute`.
"""


def _emit(payload: dict[str, object], json_mode: bool) -> None:
    print(
        json.dumps(
            payload,
            indent=2 if json_mode else None,
            sort_keys=True,
            separators=None if json_mode else (",", ":"),
        )
    )


def _load_and_check(spec_argument: str) -> tuple[Path, SimulationSpec, list[Check]]:
    spec_path = resolve_spec_path(spec_argument)
    spec, _ = load_spec(spec_path)
    checks = preflight_checks(spec, spec_path)
    return spec_path, spec, checks


def _failed(checks: list[Check]) -> bool:
    return any(check.status is CheckStatus.FAIL for check in checks)


def _execution_ready(spec: SimulationSpec, checks: list[Check]) -> bool:
    if _failed(checks) or spec.open_questions:
        return False
    try:
        spec.assert_execution_ready()
    except SpecValidationError:
        return False
    return True


def command_doctor(args: argparse.Namespace) -> int:
    report = doctor_report()
    _emit(report, args.json)
    if args.strict and not report["can_execute"]:
        return ExitCode.ENVIRONMENT_UNAVAILABLE
    return ExitCode.SUCCESS


def command_init(args: argparse.Namespace) -> int:
    directory = prepare_output_dir(args.directory)
    targets = [
        directory / "simulation.yaml",
        directory / "simulation_brief.md",
        directory / "simulation.schema.json",
    ]
    existing = [str(path) for path in targets if path.exists()]
    if existing:
        raise SpecValidationError(
            "init refuses to overwrite existing files", details={"existing": existing}
        )
    targets[0].write_text(INIT_SIMULATION, encoding="utf-8")
    targets[1].write_text(INIT_BRIEF, encoding="utf-8")
    write_json_schema(targets[2])
    _emit(
        {"status": "INITIALIZED", "directory": str(directory), "files": [str(x) for x in targets]},
        False,
    )
    return ExitCode.SUCCESS


def command_validate(args: argparse.Namespace) -> int:
    spec_path, spec, checks = _load_and_check(args.simulation)
    payload = checks_payload(checks)
    payload.update(
        {
            "ok": not _failed(checks),
            "execution_ready": _execution_ready(spec, checks),
            "simulation": str(spec_path),
            "schema_version": spec.schema_version,
        }
    )
    _emit(payload, args.json)
    return ExitCode.VALIDATION_FAILED if _failed(checks) else ExitCode.SUCCESS


def command_compile(args: argparse.Namespace) -> int:
    spec_path, spec, checks = _load_and_check(args.simulation)
    if _failed(checks):
        _emit({"status": "VALIDATION_FAILED", **checks_payload(checks)}, args.json)
        return ExitCode.VALIDATION_FAILED
    progress("Compiling deterministic Mechanical artifacts")
    artifacts = compile_simulation(spec, spec_path, args.out)
    _emit(
        {
            "status": "COMPILED",
            "execution_ready": _execution_ready(spec, checks),
            "validation": checks_payload(checks),
            "artifacts": artifacts,
        },
        args.json,
    )
    return ExitCode.SUCCESS


def _manifest(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    path = run_dir / "run-manifest.json"
    if not path.is_file():
        raise SpecValidationError(f"Run manifest is missing: {path}")
    return path, json.loads(path.read_text(encoding="utf-8"))


def _record_outputs(
    run_dir: Path,
    paths: dict[str, str],
    status: str,
    synthetic: bool,
    *,
    failure_stage: str | None = None,
    activities: tuple[str, ...] = (),
) -> None:
    manifest_path, manifest = _manifest(run_dir)
    for path in paths.values():
        add_artifact(manifest, run_dir, Path(path))
    commands_and_checks = manifest.setdefault("commands_and_checks", [])
    for activity in activities:
        if activity not in commands_and_checks:
            commands_and_checks.append(activity)
    manifest["status"] = status
    manifest["synthetic"] = synthetic
    manifest["failure_stage"] = failure_stage
    manifest["ended_at"] = utc_now()
    write_manifest(manifest_path, manifest)


def _record_manifest_activity(
    run_dir: Path, activities: tuple[str, ...], paths: dict[str, str] | None = None
) -> None:
    manifest_path = run_dir / "run-manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    commands_and_checks = manifest.setdefault("commands_and_checks", [])
    for activity in activities:
        if activity not in commands_and_checks:
            commands_and_checks.append(activity)
    for path in (paths or {}).values():
        artifact = Path(path)
        if artifact.is_file():
            add_artifact(manifest, run_dir, artifact)
    write_manifest(manifest_path, manifest)


def _mark_failure(run_dir: Path, status: str, stage: str, error: Exception) -> None:
    manifest_path, manifest = _manifest(run_dir)
    for path in run_dir.rglob("*"):
        if path.is_file():
            add_artifact(manifest, run_dir, path)
    manifest["status"] = status
    manifest["failure_stage"] = stage
    manifest["ended_at"] = utc_now()
    error_payload: dict[str, object] = {
        "type": type(error).__name__,
        "message": str(error),
    }
    if isinstance(error, AnsysSimError) and error.details:
        error_payload["details"] = error.details
    manifest["error"] = error_payload
    manifest["commands_and_checks"].append(f"failed during {stage}")
    write_manifest(manifest_path, manifest)


def _write_doctor_environment(run_dir: Path, spec: SimulationSpec, *, probe_port: bool) -> dict[str, object]:
    path = run_dir / "environment.json"
    current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    report = doctor_report(spec, probe_port=probe_port)
    path.write_text(
        json.dumps({"runtime": current, "doctor": report}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _record_manifest_activity(
        run_dir, ("doctor environment check",), {"environment": str(path)}
    )
    return report


def _dry_run(spec: SimulationSpec, run_dir: Path, checks: list[Check], json_mode: bool) -> int:
    execution_plan = {
        "status": "DRY_RUN",
        "execute_requested": False,
        "execution_ready": _execution_ready(spec, checks),
        "backend": spec.execution.backend,
        "host": spec.execution.host,
        "transport_mode": spec.execution.transport_mode,
        "steps": [
            "validate specification",
            "compile normalized specification and saved Mechanical script",
            "run doctor",
            "connect or launch Mechanical only with --execute",
            "postprocess with PyDPF",
            "run engineering verification and visual review",
        ],
    }
    plan_path = safe_join(run_dir, "execution-plan.json")
    plan_path.write_text(
        json.dumps(execution_plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    messages_path = safe_join(run_dir, "solver-messages.json")
    messages_path.write_text("[]\n", encoding="utf-8")
    summary = {
        "status": "NOT_RUN",
        "synthetic": False,
        "result_file": None,
        "node_count": 0,
        "element_count": 0,
        "solver_messages": [],
        "results": {},
    }
    dry_checks = [
        *checks,
        Check(
            "mechanical_solve",
            CheckStatus.NOT_RUN,
            "Dry-run is the default; --execute was not supplied",
        ),
        Check("dpf_postprocessing", CheckStatus.NOT_RUN, "No real result file exists in a dry-run"),
        Check("visual_review", CheckStatus.NOT_RUN, "Visual exports require a real solve"),
    ]
    verification = checks_payload(dry_checks)
    report_paths = generate_reports(run_dir, spec, summary, verification)
    report_paths.update({"execution_plan": str(plan_path), "solver_messages": str(messages_path)})
    _record_outputs(
        run_dir,
        report_paths,
        "DRY_RUN",
        False,
        activities=(
            "dry-run execution plan",
            "engineering verification",
            "visual review status recording",
            "report generation",
        ),
    )
    _emit(
        {
            "status": "DRY_RUN",
            "run_directory": str(run_dir),
            "execution_ready": execution_plan["execution_ready"],
            "artifacts": report_paths,
        },
        json_mode,
    )
    return ExitCode.SUCCESS


def _find_result_file(run_dir: Path) -> Path:
    metadata = _read_mechanical_metadata(run_dir)
    if metadata.get("result_files"):
        recorded = [Path(path) for path in metadata["result_files"]]
        candidates = [path if path.is_absolute() else run_dir / path for path in recorded]
        if len(candidates) != 1 or not candidates[0].is_file():
            raise PostprocessingError("The recorded Mechanical result file is missing or ambiguous")
        try:
            candidates[0].resolve().relative_to(run_dir.resolve())
        except ValueError as exc:
            raise PostprocessingError("Recorded result file is outside the run directory") from exc
        return candidates[0]
    results = sorted(run_dir.rglob("*.rst"))
    if not results:
        raise PostprocessingError(f"No .rst result file exists under {run_dir}")
    if len(results) > 1:
        raise PostprocessingError(
            "Multiple .rst files found; inspection requires a unique result",
            details={"files": [str(path) for path in results]},
        )
    return results[0]


def _read_mechanical_metadata(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "mechanical-artifacts.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _real_postprocess(
    run_dir: Path, spec: SimulationSpec, checks: list[Check]
) -> tuple[dict[str, Any], dict[str, Any]]:
    rst_path = _find_result_file(run_dir)
    summary = inspect_result_file(rst_path, spec)
    mechanical = _read_mechanical_metadata(run_dir)
    messages = mechanical.get("solver_messages")
    summary["solver_messages"] = messages
    summary["visual_review"] = mechanical.get("visual_review", [])
    messages_path = run_dir / "solver-messages.json"
    messages_path.write_text(
        json.dumps(messages, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    resolved_checks = [
        Check(
            "scope_resolution",
            CheckStatus.PASS,
            "Mechanical resolved every exact object and scope uniquely before solving",
            {"face_selections": mechanical.get("face_selections", [])},
        )
        if check.name == "scope_resolution"
        else check
        for check in checks
    ]
    post_checks = post_solve_checks(spec, summary)
    visual_states = summary.get("visual_review", [])
    visual_pass = any(
        isinstance(item, dict) and item.get("status") == "PASS" for item in visual_states
    )
    post_checks.append(
        Check(
            "image_export",
            CheckStatus.PASS if visual_pass else CheckStatus.NOT_RUN,
            "Mechanical exported at least one result image"
            if visual_pass
            else "Mechanical did not export a review image; see visual_review reasons",
            {"items": visual_states} if isinstance(visual_states, list) else None,
        )
    )
    post_checks.append(Check("visual_review", CheckStatus.NOT_RUN,
                             "Exported images still require explicit human or agent review"))
    verification = checks_payload([*resolved_checks, *post_checks])
    return summary, verification


def command_run(args: argparse.Namespace) -> int:
    spec_path, spec, checks = _load_and_check(args.simulation)
    if _failed(checks):
        _emit({"status": "VALIDATION_FAILED", **checks_payload(checks)}, args.json)
        return ExitCode.VALIDATION_FAILED
    default_name = datetime.now(UTC).strftime("build/run-%Y%m%dT%H%M%S%fZ")
    out = args.out or default_name
    require_fresh_run_dir(out)
    artifacts = compile_simulation(spec, spec_path, out)
    run_dir = Path(artifacts["run_directory"])
    environment = _write_doctor_environment(run_dir, spec, probe_port=args.execute)
    if not args.execute:
        return _dry_run(spec, run_dir, checks, args.json)

    try:
        spec.assert_execution_ready()
    except SpecValidationError as exc:
        _mark_failure(run_dir, "VALIDATION_FAILED", "execution_readiness", exc)
        raise
    if not environment["can_execute"] and spec.execution.backend != "fake":
        exc = EnvironmentUnavailableError(
            "doctor found no usable real Mechanical execution path", details=environment
        )
        _mark_failure(run_dir, "ENVIRONMENT_UNAVAILABLE", "environment", exc)
        raise exc
    backend = (
        FakeMechanicalBackend() if spec.execution.backend == "fake" else PyMechanicalRemoteBackend()
    )
    progress(f"Executing backend {spec.execution.backend}")
    try:
        outcome = backend.execute(spec, spec_path, run_dir, Path(artifacts["generated_script"]))
    except EnvironmentUnavailableError as exc:
        _mark_failure(run_dir, "ENVIRONMENT_UNAVAILABLE", "environment", exc)
        raise
    except AnsysSimError as exc:
        _mark_failure(run_dir, "MECHANICAL_FAILED", "mechanical_execution", exc)
        raise
    manifest_path, manifest = _manifest(run_dir)
    for path in outcome.artifacts:
        if path.exists():
            add_artifact(manifest, run_dir, path)
    manifest["status"] = outcome.status
    manifest["synthetic"] = outcome.synthetic
    if outcome.metadata.get("mechanical_product_version"):
        manifest["mechanical_product_version"] = outcome.metadata[
            "mechanical_product_version"
        ]
    manifest["instance_owned_by_run"] = bool(outcome.metadata.get("owned_instance"))
    manifest["remote_workdir"] = outcome.metadata.get("remote_workdir")
    manifest["remote_cleanup_warning"] = outcome.metadata.get("remote_cleanup_warning")
    manifest["commands_and_checks"].append(f"execute backend {spec.execution.backend}")
    write_manifest(manifest_path, manifest)

    if outcome.synthetic:
        summary = json.loads((run_dir / "results-summary.json").read_text(encoding="utf-8"))
        synthetic_checks = [
            *checks,
            Check(
                "mechanical_solve",
                CheckStatus.NOT_RUN,
                "Fake backend used; no ANSYS solve occurred",
            ),
            Check(
                "dpf_postprocessing", CheckStatus.NOT_RUN, "Synthetic values are not a DPF result"
            ),
            Check(
                "visual_review",
                CheckStatus.NOT_RUN,
                "Synthetic backend does not export solver plots",
            ),
        ]
        verification = checks_payload(synthetic_checks)
    else:
        try:
            summary, verification = _real_postprocess(run_dir, spec, checks)
        except PostprocessingError as exc:
            _mark_failure(run_dir, "POSTPROCESSING_FAILED", "postprocessing", exc)
            raise
    report_paths = generate_reports(run_dir, spec, summary, verification)
    verification_failed = verification["status"] == CheckStatus.FAIL.value
    final_status = "VERIFICATION_FAILED" if verification_failed else outcome.status
    _record_outputs(
        run_dir,
        report_paths,
        final_status,
        outcome.synthetic,
        failure_stage="verification" if verification_failed else None,
        activities=(
            "synthetic result handling"
            if outcome.synthetic
            else "PyDPF result inspection",
            "engineering verification",
            "visual review status recording",
            "report generation",
        ),
    )
    _emit(
        {
            "status": outcome.status,
            "synthetic": outcome.synthetic,
            "verification_status": verification["status"],
            "run_directory": str(run_dir),
            "artifacts": report_paths,
        },
        args.json,
    )
    if verification_failed:
        return ExitCode.VERIFICATION_FAILED
    return ExitCode.SUCCESS


def _load_run_spec(run_dir: Path) -> SimulationSpec:
    path = run_dir / "normalized-simulation.yaml"
    if not path.is_file():
        raise SpecValidationError(f"normalized-simulation.yaml is missing from {run_dir}")
    spec, _ = load_spec(path)
    return spec


def command_inspect(args: argparse.Namespace) -> int:
    target = Path(args.run_directory).expanduser().resolve()
    run_dir = target.parent if target.is_file() else target
    if not run_dir.is_dir():
        raise PostprocessingError(f"Run directory does not exist: {run_dir}")
    rst_path = (
        target
        if target.is_file() and target.suffix.lower() == ".rst"
        else _find_result_file(run_dir)
    )
    normalized_path = run_dir / "normalized-simulation.yaml"
    if not normalized_path.is_file():
        summary = inspect_result_file(rst_path)
        raw_checks = [
            Check(
                "dpf_result_file",
                CheckStatus.PASS,
                "DPF opened the raw result file",
            ),
            Check(
                "mesh_counts",
                CheckStatus.PASS
                if int(summary.get("node_count", 0)) > 0
                and int(summary.get("element_count", 0)) > 0
                else CheckStatus.FAIL,
                "Raw result mesh contains positive node and element counts",
            ),
            Check(
                "simulation_specification",
                CheckStatus.NOT_RUN,
                "No normalized simulation specification was available",
            ),
            Check(
                "engineering_validation",
                CheckStatus.NOT_RUN,
                "Loads, supports, units policy, reaction balance, and acceptance criteria are unknown",
            ),
            Check(
                "visual_review",
                CheckStatus.NOT_RUN,
                "Raw RST inspection does not have saved Mechanical visual artifacts",
            ),
        ]
        verification = checks_payload(raw_checks)
        paths = generate_inspection_reports(run_dir, summary, verification, title=rst_path.name)
        _emit(
            {
                "status": "INSPECTED",
                "inspection_mode": "raw_rst",
                "verification_status": verification["status"],
                "run_directory": str(run_dir),
                "artifacts": paths,
            },
            args.json,
        )
        return (
            ExitCode.VERIFICATION_FAILED
            if verification["status"] == CheckStatus.FAIL.value
            else ExitCode.SUCCESS
        )

    spec = _load_run_spec(run_dir)
    checks = preflight_checks(spec, normalized_path, inspect_only=True)
    summary = inspect_result_file(rst_path, spec)
    mechanical = _read_mechanical_metadata(run_dir)
    summary["solver_messages"] = mechanical.get("solver_messages")
    verification = checks_payload(checks + post_solve_checks(spec, summary))
    paths = generate_reports(run_dir, spec, summary, verification)
    _record_manifest_activity(
        run_dir,
        ("PyDPF result inspection", "engineering verification", "report generation"),
        paths,
    )
    _emit(
        {
            "status": "INSPECTED",
            "verification_status": verification["status"],
            "run_directory": str(run_dir),
            "artifacts": paths,
        },
        args.json,
    )
    return (
        ExitCode.VERIFICATION_FAILED
        if verification["status"] == CheckStatus.FAIL.value
        else ExitCode.SUCCESS
    )


def command_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_directory).expanduser().resolve()
    summary_path = run_dir / "results-summary.json"
    verification_path = run_dir / "verification.json"
    if not summary_path.is_file() or not verification_path.is_file():
        raise PostprocessingError(
            "report requires results-summary.json and verification.json; run inspect first"
        )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    normalized_path = run_dir / "normalized-simulation.yaml"
    if normalized_path.is_file():
        spec = _load_run_spec(run_dir)
        paths = generate_reports(run_dir, spec, summary, verification)
    else:
        title = Path(str(summary.get("result_file", "raw-result.rst"))).name
        paths = generate_inspection_reports(run_dir, summary, verification, title=title)
    _record_manifest_activity(run_dir, ("report regeneration",), paths)
    _emit({"status": "REPORTED", "artifacts": paths}, args.json)
    return ExitCode.SUCCESS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ansys-sim")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Diagnose Mechanical and DPF availability")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--strict", action="store_true")
    doctor.set_defaults(handler=command_doctor)

    init = subparsers.add_parser("init", help="Create simulation and brief templates")
    init.add_argument("directory")
    init.set_defaults(handler=command_init)

    validate = subparsers.add_parser("validate", help="Validate a simulation specification")
    validate.add_argument("simulation")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=command_validate)

    compile_parser = subparsers.add_parser("compile", help="Compile deterministic artifacts")
    compile_parser.add_argument("simulation")
    compile_parser.add_argument("--out", required=True)
    compile_parser.add_argument("--json", action="store_true")
    compile_parser.set_defaults(handler=command_compile)

    run = subparsers.add_parser("run", help="Plan or explicitly execute a simulation")
    run.add_argument("simulation")
    run.add_argument("--out")
    run.add_argument("--execute", action="store_true")
    run.add_argument("--json", action="store_true")
    run.set_defaults(handler=command_run)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect an existing result/run")
    inspect_parser.add_argument("run_directory")
    inspect_parser.add_argument("--json", action="store_true")
    inspect_parser.set_defaults(handler=command_inspect)

    report = subparsers.add_parser("report", help="Regenerate reports from saved JSON")
    report.add_argument("run_directory")
    report.add_argument("--json", action="store_true")
    report.set_defaults(handler=command_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except AnsysSimError as exc:
        _emit(
            {
                "status": "ERROR",
                "error": {
                    "type": exc.error_type,
                    "message": str(exc),
                    "details": exc.details,
                },
            },
            bool(getattr(args, "json", False)),
        )
        return int(exc.exit_code)
    except Exception as exc:
        _emit(
            {
                "status": "ERROR",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            },
            bool(getattr(args, "json", False)),
        )
        return int(ExitCode.MECHANICAL_FAILED)


if __name__ == "__main__":
    raise SystemExit(main())
