"""Constrained candidate search, adaptive samples and explicit confirmation."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from numbers import Real
from pathlib import Path

from ansys_skill.errors import SpecValidationError
from ansys_skill.logging import progress
from ansys_skill.paths import safe_join
from ansys_skill.study.dataset import collect_dataset
from ansys_skill.study.modeling import latest_dataset, latest_model
from ansys_skill.study.project import load_project, make_jobs, save_project
from ansys_skill.study.runner import run_study
from ansys_skill.study.sampling import design_id, latin_points, sample_record
from ansys_skill.study.storage import atomic_json, canonical_hash, read_json, study_lock
from ansys_skill.study.timing import account_activity, account_subactivity
from ansys_skill.units import normalize_quantity

_ACTIVE_ROUND_STATUSES = {"PROPOSED", "SCHEDULED", "PARTIAL", "BUDGET_EXHAUSTED"}
_VALID_PREDICTION_STATUSES = {"PREDICTED", "NEEDS_SOLVE"}


def _validate_plan_hash(plan: object) -> dict:
    if not isinstance(plan, dict):
        raise SpecValidationError("Candidate plan must be an object")
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or canonical_hash(
        {key: value for key, value in plan.items() if key != "plan_id"}
    ) != plan_id:
        raise SpecValidationError("Candidate plan was modified")
    return plan


def _read_registered_plan(root: Path, round_record: dict) -> dict:
    try:
        plan = read_json(safe_join(root, round_record["plan"]))
    except (OSError, KeyError, ValueError) as exc:
        raise SpecValidationError("Registered candidate plan is unavailable or invalid") from exc
    _validate_plan_hash(plan)
    if plan.get("plan_id") != round_record.get("plan_id"):
        raise SpecValidationError("Registered candidate plan hash does not match the study manifest")
    if plan.get("plan") != round_record.get("plan"):
        raise SpecValidationError("Registered candidate plan path does not match the study manifest")
    return plan


def _pending_solver_calls(manifest: dict, retries_per_job: int, *, split: str | None = None) -> int:
    """Count all remaining attempts, including retries for jobs without attempts."""
    calls = 0
    maximum_attempts = retries_per_job + 1
    for sample in manifest["samples"]:
        if split is not None and sample["split"] != split:
            continue
        for job in sample["jobs"]:
            if job.get("status") == "SOLVED":
                continue
            attempts = job.get("attempts", [])
            if attempts:
                calls += max(0, maximum_attempts - len(attempts))
            else:
                calls += maximum_attempts
    return calls


def _verification_reserve(study) -> int:
    return (
        study.optimization.verification_candidates
        * len(study.mesh.sizes)
        * (study.budget.retries_per_job + 1)
    )


def _number(value: object, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise SpecValidationError(f"{label} must be a finite number")
    result = float(value)
    if nonnegative and result < 0:
        raise SpecValidationError(f"{label} must be non-negative")
    return result


def _candidate_sort_key(candidate: dict) -> tuple[bool, float, float]:
    supported = candidate["prediction_status"] == "PREDICTED"
    violation = candidate["violation_score"] if supported else math.inf
    return not supported, violation, candidate["mass_kg"]


def propose_candidates(root: Path, model_path: Path | None = None, *, purpose: str = "adaptive") -> dict:
    from ansys_skill.study.geometry import geometry_summary, validate_parameters
    from ansys_skill.surrogate import load_model, predict_model

    if purpose not in {"adaptive", "verification"}:
        raise SpecValidationError("Unknown candidate purpose")
    root = root.resolve()
    with study_lock(root):
        study, _, manifest = load_project(root)
        if purpose == "adaptive" and manifest.get("direct_comparison"):
            raise SpecValidationError(
                "Adaptive sampling cannot continue after a direct comparison plan has been created"
            )
        with account_activity(root, manifest, 'optimization'):
            if purpose == "adaptive" and manifest.get("holdout_evaluated"):
                raise SpecValidationError("Final holdout was evaluated; start a new study before adaptation")
            rounds = [item for item in manifest["rounds"] if item["purpose"] == purpose]
            if purpose == "adaptive" and any(
                item["purpose"] == "verification" for item in manifest["rounds"]
            ):
                raise SpecValidationError("Adaptive sampling cannot continue after final verification has started")
            if rounds and (purpose == "verification" or rounds[-1]["status"] in _ACTIVE_ROUND_STATUSES):
                return _read_registered_plan(root, rounds[-1])
            if purpose == "adaptive" and len(rounds) >= study.optimization.max_rounds:
                return {"status": "ROUND_LIMIT", "candidates": []}

            directory = latest_model(root, manifest, model_path)
            model = load_model(directory)
            index = len(manifest["rounds"])
            seen = {sample["design_id"] for sample in manifest["samples"]}
            density = normalize_quantity(study.material.density, "density").magnitude
            candidates: list[dict] = []
            rejected: list[dict] = []
            visited_designs: set[str] = set()
            geometry_cache: dict[str, dict] = {}
            prior_prediction = manifest.get("phase_timings", {}).get("prediction", {}).get("elapsed_seconds", 0.0)
            prior_geometry = manifest.get("phase_timings", {}).get("candidate_geometry", {}).get("elapsed_seconds", 0.0)
            started = time.monotonic()
            points = latin_points(
                study.bounds(),
                study.optimization.candidate_pool,
                (study.sampling.seed + 100000 + index) % 2**32,
            )
            for ordinal, parameters in enumerate(points):
                if (manifest.get("elapsed_seconds", 0.0) + time.monotonic() - started
                        >= study.budget.max_wall_seconds):
                    return {"status": "BUDGET_EXHAUSTED", "stage": "candidate_search",
                            "evaluated_candidates": len(candidates), "candidates": []}
                identity = design_id(parameters)
                if identity in seen or identity in visited_designs:
                    continue
                visited_designs.add(identity)
                try:
                    validate_parameters(parameters)
                    with account_subactivity(manifest, "prediction"):
                        prediction = predict_model(directory, parameters)
                    prediction_status = prediction.get("status")
                    if prediction_status not in _VALID_PREDICTION_STATUSES:
                        raise SpecValidationError("Model returned an unsupported prediction status")
                    predictions = prediction.get("predictions", {})
                    if not isinstance(predictions, Mapping) or set(predictions) != set(study.targets):
                        raise SpecValidationError("Model predictions do not match the declared study targets")
                    geometry = geometry_cache.get(identity)
                    if geometry is None:
                        with account_subactivity(manifest, "candidate_geometry"):
                            geometry = geometry_summary(parameters, density)
                        if not isinstance(geometry, Mapping):
                            raise SpecValidationError("CAD geometry summary must be an object")
                        geometry_cache[identity] = dict(geometry)
                except SpecValidationError as exc:
                    rejected.append({"design_id": identity, "parameters": parameters, "reason": str(exc)})
                    continue

                mass = _number(geometry.get("mass_kg"), "CAD mass", nonnegative=True)
                violation_score = 0.0
                uncertainty_score = 0.0
                for name, target in study.targets.items():
                    item = predictions[name]
                    if not isinstance(item, Mapping):
                        raise SpecValidationError(f"Model prediction for {name!r} must be an object")
                    value = _number(item.get("value"), f"Model prediction for {name}")
                    std_value = item.get("std")
                    std = None if std_value is None else _number(std_value, f"Model uncertainty for {name}", nonnegative=True)
                    metadata = target.canonical()
                    if prediction_status == "PREDICTED":
                        violation_score += max(0.0, (value - metadata["limit"]) / metadata["reference_scale"])
                    if std is not None:
                        uncertainty_score += std / max(abs(value), metadata["reference_scale"])

                supported = prediction_status == "PREDICTED"
                candidates.append(
                    {
                        "design_id": identity,
                        "parameters": dict(parameters),
                        "mass_kg": mass,
                        "predictions": dict(predictions),
                        "prediction_status": prediction_status,
                        "surrogate_supported": supported,
                        "solver_confirmation_required": True,
                        "violation_score": violation_score if supported else None,
                        "uncertainty_score": uncertainty_score,
                        "status": "PREDICTED_CANDIDATE" if supported else "NEEDS_SOLVE",
                        "verified": False,
                    }
                )
                if ordinal % 16 == 0:
                    progress(f"Evaluated {ordinal + 1}/{len(points)} candidate geometries")

            candidates.sort(key=_candidate_sort_key)
            requested_count = (
                study.optimization.batch_size
                if purpose == "adaptive"
                else study.optimization.verification_candidates
            )
            mesh_count = len(study.mesh.sizes)
            retries = study.budget.retries_per_job
            pending_existing = _pending_solver_calls(manifest, retries)
            pending_same_split = _pending_solver_calls(manifest, retries, split="train" if purpose == "adaptive" else "verification")
            reserve_verification = _verification_reserve(study) if purpose == "adaptive" else 0
            available_for_candidates = max(
                0, study.budget.max_solver_calls - manifest["solver_calls"] - pending_existing - reserve_verification
            )
            max_attempts_per_candidate = mesh_count * (retries + 1)
            candidate_capacity = available_for_candidates // max_attempts_per_candidate
            selected_count = min(requested_count, len(candidates), candidate_capacity)
            selected = candidates[:selected_count]
            for candidate in selected:
                candidate["selection_basis"] = (
                    "predicted_constraint_and_mass"
                    if candidate["surrogate_supported"]
                    else "unreliable_prediction_requires_solver"
                )
            if purpose == "adaptive" and len(candidates) > selected_count and selected_count > 1:
                used = {item["design_id"] for item in selected[:-1]}
                exploratory = max(
                    (item for item in candidates if item["design_id"] not in used),
                    key=lambda item: item["uncertainty_score"],
                )
                selected = [*selected[:-1], exploratory]
                exploratory["selection_basis"] = "uncertainty_exploration"

            if selected:
                status = "PROPOSED"
            elif candidates and candidate_capacity == 0:
                status = "BUDGET_EXHAUSTED"
            else:
                status = "NO_CANDIDATES"
            relative = f"optimization/round-{index:03d}/plan.json"
            candidate_solver_calls = len(selected) * mesh_count
            plan = {
                "schema_version": "1.0",
                "status": status,
                "study_fingerprint": manifest["study_fingerprint"],
                "model_id": model["model_id"],
                "purpose": purpose,
                "round": index,
                "candidates": selected,
                "evaluated_candidates": len(candidates),
                "rejected": rejected,
                "search_seconds": time.monotonic() - started,
                "prediction_seconds": manifest.get("phase_timings", {}).get("prediction", {}).get("elapsed_seconds", 0.0) - prior_prediction,
                "geometry_seconds": manifest.get("phase_timings", {}).get("candidate_geometry", {}).get("elapsed_seconds", 0.0) - prior_geometry,
                "pending_same_split_calls": pending_same_split,
                "candidate_solver_calls": candidate_solver_calls,
                "additional_solver_calls": pending_same_split + candidate_solver_calls,
                "budget": {
                    "max_solver_calls": study.budget.max_solver_calls,
                    "solver_calls_used": manifest["solver_calls"],
                    "pending_existing_calls": pending_existing,
                    "reserved_final_verification_calls": reserve_verification,
                    "available_for_candidates": available_for_candidates,
                    "candidate_capacity": candidate_capacity,
                    "planned_candidate_calls": candidate_solver_calls,
                    "max_candidate_solver_calls": len(selected) * max_attempts_per_candidate,
                    "mesh_jobs_per_candidate": mesh_count,
                    "retries_per_job": retries,
                },
                "prediction_note": (
                    "Surrogate values guide search only. NEEDS_SOLVE candidates are exploratory and cannot be treated as feasible."
                ),
                "verification_policy": (
                    "Verification selects unseen design IDs so one design never crosses data partitions."
                    if purpose == "verification"
                    else None
                ),
                "verification_tradeoff": (
                    "A previously trained best design is not independently verified by this plan; verification is limited to new designs."
                    if purpose == "verification"
                    else None
                ),
                "plan": relative,
            }
            plan["plan_id"] = canonical_hash(plan)
            atomic_json(safe_join(root, relative), plan)
            manifest["rounds"].append(
                {
                    "round": index,
                    "purpose": purpose,
                    "plan": relative,
                    "plan_id": plan["plan_id"],
                    "model_id": model["model_id"],
                    "status": plan["status"],
                }
            )
            save_project(root, manifest)
            return plan


def _validate_registered_execution(root: Path, plan: dict, manifest: dict) -> dict:
    _validate_plan_hash(plan)
    if plan.get("study_fingerprint") != manifest["study_fingerprint"]:
        raise SpecValidationError("Candidate plan belongs to another study")
    plan_round = plan.get("round")
    if isinstance(plan_round, bool) or not isinstance(plan_round, int) or not 0 <= plan_round < len(manifest["rounds"]):
        raise SpecValidationError("Candidate plan is not registered in this study")
    record = manifest["rounds"][plan_round]
    if (record.get("round") != plan_round or record.get("purpose") != plan.get("purpose")
            or record.get("model_id") != plan.get("model_id") or record.get("plan_id") != plan["plan_id"]):
        raise SpecValidationError("Candidate plan does not match its registered round")
    saved = _read_registered_plan(root, record)
    if canonical_hash(saved) != canonical_hash(plan):
        raise SpecValidationError("Candidate plan content differs from its registered artifact")
    if plan.get("status") != "PROPOSED":
        return record
    if plan.get("purpose") not in {"adaptive", "verification"}:
        raise SpecValidationError("Candidate plan has an unknown purpose")
    candidates = plan.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise SpecValidationError("Proposed candidate plan must contain candidates")
    identities: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or not isinstance(candidate.get("parameters"), Mapping):
            raise SpecValidationError("Candidate plan contains a malformed candidate")
        identity = candidate.get("design_id")
        if not isinstance(identity, str) or design_id(candidate["parameters"]) != identity:
            raise SpecValidationError("Candidate design ID does not match its parameters")
        if identity in identities or identity in manifest["frozen_test_designs"]:
            raise SpecValidationError("Candidate plan duplicates a design or uses a frozen test design")
        identities.add(identity)
    return record


def execute_proposal(root: Path, plan: dict, *, execute: bool = False) -> dict:
    _validate_plan_hash(plan)
    if not execute or plan.get("status") != "PROPOSED":
        return plan
    root = root.resolve()
    with study_lock(root):
        study, _, manifest = load_project(root, check_code=True)
        record = _validate_registered_execution(root, plan, manifest)
        purpose = plan["purpose"]
        if purpose == "adaptive":
            if manifest.get("direct_comparison"):
                raise SpecValidationError(
                    "Adaptive sampling cannot continue after a direct comparison plan has been created"
                )
            if manifest.get("holdout_evaluated"):
                raise SpecValidationError("Final holdout was evaluated; start a new study before adaptation")
            if any(item["purpose"] == "verification" for item in manifest["rounds"]):
                raise SpecValidationError("Adaptive sampling cannot continue after final verification has started")
        split = "train" if purpose == "adaptive" else "verification"
        existing = {sample["design_id"]: sample for sample in manifest["samples"]}
        for candidate in plan["candidates"]:
            previous = existing.get(candidate["design_id"])
            if previous is None:
                sample = sample_record(candidate["parameters"], split, ordinal=len(manifest["samples"]))
                sample["jobs"] = make_jobs(study)
                sample["candidate_plan"] = plan["plan"]
                manifest["samples"].append(sample)
                existing[candidate["design_id"]] = sample
            elif previous["split"] != split:
                raise SpecValidationError("A candidate design cannot be reused across data partitions")
            elif previous.get("candidate_plan") != plan["plan"]:
                raise SpecValidationError("Candidate already belongs to a different proposal")

        pending = _pending_solver_calls(manifest, study.budget.retries_per_job)
        reserve_verification = _verification_reserve(study) if purpose == "adaptive" else 0
        required = pending + reserve_verification
        available = study.budget.max_solver_calls - manifest["solver_calls"]
        if required > available:
            return {
                "status": "BUDGET_EXHAUSTED",
                "candidates": plan["candidates"],
                "required_solver_calls": required,
                "remaining_solver_calls": max(0, available),
            }
        split_attempts_used = sum(
            len(job.get("attempts", []))
            for sample in manifest["samples"]
            if sample["split"] == split
            for job in sample["jobs"]
        )
        split_call_limit = split_attempts_used + _pending_solver_calls(
            manifest, study.budget.retries_per_job, split=split
        )
        record["status"] = "SCHEDULED"
        save_project(root, manifest)

    result = run_study(
        root,
        execute=True,
        resume=True,
        splits=(split,),
        solver_call_limit=split_call_limit,
    )
    with study_lock(root):
        _, _, manifest = load_project(root)
        ids = {item["design_id"] for item in plan["candidates"]}
        by_design = {
            sample["design_id"]: sample
            for sample in manifest["samples"]
            if sample["design_id"] in ids and sample["split"] == split
        }
        states = [by_design[item]["status"] for item in ids if item in by_design]
        manifest["rounds"][plan["round"]]["status"] = (
            "SOLVED" if len(states) == len(ids) and states and all(state == "SOLVED" for state in states) else "PARTIAL"
        )
        save_project(root, manifest)
    return result


def verify_candidates(
    root: Path,
    model_path: Path | None = None,
    *,
    execute: bool = False,
    reviews_path: Path | None = None,
) -> dict:
    plan = propose_candidates(root, model_path, purpose="verification")
    if plan["status"] != "PROPOSED":
        if plan["status"] == "BUDGET_EXHAUSTED":
            return plan
        return {
            "status": "NOT_RUN",
            "purpose": "verification",
            "reason": plan["status"],
            "candidates": [],
            "model_id": plan.get("model_id"),
            "study_fingerprint": plan.get("study_fingerprint"),
        }
    from ansys_skill.surrogate import load_model

    _, _, current = load_project(root)
    active_model = load_model(latest_model(root, current, model_path))
    if plan.get("model_id") != active_model["model_id"]:
        raise SpecValidationError("Verification plan belongs to a different model; create a new study")
    execution = execute_proposal(root, plan, execute=execute)
    if not execute or execution["status"] in {"BUDGET_EXHAUSTED", "INTERRUPTED"}:
        return execution

    collect_dataset(root, reviews_path=reviews_path)
    _, _, manifest = load_project(root)
    dataset = latest_dataset(root, manifest)
    rows = {row["design_id"]: row for row in dataset["rows"]}
    target_names = set(dataset["targets"])
    confirmed = []
    for candidate in plan["candidates"]:
        row = rows.get(candidate["design_id"], {})
        actual_targets = row.get("targets", {})
        accepted = set(row.get("accepted_targets", []))
        source = row.get("source", {})
        source_is_solver = source.get("kind") == "solver" and source.get("synthetic") is False
        complete_values = isinstance(actual_targets, Mapping) and all(
            name in actual_targets
            and isinstance(actual_targets[name], Real)
            and not isinstance(actual_targets[name], bool)
            and math.isfinite(float(actual_targets[name]))
            for name in target_names
        )
        mass = row.get("mass_kg")
        mass_valid = (
            isinstance(mass, Real)
            and not isinstance(mass, bool)
            and math.isfinite(float(mass))
            and float(mass) >= 0
        )
        verified = (
            bool(row)
            and row.get("split") == "verification"
            and source_is_solver
            and target_names <= accepted
            and complete_values
            and mass_valid
        )
        feasibility = row.get("feasibility", {})
        feasible = verified and isinstance(feasibility, Mapping) and all(
            feasibility.get(name) == "FEASIBLE" for name in target_names
        )
        errors = {
            name: abs(float(actual_targets[name]) - float(item["value"]))
            for name, item in candidate["predictions"].items()
            if isinstance(actual_targets, Mapping)
            and name in actual_targets
            and isinstance(actual_targets[name], Real)
            and not isinstance(actual_targets[name], bool)
            and math.isfinite(float(actual_targets[name]))
        }
        confirmed.append(
            {
                **candidate,
                "sample_id": row.get("sample_id"),
                "mass_kg": float(mass) if mass_valid else candidate["mass_kg"],
                "targets": actual_targets if isinstance(actual_targets, Mapping) else {},
                "accepted_targets": sorted(accepted),
                "feasible": bool(feasible),
                "verified": bool(verified),
                "prediction_errors": errors,
            }
        )
    feasible = [item for item in confirmed if item["verified"] and item["feasible"]]
    best = min(feasible, key=lambda item: item["mass_kg"], default=None)
    incomplete = any(not item["verified"] for item in confirmed)
    result = {
        "status": "REVIEW_REQUIRED" if incomplete else "PASS" if best else "FAIL",
        "candidates": confirmed,
        "best_sample_id": best["sample_id"] if best else None,
        "study_fingerprint": manifest["study_fingerprint"],
        "model_id": plan["model_id"],
        "verification_tradeoff": plan["verification_tradeoff"],
    }
    atomic_json(root / "verification.json", result)
    return result
