"""CLI adapters for studies; optional dependencies load only when needed."""

from __future__ import annotations

import json
from pathlib import Path

from ansys_skill.errors import ExitCode, SpecValidationError
from ansys_skill.study.project import create_plan, load_project, planning_inputs
from ansys_skill.study.runner import run_study, status_payload
from ansys_skill.study.storage import read_json
from ansys_skill.study.templates import init_study


def _result(payload: dict, args) -> int:
    print(json.dumps(payload, indent=2 if args.json else None, sort_keys=True, allow_nan=False))
    status = payload.get("status")
    if status in {"FAIL", "NOT_RUN", "BUDGET_EXHAUSTED", "REVIEW_REQUIRED", "INSUFFICIENT_DATA", "NEEDS_SOLVE"}:
        return ExitCode.VERIFICATION_FAILED
    if status in {"PARTIAL", "INTERRUPTED"}:
        return ExitCode.MECHANICAL_FAILED
    return ExitCode.SUCCESS


def command_study(args) -> int:
    command = args.study_command
    root = Path(args.path).expanduser().resolve()
    if command == "init":
        payload = init_study(root)
    elif command == "validate":
        study, _, _ = planning_inputs(root)
        from ansys_skill.study.sampling import plan_samples
        samples, rejected = plan_samples(study)
        payload = {"status": "VALIDATED", "samples": len(samples),
                   "rejected_combinations": rejected, "solver_started": False}
    elif command == "plan":
        payload = create_plan(root, Path(args.out).expanduser().resolve())
    elif command == "run":
        payload = run_study(root, execute=args.execute, resume=args.resume, limit=args.limit)
    elif command == "status":
        _, _, manifest = load_project(root)
        payload = status_payload(manifest)
    elif command == "recover":
        from ansys_skill.study.recovery import recover_study
        payload = recover_study(root)
    elif command == "collect":
        from ansys_skill.study.dataset import collect_dataset
        payload = collect_dataset(root, reviews_path=Path(args.reviews) if args.reviews else None)
    elif command == "report":
        from ansys_skill.study.report import generate_study_report
        payload = generate_study_report(root)
    elif command == "export":
        from ansys_skill.study.bundles import export_bundle
        payload = export_bundle(root, Path(args.out).expanduser().resolve(), kind=args.kind)
    elif command == "import":
        from ansys_skill.study.bundles import import_bundle
        payload = import_bundle(root, Path(args.out).expanduser().resolve(),
                                expected_study_id=args.expected_study_id)
    elif command == "optimize":
        from ansys_skill.study.optimization import execute_proposal, propose_candidates
        plan = propose_candidates(root, Path(args.model) if args.model else None)
        payload = execute_proposal(root, plan, execute=args.execute) if plan["status"] == "PROPOSED" else plan
    elif command == "verify":
        from ansys_skill.study.optimization import verify_candidates
        payload = verify_candidates(root, Path(args.model) if args.model else None, execute=args.execute,
                                    reviews_path=Path(args.reviews) if args.reviews else None)
    elif command == "workflow":
        from ansys_skill.study.workflow import complete_workflow
        payload = complete_workflow(root, execute=args.execute, resume=args.resume,
                                    reviews_path=Path(args.reviews) if args.reviews else None)
    elif command == "compare":
        from ansys_skill.study.comparison import run_comparison
        payload = run_comparison(root, execute=args.execute,
                                 reviews_path=Path(args.reviews) if args.reviews else None)
    else:
        raise SpecValidationError("Unknown study command")
    return _result(payload, args)


def command_surrogate(args) -> int:
    from ansys_skill.study.modeling import evaluate_study, train_study
    from ansys_skill.surrogate import predict_model

    path = Path(args.path).expanduser().resolve()
    if args.surrogate_command == "train":
        payload = train_study(path)
    elif args.surrogate_command == "evaluate":
        payload = evaluate_study(path, Path(args.model) if args.model else None)
    else:
        from ansys_skill.study.geometry import validate_parameters
        parameters = read_json(Path(args.parameters))
        validate_parameters(parameters)
        payload = predict_model(path, parameters)
    return _result(payload, args)


def register_commands(subparsers) -> None:
    study = subparsers.add_parser("study", help="Plan, execute and audit a parameterized design study")
    actions = study.add_subparsers(dest="study_command", required=True)
    helps = {
        "init": "Write an explicit bracket study template",
        "validate": "Validate study inputs and constrained parameter sampling",
        "plan": "Create a portable immutable study plan",
        "run": "Prepare dry-runs or explicitly execute serial mesh studies",
        "status": "Read study execution state",
        "recover": "Remove a local lock only after proving its processes are stopped",
        "collect": "Create a versioned dataset using numerical quality evidence",
        "report": "Rebuild HTML and Markdown reports from recorded evidence",
        "export": "Package private Windows task or result artifacts",
        "import": "Verify and import a package into a new directory",
        "optimize": "Propose constrained designs and optionally execute adaptive samples",
        "verify": "Propose final designs and optionally confirm them with Mechanical",
        "workflow": "Run the complete budgeted design workflow",
        "compare": "Measure independent direct search with the same solver-call allowance",
    }
    for name, help_text in helps.items():
        parser = actions.add_parser(name, help=help_text)
        parser.add_argument("path", help="Study directory, input YAML or bundle according to the command")
        parser.add_argument("--json", action="store_true")
        parser.set_defaults(handler=command_study)
        if name in {"plan", "export", "import"}:
            parser.add_argument("--out", required=True)
        if name in {"run", "workflow", "optimize", "verify", "compare"}:
            parser.add_argument("--execute", action="store_true", help="Explicitly allow solver calls within the study budget")
        if name in {"run", "workflow"}:
            parser.add_argument("--resume", action="store_true")
        if name == "run":
            parser.add_argument("--limit", type=int, help="Limit the number of additional design points")
        if name in {"collect", "verify", "workflow", "compare"}:
            parser.add_argument("--reviews", help="Recorded stress reviews bound to individual RST hashes")
        if name in {"optimize", "verify"}:
            parser.add_argument("--model")
        if name == "export":
            parser.add_argument("--kind", choices=["task", "results"], default="task")
        if name == "import":
            parser.add_argument("--expected-study-id")
    surrogate = subparsers.add_parser("surrogate", help="Train, evaluate and predict with auditable surrogate models")
    models = surrogate.add_subparsers(dest="surrogate_command", required=True)
    for name in ("train", "evaluate", "predict"):
        parser = models.add_parser(name)
        parser.add_argument("path", help="Study directory for training/evaluation; model directory for prediction")
        parser.add_argument("--json", action="store_true")
        if name == "evaluate":
            parser.add_argument("--model")
        if name == "predict":
            parser.add_argument("--parameters", required=True, help="JSON object of unit-qualified feature names with SI values")
        parser.set_defaults(handler=command_surrogate)
