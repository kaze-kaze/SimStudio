"""An independent direct-search control with the same solver-call allowance."""

from __future__ import annotations

from pathlib import Path

from ansys_skill.errors import SpecValidationError
from ansys_skill.study.dataset import collect_dataset
from ansys_skill.study.geometry import validate_parameters
from ansys_skill.study.modeling import latest_dataset
from ansys_skill.study.project import load_project, make_jobs, save_project
from ansys_skill.study.runner import run_study
from ansys_skill.study.sampling import design_id, latin_points, sample_record
from ansys_skill.study.storage import atomic_json, study_lock


def comparison_plan(root: Path) -> dict:
    with study_lock(root):
        study, _, manifest = load_project(root, check_code=True)
        previous = manifest.get("direct_comparison")
        if previous:
            return previous
        baseline = [s for s in manifest["samples"] if s["split"] == "baseline"]
        evaluation = [s for s in manifest["samples"] if s["split"] == "test"]
        surrogate = [s for s in manifest["samples"] if s["split"] in {"train", "verification"}]
        def calls(samples):
            return sum(len(j["attempts"]) for s in samples for j in s["jobs"])
        shared_calls = calls(baseline) + calls(evaluation)
        allowance = calls(surrogate)
        count = allowance // len(study.mesh.sizes)
        if count == 0:
            raise SpecValidationError("No completed surrogate search budget is available for comparison")
        if allowance > study.budget.max_solver_calls - manifest["solver_calls"]:
            return {"status": "BUDGET_EXHAUSTED", "required_solver_calls": allowance}
        seen = {s["design_id"] for s in manifest["samples"]}
        selected = []
        for parameters in latin_points(study.bounds(), count * 3, (study.sampling.seed + 999999) % 2**32):
            try:
                validate_parameters(parameters)
            except SpecValidationError:
                continue
            identity = design_id(parameters)
            if identity in seen:
                continue
            selected.append(parameters)
            seen.add(identity)
            if len(selected) == count:
                break
        if len(selected) != count:
            raise SpecValidationError("Insufficient distinct valid comparison samples")
        plan = {"status": "PLANNED", "shared_solver_calls": shared_calls,
                "surrogate_solver_calls": shared_calls + allowance,
                "direct_search_allowance": allowance, "sample_count": count,
                "parameters": selected, "inference_used_for_sampling": False,
                "shared_evidence": "Baseline and frozen accuracy holdout; holdout does not enter design search."}
        manifest["direct_comparison"] = plan
        save_project(root, manifest)
        atomic_json(root / "comparison-plan.json", plan)
        return plan


def run_comparison(root: Path, *, execute=False, reviews_path=None) -> dict:
    plan = comparison_plan(root)
    if not execute or plan["status"] == "BUDGET_EXHAUSTED":
        return plan
    with study_lock(root):
        study, _, manifest = load_project(root, check_code=True)
        seen = {s["design_id"] for s in manifest["samples"]}
        for parameters in plan["parameters"]:
            if design_id(parameters) in seen:
                continue
            sample = sample_record(parameters, "comparison", ordinal=len(manifest["samples"]))
            sample["jobs"] = make_jobs(study)
            manifest["samples"].append(sample)
        save_project(root, manifest)
    result = run_study(root, execute=True, resume=True, splits=("comparison",),
                       solver_call_limit=plan["direct_search_allowance"])
    collect_dataset(root, reviews_path=reviews_path)
    study, _, manifest = load_project(root)
    dataset = latest_dataset(root, manifest)
    def eligible(split):
        return [row for row in dataset["rows"] if row["split"] in split
                and all(row["feasibility"].get(name) == "FEASIBLE" for name in study.targets)]
    direct = eligible({"baseline", "comparison"})
    surrogate = eligible({"baseline", "train", "verification"})
    calls = sum(len(job["attempts"]) for sample in manifest["samples"]
                if sample["split"] == "comparison" for job in sample["jobs"])
    expected = {design_id(parameters) for parameters in plan["parameters"]}
    samples = [sample for sample in manifest["samples"] if sample["split"] == "comparison"]
    rows = [row for row in dataset["rows"] if row["split"] == "comparison"]
    complete = (bool(expected) and len(samples) == len(expected)
                and {sample["design_id"] for sample in samples} == expected
                and all(sample["status"] == "SOLVED" for sample in samples))
    quality_complete = (len(rows) == len(expected)
                        and {row["design_id"] for row in rows} == expected
                        and all(set(row["accepted_targets"]) == set(study.targets) for row in rows))
    direct_best = min(direct, key=lambda row: row["mass_kg"], default=None)
    surrogate_best = min(surrogate, key=lambda row: row["mass_kg"], default=None)
    report = {
        "status": "PASS" if complete and quality_complete and direct_best and surrogate_best else "NOT_RUN",
        "execution_status": result["status"],
        "allowance_equal": True, "direct_search_allowance": plan["direct_search_allowance"],
        "surrogate_total_solver_calls": plan["surrogate_solver_calls"],
        "direct_total_solver_calls": plan["shared_solver_calls"] + calls,
        "shared_solver_calls": plan["shared_solver_calls"],
        "direct_best": {key: direct_best[key] for key in ("sample_id", "mass_kg", "targets")} if direct_best else None,
        "surrogate_best": {key: surrogate_best[key] for key in ("sample_id", "mass_kg", "targets")} if surrogate_best else None,
        "mass_improvement_vs_direct": ((direct_best["mass_kg"] - surrogate_best["mass_kg"]) / direct_best["mass_kg"])
                                      if direct_best and surrogate_best else None,
        "solver_command_seconds": {split: sum(row["solver_command_seconds"] for row in dataset["rows"] if row["split"] == split)
                                   for split in ("baseline", "train", "test", "verification", "comparison")},
        "training_seconds": sum(model["training_seconds"] for model in manifest["models"]),
        "study_elapsed_seconds": manifest["elapsed_seconds"],
        "conclusion": "Measured control comparison; no speedup is assumed.",
    }
    atomic_json(root / "comparison.json", report)
    return report
