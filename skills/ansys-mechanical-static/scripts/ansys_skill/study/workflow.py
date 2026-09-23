"""Complete orchestration with quality gates and an untouched final holdout."""

from __future__ import annotations

from pathlib import Path

from ansys_skill.study.dataset import collect_dataset
from ansys_skill.study.modeling import evaluate_study, latest_dataset, train_study
from ansys_skill.study.optimization import execute_proposal, propose_candidates, verify_candidates
from ansys_skill.study.project import load_project
from ansys_skill.study.runner import run_study
from ansys_skill.study.storage import atomic_json


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
    result = run_study(root, execute=execute, resume=resume)
    if not execute:
        return {**result, "report": generate_study_report(root)}
    if result["status"] in {"BUDGET_EXHAUSTED", "INTERRUPTED"}:
        return {**result, "report": generate_study_report(root)}
    collect_dataset(root, reviews_path=reviews_path)
    study, _, manifest = load_project(root)
    dataset = latest_dataset(root, manifest)
    ready, counts = _training_ready(study, dataset)
    if not ready:
        return {"status": "REVIEW_REQUIRED", "accepted_training_samples": counts,
                "message": "Inspect recorded numerical, mesh and stress-review exclusions before training.",
                "report": generate_study_report(root)}
    if not manifest.get("holdout_evaluated"):
        training = train_study(root)
        if training["status"] != "TRAINED":
            return {**training, "report": generate_study_report(root)}
        previous_mass = _best_mass(dataset)
        for _ in range(study.optimization.max_rounds):
            plan = propose_candidates(root)
            if plan["status"] != "PROPOSED":
                break
            result = execute_proposal(root, plan, execute=True)
            if result["status"] in {"BUDGET_EXHAUSTED", "INTERRUPTED"}:
                return {**result, "report": generate_study_report(root)}
            collect_dataset(root, reviews_path=reviews_path)
            study, _, manifest = load_project(root)
            dataset = latest_dataset(root, manifest)
            new_ids = {item["design_id"] for item in plan["candidates"]}
            new_rows = [row for row in dataset["rows"] if row["design_id"] in new_ids]
            if len(new_rows) != len(new_ids) or any(set(row["accepted_targets"]) != set(study.targets) for row in new_rows):
                return {"status": "REVIEW_REQUIRED", "message": "New samples require quality review.",
                        "report": generate_study_report(root)}
            training = train_study(root)
            if training["status"] != "TRAINED":
                return {**training, "report": generate_study_report(root)}
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
        return {"status": "REVIEW_REQUIRED" if evaluation.get("status") == "NOT_RUN" else "FAIL",
                "stage": "independent_model_evaluation",
                "evaluation": evaluation, "report": generate_study_report(root)}
    verification = verify_candidates(root, execute=True, reviews_path=reviews_path)
    comparison = {"status": "NOT_RUN"}
    if verification["status"] == "PASS" and study.optimization.compare_direct_search:
        from ansys_skill.study.comparison import run_comparison
        comparison = run_comparison(root, execute=True, reviews_path=reviews_path)
    result = {"status": verification["status"], "model_evaluation": evaluation["status"],
              "verification": verification, "engineering_validation": verification["status"],
              "equal_budget_comparison": comparison}
    if study.optimization.compare_direct_search and comparison["status"] != "PASS":
        result["status"] = "REVIEW_REQUIRED" if comparison["status"] == "NOT_RUN" else comparison["status"]
    atomic_json(root / "workflow-result.json", result)
    result["report"] = generate_study_report(root)
    return result
