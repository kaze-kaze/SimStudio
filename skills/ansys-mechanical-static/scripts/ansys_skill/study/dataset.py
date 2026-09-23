"""Collect immutable per-target training eligibility and provenance."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from ansys_skill.errors import SpecValidationError
from ansys_skill.manifest import utc_now
from ansys_skill.paths import safe_join
from ansys_skill.study.project import load_project, save_project
from ansys_skill.study.schema import FEATURE_NAMES
from ansys_skill.study.storage import (
    atomic_json,
    atomic_text,
    canonical_hash,
    read_json,
    study_lock,
    verify_hashes,
)
from ansys_skill.study.timing import account_activity


def collect_dataset(root: Path, *, reviews_path: Path | None = None) -> dict:
    from ansys_skill.study.quality import assess_mesh_convergence, evaluate_run

    root = root.resolve()
    with study_lock(root):
        study, _, manifest = load_project(root)
        with account_activity(root, manifest, 'collection'):
            reviews = read_json(reviews_path) if reviews_path else {}
            rows, excluded = [], []
            for sample in manifest["samples"]:
                levels, sources, failures = [], [], []
                if not sample.get("geometry"):
                    excluded.append({"sample_id": sample["sample_id"], "reason": "Geometry not prepared"})
                    continue
                for job in sample["jobs"]:
                    if not job["attempts"] or job["attempts"][-1]["status"] != "SOLVED":
                        failures.append(f"mesh-{job['mesh_index']}: no completed real solve")
                        continue
                    attempt = job["attempts"][-1]
                    run_dir = safe_join(root, attempt["path"])
                    try:
                        verify_hashes(run_dir, attempt["hashes"])
                        level = evaluate_run(run_dir, study, sample["geometry"], reviews)
                        # The same evidence must retain its dataset identity after a machine transfer.
                        level.setdefault("evidence", {})["run_directory"] = attempt["path"]
                        levels.append(level)
                        sources.append({"run_directory": attempt["path"], "hashes": attempt["hashes"],
                                        "elapsed_seconds": attempt["elapsed_seconds"],
                                        "mesh_size": job["mesh_size"]})
                    except SpecValidationError as exc:
                        failures.append(str(exc))
                mesh = assess_mesh_convergence(study, levels)
                accepted, target_reasons = [], {}
                values = levels[-1].get("values", {}) if levels else {}
                for target in study.targets:
                    reasons = list(failures)
                    if len(levels) != len(sample["jobs"]):
                        reasons.append("Not every planned mesh was evaluated")
                    if not levels or any(target not in level.get("accepted_targets", []) for level in levels):
                        reasons.append("Required numerical or engineering evidence is incomplete")
                    if mesh.get("targets", {}).get(target, {}).get("status") != "PASS":
                        reasons.append("Mesh convergence did not pass")
                    if reasons:
                        target_reasons[target] = reasons
                    else:
                        accepted.append(target)
                row = {
                    "sample_id": sample["sample_id"], "design_id": sample["design_id"],
                    "split": sample["split"], "parameters": sample["parameters"],
                    "mass_kg": sample["geometry"]["mass_kg"],
                    "targets": values, "accepted_targets": accepted, "exclusions": target_reasons,
                    "feasibility": {target: ("FEASIBLE" if values[target] <= study.targets[target].canonical()["limit"]
                                              else "INFEASIBLE") if target in accepted else "UNKNOWN"
                                    for target in study.targets},
                    "source": {"kind": "solver",
                               "synthetic": any(level.get("synthetic") is not False for level in levels),
                               "complete_real_evidence": bool(levels) and all(
                                   level.get("evidence", {}).get("provenance", {}).get("real") is True for level in levels),
                               "runs": sources, "geometry_sha256": sample["geometry"]["geometry_sha256"]},
                    "solver_calls": sum(len(job["attempts"]) for job in sample["jobs"]),
                    "solver_command_seconds": sum(attempt.get("elapsed_seconds", 0) or 0
                        for job in sample["jobs"] for attempt in job["attempts"]),
                    "mesh_convergence": mesh, "quality": levels,
                }
                rows.append(row)
                if target_reasons:
                    excluded.append({"sample_id": sample["sample_id"], "targets": target_reasons})
            dataset = {
                "schema_version": "1.0", "study_id": manifest["study_id"],
                "study_fingerprint": manifest["study_fingerprint"], "evidence_kind": "solver",
                "feature_names": list(FEATURE_NAMES), "feature_units": {n: "meter" for n in FEATURE_NAMES},
                "bounds": study.bounds(), "targets": {name: target.canonical() for name, target in study.targets.items()},
                "frozen_test_designs": manifest["frozen_test_designs"],
                "reviews_sha256": canonical_hash(reviews), "rows": rows, "excluded": excluded,
            }
            dataset_id = canonical_hash(dataset)
            dataset["dataset_id"] = dataset_id
            directory = root / "datasets" / dataset_id
            if directory.exists():
                if read_json(directory / "dataset.json") != dataset:
                    raise SpecValidationError("Dataset version collision or modified data")
            else:
                directory.mkdir(parents=True)
                atomic_json(directory / "dataset.json", dataset)
                atomic_json(directory / "dataset-manifest.json",
                            {"dataset_id": dataset_id, "created_at": utc_now(),
                             "study_fingerprint": manifest["study_fingerprint"],
                             "row_count": len(rows), "excluded": excluded})
                _write_csv(directory / "dataset.csv", dataset)
            reference = f"datasets/{dataset_id}/dataset.json"
            if reference not in manifest["datasets"]:
                manifest["datasets"].append(reference)
                save_project(root, manifest)
            return {"status": "COLLECTED", "dataset_id": dataset_id, "dataset": reference,
                    "rows": len(rows), "accepted": {target: sum(target in row["accepted_targets"] for row in rows)
                                                          for target in study.targets},
                    "engineering_validation": "PASS" if rows and not excluded else "NOT_RUN"}


def _write_csv(path: Path, dataset: dict) -> None:
    stream = io.StringIO(newline="")
    features, targets = dataset["feature_names"], list(dataset["targets"])
    writer = csv.writer(stream)
    writer.writerow(["sample_id", "design_id", "split", "mass_kg",
                     *[name + "_m" for name in features],
                     *[f"{name} [{dataset['targets'][name]['unit']}]" for name in targets],
                     "accepted_targets"])
    for row in dataset["rows"]:
        writer.writerow([row["sample_id"], row["design_id"], row["split"], row["mass_kg"],
                         *[row["parameters"][name] for name in features],
                         *[row["targets"].get(name, "") for name in targets],
                         ";".join(row["accepted_targets"])])
    atomic_text(path, stream.getvalue())


def load_dataset(path: Path) -> dict:
    dataset = read_json(path)
    expected = dataset.get("dataset_id")
    if canonical_hash({key: value for key, value in dataset.items() if key != "dataset_id"}) != expected:
        raise SpecValidationError("Dataset hash does not match its contents")
    return dataset
