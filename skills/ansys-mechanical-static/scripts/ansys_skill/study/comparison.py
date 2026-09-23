"""An independent direct-search control with the same solver-call allowance."""

from __future__ import annotations

import math
from numbers import Real
from pathlib import Path

from ansys_skill.errors import SpecValidationError
from ansys_skill.paths import safe_join
from ansys_skill.study.dataset import collect_dataset
from ansys_skill.study.geometry import validate_parameters
from ansys_skill.study.modeling import latest_dataset
from ansys_skill.study.project import load_project, make_jobs, save_project
from ansys_skill.study.runner import run_study
from ansys_skill.study.sampling import design_id, latin_points, sample_record
from ansys_skill.study.storage import atomic_json, canonical_hash, read_json, study_lock

_RESEARCH_SPLITS = ("baseline", "test", "train", "verification")
_REPORT_SPLITS = (*_RESEARCH_SPLITS, "comparison")
_ATTEMPT_PHASES = ("mesh", "solve", "backend_total", "postprocessing", "report_generation")


def _research_snapshot(manifest: dict) -> dict:
    """Freeze only the evidence used to set the comparison allowance and holdout."""
    samples = manifest.get("samples", [])
    design_ids = {
        split: sorted(sample["design_id"] for sample in samples if sample["split"] == split)
        for split in _RESEARCH_SPLITS
    }
    ledger = []
    for split in _RESEARCH_SPLITS:
        selected = sorted(
            (sample for sample in samples if sample["split"] == split),
            key=lambda sample: (sample["design_id"], sample.get("sample_id", "")),
        )
        for sample in selected:
            jobs = sorted(sample.get("jobs", []), key=lambda job: job.get("mesh_index", -1))
            for job in jobs:
                attempts = [
                    {
                        "ordinal": attempt.get("attempt", index + 1),
                        "path": attempt.get("path"),
                        "status": attempt.get("status"),
                        "elapsed_seconds": attempt.get("elapsed_seconds"),
                        "record_sha256": canonical_hash(attempt),
                    }
                    for index, attempt in enumerate(job.get("attempts", []))
                ]
                ledger.append({
                    "split": split,
                    "sample_id": sample.get("sample_id"),
                    "design_id": sample["design_id"],
                    "mesh_index": job.get("mesh_index"),
                    "attempts": attempts,
                })
    snapshot = {"design_ids": design_ids, "attempt_ledger": ledger}
    snapshot["snapshot_id"] = canonical_hash(snapshot)
    return snapshot


def _validate_research_snapshot(plan: dict, manifest: dict) -> None:
    snapshot = plan.get("research_snapshot")
    if not isinstance(snapshot, dict):
        raise SpecValidationError(
            "Direct comparison plan is stale or lacks a research snapshot; create a new study"
        )
    expected = _research_snapshot(manifest)
    if (snapshot.get("snapshot_id") != expected["snapshot_id"]
            or canonical_hash({key: value for key, value in snapshot.items() if key != "snapshot_id"})
            != expected["snapshot_id"]):
        raise SpecValidationError(
            "Direct comparison plan is stale because baseline/test/train/verification evidence changed; "
            "create a new study"
        )


def _attempts(manifest: dict, split: str | None = None) -> list[dict]:
    return [
        attempt
        for sample in manifest.get("samples", [])
        if split is None or sample.get("split") == split
        for job in sample.get("jobs", [])
        for attempt in job.get("attempts", [])
    ]


def _seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


def _cost_summary(attempts: list[dict]) -> dict:
    values = [_seconds(attempt.get("elapsed_seconds")) for attempt in attempts]
    known = [value for value in values if value is not None]
    unknown = len(values) - len(known)
    return {
        "calls": len(attempts),
        "seconds": sum(known) if not unknown else None,
        "known_seconds": sum(known) if known else None,
        "timed_calls": len(known),
        "unknown_time_calls": unknown,
        "failed_calls": sum(attempt.get("status") in {"FAILED", "INTERRUPTED"} for attempt in attempts),
        "running_calls": sum(attempt.get("status") == "RUNNING" for attempt in attempts),
        "status": "NOT_RUN" if not attempts else "PARTIAL" if unknown else "RECORDED",
    }


def _phase_costs(manifest: dict) -> dict:
    result = {}
    for split in _REPORT_SPLITS:
        attempts = _attempts(manifest, split)
        names = set(_ATTEMPT_PHASES)
        for attempt in attempts:
            phases = attempt.get("phase_timings", {})
            if isinstance(phases, dict):
                names.update(phases)
        result[split] = {}
        for name in sorted(names):
            recorded = []
            for attempt in attempts:
                phases = attempt.get("phase_timings", {})
                phase = phases.get(name) if isinstance(phases, dict) else None
                elapsed = _seconds(phase.get("elapsed_seconds")) if isinstance(phase, dict) else None
                if isinstance(phase, dict) and phase.get("status") == "RECORDED" and elapsed is not None:
                    recorded.append(elapsed)
            unknown = len(attempts) - len(recorded)
            result[split][name] = {
                "status": "NOT_RUN" if not recorded else "PARTIAL" if unknown else "RECORDED",
                "known_seconds": sum(recorded) if recorded else None,
                "recorded_attempts": len(recorded),
                "unknown_attempts": unknown,
            }
    return result


def _geometry_costs(manifest: dict) -> dict:
    result = {}
    for split in _REPORT_SPLITS:
        samples = [sample for sample in manifest.get("samples", []) if sample.get("split") == split]
        timings = []
        for sample in samples:
            geometry = sample.get("geometry")
            value = sample.get("geometry_seconds")
            if value is None and isinstance(geometry, dict):
                value = geometry.get("geometry_seconds")
            duration = _seconds(value)
            if duration is not None:
                timings.append(duration)
        unknown = len(samples) - len(timings)
        result[split] = {
            "status": "NOT_RUN" if not timings else "PARTIAL" if unknown else "RECORDED",
            "sample_count": len(samples),
            "timed_samples": len(timings),
            "unknown_samples": unknown,
            "known_seconds": sum(timings) if timings else None,
            "seconds_per_sample": sum(timings) / len(timings) if timings else None,
        }
    return result


def _round_search_costs(root: Path, manifest: dict) -> list[dict]:
    result = []
    for record in manifest.get("rounds", []):
        duration = None
        path = record.get("plan")
        if isinstance(path, str):
            try:
                plan = read_json(safe_join(root, path))
                duration = _seconds(plan.get("search_seconds"))
            except (OSError, SpecValidationError, ValueError):
                duration = None
        result.append({
            "round": record.get("round"),
            "purpose": record.get("purpose"),
            "round_status": record.get("status", "NOT_RUN"),
            "status": "RECORDED" if duration is not None else "NOT_RUN",
            "search_seconds": duration,
        })
    return result


def _target_margins(row: dict | None, study) -> dict:
    result = {}
    values = row.get("targets", {}) if isinstance(row, dict) else {}
    feasibility = row.get("feasibility", {}) if isinstance(row, dict) else {}
    for name, target in study.targets.items():
        canonical = target.canonical()
        value = values.get(name) if isinstance(values, dict) else None
        valid = (isinstance(value, Real) and not isinstance(value, bool)
                 and math.isfinite(float(value)))
        result[name] = {
            "value": float(value) if valid else None,
            "limit": canonical["limit"],
            "margin": canonical["limit"] - float(value) if valid else None,
            "unit": canonical["unit"],
            "status": "RECORDED" if valid else "NOT_RUN",
            "feasibility": (
                feasibility.get(name, "UNKNOWN") if isinstance(feasibility, dict) else "UNKNOWN"
            ) if not valid else (
                feasibility.get(name, "FEASIBLE" if float(value) <= canonical["limit"] else "INFEASIBLE")
                if isinstance(feasibility, dict) else
                "FEASIBLE" if float(value) <= canonical["limit"] else "INFEASIBLE"
            ),
        }
    return result


def _verified_candidate(
    root: Path, study, dataset: dict, manifest: dict
) -> tuple[dict | None, str]:
    path = safe_join(root, "verification.json")
    if not path.is_file():
        return None, "NOT_RUN"
    try:
        evidence = read_json(path)
    except SpecValidationError:
        return None, "INVALID"
    sample_id = evidence.get("best_sample_id")
    candidates = evidence.get("candidates", [])
    if not isinstance(sample_id, str) or not isinstance(candidates, list):
        return None, "NOT_RUN"
    if (evidence.get("study_fingerprint") != manifest.get("study_fingerprint")
            or dataset.get("study_fingerprint") != manifest.get("study_fingerprint")
            or dataset.get("frozen_test_designs") != manifest.get("frozen_test_designs")):
        return None, "STALE"
    verification_rounds = [record for record in manifest.get("rounds", [])
                           if record.get("purpose") == "verification"]
    if not verification_rounds:
        return None, "STALE"
    verification_round = verification_rounds[-1]
    frozen_model_id = verification_round.get("model_id")
    holdout_model_id = manifest.get("holdout_evaluated", {}).get("model_id")
    if (not frozen_model_id or evidence.get("model_id") != frozen_model_id
            or (holdout_model_id is not None and evidence.get("model_id") != holdout_model_id)):
        return None, "STALE"
    try:
        verification_plan = read_json(safe_join(root, verification_round["plan"]))
    except (KeyError, OSError, SpecValidationError, ValueError):
        return None, "STALE"
    if (verification_plan.get("model_id") != frozen_model_id
            or verification_plan.get("study_fingerprint") != manifest.get("study_fingerprint")):
        return None, "STALE"
    candidate = next((item for item in candidates
                      if isinstance(item, dict) and item.get("sample_id") == sample_id
                      and item.get("verified") is True and item.get("feasible") is True), None)
    if candidate is None:
        return None, "NOT_RUN"
    samples = [sample for sample in manifest.get("samples", [])
               if sample.get("sample_id") == sample_id and sample.get("split") == "verification"]
    rows = [row for row in dataset.get("rows", [])
            if row.get("sample_id") == sample_id and row.get("split") == "verification"]
    if len(samples) != 1 or len(rows) != 1:
        return None, "STALE"
    sample, row = samples[0], rows[0]
    planned_candidates = verification_plan.get("candidates", [])
    if not isinstance(planned_candidates, list):
        return None, "STALE"
    planned_ids = {item.get("design_id") for item in planned_candidates if isinstance(item, dict)}
    if sample.get("candidate_plan") != verification_round.get("plan") or sample.get("design_id") not in planned_ids:
        return None, "STALE"
    source = row.get("source", {})
    target_names = set(study.targets)
    row_targets = row.get("targets", {})
    candidate_targets = candidate.get("targets", {})
    mass = row.get("mass_kg")
    candidate_mass = candidate.get("mass_kg")
    accepted = set(row.get("accepted_targets", []))
    feasibility = row.get("feasibility", {})
    matches = (
        isinstance(source, dict)
        and
        candidate.get("design_id") == sample.get("design_id") == row.get("design_id")
        and source.get("kind") == "solver"
        and source.get("synthetic") is False
        and source.get("complete_real_evidence") is True
        and target_names <= accepted
        and target_names <= set(candidate.get("accepted_targets", []))
        and all(feasibility.get(name) == "FEASIBLE" for name in target_names)
        and isinstance(row_targets, dict)
        and isinstance(candidate_targets, dict)
        and all(name in row_targets and candidate_targets.get(name) == row_targets[name]
                for name in target_names)
        and _seconds(mass) is not None and _seconds(candidate_mass) is not None
        and float(mass) == float(candidate_mass)
    )
    if not matches:
        return None, "STALE"
    keys = ("sample_id", "design_id", "mass_kg", "targets", "accepted_targets",
            "feasible", "verified", "prediction_errors")
    return {
        **{key: candidate[key] for key in keys if key in candidate},
        "model_id": evidence["model_id"],
        "study_fingerprint": evidence["study_fingerprint"],
    }, "RECORDED"


def _baseline_comparison(baseline: dict | None, candidates: dict[str, dict | None], study) -> dict:
    if baseline is None:
        return {name: {"status": "NOT_RUN", "mass_delta_kg": None, "target_value_delta": {}}
                for name in candidates}
    result = {}
    baseline_targets = baseline.get("targets", {})
    for name, candidate in candidates.items():
        if candidate is None:
            result[name] = {"status": "NOT_RUN", "mass_delta_kg": None, "target_value_delta": {}}
            continue
        base_mass, candidate_mass = baseline.get("mass_kg"), candidate.get("mass_kg")
        mass_delta = (float(candidate_mass) - float(base_mass)
                      if all(isinstance(value, Real) and not isinstance(value, bool)
                             and math.isfinite(float(value)) for value in (base_mass, candidate_mass)) else None)
        targets = candidate.get("targets", {})
        deltas = {}
        for target_name, target in study.targets.items():
            old = baseline_targets.get(target_name) if isinstance(baseline_targets, dict) else None
            new = targets.get(target_name) if isinstance(targets, dict) else None
            valid = all(isinstance(value, Real) and not isinstance(value, bool)
                        and math.isfinite(float(value)) for value in (old, new))
            deltas[target_name] = {
                "value_delta": float(new) - float(old) if valid else None,
                "unit": target.canonical()["unit"],
                "status": "RECORDED" if valid else "NOT_RUN",
            }
        result[name] = {"status": "RECORDED", "mass_delta_kg": mass_delta,
                        "target_value_delta": deltas}
        if mass_delta is None or any(item["status"] != "RECORDED" for item in deltas.values()):
            result[name]["status"] = "PARTIAL"
    return result


def comparison_plan(root: Path) -> dict:
    with study_lock(root):
        study, _, manifest = load_project(root, check_code=True)
        previous = manifest.get("direct_comparison")
        if previous:
            _validate_research_snapshot(previous, manifest)
            return previous
        snapshot = _research_snapshot(manifest)
        samples = manifest["samples"]

        def calls(split: str) -> int:
            return sum(len(job.get("attempts", [])) for sample in samples
                       if sample["split"] == split for job in sample["jobs"])

        shared_calls = calls("baseline") + calls("test")
        allowance = calls("train") + calls("verification")
        remaining = max(0, study.budget.max_solver_calls - manifest["solver_calls"])
        if allowance == 0:
            return {"status": "BUDGET_EXHAUSTED", "reason": "NO_SURROGATE_SEARCH_ATTEMPTS",
                    "required_solver_calls": len(study.mesh.sizes), "remaining_solver_calls": remaining}
        if allowance > remaining:
            return {"status": "BUDGET_EXHAUSTED", "required_solver_calls": allowance,
                    "remaining_solver_calls": remaining}
        count = allowance // len(study.mesh.sizes)
        if count == 0:
            return {"status": "BUDGET_EXHAUSTED", "required_solver_calls": len(study.mesh.sizes),
                    "remaining_solver_calls": remaining,
                    "reason": "SURROGATE_ATTEMPTS_DO_NOT_COVER_ONE_MESH_SET"}
        seen = {sample["design_id"] for sample in samples}
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
        plan = {
            "status": "PLANNED",
            "shared_solver_calls": shared_calls,
            "surrogate_solver_calls": shared_calls + allowance,
            "direct_search_allowance": allowance,
            "sample_count": count,
            "parameters": selected,
            "inference_used_for_sampling": False,
            "shared_evidence": "Baseline and frozen accuracy holdout; holdout does not enter design search.",
            "research_snapshot": snapshot,
        }
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
        _validate_research_snapshot(plan, manifest)
        seen = {sample["design_id"] for sample in manifest["samples"]}
        for parameters in plan["parameters"]:
            if design_id(parameters) in seen:
                continue
            sample = sample_record(parameters, "comparison", ordinal=len(manifest["samples"]))
            sample["jobs"] = make_jobs(study)
            manifest["samples"].append(sample)
            seen.add(sample["design_id"])
        save_project(root, manifest)
    result = run_study(root, execute=True, resume=True, splits=("comparison",),
                       solver_call_limit=plan["direct_search_allowance"])
    collect_dataset(root, reviews_path=reviews_path)
    study, _, manifest = load_project(root)
    _validate_research_snapshot(plan, manifest)
    dataset = latest_dataset(root, manifest)

    def eligible(splits):
        return [row for row in dataset["rows"] if row["split"] in splits
                and all(row.get("feasibility", {}).get(name) == "FEASIBLE" for name in study.targets)]

    direct = eligible({"baseline", "comparison"})
    surrogate = eligible({"baseline", "train", "verification"})
    observed_training = eligible({"train"})
    expected = {design_id(parameters) for parameters in plan["parameters"]}
    comparison_samples = [sample for sample in manifest["samples"] if sample["split"] == "comparison"]
    rows = [row for row in dataset["rows"] if row["split"] == "comparison"]
    complete = (bool(expected) and len(comparison_samples) == len(expected)
                and {sample["design_id"] for sample in comparison_samples} == expected
                and all(sample["status"] == "SOLVED" for sample in comparison_samples))
    quality_complete = (len(rows) == len(expected)
                        and {row["design_id"] for row in rows} == expected
                        and all(set(row.get("accepted_targets", [])) == set(study.targets) for row in rows))
    direct_best = min(direct, key=lambda row: row["mass_kg"], default=None)
    surrogate_best = min(surrogate, key=lambda row: row["mass_kg"], default=None)
    training_best = min(observed_training, key=lambda row: row["mass_kg"], default=None)
    baseline = next((row for row in dataset["rows"] if row.get("split") == "baseline"), None)
    verified, verification_status = _verified_candidate(root, study, dataset, manifest)

    attempts_by_split = {split: _attempts(manifest, split) for split in _REPORT_SPLITS}
    costs_by_split = {split: _cost_summary(attempts) for split, attempts in attempts_by_split.items()}
    all_attempts = [attempt for values in attempts_by_split.values() for attempt in values]
    costs_total = _cost_summary(all_attempts)
    solver_command_seconds = {split: costs["seconds"] for split, costs in costs_by_split.items()}
    solver_calls = {split: costs["calls"] for split, costs in costs_by_split.items()}
    shared_actual_calls = solver_calls["baseline"] + solver_calls["test"]
    surrogate_actual_calls = shared_actual_calls + solver_calls["train"] + solver_calls["verification"]
    direct_actual_calls = shared_actual_calls + solver_calls["comparison"]
    comparison_failed_attempts = costs_by_split["comparison"]["failed_calls"]
    terminal_failures = {"FAILED", "GEOMETRY_FAILED", "INTERRUPTED"}
    failed_samples = [sample.get("sample_id") for sample in comparison_samples
                      if sample.get("status") in terminal_failures]
    if result.get("status") == "BUDGET_EXHAUSTED":
        status = "BUDGET_EXHAUSTED"
    elif result.get("status") == "INTERRUPTED":
        status = "INTERRUPTED"
    elif result.get("status") == "FAILED" or failed_samples:
        status = "FAILED"
    elif complete and quality_complete and direct_best and surrogate_best:
        status = "PASS"
    elif result.get("status") == "PARTIAL":
        status = "PARTIAL"
    else:
        status = "NOT_RUN"

    candidate_rows = {
        "direct_best": direct_best,
        "surrogate_best": surrogate_best,
        "best_observed_training": training_best,
        "verified_candidate": verified,
    }
    margins = {"baseline": _target_margins(baseline, study)}
    margins.update({name: _target_margins(row, study) for name, row in candidate_rows.items()})
    report = {
        "status": status,
        "execution_status": result.get("status", "NOT_RUN"),
        "completion_status": "COMPLETE" if complete and quality_complete else "INCOMPLETE",
        "complete": complete,
        "quality_complete": quality_complete,
        "allowance_equal": True,
        "actual_calls_equal": solver_calls["train"] + solver_calls["verification"] == solver_calls["comparison"],
        "direct_search_allowance": plan["direct_search_allowance"],
        "surrogate_total_solver_calls": surrogate_actual_calls,
        "direct_total_solver_calls": direct_actual_calls,
        "shared_solver_calls": plan["shared_solver_calls"],
        "actual_shared_solver_calls": shared_actual_calls,
        "solver_calls_by_split": solver_calls,
        "direct_search_calls_used": solver_calls["comparison"],
        "surrogate_search_calls_used": solver_calls["train"] + solver_calls["verification"],
        "direct_best": {key: direct_best[key] for key in ("sample_id", "design_id", "mass_kg", "targets")} if direct_best else None,
        "surrogate_best": {key: surrogate_best[key] for key in ("sample_id", "design_id", "mass_kg", "targets")} if surrogate_best else None,
        "best_observed_training": {key: training_best[key] for key in ("sample_id", "design_id", "mass_kg", "targets")} if training_best else None,
        "recommendation_status": "OBSERVED_TRAINING_NOT_INDEPENDENTLY_VERIFIED",
        "verified_candidate": verified,
        "verification_evidence_status": verification_status,
        "target_margins": margins,
        "baseline_comparison": _baseline_comparison(baseline, candidate_rows, study),
        "mass_improvement_vs_direct": ((direct_best["mass_kg"] - surrogate_best["mass_kg"]) / direct_best["mass_kg"])
                                       if direct_best and surrogate_best and direct_best["mass_kg"] else None,
        "solver_command_seconds": solver_command_seconds,
        "solver_costs_by_split": costs_by_split,
        "solver_costs_total": costs_total,
        "geometry_seconds_per_sample": _geometry_costs(manifest),
        "phase_timings": manifest.get("phase_timings", {}),
        "phase_timings_by_split": _phase_costs(manifest),
        "phase_timing_accounting": {
            "backend_total_includes": ["mesh", "solve"],
            "backend_total_is_separate_from_component_sum": True,
        },
        "round_search_seconds": _round_search_costs(root, manifest),
        "training_seconds": sum(model.get("training_seconds", 0) or 0 for model in manifest.get("models", [])),
        "study_elapsed_seconds": manifest.get("elapsed_seconds"),
        "budget": {
            "max_solver_calls": study.budget.max_solver_calls,
            "solver_calls_used": manifest.get("solver_calls", costs_total["calls"]),
            "solver_calls_remaining": max(
                0, study.budget.max_solver_calls - manifest.get("solver_calls", costs_total["calls"])
            ),
            "direct_search_allowance": plan["direct_search_allowance"],
            "direct_search_calls_used": solver_calls["comparison"],
            "direct_search_calls_remaining": max(0, plan["direct_search_allowance"] - solver_calls["comparison"]),
        },
        "failures": {
            "failed_attempts": comparison_failed_attempts,
            "failed_samples": failed_samples,
            "budget_exhausted": status == "BUDGET_EXHAUSTED",
        },
        "conclusion": "Measured control comparison; observed training results are not independent recommendations.",
    }
    atomic_json(root / "comparison.json", report)
    return report
