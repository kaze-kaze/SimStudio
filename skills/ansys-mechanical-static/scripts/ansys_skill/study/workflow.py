"""Complete orchestration with quality gates and an untouched final holdout."""

from __future__ import annotations

from pathlib import Path

from ansys_skill.errors import SpecValidationError
from ansys_skill.manifest import sha256_file
from ansys_skill.paths import safe_join
from ansys_skill.study.dataset import collect_dataset
from ansys_skill.study.modeling import evaluate_study, latest_dataset, train_study
from ansys_skill.study.optimization import execute_proposal, propose_candidates, verify_candidates
from ansys_skill.study.project import load_project
from ansys_skill.study.runner import run_study
from ansys_skill.study.storage import atomic_json, canonical_hash, read_json, study_lock


def _evidence_fingerprint(root: Path, manifest: dict) -> str:
    keys = ("study_id", "study_fingerprint", "code_fingerprint", "inputs", "samples",
            "datasets", "models", "rounds", "holdout_evaluated", "direct_comparison",
            "solver_calls", "execution_context")
    paths = {"verification.json", "comparison.json"}
    paths.update(manifest.get("datasets", [])[-1:])
    for model in manifest.get("models", []):
        paths.update(f"{model['path']}/{name}" for name in (
            "model.json", "model-card.json", "training-provenance.json", "evaluation.json"))
    hashes = {}
    for relative in sorted(paths):
        path = safe_join(root, relative)
        hashes[relative] = sha256_file(path) if path.is_file() and not path.is_symlink() else None
    return canonical_hash({"manifest": {key: manifest.get(key) for key in keys}, "artifacts": hashes})


def recorded_workflow_result(root: Path, manifest: dict) -> dict | None:
    """Return an outcome only while its small result artifacts and ledger still match."""
    try:
        result = read_json(root / "workflow-result.json")
        if result.get("evidence_fingerprint") == _evidence_fingerprint(root, manifest):
            return result
    except (SpecValidationError, OSError, ValueError, KeyError):
        return None
    return None


def _finish(root: Path, result: dict) -> dict:
    from ansys_skill.study.report import generate_study_report

    with study_lock(root):
        _, _, manifest = load_project(root)
        result = {**result, "study_fingerprint": manifest.get("study_fingerprint"),
                  "evidence_fingerprint": _evidence_fingerprint(root, manifest)}
        atomic_json(root / "workflow-result.json", result)
    return {**result, "report": generate_study_report(root)}


def _training_ready(study, dataset):
    counts = {name: sum(row["split"] == "train" and name in row["accepted_targets"]
                        for row in dataset["rows"]) for name in study.targets}
    enough = all(count >= max(6, study.model.cv_folds + 1) for count in counts.values())
    return enough, counts


def _best_mass(dataset):
    rows = [row for row in dataset["rows"] if row["split"] in {"train", "baseline"}
            and all(row["feasibility"].get(name) == "FEASIBLE" for name in dataset["targets"])]
    return min((row["mass_kg"] for row in rows), default=None)


def complete_workflow(root: Path, *, execute=False, resume=False, reviews_path=None) -> dict:
    from ansys_skill.study.report import generate_study_report

    root = root.resolve()
    result = run_study(root, execute=execute, resume=resume, splits=("baseline", "train", "test"))
    if not execute:
        return {**result, "report": generate_study_report(root)}
    if result["status"] in {"BUDGET_EXHAUSTED", "INTERRUPTED"}:
        return _finish(root, result)
    collect_dataset(root, reviews_path=reviews_path)
    study, _, manifest = load_project(root)
    dataset = latest_dataset(root, manifest)
    ready, counts = _training_ready(study, dataset)
    if not ready:
        return _finish(root, {"status": "REVIEW_REQUIRED", "accepted_training_samples": counts,
                "message": "Inspect recorded numerical, mesh and stress-review exclusions before training."})
    if not manifest.get("holdout_evaluated"):
        training = train_study(root)
        if training["status"] != "TRAINED":
            return _finish(root, training)
        previous_mass = _best_mass(dataset)
        for _ in range(study.optimization.max_rounds):
            plan = propose_candidates(root)
            if plan["status"] == "BUDGET_EXHAUSTED":
                return _finish(root, plan)
            if plan["status"] != "PROPOSED":
                break
            result = execute_proposal(root, plan, execute=True)
            if result["status"] in {"BUDGET_EXHAUSTED", "INTERRUPTED"}:
                return _finish(root, result)
            collect_dataset(root, reviews_path=reviews_path)
            study, _, manifest = load_project(root)
            dataset = latest_dataset(root, manifest)
            new_ids = {item["design_id"] for item in plan["candidates"]}
            new_rows = [row for row in dataset["rows"] if row["design_id"] in new_ids]
            if len(new_rows) != len(new_ids) or any(set(row["accepted_targets"]) != set(study.targets) for row in new_rows):
                return _finish(root, {"status": "REVIEW_REQUIRED", "message": "New samples require quality review."})
            training = train_study(root)
            if training["status"] != "TRAINED":
                return _finish(root, training)
            current_mass = _best_mass(dataset)
            if (previous_mass is not None and current_mass is not None
                    and (previous_mass - current_mass) / previous_mass <= study.optimization.improvement_tolerance):
                break
            previous_mass = current_mass
        evaluation = evaluate_study(root)
    else:
        path = root / manifest["holdout_evaluated"]["model"] / "evaluation.json"
        # Re-evaluate the same frozen model if publication was interrupted or test quality changed.
        evaluation = evaluate_study(root, model_path=path.parent)
    if evaluation.get("status") != "PASS":
        return _finish(root, {"status": "REVIEW_REQUIRED" if evaluation.get("status") == "NOT_RUN" else "FAIL",
                "stage": "independent_model_evaluation",
                "evaluation": evaluation})
    verification = verify_candidates(root, execute=True, reviews_path=reviews_path)
    comparison = {"status": "NOT_RUN"}
    if verification["status"] == "PASS" and study.optimization.compare_direct_search:
        from ansys_skill.study.comparison import run_comparison
        comparison = run_comparison(root, execute=True, reviews_path=reviews_path)
    result = {"status": verification["status"], "model_evaluation": evaluation["status"],
              "verification": verification, "engineering_validation": verification["status"],
              "equal_budget_comparison": comparison}
    if (verification["status"] == "PASS" and study.optimization.compare_direct_search
            and comparison["status"] != "PASS"):
        result["status"] = "REVIEW_REQUIRED" if comparison["status"] == "NOT_RUN" else comparison["status"]
    return _finish(root, result)
