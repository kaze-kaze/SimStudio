"""Evidence-based numerical quality checks for controlled Mechanical studies."""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
from contextlib import suppress
from itertools import pairwise
from pathlib import Path, PureWindowsPath
from typing import Any

from ansys_skill.errors import PathSafetyError
from ansys_skill.manifest import sha256_file
from ansys_skill.paths import safe_join
from ansys_skill.schema import ResultType, SimulationSpec, load_spec
from ansys_skill.study.mesh_quality import (
    assess_mesh_quality,
    mesh_quality_review_check,
    mesh_review_matches_target,
    mesh_target_gate,
)
from ansys_skill.study.planar_faces import boundaries_match, measure_planar_face
from ansys_skill.study.schema import StudySpec
from ansys_skill.units import normalize_direction, normalize_quantity
from ansys_skill.validation.statuses import Check, CheckStatus, aggregate_checks

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DENSITY_REL_TOLERANCE = 1e-9
_FACE_AREA_REL_TOLERANCE = 1e-6
_FACE_POSITION_TOLERANCE_M = 1e-9
_FACE_NORMAL_TOLERANCE = 1e-8
_MOMENT_REL_TOLERANCE = 0.01


def _check(
    name: str, status: CheckStatus | str, message: str, evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"name": name, "status": status.value if isinstance(status, CheckStatus) else str(status),
            "message": message, "evidence": evidence or {}}


def _status(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return CheckStatus.NOT_RUN.value
    return aggregate_checks([
        Check(item["name"], CheckStatus(item["status"]), item["message"])
        for item in checks
    ]).value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=_reject_json_constant)


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a numeric value")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Expected a finite numeric value")
    return result


def _vector(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("Expected a three-component vector")
    return [_number(component) for component in value]


def _norm(vector: list[float]) -> float:
    return math.sqrt(math.fsum(component * component for component in vector))


def _sum_vectors(vectors: list[list[float]]) -> list[float]:
    return [math.fsum(vector[index] for vector in vectors) for index in range(3)]


def _cross(left: list[float], right: list[float]) -> list[float]:
    return [left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0]]


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _canonical_unit(dimension: str) -> str:
    unit = {"length": "meter", "pressure": "pascal", "force": "newton"}[dimension]
    return normalize_quantity(f"1 {unit}", dimension).unit


def _load_artifact(run_dir: Path, name: str, expected: type) -> tuple[Any | None, dict | None]:
    path = run_dir / name
    if not path.is_file() or path.is_symlink():
        return None, _check(name, CheckStatus.NOT_RUN, f"Missing {name}", {"path": str(path)})
    try:
        payload = _read_json(path)
    except (OSError, UnicodeError, ValueError) as exc:
        return None, _check(name, CheckStatus.FAIL, f"Invalid {name}", {"error": str(exc)})
    if not isinstance(payload, expected):
        return None, _check(name, CheckStatus.FAIL, f"Invalid top-level structure in {name}",
                            {"expected_type": expected.__name__,
                             "actual_type": type(payload).__name__})
    return payload, None


def _verification_checks(verification: dict | None) -> tuple[dict[str, dict], list[dict]]:
    if verification is None:
        return {}, [_check("verification_evidence", CheckStatus.NOT_RUN, "Missing verification.json")]
    items = verification.get("checks")
    if not isinstance(items, list):
        return {}, [_check("verification_evidence", CheckStatus.FAIL,
                           "verification.json has no checks list")]
    by_name: dict[str, dict] = {}
    copied: list[dict] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            return {}, [_check("verification_evidence", CheckStatus.FAIL,
                               "verification.json contains a malformed check")]
        if item["name"] in by_name:
            return {}, [_check("verification_evidence", CheckStatus.FAIL,
                               "verification.json contains a duplicate check name", {"name": item["name"]})]
        try:
            status = CheckStatus(item.get("status"))
        except (TypeError, ValueError):
            return {}, [_check("verification_evidence", CheckStatus.FAIL,
                               "verification.json contains an unknown check status",
                               {"name": item["name"], "status": item.get("status")})]
        message, evidence = item.get("message", ""), item.get("evidence", {})
        if not isinstance(message, str) or not isinstance(evidence, dict):
            return {}, [_check("verification_evidence", CheckStatus.FAIL,
                               "verification.json check fields have invalid types", {"name": item["name"]})]
        record = _check(item["name"], status, message, evidence)
        by_name[item["name"]] = record
        copied.append(record)
    declared = verification.get("status")
    computed = _status(copied)
    if declared != computed:
        return {}, [_check("verification_evidence", CheckStatus.FAIL,
                           "verification.json aggregate status does not match its checks",
                           {"declared_status": declared, "computed_status": computed})]
    return by_name, [_check("verification_evidence", CheckStatus.PASS,
                            "Per-check verification evidence is structurally valid", {"status": computed})]


def _source_check(run_dir: Path, manifest: dict | None) -> tuple[SimulationSpec | None, dict]:
    path = run_dir / "normalized-simulation.yaml"
    if not path.is_file() or path.is_symlink():
        return None, _check("source_configuration", CheckStatus.NOT_RUN,
                            "Missing normalized-simulation.yaml")
    if manifest is None:
        return None, _check("source_configuration", CheckStatus.NOT_RUN,
                            "Missing run-manifest.json; configuration provenance cannot be checked")
    hashes = manifest.get("hashes")
    if not isinstance(hashes, dict):
        return None, _check("source_configuration", CheckStatus.FAIL,
                            "run-manifest.json has an invalid hashes structure")
    source_hash, normalized_hash = hashes.get("source_spec_sha256"), hashes.get("normalized_spec_sha256")
    if not _is_sha256(source_hash) or not _is_sha256(normalized_hash):
        return None, _check("source_configuration", CheckStatus.NOT_RUN,
                            "A valid source-spec or normalized-spec SHA256 is missing",
                            {"source_spec_sha256_present": _is_sha256(source_hash),
                             "normalized_spec_sha256_present": _is_sha256(normalized_hash)})
    actual_hash = sha256_file(path)
    if actual_hash != normalized_hash:
        return None, _check("source_configuration", CheckStatus.FAIL,
                            "normalized-simulation.yaml does not match its manifest hash",
                            {"expected_sha256": normalized_hash, "actual_sha256": actual_hash})
    try:
        simulation, _ = load_spec(path)
    except Exception as exc:
        return None, _check("source_configuration", CheckStatus.FAIL,
                            "normalized-simulation.yaml failed schema validation", {"error": str(exc)})
    return simulation, _check("source_configuration", CheckStatus.PASS,
                              "Normalized simulation is readable and its hash matches",
                              {"source_spec_sha256": source_hash,
                               "normalized_spec_sha256": actual_hash})


def _real_solve_check(
    manifest: dict | None, summary: dict | None, artifacts: dict | None,
    simulation: SimulationSpec | None, result_check: dict,
) -> dict:
    if any(item is None for item in (manifest, summary, artifacts, simulation)):
        return _check("real_solve", CheckStatus.NOT_RUN, "Missing evidence required to verify a real solve")
    assert manifest is not None and summary is not None and artifacts is not None and simulation is not None
    if (manifest.get("synthetic") is True or summary.get("synthetic") is True
            or artifacts.get("status") == "SYNTHETIC"
            or manifest.get("execution_mode") == "fake" or simulation.execution.backend == "fake"):
        return _check("real_solve", CheckStatus.FAIL,
                      "Synthetic or fake execution cannot be used as engineering data")
    if (manifest.get("status") != "SOLVED" or summary.get("status") != "POSTPROCESSED"
            or artifacts.get("status") != "SOLVED" or manifest.get("failure_stage") is not None
            or artifacts.get("error") is not None):
        return _check("real_solve", CheckStatus.FAIL, "Run did not complete with SOLVED status",
                      {"manifest_status": manifest.get("status"),
                       "summary_status": summary.get("status"),
                       "artifact_status": artifacts.get("status"),
                       "failure_stage": manifest.get("failure_stage")})
    if manifest.get("synthetic") is not False or summary.get("synthetic") is not False:
        return _check("real_solve", CheckStatus.NOT_RUN,
                      "Run does not explicitly declare synthetic=false")
    if "failure_stage" not in manifest:
        return _check("real_solve", CheckStatus.NOT_RUN,
                      "Run manifest does not record a failure_stage field")
    if manifest.get("execution_mode") != simulation.execution.backend:
        return _check("real_solve", CheckStatus.FAIL, "Run backend does not match normalized simulation",
                      {"manifest_backend": manifest.get("execution_mode"),
                       "simulation_backend": simulation.execution.backend})
    if result_check["status"] == CheckStatus.FAIL.value:
        return _check("real_solve", CheckStatus.FAIL,
                      "The RST file does not match a trusted result-file checksum")
    if result_check["status"] != CheckStatus.PASS.value:
        return _check("real_solve", CheckStatus.NOT_RUN,
                      "A trusted result-file checksum is unavailable")
    return _check("real_solve", CheckStatus.PASS, "Run status, backend, and non-synthetic markers agree",
                  {"backend": simulation.execution.backend, "status": "SOLVED"})


def _geometry_check(
    run_dir: Path, geometry: dict, manifest: dict | None, simulation: SimulationSpec | None,
    density_kg_m3: float | None,
) -> tuple[dict, dict[str, dict[str, Any]]]:
    scopes: dict[str, dict[str, Any]] = {}
    if simulation is None or manifest is None:
        return (_check("geometry_provenance", CheckStatus.NOT_RUN,
                       "Missing normalized configuration or run manifest; CAD input cannot be bound"), scopes)
    hashes = manifest.get("hashes")
    if not isinstance(hashes, dict):
        return _check("geometry_provenance", CheckStatus.FAIL, "Run manifest has an invalid hashes structure"), scopes
    evidence: dict[str, Any] = {}
    try:
        geometry_hash = geometry.get("geometry_sha256")
        volume, mass = _number(geometry.get("volume_m3")), _number(geometry.get("mass_kg"))
        center = _vector(geometry.get("center_of_mass_m"))
        body_name = geometry.get("body_name")
        if (not _is_sha256(geometry_hash) or volume <= 0 or mass <= 0
                or not isinstance(body_name, str) or not body_name):
            raise ValueError("geometry metadata is incomplete or invalid")
        geometry_file = simulation.inputs.geometry_file
        if not isinstance(geometry_file, str) or not geometry_file:
            raise ValueError("normalized simulation has no geometry_file")
        geometry_path = safe_join(run_dir, geometry_file)
        if not geometry_path.is_file() or geometry_path.is_symlink():
            return (_check("geometry_provenance", CheckStatus.NOT_RUN,
                           "Run directory is missing the CAD input from the controlled generator",
                           {"geometry_file": geometry_file}), scopes)
        actual_hash, input_hash = sha256_file(geometry_path), hashes.get("input_sha256")
        evidence.update({"geometry_file": geometry_file, "geometry_sha256": geometry_hash,
                         "input_sha256": input_hash, "actual_sha256": actual_hash,
                         "volume_m3": volume, "mass_kg": mass,
                         "center_of_mass_m": center, "body_name": body_name})
        if actual_hash != geometry_hash or input_hash != geometry_hash:
            return (_check("geometry_provenance", CheckStatus.FAIL,
                           "Controlled CAD, geometry metadata, and run input hashes do not match", evidence), scopes)
        if len(simulation.bodies) != 1 or simulation.bodies[0].name != body_name:
            return (_check("geometry_provenance", CheckStatus.FAIL,
                           "Normalized simulation body does not match the controlled geometry", evidence), scopes)
        expected_scopes = geometry.get("scopes")
        if not isinstance(expected_scopes, dict):
            raise ValueError("geometry scopes are missing")
        config_scopes = {item.id: item for item in simulation.scopes}
        for name in ("mounting_face", "front_face", "bearing_pad"):
            item = expected_scopes.get(name)
            scope = config_scopes.get(name)
            if not isinstance(item, dict) or scope is None:
                raise ValueError(f"geometry or simulation scope {name!r} is missing")
            area = _number(item.get("area_m2"))
            centroid, normal = _vector(item.get("centroid_m")), normalize_direction(_vector(item.get("normal")))
            axis, extreme = item.get("axis"), item.get("extreme")
            if (area <= 0 or axis not in {"x", "y", "z"} or extreme not in {"min", "max"}
                    or scope.kind.value != "axis_extreme_face" or scope.body != body_name
                    or scope.axis != axis or scope.extreme != extreme):
                raise ValueError(f"geometry and normalized scope {name!r} do not match")
            scopes[name] = {"area_m2": area, "centroid_m": centroid,
                            "normal": list(normal), "axis": axis, "extreme": extreme}
            if "boundary_summary" in item:
                boundary = item["boundary_summary"]
                if (not isinstance(boundary, dict) or len(boundary.get("corners_m", [])) != 4
                        or not isinstance(boundary.get("holes"), list)
                        or len(boundary["holes"]) > 4):
                    raise ValueError("Controlled boundary summary is malformed")
                scopes[name]["boundary_summary"] = {
                    "corners_m": [_vector(point) for point in boundary["corners_m"]],
                    "holes": [{"center_m": _vector(hole["center_m"]),
                               "radius_m": _number(hole["radius_m"])} for hole in boundary["holes"]],
                }
                if any(hole["radius_m"] <= 0 for hole in scopes[name]["boundary_summary"]["holes"]):
                    raise ValueError("Circular hole radius must be positive")
        if density_kg_m3 is not None:
            derived_mass = volume * density_kg_m3
            evidence.update(density_kg_m3=density_kg_m3, derived_mass_kg=derived_mass)
            if not math.isclose(mass, derived_mass, rel_tol=_DENSITY_REL_TOLERANCE, abs_tol=1e-12):
                return (_check("geometry_provenance", CheckStatus.FAIL,
                               "geometry mass does not equal volume times verified density", evidence), scopes)
    except Exception as exc:
        return (_check("geometry_provenance", CheckStatus.FAIL,
                       "Controlled geometry metadata is invalid", {**evidence, "error": str(exc)}), scopes)
    return (_check("geometry_provenance", CheckStatus.PASS,
                   "CAD hash, body identity, volume, centroid, and controlled scopes are valid", evidence), scopes)


def _material_density_check(
    run_dir: Path, study: StudySpec, simulation: SimulationSpec | None,
) -> tuple[dict, float | None]:
    if simulation is None:
        return _check("material_density", CheckStatus.NOT_RUN,
                      "Missing normalized configuration; material cannot be mapped to the solver deck"), None
    expected = normalize_quantity(study.material.density, "density").magnitude
    materials = {item.name: item for item in simulation.materials}
    body_material = (materials.get(simulation.bodies[0].material)
                     if len(simulation.bodies) == 1 else None)
    if (body_material is None or body_material.source.value != "engineering_data"
            or body_material.engineering_data_name != study.material.engineering_data_name
            or not study.material.property_source.strip()):
        return _check("material_density", CheckStatus.FAIL,
                      "Study material evidence does not match the normalized simulation material",
                      {"study_engineering_data_name": study.material.engineering_data_name,
                       "simulation_engineering_data_name": (body_material.engineering_data_name
                                                             if body_material else None),
                       "property_source_present": bool(study.material.property_source.strip())}), None
    decks = sorted(path for path in run_dir.rglob("ds.dat")
                   if path.is_file() and not path.is_symlink())
    if not decks:
        return _check("material_density", CheckStatus.NOT_RUN,
                      "No solver ds.dat was found; actual material density cannot be verified",
                      {"expected_density_kg_m3": expected}), None
    hashes = {path.relative_to(run_dir).as_posix(): sha256_file(path) for path in decks}
    if len(set(hashes.values())) != 1:
        return _check("material_density", CheckStatus.FAIL,
                      "Conflicting solver material evidence: ds.dat copies differ", {"deck_hashes": hashes}), None
    mks, densities, malformed = False, [], []
    try:
        lines = decks[0].read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return _check("material_density", CheckStatus.FAIL, "Cannot read solver ds.dat",
                      {"error": str(exc)}), None
    for line_number, line in enumerate(lines, 1):
        parts = [part.strip() for part in line.split("!", 1)[0].split(",")]
        upper = [part.upper() for part in parts]
        if upper[:2] == ["/UNITS", "MKS"]:
            mks = True
        if len(parts) >= 4 and upper[:2] == ["MP", "DENS"]:
            try:
                material_id = int(parts[2])
                value = float(parts[3].replace("D", "E").replace("d", "e"))
                if material_id <= 0 or not math.isfinite(value):
                    raise ValueError("invalid material id or density")
                densities.append({"line_number": line_number, "material_id": material_id,
                                  "value_kg_m3": value})
            except ValueError as exc:
                malformed.append({"line_number": line_number, "line": line, "error": str(exc)})
    evidence = {"deck_hashes": hashes, "unit_system": "MKS" if mks else None,
                "expected_density_kg_m3": expected, "deck_densities": densities,
                "malformed_density_lines": malformed,
                "engineering_data_name": study.material.engineering_data_name,
                "property_source": study.material.property_source}
    if malformed:
        return _check("material_density", CheckStatus.FAIL,
                      "Malformed MP,DENS data in the solver deck", evidence), None
    if not mks or not densities:
        return _check("material_density", CheckStatus.NOT_RUN,
                      "Solver deck has no interpretable MKS MP,DENS measurement", evidence), None
    material_ids = {item["material_id"] for item in densities}
    if material_ids != {1}:
        return _check("material_density", CheckStatus.FAIL,
                      "The controlled single-body material must map to solver material ID 1",
                      {**evidence, "actual_material_ids": sorted(material_ids)}), None
    if not all(math.isclose(item["value_kg_m3"], expected,
                            rel_tol=_DENSITY_REL_TOLERANCE, abs_tol=1e-9) for item in densities):
        return _check("material_density", CheckStatus.FAIL,
                      "Measured solver-deck density does not match the study configuration", evidence), None
    return _check("material_density", CheckStatus.PASS,
                  "Measured MP,DENS in solver ds.dat matches the study density", evidence), expected


def _selected_faces_check(
    run_dir: Path, geometry_scopes: dict[str, dict[str, Any]], simulation: SimulationSpec | None,
) -> tuple[dict, dict[str, dict[str, Any]]]:
    path = run_dir / "face-selection-report.json"
    if not path.is_file() or path.is_symlink():
        return _check("selected_face_geometry", CheckStatus.NOT_RUN,
                      "Missing face-selection-report.json"), {}
    try:
        records = _read_json(path)
    except (OSError, UnicodeError, ValueError) as exc:
        return _check("selected_face_geometry", CheckStatus.FAIL,
                      "Invalid face-selection-report.json", {"error": str(exc)}), {}
    if not isinstance(records, list) or simulation is None:
        return _check("selected_face_geometry", CheckStatus.FAIL,
                      "Face-selection report or simulation configuration has an invalid structure"), {}
    expected_names = {"mounting_face", "front_face", "bearing_pad"}
    if set(geometry_scopes) != expected_names:
        return _check("selected_face_geometry", CheckStatus.NOT_RUN,
                      "Complete controlled geometry scope evidence is required before face comparison",
                      {"expected_scopes": sorted(expected_names),
                       "available_scopes": sorted(geometry_scopes)}), {}
    sim_scopes = {item.id: item for item in simulation.scopes}
    selected: dict[str, dict[str, Any]] = {}
    details: list[dict[str, Any]] = []
    for name, expected in geometry_scopes.items():
        scope = sim_scopes.get(name)
        matches = [item for item in records if isinstance(item, dict) and item.get("scope_id") == name]
        if scope is None or len(matches) != 1:
            details.append({"scope_id": name, "status": "NOT_RUN",
                            "reason": "normalized scope or unique face-selection record missing"})
            continue
        record, faces = matches[0], matches[0].get("matched")
        if not isinstance(faces, list) or len(faces) != 1 or not isinstance(faces[0], dict):
            details.append({"scope_id": name, "status": "FAIL",
                            "reason": "controlled axis_extreme_face must resolve to exactly one face",
                            "matched_count": len(faces) if isinstance(faces, list) else None})
            continue
        face = faces[0]
        try:
            area = normalize_quantity(f"{_number(face.get('area'))} {face.get('area_unit')}", "area").magnitude
            centroid = [normalize_quantity(f"{_number(value)} {face.get('centroid_unit')}", "length").magnitude
                        for value in _vector(face.get("centroid"))]
            normal = list(normalize_direction(_vector(face.get("normal"))))
            reported_area, reported_centroid = area, centroid
            boundary_evidence = {}
            if "boundary_summary" in expected:
                boundary = face.get("boundary")
                if not isinstance(boundary, dict) or boundary.get("status") != "CAPTURED":
                    details.append({"scope_id": name, "status": "NOT_RUN",
                                    "reason": "Missing captured Mechanical curve-boundary evidence"})
                    continue
                measured = measure_planar_face(boundary, axis=expected["axis"],
                                               unit=face.get("centroid_unit"),
                                               tolerance_m=_FACE_POSITION_TOLERANCE_M)
                if not boundaries_match(measured["boundary_summary"], expected["boundary_summary"],
                                        _FACE_POSITION_TOLERANCE_M):
                    raise ValueError("Mechanical outer vertices or circular holes differ from CAD")
                area, centroid = measured["area_m2"], measured["centroid_m"]
                boundary_evidence = {"measurement": "analytic_rectangle_minus_circles",
                                     "boundary_summary": measured["boundary_summary"],
                                     "reported_tessellation_area_m2": reported_area,
                                     "reported_tessellation_centroid_m": reported_centroid}
            area_ok = math.isclose(area, expected["area_m2"],
                                   rel_tol=_FACE_AREA_REL_TOLERANCE, abs_tol=1e-12)
            centroid_error = math.dist(centroid, expected["centroid_m"])
            normal_error = math.dist(normal, expected["normal"])
            identity_ok = (record.get("axis") == expected["axis"] == scope.axis
                           and record.get("extreme") == expected["extreme"] == scope.extreme)
            passed = (area_ok and centroid_error <= _FACE_POSITION_TOLERANCE_M
                      and normal_error <= _FACE_NORMAL_TOLERANCE and identity_ok)
            details.append({"scope_id": name, "status": "PASS" if passed else "FAIL",
                            "actual_area_m2": area, "expected_area_m2": expected["area_m2"],
                            "actual_centroid_m": centroid, "expected_centroid_m": expected["centroid_m"],
                            "centroid_error_m": centroid_error, "actual_normal": normal,
                            "expected_normal": expected["normal"], "normal_error": normal_error,
                            "axis": record.get("axis"), "extreme": record.get("extreme"),
                            **boundary_evidence})
            selected[name] = {"area_m2": area, "centroid_m": centroid, "normal": normal}
        except (TypeError, ValueError) as exc:
            details.append({"scope_id": name, "status": "FAIL", "reason": str(exc)})
    if any(item["status"] == CheckStatus.FAIL.value for item in details):
        status = CheckStatus.FAIL
    elif any(item["status"] == CheckStatus.NOT_RUN.value for item in details):
        status = CheckStatus.NOT_RUN
    else:
        status = CheckStatus.PASS
    messages = {CheckStatus.PASS: "Mechanical face area, centroid, and normal match the controlled CAD scopes",
                CheckStatus.FAIL: "Mechanical face selections do not match the controlled CAD scopes",
                CheckStatus.NOT_RUN: "Some CAD scopes lack verifiable selected-face evidence"}
    return _check("selected_face_geometry", status, messages[status], {"faces": details}), selected


def _reported_basename(value: str) -> str:
    return PureWindowsPath(value.replace("/", "\\")).name


def _result_file_attestation(run_dir: Path, rst_path: Path, manifest: dict | None) -> dict:
    actual_hash = sha256_file(rst_path)
    declarations: list[dict[str, str]] = []
    manifest_hashes = manifest.get("hashes") if isinstance(manifest, dict) else None
    if isinstance(manifest_hashes, dict):
        for key in ("result_file_sha256", "result_sha256", "rst_sha256"):
            if key in manifest_hashes:
                declared = manifest_hashes[key]
                if not _is_sha256(declared):
                    return _check("result_file_integrity", CheckStatus.FAIL,
                                  "Run manifest declares an invalid RST SHA256", {"field": key})
                declarations.append({"source": f"run-manifest.json hashes.{key}",
                                     "sha256": declared})

    study_manifest_path = next((parent / "study-manifest.json" for parent in run_dir.parents
                                if (parent / "study-manifest.json").is_file()), None)
    if study_manifest_path is not None:
        try:
            project_root = study_manifest_path.parent.resolve()
            study_manifest = _read_json(study_manifest_path)
            if not isinstance(study_manifest, dict) or not isinstance(study_manifest.get("samples"), list):
                raise ValueError("study-manifest.json has no samples list")
            matching_attempts = []
            for sample in study_manifest["samples"]:
                jobs = sample.get("jobs", []) if isinstance(sample, dict) else []
                for job in jobs if isinstance(jobs, list) else []:
                    attempts = job.get("attempts", []) if isinstance(job, dict) else []
                    for attempt in attempts if isinstance(attempts, list) else []:
                        if not isinstance(attempt, dict) or attempt.get("status") != "SOLVED":
                            continue
                        relative_run = attempt.get("path")
                        if not isinstance(relative_run, str):
                            continue
                        try:
                            declared_run = safe_join(project_root, relative_run).resolve()
                        except (OSError, PathSafetyError, ValueError):
                            continue
                        if declared_run == run_dir.resolve():
                            relative_rst = rst_path.relative_to(run_dir.resolve()).as_posix()
                            hashes = attempt.get("hashes")
                            digest = hashes.get(relative_rst) if isinstance(hashes, dict) else None
                            if not _is_sha256(digest):
                                raise ValueError("Solved attempt has no valid hash for its RST")
                            matching_attempts.append(digest)
            if len(matching_attempts) != 1:
                raise ValueError("RST is not bound to exactly one solved study attempt")
            declarations.append({"source": "study-manifest.json solved-attempt inventory",
                                 "sha256": matching_attempts[0]})
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            return _check("result_file_integrity", CheckStatus.FAIL,
                          "Study attempt checksum evidence is invalid",
                          {"error": str(exc), "actual_sha256": actual_hash})

    if not declarations:
        return _check("result_file_integrity", CheckStatus.NOT_RUN,
                      "No manifest-bound RST SHA256 is available",
                      {"actual_sha256": actual_hash})
    declared_hashes = {item["sha256"] for item in declarations}
    if len(declared_hashes) != 1 or actual_hash not in declared_hashes:
        return _check("result_file_integrity", CheckStatus.FAIL,
                      "Computed RST SHA256 conflicts with declared result provenance",
                      {"actual_sha256": actual_hash, "declarations": declarations})
    return _check("result_file_integrity", CheckStatus.PASS,
                  "Computed RST SHA256 matches manifest-bound solve evidence",
                  {"actual_sha256": actual_hash, "declarations": declarations})


def _result_file_check(
    run_dir: Path, summary: dict | None, artifacts: dict | None, manifest: dict | None,
) -> tuple[dict, Path | None, str | None]:
    if summary is None or artifacts is None:
        return _check("result_file", CheckStatus.NOT_RUN,
                      "Missing result summary or Mechanical artifact"), None, None
    listed, reported = artifacts.get("result_files"), summary.get("result_file")
    if not isinstance(listed, list) or not listed or not isinstance(reported, str) or not reported.strip():
        return _check("result_file", CheckStatus.NOT_RUN,
                      "RST is not listed in both the result summary and Mechanical artifact",
                      {"reported_result_file": reported, "artifact_result_files": listed}), None, None
    try:
        candidates: list[Path] = []
        for item in listed:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("Mechanical result_files contains an invalid path")
            path = safe_join(run_dir, item)
            if path.suffix.casefold() == ".rst":
                candidates.append(path)
        report_name = _reported_basename(reported.strip())
        named = [path for path in candidates if path.name.casefold() == report_name.casefold()]
        existing = [path for path in named if path.is_file() and not path.is_symlink()
                    and path.stat().st_size > 0]
        if len(named) != 1 or len(existing) != 1:
            status = CheckStatus.FAIL if len(named) > 1 else CheckStatus.NOT_RUN
            return _check("result_file", status,
                          "Could not uniquely locate the summary RST from relative Mechanical result_files",
                          {"reported_basename": report_name,
                           "artifact_result_files": [str(path) for path in candidates]}), None, None
        selected = existing[0].resolve(strict=True)
        if not selected.is_relative_to(run_dir.resolve()):
            raise ValueError("RST path escapes the run directory")
        digest = sha256_file(selected)
        attestation = _result_file_attestation(run_dir, selected, manifest)
        if attestation["status"] != CheckStatus.PASS.value:
            return (_check("result_file", attestation["status"], attestation["message"],
                           {**attestation["evidence"],
                            "path": selected.relative_to(run_dir.resolve()).as_posix(),
                            "reported_result_file": reported, "sha256": digest}), selected, digest)
        return (_check("result_file", CheckStatus.PASS,
                       "Mechanical relative result_files matches the summary basename and manifest-bound RST SHA256",
                       {"path": selected.relative_to(run_dir.resolve()).as_posix(),
                        "reported_result_file": reported, "basename": report_name,
                        **attestation["evidence"]}), selected, digest)
    except (OSError, ValueError, TypeError, PathSafetyError) as exc:
        return _check("result_file", CheckStatus.FAIL, "RST path provenance is invalid",
                      {"error": str(exc)}), None, None


def _parse_reaction_vector(item: dict) -> list[float]:
    count = item.get("value_count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("reaction result is empty")
    if "canonical_sum_vector" in item:
        if item.get("canonical_sum_vector_unit") != _canonical_unit("force"):
            raise ValueError("reaction canonical sum vector has a missing or non-SI unit")
        return _vector(item["canonical_sum_vector"])
    vector, unit = _vector(item.get("sum_vector")), item.get("sum_vector_unit")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("reaction sum vector has no unit")
    return [normalize_quantity(f"{value} {unit}", "force").magnitude for value in vector]


def _summary_reaction(simulation: SimulationSpec, summary: dict) -> list[float]:
    results = summary.get("results")
    if not isinstance(results, dict):
        raise ValueError("result summary has no results mapping")
    requests = [item for item in simulation.requested_results if item.type is ResultType.REACTION_FORCE]
    if not requests:
        raise ValueError("no requested support reaction result")
    supports: set[str] = set()
    vectors = []
    for request in requests:
        if request.support in supports:
            continue
        supports.add(request.support)
        item = results.get(request.id)
        if not isinstance(item, dict):
            raise ValueError(f"reaction result {request.id!r} is missing")
        vectors.append(_parse_reaction_vector(item))
    return _sum_vectors(vectors)


def _saved_nodal_reaction_evidence(
    run_dir: Path, rst_path: Path,
) -> tuple[tuple[list[float], list[float]] | None, str | None]:
    """Reuse nodal data only when the saved engineering record binds it to this RST."""
    record_path = run_dir / "engineering-checks.json"
    nodal_path = run_dir / "nodal-evidence.json"
    if not record_path.is_file() or record_path.is_symlink() or not nodal_path.is_file() or nodal_path.is_symlink():
        return None, "saved nodal reaction evidence is absent"
    try:
        record, nodal = _read_json(record_path), _read_json(nodal_path)
        if not isinstance(record, dict) or not isinstance(nodal, dict):
            raise ValueError("saved nodal evidence has an invalid structure")
        hashes, reference = record.get("hashes"), record.get("nodal_evidence")
        if not isinstance(hashes, dict):
            raise ValueError("engineering-checks.json has no hash record")
        if (hashes.get("rst_sha256") != sha256_file(rst_path)
                or hashes.get("nodal_evidence_sha256") != sha256_file(nodal_path)):
            raise ValueError("saved nodal evidence is not bound to the current RST and file hashes")
        if not isinstance(reference, str) or PureWindowsPath(reference.replace("/", "\\")).name != nodal_path.name:
            raise ValueError("engineering-checks.json references a different nodal-evidence file")
        checks = record.get("checks")
        check_statuses = {item.get("name"): item.get("status") for item in checks
                          if isinstance(item, dict)} if isinstance(checks, list) else {}
        if check_statuses.get("rst_preserved") != "PASS" or check_statuses.get("physical_scopes") != "PASS":
            raise ValueError("saved nodal evidence lacks passing RST and physical-scope checks")
        node_ids, coordinates = nodal.get("node_ids"), nodal.get("coordinates_m")
        support_ids, reactions = nodal.get("support_node_ids"), nodal.get("reaction_force_N")
        if (not isinstance(node_ids, list) or not isinstance(coordinates, list)
                or len(node_ids) != len(coordinates) or not isinstance(support_ids, list)
                or not isinstance(reactions, list) or len(support_ids) != len(reactions)
                or not support_ids):
            raise ValueError("saved nodal coordinates and support reactions have invalid cardinality")
        coordinate_by_id = {int(node): _vector(point) for node, point in zip(node_ids, coordinates, strict=True)}
        if len(coordinate_by_id) != len(node_ids):
            raise ValueError("saved nodal coordinates contain duplicate node IDs")
        if len(set(support_ids)) != len(support_ids) or any(node not in coordinate_by_id for node in support_ids):
            raise ValueError("saved support node IDs are duplicate or lack coordinates")
        reaction_rows = [_vector(row) for row in reactions]
        reaction = _sum_vectors(reaction_rows)
        moment = _sum_vectors([_cross(coordinate_by_id[node], vector)
                               for node, vector in zip(support_ids, reaction_rows, strict=True)])
        return (reaction, moment), None
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        return None, str(exc)


def _isolated_dpf_reaction_evidence(
    rst_path: Path, simulation: SimulationSpec, run_dir: Path,
) -> tuple[list[float], list[float]]:
    """Extract nodal reactions in a child process so DPF cannot alter the collector environment."""
    worker = Path(__file__).with_name("quality_dpf_worker.py")
    with tempfile.TemporaryDirectory(prefix="ansys-study-dpf-") as temporary:
        directory = Path(temporary)
        request_path, result_path = directory / "request.json", directory / "result.json"
        request_path.write_text(json.dumps({
            "rst_path": str(rst_path),
            "simulation": simulation.model_dump(mode="json", exclude_none=True),
        }, allow_nan=False), encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, str(worker), "--request", str(request_path),
                 "--result", str(result_path)],
                cwd=run_dir, capture_output=True, check=False, timeout=180,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Isolated DPF worker timed out") from exc
        if completed.returncode != 0 or not result_path.is_file():
            detail = completed.stderr.decode("utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"Isolated DPF worker failed: {detail or completed.returncode}")
        payload = _read_json(result_path)
        if not isinstance(payload, dict):
            raise ValueError("Isolated DPF worker returned an invalid payload")
        return _vector(payload.get("reaction_force_N")), _vector(payload.get("reaction_moment_Nm"))


def _applied_loads(
    simulation: SimulationSpec, geometry: dict, selected: dict[str, dict], density_kg_m3: float,
) -> tuple[list[list[float]], list[list[float]]]:
    volume = _number(geometry["volume_m3"])
    center = _vector(geometry["center_of_mass_m"])
    forces, moments = [], []
    for load in simulation.loads:
        if load.type == "force":
            if load.components is not None:
                vector = [normalize_quantity(value, "force").magnitude for value in load.components.values()]
            else:
                magnitude = normalize_quantity(load.magnitude, "force").magnitude
                vector = [magnitude * value for value in normalize_direction(load.direction)]
            face = selected.get(load.scope or "")
            if face is None:
                raise LookupError(f"force scope {load.scope!r} has no verified face")
            point = face["centroid_m"]
        elif load.type == "pressure":
            face = selected.get(load.scope or "")
            if face is None:
                raise LookupError(f"pressure scope {load.scope!r} has no verified face")
            pressure = normalize_quantity(load.magnitude, "pressure").magnitude
            # Positive Mechanical pressure acts inward, opposite the selected face normal.
            vector = [-pressure * face["area_m2"] * value for value in face["normal"]]
            point = face["centroid_m"]
        else:
            acceleration = normalize_quantity(load.magnitude, "acceleration").magnitude
            weight = volume * density_kg_m3 * acceleration
            vector = [weight * value for value in normalize_direction(load.direction)]
            point = center
        forces.append(vector)
        moments.append(_cross(point, vector))
    return forces, moments


def _reaction_checks(
    run_dir: Path, simulation: SimulationSpec | None, summary: dict | None, rst_path: Path | None,
    geometry: dict, selected: dict[str, dict], density: float | None, need_moment: bool,
    *, real_solve: bool,
) -> tuple[dict, dict | None]:
    if not real_solve:
        missing = _check("derived_reaction_balance", CheckStatus.NOT_RUN,
                         "A verified real solve is required for derived reaction balance")
        moment = (_check("derived_moment_balance", CheckStatus.NOT_RUN,
                         "A verified real solve is required for derived moment balance")
                  if need_moment else None)
        return missing, moment
    if simulation is None or summary is None or density is None:
        missing = _check("derived_reaction_balance", CheckStatus.NOT_RUN,
                         "Missing simulation, result, or verified material density")
        moment = (_check("derived_moment_balance", CheckStatus.NOT_RUN,
                         "Missing inputs required to calculate support reaction moment") if need_moment else None)
        return missing, moment
    try:
        applied, applied_moments = _applied_loads(simulation, geometry, selected, density)
    except (KeyError, TypeError, ValueError, LookupError) as exc:
        missing = _check("derived_reaction_balance", CheckStatus.NOT_RUN,
                         "Cannot construct an independent resultant from verified loads and face scopes",
                         {"reason": str(exc)})
        moment = (_check("derived_moment_balance", CheckStatus.NOT_RUN,
                         "Cannot construct an independent moment reference",
                         {"reason": str(exc)}) if need_moment else None)
        return missing, moment
    applied_force = _sum_vectors(applied)
    force_scale = _norm(applied_force)
    if force_scale <= 0:
        missing = _check("derived_reaction_balance", CheckStatus.NOT_RUN,
                         "The applied resultant is zero; a relative reaction residual is undefined",
                         {"applied_resultant_N": applied_force})
        moment = (_check("derived_moment_balance", CheckStatus.NOT_RUN,
                         "Cannot construct a valid relative moment reference") if need_moment else None)
        return missing, moment
    try:
        reaction = _summary_reaction(simulation, summary)
        reaction_source = "results-summary.json canonical_sum_vector"
        actual_moment = None
        dpf_error = None
    except (KeyError, TypeError, ValueError) as exc:
        reaction, actual_moment, reaction_source, dpf_error = None, None, None, str(exc)
    if need_moment or reaction is None:
        if rst_path is None:
            dpf_error = "RST is unavailable"
        else:
            saved, saved_error = _saved_nodal_reaction_evidence(run_dir, rst_path)
            if saved is not None:
                reaction, actual_moment = saved
                reaction_source = "hash-verified saved nodal-evidence.json"
            else:
                try:
                    reaction, actual_moment = _isolated_dpf_reaction_evidence(
                        rst_path, simulation, run_dir
                    )
                    reaction_source = "isolated PyDPF worker"
                except Exception as exc:  # DPF is optional and must never be mistaken for evidence.
                    dpf_error = f"Saved nodal evidence unavailable ({saved_error}); {exc}"
    reaction_check = (
        _check("derived_reaction_balance", CheckStatus.NOT_RUN,
               "No unit-qualified support reaction resultant is available",
               {"reason": dpf_error or "reaction vector unavailable"})
        if reaction is None else None
    )
    if reaction is not None:
        residual = _sum_vectors([reaction, applied_force])
        relative = _norm(residual) / force_scale
        tolerance = simulation.validation.reaction_balance_relative_tolerance
        reaction_check = _check("derived_reaction_balance",
                                CheckStatus.PASS if relative <= tolerance else CheckStatus.FAIL,
                                "Support reactions balance the independent force/pressure/gravity resultant",
                                {"applied_resultant_N": applied_force, "reaction_resultant_N": reaction,
                                 "residual_N": residual, "relative_residual": relative,
                                 "relative_tolerance": tolerance, "reaction_source": reaction_source})
    moment_check = None
    if need_moment:
        if actual_moment is None and rst_path is not None:
            dpf_error = dpf_error or "No nodal reaction moment was extracted"
        applied_moment = _sum_vectors(applied_moments)
        scale = _norm(applied_moment)
        if actual_moment is None:
            moment_check = _check("derived_moment_balance", CheckStatus.NOT_RUN,
                                  "PyDPF nodal coordinates or support reactions are unavailable; moment was not calculated",
                                  {"reason": dpf_error or "DPF evidence unavailable"})
        elif scale <= 0:
            moment_check = _check("derived_moment_balance", CheckStatus.NOT_RUN,
                                  "The applied moment is zero; a relative residual is undefined",
                                  {"applied_moment_Nm": applied_moment})
        else:
            residual = _sum_vectors([actual_moment, applied_moment])
            relative = _norm(residual) / scale
            moment_check = _check("derived_moment_balance",
                                  CheckStatus.PASS if relative <= _MOMENT_REL_TOLERANCE else CheckStatus.FAIL,
                                  "Support nodal reaction moment balances the independent applied moment",
                                  {"applied_moment_Nm": applied_moment,
                                   "reaction_moment_Nm": actual_moment, "residual_Nm": residual,
                                   "relative_residual": relative,
                                   "relative_tolerance": _MOMENT_REL_TOLERANCE,
                                   "moment_origin_m": [0.0, 0.0, 0.0],
                                   "reaction_source": reaction_source})
    return reaction_check, moment_check


def _target_value_check(
    study: StudySpec, target_name: str, summary: dict | None, simulation: SimulationSpec | None,
) -> tuple[dict, float | None]:
    target = study.targets[target_name]
    check_name = f"target_value:{target_name}"
    if summary is None or simulation is None:
        return _check(check_name, CheckStatus.NOT_RUN, "Missing simulation or result summary"), None
    requested = {item.id: item for item in simulation.requested_results}
    request = requested.get(target.result_id)
    expected = ({ResultType.TOTAL_DEFORMATION, ResultType.DIRECTIONAL_DEFORMATION}
                if target.dimension == "length" else {ResultType.EQUIVALENT_VON_MISES_STRESS})
    if request is None or request.type not in expected:
        return _check(check_name, CheckStatus.FAIL,
                      "Study target does not match a requested result in normalized simulation",
                      {"result_id": target.result_id, "dimension": target.dimension}), None
    results = summary.get("results")
    result = results.get(target.result_id) if isinstance(results, dict) else None
    if result is None:
        return _check(check_name, CheckStatus.NOT_RUN, "Target metric is missing from the result summary",
                      {"result_id": target.result_id}), None
    if not isinstance(result, dict):
        return _check(check_name, CheckStatus.FAIL, "Target result has an invalid structure",
                      {"result_id": target.result_id}), None
    try:
        raw_value = _number(result.get("canonical_maximum"))
        count = result.get("value_count")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError("value_count must be a positive integer")
        unit = _canonical_unit(target.dimension)
        if result.get("canonical_unit") != unit:
            raise ValueError(f"canonical_unit must be {unit!r}")
    except (TypeError, ValueError) as exc:
        return _check(check_name, CheckStatus.FAIL,
                      "Target result is not a non-empty finite metric with a canonical SI unit",
                      {"result_id": target.result_id, "error": str(exc),
                       "canonical_unit": result.get("canonical_unit"),
                       "value_count": result.get("value_count")}), None
    value = abs(raw_value)
    return _check(check_name, CheckStatus.PASS,
                  "Target result has a valid canonical SI scalar and non-empty DPF sample",
                  {"result_id": target.result_id, "value": value,
                   "canonical_unit": unit, "value_count": count}), value


def _review_check(target_name: str, result_hash: str | None, reviews: dict | None) -> dict:
    name = f"stress_review:{target_name}"
    if result_hash is None or reviews is None or result_hash not in reviews:
        return _check(name, CheckStatus.NOT_RUN, "A stress singularity review is required for this RST hash",
                      {"result_file_sha256": result_hash, "review_status": "REVIEW_REQUIRED"})
    review = reviews[result_hash]
    if not isinstance(review, dict):
        return _check(name, CheckStatus.FAIL, "Stress review record has an invalid structure",
                      {"result_file_sha256": result_hash})
    reviewer, rationale, citations = review.get("reviewer"), review.get("rationale"), review.get("evidence")
    if (review.get("status") != "PASS" or not isinstance(reviewer, str) or not reviewer.strip()
            or not isinstance(rationale, str) or not rationale.strip()
            or not isinstance(citations, list) or not citations
            or any(not isinstance(item, str) or not item.strip() for item in citations)):
        return _check(name, CheckStatus.FAIL, "Stress review requires PASS, a reviewer, rationale, and evidence",
                      {"result_file_sha256": result_hash, "review_status": review.get("status")})
    return _check(name, CheckStatus.PASS, "An explicit stress review is recorded for the current RST hash",
                  {"result_file_sha256": result_hash, "review_status": "PASS",
                   "reviewer": reviewer, "rationale": rationale, "evidence": citations})


def _mesh_shape_check(artifacts: dict | None) -> dict:
    analysis = artifacts.get("analysis") if isinstance(artifacts, dict) else None
    quality = analysis.get("mesh_quality") if isinstance(analysis, dict) else None
    result = assess_mesh_quality(quality)
    evidence = dict(result["evidence"])
    if result["quality_sha256"] is not None:
        evidence["quality_sha256"] = result["quality_sha256"]
    return _check("mesh_shape_quality", CheckStatus(result["status"]),
                  result["message"], evidence)


def _mesh_warning_review_check(
    target_name: str, result_hash: str | None, mesh_check: dict, reviews: dict | None,
) -> dict:
    result = mesh_quality_review_check(
        target_name, result_hash, mesh_check["evidence"].get("quality_sha256"), reviews,
        mesh_check["status"],
    )
    return _check(f"mesh_quality_review:{target_name}", CheckStatus(result["status"]),
                  result["message"], result["evidence"])


def evaluate_run(
    run_dir: Path, study: StudySpec, geometry: dict, reviews: dict | None = None,
) -> dict:
    """Assess one run as study data; engineering feasibility remains a separate decision."""
    run_dir = Path(run_dir).resolve()
    checks: list[dict] = []
    manifest, manifest_error = _load_artifact(run_dir, "run-manifest.json", dict)
    summary, summary_error = _load_artifact(run_dir, "results-summary.json", dict)
    verification, verification_error = _load_artifact(run_dir, "verification.json", dict)
    artifacts, artifacts_error = _load_artifact(run_dir, "mechanical-artifacts.json", dict)
    checks.extend(item for item in (manifest_error, summary_error, verification_error, artifacts_error)
                  if item is not None)
    verification_by_name, verification_meta = _verification_checks(verification)
    checks.extend(verification_meta)
    checks.extend(dict(item) for item in verification_by_name.values())

    simulation, source_check = _source_check(run_dir, manifest)
    result_check, rst_path, result_hash = _result_file_check(
        run_dir, summary, artifacts, manifest
    )
    real_check = _real_solve_check(manifest, summary, artifacts, simulation, result_check)
    density_check, density = _material_density_check(run_dir, study, simulation)
    geometry_check, geometry_scopes = _geometry_check(run_dir, geometry, manifest, simulation, density)
    face_check, selected = _selected_faces_check(run_dir, geometry_scopes, simulation)
    mesh_shape_check = _mesh_shape_check(artifacts)
    checks.extend((source_check, real_check, result_check, density_check, geometry_check, face_check, mesh_shape_check))

    need_moment = any("moment_balance" in item.required_checks for item in study.targets.values())
    reaction_check, moment_check = _reaction_checks(
        run_dir, simulation, summary, rst_path, geometry, selected, density, need_moment,
        real_solve=real_check["status"] == CheckStatus.PASS.value,
    )
    checks.append(reaction_check)
    if moment_check is not None:
        checks.append(moment_check)

    values: dict[str, float] = {}
    target_checks: dict[str, list[dict]] = {}
    accepted_targets: list[str] = []
    common_gates = [verification_meta[0], source_check, real_check, result_check,
                    density_check, geometry_check, face_check]
    review_statuses: dict[str, dict[str, str | None]] = {}
    for target_name, target in study.targets.items():
        item_checks = [dict(item) for item in common_gates]
        item_checks.append(dict(mesh_shape_check))
        mesh_review = None
        if mesh_shape_check["status"] in {CheckStatus.WARN.value, CheckStatus.FAIL.value}:
            mesh_review = _mesh_warning_review_check(target_name, result_hash, mesh_shape_check, reviews)
            checks.append(mesh_review)
            item_checks.append(mesh_review)
        value_check, value = _target_value_check(study, target_name, summary, simulation)
        checks.append(value_check)
        item_checks.append(value_check)
        if value is not None:
            values[target_name] = value
        required_ok = True
        for required in target.required_checks:
            original = verification_by_name.get(required)
            if original is None:
                original = _check(required, CheckStatus.NOT_RUN,
                                  f"Required check {required!r} is missing from verification.json")
            item_checks.append(dict(original))
            if required == "reaction_balance" and original["status"] == CheckStatus.NOT_RUN.value:
                item_checks.append(dict(reaction_check))
                satisfied = reaction_check["status"] == CheckStatus.PASS.value
            elif required == "moment_balance":
                derived = moment_check or _check("derived_moment_balance", CheckStatus.NOT_RUN,
                                                 "DPF moment extraction was not requested")
                item_checks.append(dict(derived))
                satisfied = (original["status"] == CheckStatus.PASS.value
                             or derived["status"] == CheckStatus.PASS.value)
            else:
                satisfied = original["status"] == CheckStatus.PASS.value
            required_ok = required_ok and satisfied
        if target.require_stress_review:
            review = _review_check(target_name, result_hash, reviews)
            checks.append(review)
            item_checks.append(review)
            review_statuses[target_name] = {
                "status": review["status"],
                "review_status": review["evidence"].get("review_status"),
            }
            required_ok = required_ok and review["status"] == CheckStatus.PASS.value
        target_checks[target_name] = item_checks
        mesh_gate_status = mesh_target_gate(mesh_shape_check["status"],
                                            mesh_review["status"] if mesh_review else None)
        if (value is not None and all(item["status"] == CheckStatus.PASS.value for item in common_gates)
                and mesh_gate_status is CheckStatus.PASS and required_ok):
            accepted_targets.append(target_name)

    source_hashes = manifest.get("hashes", {}) if isinstance(manifest, dict) else {}
    stress_review_required = any(target.require_stress_review for target in study.targets.values())
    review_status = (
        "REVIEW_REQUIRED" if any(item.get("review_status") == "REVIEW_REQUIRED"
                                  for item in review_statuses.values())
        else "FAIL" if any(item.get("status") == CheckStatus.FAIL.value
                           for item in review_statuses.values())
        else "PASS" if review_statuses else "NOT_REQUIRED"
    )
    evidence: dict[str, Any] = {
        "run_directory": str(run_dir),
        "result_file_sha256": result_hash,
        "review_status": review_status if stress_review_required else "NOT_REQUIRED",
        "review_statuses": review_statuses,
        "provenance": {
            "run_status": manifest.get("status") if manifest else None,
            "synthetic": manifest.get("synthetic") if manifest else None,
            "execution_mode": manifest.get("execution_mode") if manifest else None,
            "result_file": result_check["evidence"].get("path"),
            "result_file_sha256": result_hash,
            "source_spec_sha256": source_hashes.get("source_spec_sha256") if isinstance(source_hashes, dict) else None,
            "normalized_spec_sha256": source_hashes.get("normalized_spec_sha256") if isinstance(source_hashes, dict) else None,
            "geometry_sha256": geometry.get("geometry_sha256") if isinstance(geometry, dict) else None,
            "real": real_check["status"] == CheckStatus.PASS.value,
        },
        "mesh_size_m": None,
        "node_count": summary.get("node_count") if summary else None,
        "element_count": summary.get("element_count") if summary else None,
        "raw_verification_status": verification.get("status") if verification else None,
    }
    if simulation is not None:
        with suppress(TypeError, ValueError):
            evidence["mesh_size_m"] = normalize_quantity(simulation.mesh.global_element_size, "length").magnitude
    return {"status": _status(checks),
        "synthetic": manifest is None or manifest.get("synthetic") is not False,
            "values": values, "checks": checks, "target_checks": target_checks,
            "accepted_targets": accepted_targets, "evidence": evidence}


def _mesh_target_valid(level: dict, target_name: str, target: Any) -> tuple[CheckStatus, str]:
    """Validate only the checks that govern one target in an evaluator record."""
    accepted = level.get("accepted_targets")
    target_checks = level.get("target_checks")
    if (not isinstance(accepted, list) or not isinstance(target_checks, dict)
            or target_name not in target_checks):
        return CheckStatus.FAIL, "per-target level checks are missing or malformed"
    per_target = target_checks[target_name]
    if not isinstance(per_target, list):
        return CheckStatus.FAIL, "target checks are malformed"
    by_name: dict[str, dict] = {}
    for item in per_target:
        if (not isinstance(item, dict) or not isinstance(item.get("name"), str)
                or item["name"] in by_name
                or item.get("status") not in {status.value for status in CheckStatus}):
            return CheckStatus.FAIL, "target checks contain malformed or duplicate records"
        by_name[item["name"]] = item

    common_names = ("verification_evidence", "source_configuration", "real_solve",
                    "result_file", "material_density", "geometry_provenance", "selected_face_geometry")
    for item in by_name.values():
        if item["status"] == CheckStatus.FAIL.value:
            return CheckStatus.FAIL, f"target check {item['name']!r} failed"
    for name in common_names:
        item = by_name.get(name)
        if item is None or item["status"] != CheckStatus.PASS.value:
            status = CheckStatus.FAIL if item and item["status"] == CheckStatus.FAIL.value else CheckStatus.NOT_RUN
            return status, f"target common check {name!r} did not pass"
    mesh_check = by_name.get("mesh_shape_quality")
    if mesh_check is None:
        return CheckStatus.NOT_RUN, "target mesh shape check is missing"
    if mesh_check["status"] == CheckStatus.WARN.value:
        review = by_name.get(f"mesh_quality_review:{target_name}")
        if review is None or review["status"] == CheckStatus.NOT_RUN.value:
            return CheckStatus.NOT_RUN, "raw mesh warning has no target-bound review"
        evidence = level.get("evidence")
        provenance = evidence.get("provenance") if isinstance(evidence, dict) else None
        result_hash = provenance.get("result_file_sha256") if isinstance(provenance, dict) else None
        quality_hash = mesh_check.get("evidence", {}).get("quality_sha256")
        if not mesh_review_matches_target(review, target_name, result_hash, quality_hash):
            return CheckStatus.FAIL, "mesh warning review is not bound to this target and evidence"
    elif mesh_check["status"] == CheckStatus.FAIL.value:
        return CheckStatus.FAIL, "mesh shape quality failed"
    elif mesh_check["status"] == CheckStatus.NOT_RUN.value:
        return CheckStatus.NOT_RUN, "mesh shape quality did not run"
    elif mesh_check["status"] != CheckStatus.PASS.value:
        return CheckStatus.FAIL, "mesh shape quality status is malformed"
    value_check = by_name.get(f"target_value:{target_name}")
    if value_check is None or value_check["status"] != CheckStatus.PASS.value:
        status = (CheckStatus.FAIL if value_check
                  and value_check["status"] == CheckStatus.FAIL.value else CheckStatus.NOT_RUN)
        return status, "target value check did not pass"
    for required in target.required_checks:
        item = by_name.get(required)
        if item is not None and item["status"] == CheckStatus.PASS.value:
            continue
        if required == "reaction_balance":
            derived = by_name.get("derived_reaction_balance")
            if (item is not None and item["status"] == CheckStatus.NOT_RUN.value
                    and derived is not None and derived["status"] == CheckStatus.PASS.value):
                continue
        if required == "moment_balance":
            derived = by_name.get("derived_moment_balance")
            if derived is not None and derived["status"] == CheckStatus.PASS.value:
                continue
        status = CheckStatus.FAIL if item and item["status"] == CheckStatus.FAIL.value else CheckStatus.NOT_RUN
        return status, f"required target check {required!r} did not pass"
    if target.require_stress_review:
        review = by_name.get(f"stress_review:{target_name}")
        if review is None or review["status"] != CheckStatus.PASS.value:
            status = (CheckStatus.FAIL if review and review["status"] == CheckStatus.FAIL.value
                      else CheckStatus.NOT_RUN)
            return status, "required stress review did not pass"
    if target_name not in accepted:
        return CheckStatus.NOT_RUN, "target is not accepted as study data at this level"
    return CheckStatus.PASS, ""


def _mesh_level_valid(level: dict, target_name: str, target: Any) -> tuple[CheckStatus, str]:
    if not isinstance(level, dict):
        return CheckStatus.FAIL, "level record is not an object"
    if level.get("synthetic") is True:
        return CheckStatus.FAIL, "level is synthetic"
    if level.get("synthetic") is not False:
        return CheckStatus.NOT_RUN, "level lacks an explicit synthetic=false marker"
    if level.get("status") not in {CheckStatus.PASS.value, CheckStatus.WARN.value,
                                      CheckStatus.FAIL.value}:
        return CheckStatus.FAIL, "level quality status is malformed"
    checks = level.get("checks")
    if not isinstance(checks, list):
        return CheckStatus.FAIL, "level global checks are missing or malformed"
    real_checks = [item for item in checks
                   if isinstance(item, dict) and item.get("name") == "real_solve"]
    if len(real_checks) != 1:
        return CheckStatus.FAIL, "level must contain exactly one real_solve check"
    if real_checks[0].get("status") == CheckStatus.FAIL.value:
        return CheckStatus.FAIL, "level real_solve check failed"
    if real_checks[0].get("status") != CheckStatus.PASS.value:
        return CheckStatus.NOT_RUN, "level real_solve check did not pass"
    evidence = level.get("evidence")
    provenance = evidence.get("provenance") if isinstance(evidence, dict) else None
    if not isinstance(provenance, dict):
        return CheckStatus.NOT_RUN, "level lacks solve provenance"
    if provenance.get("real") is False or provenance.get("run_status") != "SOLVED":
        return CheckStatus.FAIL, "level is not a successful real solve"
    if (provenance.get("real") is not True
            or not all(_is_sha256(provenance.get(key)) for key in
                       ("result_file_sha256", "source_spec_sha256", "normalized_spec_sha256",
                        "geometry_sha256"))):
        return CheckStatus.NOT_RUN, "level lacks verified real RST provenance"
    return _mesh_target_valid(level, target_name, target)


def assess_mesh_convergence(study: StudySpec, levels: list[dict]) -> dict:
    """Assess mesh changes for all targets while preserving coarse-to-fine input order."""
    checks: list[dict] = []
    if len(levels) < 3:
        checks.append(_check("mesh_level_count", CheckStatus.NOT_RUN,
                             "At least three mesh levels are required to assess convergence",
                             {"provided_levels": len(levels), "required_levels": 3}))
    else:
        checks.append(_check("mesh_level_count", CheckStatus.PASS,
                             "Mesh-level count meets the minimum of three",
                             {"provided_levels": len(levels)}))
    target_results: dict[str, dict[str, Any]] = {}
    for target_name, target in study.targets.items():
        values: list[float | None] = []
        malformed_values: list[int] = []
        level_statuses, reasons = [], []
        mesh_sizes, node_counts, element_counts = [], [], []
        for index, level in enumerate(levels):
            level_status, reason = _mesh_level_valid(level, target_name, target)
            level_statuses.append(level_status)
            if reason:
                reasons.append(f"level {index}: {reason}")
            raw_value = (level.get("values", {}).get(target_name)
                         if isinstance(level, dict) and isinstance(level.get("values"), dict) else None)
            try:
                values.append(abs(_number(raw_value)) if raw_value is not None else None)
            except ValueError:
                values.append(None)
                malformed_values.append(index)
                reasons.append(f"level {index}: target value is non-finite or malformed")
            evidence = level.get("evidence") if isinstance(level, dict) else None
            evidence = evidence if isinstance(evidence, dict) else {}
            try:
                mesh_sizes.append(_number(evidence.get("mesh_size_m")))
            except ValueError:
                mesh_sizes.append(None)
            node_counts.append(evidence.get("node_count"))
            element_counts.append(evidence.get("element_count"))

        adjacent: list[dict[str, Any]] = []
        reference = normalize_quantity(target.reference_scale, target.dimension).magnitude
        absolute_tolerance = normalize_quantity(target.absolute_tolerance, target.dimension).magnitude
        limit = absolute_tolerance + target.mesh_relative_tolerance * reference
        for index, (coarse, fine) in enumerate(pairwise(values)):
            valid_pair = (coarse is not None and fine is not None
                          and math.isfinite(coarse) and math.isfinite(fine))
            delta = abs(fine - coarse) if valid_pair else None
            adjacent.append({"from_level": index, "to_level": index + 1,
                             "coarse_value": coarse, "fine_value": fine,
                             "absolute_change": delta,
                             "relative_change": delta / reference if delta is not None else None,
                             "limit": limit,
                             "within_limit": delta <= limit if delta is not None else False})
        has_all_values = all(value is not None and math.isfinite(value) for value in values)
        status = CheckStatus.PASS
        if len(levels) < 3:
            status = CheckStatus.NOT_RUN
            reasons.append("at least three levels are required")
        elif any(item is CheckStatus.FAIL for item in level_statuses):
            status = CheckStatus.FAIL
        elif any(item is CheckStatus.NOT_RUN for item in level_statuses):
            status = CheckStatus.NOT_RUN
        elif malformed_values:
            status = CheckStatus.FAIL
            reasons.append(f"non-finite or malformed values at levels {malformed_values}")
        elif any(value is None for value in values):
            status = CheckStatus.NOT_RUN
            reasons.append("one or more target values are missing")
        elif not has_all_values:
            status = CheckStatus.FAIL
            reasons.append("one or more target values are non-finite")
        elif any(size is None or not math.isfinite(size) or size <= 0 for size in mesh_sizes):
            status = CheckStatus.NOT_RUN
            reasons.append("mesh size evidence is missing or invalid")
        elif any(left <= right for left, right in pairwise(mesh_sizes)):
            status = CheckStatus.FAIL
            reasons.append("mesh sizes are not strictly refined from coarse to fine")
        elif any(not isinstance(count, int) or isinstance(count, bool) or count <= 0
                 for count in node_counts + element_counts):
            status = CheckStatus.NOT_RUN
            reasons.append("positive node and element counts are required")
        elif (any(left >= right for left, right in pairwise(node_counts))
              or any(left >= right for left, right in pairwise(element_counts))):
            status = CheckStatus.FAIL
            reasons.append("node and element counts did not increase at every refinement")
        elif not adjacent[-1]["within_limit"]:
            status = CheckStatus.FAIL
            reasons.append("finest adjacent change exceeds absolute-plus-relative mesh tolerance")
        elif (len(adjacent) >= 2
              and adjacent[-1]["absolute_change"] > adjacent[-2]["absolute_change"]):
            status = CheckStatus.WARN
            reasons.append("adjacent change increased on the finest refinement; trend is worsening")
        message = "; ".join(reasons) if reasons else (
            "finest adjacent change is within tolerance and refinement trend is not worsening"
        )
        target_results[target_name] = {
            "status": status.value, "values": values,
            "relative_change": adjacent[-1]["relative_change"] if adjacent else None,
            "absolute_change": adjacent[-1]["absolute_change"] if adjacent else None,
            "limit": limit,
            "message": message, "adjacent_changes": adjacent,
        }
        checks.append(_check(f"mesh_convergence:{target_name}", status, message,
                             {"values": values, "mesh_sizes_m": mesh_sizes,
                              "node_counts": node_counts, "element_counts": element_counts,
                              "adjacent_changes": adjacent, "reasons": reasons}))
    return {"status": _status(checks), "targets": target_results, "checks": checks}
