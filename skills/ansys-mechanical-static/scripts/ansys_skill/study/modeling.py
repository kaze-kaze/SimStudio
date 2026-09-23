"""Connect immutable study datasets to the numerical model API."""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from ansys_skill.errors import SpecValidationError
from ansys_skill.manifest import utc_now
from ansys_skill.paths import safe_join
from ansys_skill.study.dataset import load_dataset
from ansys_skill.study.project import load_project, save_project
from ansys_skill.study.storage import atomic_json, canonical_hash, read_json, study_lock
from ansys_skill.study.timing import account_activity


def latest_dataset(root: Path, manifest: dict) -> dict:
    if not manifest["datasets"]:
        raise SpecValidationError("Collect a real, quality-qualified dataset before training")
    data = load_dataset(safe_join(root, manifest["datasets"][-1]))
    if (data["study_fingerprint"] != manifest["study_fingerprint"]
            or data.get("study_id") != manifest["study_id"]
            or data.get("frozen_test_designs") != manifest["frozen_test_designs"]):
        raise SpecValidationError("Dataset belongs to another study")
    return data


def latest_model(root: Path, manifest: dict, requested: Path | None = None) -> Path:
    from ansys_skill.surrogate import load_model

    if requested is not None:
        directory = requested.resolve()
    elif manifest.get("holdout_evaluated"):
        directory = safe_join(root, manifest["holdout_evaluated"]["model"])
    elif manifest["models"]:
        directory = safe_join(root, manifest["models"][-1]["path"])
    else:
        raise SpecValidationError("Train a surrogate before searching designs")
    try:
        directory.relative_to(root.resolve())
    except ValueError as exc:
        raise SpecValidationError("Study model must be stored within this study directory") from exc
    model = load_model(directory)
    if model.get("evidence_kind") != "solver":
        raise SpecValidationError("Engineering studies require a model trained from solver evidence")
    if model.get("study_fingerprint") != manifest["study_fingerprint"]:
        raise SpecValidationError("Model belongs to a different physical study")
    if (manifest.get("holdout_evaluated")
            and directory.relative_to(root.resolve()).as_posix() != manifest["holdout_evaluated"]["model"]):
        raise SpecValidationError("The final holdout is frozen to its first evaluated model")
    if (manifest.get("holdout_evaluated")
            and model["model_id"] != manifest["holdout_evaluated"].get("model_id")):
        raise SpecValidationError("The frozen model content changed after holdout commitment")
    return directory


def train_study(root: Path) -> dict:
    from ansys_skill.surrogate import load_model, train_model

    root = root.resolve()
    with study_lock(root):
        study, _, manifest = load_project(root, check_code=True)
        with account_activity(root, manifest, 'model_training'):
            dataset = latest_dataset(root, manifest)
            options = study.model.model_dump()
            request_id = canonical_hash({"dataset": dataset["dataset_id"], "options": options,
                                         "code": manifest["code_fingerprint"]})[:24]
            relative = f"models/{request_id}"
            directory = safe_join(root, relative)
            if directory.exists():
                model = load_model(directory)
                provenance = read_json(directory / "training-provenance.json")
                if any(provenance.get(key) != expected for key, expected in {
                    "dataset_id": dataset["dataset_id"], "request_id": request_id,
                    "study_fingerprint": manifest["study_fingerprint"],
                    "code_fingerprint": manifest["code_fingerprint"], "model_id": model["model_id"],
                }.items()):
                    raise SpecValidationError("Cached model does not match its dataset")
                if not any(record["path"] == relative for record in manifest["models"]):
                    # Recover a completed atomic model write if manifest publication was interrupted.
                    manifest["models"].append({key: provenance[key] for key in
                        ("model_id", "path", "dataset_id", "created_at", "training_seconds")})
                    save_project(root, manifest)
                return {"status": "TRAINED", "model_id": model["model_id"], "path": relative, "reused": True}
            if manifest.get("holdout_evaluated"):
                raise SpecValidationError("Final holdout was already inspected; create a new study before retraining")
            if manifest.get("elapsed_seconds", 0.0) >= study.budget.max_wall_seconds:
                return {"status": "BUDGET_EXHAUSTED", "stage": "model_training"}
            started = time.monotonic()
            directory.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".training-", dir=directory.parent))
            try:
                result = train_model(dataset, staging, options)
                card_path = staging / "model-card.json"
                card = read_json(card_path)
                card.update({
                    "dataset_id": dataset["dataset_id"],
                    "engineering_context": dataset["engineering_context"],
                    "execution_context": dataset["execution_context"],
                    "code_fingerprint": manifest["code_fingerprint"],
                })
                atomic_json(card_path, card)
                record = {"model_id": result["model_id"], "path": relative,
                          "dataset_id": dataset["dataset_id"], "created_at": utc_now(),
                          "training_seconds": time.monotonic() - started}
                atomic_json(staging / "training-provenance.json", {
                    **record, "request_id": request_id,
                    "study_fingerprint": manifest["study_fingerprint"],
                    "model_id": result["model_id"], "code_fingerprint": manifest["code_fingerprint"],
                })
                staging.rename(directory)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
            manifest["models"].append(record)
            save_project(root, manifest)
            return {"status": "TRAINED", **record}


def evaluate_study(root: Path, model_path: Path | None = None) -> dict:
    from ansys_skill.surrogate import evaluate_model, load_model

    root = root.resolve()
    with study_lock(root):
        study, _, manifest = load_project(root)
        with account_activity(root, manifest, 'evaluation'):
            directory = latest_model(root, manifest, model_path)
            relative = directory.relative_to(root).as_posix()
            previous = manifest.get("holdout_evaluated")
            if previous and previous["model"] != relative:
                raise SpecValidationError("The final holdout is frozen to its first evaluated model")
            dataset = latest_dataset(root, manifest)
            expected = set(manifest["frozen_test_designs"])
            rows = [row for row in dataset["rows"] if row["split"] == "test"]
            ready = {row["design_id"] for row in rows
                     if set(study.targets) <= set(row["accepted_targets"])}
            if not expected or expected != ready or len(rows) != len(expected):
                return {"status": "NOT_RUN", "stage": "independent_test_readiness",
                        "missing_design_ids": sorted(expected - ready),
                    "message": "Every frozen test design must qualify before inspecting final errors."}
            model_id = load_model(directory)["model_id"]
            if previous and previous.get("model_id") != model_id:
                raise SpecValidationError("The frozen model content changed after holdout commitment")
            test_hash = canonical_hash([
                {key: row.get(key) for key in ("design_id", "parameters", "targets", "source")}
                for row in sorted(rows, key=lambda row: row["design_id"])])
            if previous and previous.get("test_evidence_hash") != test_hash:
                raise SpecValidationError("Final test labels or source evidence changed after holdout commitment")
            started = time.monotonic()
            # Record the commitment before publishing errors so interruption cannot unfreeze the holdout.
            manifest["holdout_evaluated"] = {"model": relative, "model_id": model_id,
                                             "test_evidence_hash": test_hash,
                                             "dataset": manifest["datasets"][-1], "at": utc_now()}
            save_project(root, manifest)
            result = evaluate_model(directory, dataset)
            result["evaluation_seconds"] = time.monotonic() - started
            atomic_json(directory / "evaluation.json", result)
            return result
