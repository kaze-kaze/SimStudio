"""Materialize portable study inputs without changing single-run contracts."""

from __future__ import annotations

import copy
import importlib.metadata
import time
from pathlib import Path

import yaml

from ansys_skill.errors import SpecValidationError
from ansys_skill.manifest import sha256_file, utc_now
from ansys_skill.paths import require_fresh_run_dir, safe_join
from ansys_skill.schema import ResultType, SimulationSpec, load_spec
from ansys_skill.study.sampling import plan_samples
from ansys_skill.study.schema import StudySpec, load_study
from ansys_skill.study.storage import (
    atomic_json,
    atomic_text,
    canonical_hash,
    code_fingerprint,
    read_json,
)
from ansys_skill.units import normalize_quantity


def validate_base(study: StudySpec, base: SimulationSpec) -> None:
    if base.mode.value != "from_geometry" or base.bodies[0].name != "GussetedBracket|Solid":
        raise SpecValidationError("The controlled bracket study requires its single-solid body")
    materials = {item.name: item for item in base.materials}
    material = materials[base.bodies[0].material]
    if material.engineering_data_name != study.material.engineering_data_name:
        raise SpecValidationError("Study and solver materials do not match")
    if base.execution.backend == "fake":
        raise SpecValidationError("Engineering studies cannot use the fake backend")
    scopes = {scope.id: scope for scope in base.scopes}
    expected = {"mounting_face": ("x", "min"), "front_face": ("x", "max"),
                "bearing_pad": ("z", "max")}
    for name, (axis, extreme) in expected.items():
        scope = scopes.get(name)
        if (scope is None or scope.kind.value != "axis_extreme_face"
                or scope.axis != axis or scope.extreme != extreme or scope.body != base.bodies[0].name):
            raise SpecValidationError(f"Controlled geometry requires the expected {name} scope")
    if len(base.supports) != 1 or base.supports[0].scope != "mounting_face":
        raise SpecValidationError("The study requires one rear-face fixed support")
    if any(load.scope and load.scope not in expected for load in base.loads):
        raise SpecValidationError("Load scope is not described by the controlled geometry")
    if base.open_questions:
        raise SpecValidationError("Resolve the base simulation open questions before planning")
    results = {result.id: result for result in base.requested_results}
    for name, target in study.targets.items():
        result = results.get(target.result_id)
        types = ({ResultType.TOTAL_DEFORMATION, ResultType.DIRECTIONAL_DEFORMATION}
                 if target.dimension == "length" else {ResultType.EQUIVALENT_VON_MISES_STRESS})
        if result is None or result.type not in types:
            raise SpecValidationError(f"Target {name} is missing or has the wrong result type")
    if not any(result.type is ResultType.REACTION_FORCE for result in base.requested_results):
        raise SpecValidationError("Studies require a support reaction result")


def planning_inputs(source: Path) -> tuple[StudySpec, SimulationSpec, dict]:
    study = load_study(source)
    base_path = (source.parent / study.base_simulation).resolve()
    base, document = load_spec(base_path)
    validate_base(study, base)
    return study, base, document


def create_plan(source: Path, output: Path) -> dict:
    study, base, document = planning_inputs(source.resolve())
    samples, rejections = plan_samples(study)
    require_fresh_run_dir(output)
    output.mkdir(parents=True, exist_ok=True)
    study_document = study.model_dump(mode="json")
    study_document["base_simulation"] = "base-simulation.yaml"
    # Geometry is produced per design point. Never retain the source machine's CAD path.
    document["inputs"] = {"geometry_file": "geometry.step"}
    atomic_text(output / "study.yaml", yaml.safe_dump(study_document, sort_keys=False))
    atomic_text(output / "base-simulation.yaml", yaml.safe_dump(document, sort_keys=False))
    fingerprint = canonical_hash({"study": study_document, "base_simulation": document})
    for sample in samples:
        sample["jobs"] = make_jobs(study)
    try:
        version = importlib.metadata.version("text-to-ansys")
    except importlib.metadata.PackageNotFoundError:
        version = "source"
    manifest = {
        "schema_version": "1.0", "study_id": fingerprint[:20],
        "study_fingerprint": fingerprint, "name": study.name, "status": "PLANNED",
        "created_at": utc_now(), "updated_at": utc_now(), "package_version": version,
        "code_fingerprint": code_fingerprint(), "synthetic": False,
        "inputs": {name: sha256_file(output / name)
                   for name in ("study.yaml", "base-simulation.yaml")},
        "samples": samples, "sampling_rejections": rejections, "solver_calls": 0, "elapsed_seconds": 0.0,
        "frozen_test_designs": sorted(s["design_id"] for s in samples if s["split"] == "test"),
        "execution_context": None, "datasets": [], "models": [], "rounds": [],
    }
    atomic_json(output / "study-manifest.json", manifest)
    plan = {"schema_version": "1.0", "study_id": manifest["study_id"],
            "status": "PLANNED", "default_mode": "dry_run",
            "sample_count": len(samples), "initial_solver_calls": sum(len(s["jobs"]) for s in samples),
            "max_solver_calls": study.budget.max_solver_calls,
            "mesh_sizes": study.mesh.sizes, "backend": base.execution.backend,
            "partitions": {kind: sum(s["split"] == kind for s in samples)
                           for kind in ("baseline", "train", "test")},
            "feature_bounds": study.bounds(), "targets": {k: v.canonical() for k, v in study.targets.items()},
            "remaining_budget_covers": "retries, active samples and final verification"}
    atomic_json(output / "study-plan.json", plan)
    return plan


def make_jobs(study: StudySpec) -> list[dict]:
    return [{"mesh_index": index, "mesh_size": size, "status": "PLANNED", "attempts": []}
            for index, size in enumerate(study.mesh.sizes)]


def engineering_context(study: StudySpec, base: SimulationSpec) -> dict:
    """Describe the fixed physics and target interpretation without machine-specific input paths."""
    from ansys_skill.study.geometry import GENERATOR_VERSION

    document = base.model_dump(mode="json", exclude_none=True)
    fields = ("units", "coordinate_systems", "bodies", "materials", "scopes", "analysis",
              "supports", "loads", "requested_results", "validation", "assumptions")
    return {
        "geometry": {"generator": study.geometry, "generator_version": GENERATOR_VERSION},
        "material_evidence": study.material.model_dump(mode="json"),
        "simulation": {key: document[key] for key in fields},
        "mesh_study": study.mesh.model_dump(mode="json"),
        "target_definitions": {name: target.model_dump(mode="json")
                               for name, target in study.targets.items()},
        "target_statistic": "Maximum absolute requested nodal result in canonical SI units",
    }


def load_project(root: Path, *, check_code: bool = False) -> tuple[StudySpec, SimulationSpec, dict]:
    root = root.resolve()
    manifest = read_json(root / "study-manifest.json")
    for name, digest in manifest["inputs"].items():
        path = safe_join(root, name)
        if not path.is_file() or path.is_symlink() or sha256_file(path) != digest:
            raise SpecValidationError(f"Study input changed: {name}; create a new study")
    study = load_study(root / "study.yaml")
    base, document = load_spec(root / "base-simulation.yaml")
    validate_base(study, base)
    fingerprint = canonical_hash({"study": study.model_dump(mode="json"), "base_simulation": document})
    if fingerprint != manifest["study_fingerprint"] or fingerprint[:20] != manifest["study_id"]:
        raise SpecValidationError("Study identity is inconsistent with its input files")
    if check_code and manifest["code_fingerprint"] != code_fingerprint():
        raise SpecValidationError("Compiler/study code changed; create a new study to avoid stale results")
    design_splits, sample_ids = {}, set()
    for sample in manifest["samples"]:
        from ansys_skill.study.geometry import validate_parameters
        from ansys_skill.study.sampling import design_id

        validate_parameters(sample["parameters"])
        if sample["split"] not in {"baseline", "train", "test", "verification", "comparison"}:
            raise SpecValidationError("Unknown design partition")
        if design_id(sample["parameters"]) != sample["design_id"]:
            raise SpecValidationError("Sample design identity does not match its parameters")
        expected_id = f"{sample['split']}-{sample['design_id']}"
        if sample["sample_id"] != expected_id or expected_id in sample_ids:
            raise SpecValidationError("Sample identity is inconsistent or duplicated")
        sample_ids.add(expected_id)
        if len(sample["jobs"]) != len(study.mesh.sizes):
            raise SpecValidationError("Sample does not contain every planned mesh level")
        for index, job in enumerate(sample["jobs"]):
            if job["mesh_index"] != index or job["mesh_size"] != study.mesh.sizes[index]:
                raise SpecValidationError("Mesh job changed from the study definition")
        if any(not low - 1e-15 <= sample["parameters"][name] <= high + 1e-15
               for name, (low, high) in study.bounds().items()):
            raise SpecValidationError("Sample falls outside the study parameter space")
        old = design_splits.setdefault(sample["design_id"], sample["split"])
        if old != sample["split"]:
            raise SpecValidationError("A design appears in multiple data partitions")
    tests = sorted(s["design_id"] for s in manifest["samples"] if s["split"] == "test")
    if tests != manifest["frozen_test_designs"]:
        raise SpecValidationError("Frozen test partition was changed")
    attempts = [attempt for sample in manifest["samples"] for job in sample["jobs"]
                for attempt in job["attempts"]]
    if manifest["solver_calls"] != len(attempts):
        raise SpecValidationError("Solver call count does not match the attempt ledger")
    return study, base, manifest


def sample_directory(root: Path, sample: dict) -> Path:
    return safe_join(root, "samples/" + sample["sample_id"])


def prepare_sample(root: Path, sample: dict, study: StudySpec, base: SimulationSpec) -> dict:
    from ansys_skill.study.geometry import build_geometry

    directory = sample_directory(root, sample)
    directory.mkdir(parents=True, exist_ok=True)
    if sample.get("geometry"):
        geometry = sample["geometry"]
        if sha256_file(directory / "geometry.step") != geometry["geometry_sha256"]:
            raise SpecValidationError("Prepared geometry changed; refusing to reuse sample")
        if read_json(directory / "geometry-properties.json") != geometry:
            raise SpecValidationError("Geometry metadata changed; refusing to reuse sample")
    else:
        started = time.monotonic()
        try:
            geometry = build_geometry(sample["parameters"], directory,
                                      density_kg_m3=normalize_quantity(study.material.density, "density").magnitude)
        finally:
            sample["geometry_seconds"] = sample.get("geometry_seconds", 0.0) + time.monotonic() - started
            sample["geometry_preparations"] = sample.get("geometry_preparations", 0) + 1
        sample["geometry"] = geometry
    for job in sample["jobs"]:
        spec_path = directory / f"mesh-{job['mesh_index']}.yaml"
        document = copy.deepcopy(base.model_dump(mode="json", exclude_none=True))
        document["project"]["name"] = study.name + "-" + sample["design_id"]
        document["inputs"] = {"geometry_file": "geometry.step"}
        document["mesh"] = {"global_element_size": job["mesh_size"], "element_order": study.mesh.element_order}
        SimulationSpec.model_validate(document)
        data = yaml.safe_dump(document, sort_keys=False)
        if spec_path.exists() and spec_path.read_text(encoding="utf-8") != data:
            raise SpecValidationError("Prepared simulation specification changed")
        atomic_text(spec_path, data)
        job["specification"] = spec_path.relative_to(root).as_posix()
        job["spec_sha256"] = sha256_file(spec_path)
    sample["status"] = "GEOMETRY_READY"
    return geometry


def save_project(root: Path, manifest: dict) -> None:
    manifest["updated_at"] = utc_now()
    atomic_json(root / "study-manifest.json", manifest)
