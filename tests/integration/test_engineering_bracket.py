"""Opt-in, five-solve acceptance study for the single-solid equipment bracket.

All assertions run after the module fixture has written the study evidence.
Stress convergence concerns nodal statistics on the pressure pad, not the global
stress peak. Fixed tolerances must not be relaxed to accommodate a failed study.
"""
from __future__ import annotations

import copy
import json
import math
import os
import struct
import subprocess
import sys
import traceback
from collections import Counter
from io import BytesIO
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import yaml
from ansys_skill.cli import _find_result_file
from ansys_skill.manifest import sha256_file
from ansys_skill.postprocessing.dpf import _equivalent_stress, _resolve_scope, _scope_name
from ansys_skill.schema import load_spec
from ansys_skill.units import normalize_direction, normalize_quantity
from ansys_skill.validation.statuses import Check, CheckStatus, aggregate_checks

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "gusseted-bracket"
REAL_BACKENDS = ("pymechanical_remote", "mechanical_batch")
TIMEOUT_SECONDS = 1800
DENSITY_KG_M3 = 7850.0
GRAVITY_M_S2 = 9.80665
FORCE_N = [1000.0, 1500.0, -500.0]
PRESSURE_PA = 800000.0
FORCE_TOLERANCE = 0.005
MOMENT_TOLERANCE = 0.01
DISPLACEMENT_TOLERANCE = 0.05
STRESS_TOLERANCE = 0.10
COORDINATE_TOLERANCE_M = 1e-12
LINEARITY_RELATIVE_TOLERANCE = 1e-6
LINEARITY_ABSOLUTE_TOLERANCE_M = 1e-12
IMAGE_NAMES = ("mesh.png", "total-deformation.png", "equivalent-stress.png")
# Order matters: run serially and retain all three fine-mesh fields.
CASES = (
    ("mixed_12mm", 12, 1.0),
    ("mixed_8mm", 8, 1.0),
    ("mixed_5mm", 5, 1.0),
    ("gravity_5mm", 5, 0.0),
    ("double_mechanical_5mm", 5, 2.0),
)

pytestmark = [
    pytest.mark.ansys_integration,
    pytest.mark.skipif(
        os.getenv("ANSYS_AVAILABLE") != "1",
        reason="NOT_RUN: real bracket study requires ANSYS_AVAILABLE=1",
    ),
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _check(name: str, passed: bool, **evidence: Any) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if passed else "FAIL", "evidence": evidence}


def _status(checks: list[dict[str, Any]]) -> str:
    return aggregate_checks([Check(c["name"], CheckStatus(c["status"]), "") for c in checks]).value


def _norm(vector: Any) -> float:
    return math.sqrt(math.fsum(float(v) ** 2 for v in vector))


def _sum_vectors(vectors: Any) -> list[float]:
    rows = list(vectors)
    return [math.fsum(row[i] for row in rows) for i in range(3)]


def _cross(a: Any, b: Any) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def _force_vector(load: Any) -> list[float]:
    if load.components is not None:
        return [normalize_quantity(v, "force").magnitude for v in load.components.values()]
    magnitude = normalize_quantity(load.magnitude, "force").magnitude
    return [magnitude * v for v in normalize_direction(load.direction)]


def _reference() -> tuple[dict, dict, dict]:
    spec_path = EXAMPLE / "simulation.yaml"
    properties_path = EXAMPLE / "geometry-properties.json"
    spec, document = load_spec(spec_path)
    geometry = (EXAMPLE / spec.inputs.geometry_file).resolve(strict=True)
    properties = _read_json(properties_path)
    _require(spec.mode.value == "from_geometry" and len(spec.bodies) == 1,
             "The bracket study requires the single-solid geometry mode")
    _require(len(spec.supports) == 1, "Exactly one fixed back-face support is required")
    loads = {kind: [item for item in spec.loads if item.type == kind]
             for kind in ("force", "pressure", "gravity")}
    _require(all(len(items) == 1 for items in loads.values()),
             "The base case requires exactly one force, pressure, and gravity load")
    force, pressure, gravity = (loads[kind][0] for kind in ("force", "pressure", "gravity"))
    _require(math.dist(_force_vector(force), FORCE_N) < 1e-9, "Unexpected base force")
    _require(math.isclose(normalize_quantity(pressure.magnitude, "pressure").magnitude,
                         PRESSURE_PA, rel_tol=1e-12), "Unexpected base pressure")
    _require(normalize_direction(gravity.direction) == (0.0, 0.0, -1.0),
             "Gravity must point along global -Z")
    material = next(item for item in spec.materials if item.name == spec.bodies[0].material)
    _require(material.engineering_data_name == "Structural Steel",
             "The independent weight reference requires Structural Steel (7850 kg/m^3)")
    _require(not spec.validation.cantilever.enabled, "The beam validator is inapplicable here")
    _require(properties["geometry_sha256"] == sha256_file(geometry),
             "Geometry properties do not match the STEP hash")
    volume = float(properties["volume_mm3"])
    _require(math.isfinite(volume) and volume > 0, "Invalid reference volume")
    for key, expected in (("pressure_centroid_mm", [165.0, 35.0, 188.0]),
                          ("force_centroid_mm", [240.0, 0.0, 170.0])):
        _require(len(properties[key]) == 3 and math.dist(properties[key], expected) < 1e-6,
                 "Unexpected reference " + key)
    center = properties["center_of_mass_mm"]
    _require(len(center) == 3 and all(math.isfinite(float(v)) for v in center),
             "Invalid center of mass")
    _require(math.isclose(float(properties["pressure_area_mm2"]), 4200.0, rel_tol=1e-12),
             "Unexpected pressure-pad area")
    document["inputs"]["geometry_file"] = str(geometry)
    provenance = {"geometry_file": str(geometry), "geometry_sha256": sha256_file(geometry),
                  "reference_sha256": sha256_file(properties_path),
                  "source_spec_sha256": sha256_file(spec_path),
                  "pressure_scope": pressure.scope, "force_scope": force.scope,
                  "support_scope": spec.supports[0].scope}
    return document, properties, provenance


def _case_document(base: dict, backend: str, mesh_mm: int, factor: float) -> dict:
    document = copy.deepcopy(base)
    document["mesh"] = {"global_element_size": f"{mesh_mm} mm", "element_order": "quadratic"}
    document["execution"].update(backend=backend, timeout_seconds=TIMEOUT_SECONDS)
    document["output"].update(export_images=True, save_project=True)
    if factor == 0:
        document["loads"] = [load for load in document["loads"] if load["type"] == "gravity"]
    else:
        for load in document["loads"]:
            if load["type"] == "force":
                load.pop("magnitude", None)
                load.pop("direction", None)
                load["components"] = {axis: f"{value * factor:.17g} N"
                                      for axis, value in zip("xyz", FORCE_N, strict=True)}
            elif load["type"] == "pressure":
                load["magnitude"] = f"{PRESSURE_PA * factor:.17g} Pa"
    return document


def _expected_loads(properties: dict, factor: float) -> dict:
    mass = DENSITY_KG_M3 * float(properties["volume_mm3"]) * 1e-9
    forces = [[factor * v for v in FORCE_N],
              [0.0, 0.0, -factor * PRESSURE_PA * properties["pressure_area_mm2"] * 1e-6],
              [0.0, 0.0, -mass * GRAVITY_M_S2]]
    positions = [[float(v) * 1e-3 for v in properties[key]] for key in
                 ("force_centroid_mm", "pressure_centroid_mm", "center_of_mass_mm")]
    return {"density_kg_m3": DENSITY_KG_M3, "mass_kg": mass, "gravity_m_s2": GRAVITY_M_S2,
            "force_and_pressure_factor": factor, "moment_origin_m": [0.0, 0.0, 0.0],
            "component_forces_N": dict(zip(("force", "pressure", "gravity"), forces, strict=True)),
            "application_points_m": positions, "total_force_N": _sum_vectors(forces),
            "total_moment_Nm": _sum_vectors(_cross(r, f) for r, f in zip(positions, forces, strict=True))}


def _nodal_rows(fields: Any, width: int, dimension: str, fallback_unit: str = "") -> dict:
    """Map by entity ID, never by the incidental ordering of two DPF fields."""
    values = {}
    for field in fields:
        _require(str(field.location) == "Nodal", "Expected a nodal DPF field")
        unit = str(field.unit or fallback_unit).strip()
        _require(bool(unit), "Missing DPF field unit")
        scale = normalize_quantity("1 " + unit, dimension).magnitude
        data = field.data.tolist() if hasattr(field.data, "tolist") else list(field.data)
        ids = list(field.scoping.ids)
        _require(len(data) == len(ids), "DPF IDs and field rows are not one-to-one")
        for node_id, row in zip(ids, data, strict=True):
            row = list(row) if isinstance(row, (list, tuple)) else [row]
            _require(len(row) == width, "Unexpected DPF component count")
            converted = [float(v) * scale for v in row]
            _require(all(math.isfinite(v) for v in converted), "Non-finite DPF field")
            _require(int(node_id) not in values, "Duplicate node ID across DPF fields")
            values[int(node_id)] = converted
    _require(bool(values), "Empty DPF field")
    return values


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (position - low) * (ordered[high] - ordered[low])


def _balance(name: str, actual: list, expected: list, tolerance: float, unit: str) -> dict:
    residual = _sum_vectors([actual, expected])
    scale = _norm(expected)
    _require(scale > 0, "A non-zero independent resultant is required for " + name)
    relative = _norm(residual) / scale
    return _check(name, relative <= tolerance, applied=expected, reaction=actual, unit=unit,
                  residual=residual, relative_residual=relative, relative_tolerance=tolerance)


def _solver_input_checks(run: Path) -> list[dict]:
    paths = sorted(run.rglob("ds.dat"))
    _require(bool(paths), "No saved ds.dat is available for material and element verification")
    hashes = {str(path): sha256_file(path) for path in paths}
    _require(len(set(hashes.values())) == 1, "Conflicting solver-input copies exist")
    materials, element_types, lines = {}, {}, []
    mks = False
    for number, line in enumerate(paths[0].read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        parts = [part.strip().upper() for part in line.split("!", 1)[0].split(",")]
        if parts[:2] == ["/UNITS", "MKS"]:
            mks = True
        if len(parts) >= 4 and parts[0] == "MP" and parts[1] in {"DENS", "EX", "NUXY"}:
            materials.setdefault(parts[1], []).append(
                {"material_id": int(parts[2]), "value": float(parts[3].replace("D", "E"))})
            lines.append({"line_number": number, "text": line})
        if len(parts) >= 3 and parts[0] == "ET":
            element_types.setdefault(int(parts[1]), []).append(int(parts[2]))
            lines.append({"line_number": number, "text": line})
    targets = {"DENS": DENSITY_KG_M3, "EX": 200e9, "NUXY": 0.3}
    material_ok = mks and all(materials.get(key) and all(
        item["material_id"] == 1 and math.isclose(item["value"], target, rel_tol=1e-12)
        for item in materials[key]) for key, target in targets.items())
    types_ok = element_types.get(1) == [187] and all(
        values == [154] for type_id, values in element_types.items() if type_id != 1)
    evidence = {"paths_and_sha256": hashes, "source_lines": lines, "unit_system": "MKS" if mks else None}
    return [_check("solver_input_materials", bool(material_ok), actual=materials, expected=targets, **evidence),
            _check("solver_input_element_types", types_ok, actual=element_types,
                   required_solid="ET,1,187 (SOLID187)", permitted_load_surface="SURF154", **evidence)]


def _face_geometry_check(run: Path, properties: dict, provenance: dict) -> dict:
    selections = json.loads((run / "face-selection-report.json").read_text(encoding="utf-8"))
    evidence = []
    for role, normal in (("pressure", [0.0, 0.0, 1.0]),
                         ("force", [1.0, 0.0, 0.0]), ("support", [-1.0, 0.0, 0.0])):
        records = [item for item in selections if item["scope_id"] == provenance[role + "_scope"]]
        _require(len(records) == 1 and len(records[0]["matched"]) == 1,
                 "Expected one resolved face for " + role)
        face = records[0]["matched"][0]
        area = normalize_quantity(f"{face['area']} {face['area_unit']}", "area").magnitude
        centroid = [normalize_quantity(f"{v} {face['centroid_unit']}", "length").magnitude
                    for v in face["centroid"]]
        passed = area > 0 and math.dist(face["normal"], normal) <= 1e-8
        if role == "support":
            target_area, target_centroid = None, None
            passed = passed and abs(centroid[0]) <= 1e-9
        else:
            target_area = (properties["pressure_area_mm2"] if role == "pressure"
                           else properties.get("force_area_mm2", 3200.0)) * 1e-6
            target_centroid = [v * 1e-3 for v in properties[role + "_centroid_mm"]]
            passed = (passed and math.isclose(area, target_area, rel_tol=1e-6)
                      and math.dist(centroid, target_centroid) <= 1e-9)
        evidence.append({"role": role, "status": "PASS" if passed else "FAIL",
                         "actual_face": face, "area_m2": area, "centroid_m": centroid,
                         "expected_area_m2": target_area, "expected_centroid_m": target_centroid})
    return _check("selected_face_geometry", all(item["status"] == "PASS" for item in evidence), faces=evidence)


def _extract_numerics(run: Path, spec: Any, provenance: dict, expected: dict, record: dict) -> None:
    # Lazy import keeps offline collection independent of ANSYS and DPF servers.
    from ansys.dpf import core as dpf

    rst = _find_result_file(run)
    before_hash = sha256_file(rst)
    model = dpf.Model(str(rst))
    mesh = model.metadata.meshed_region
    coordinates = _nodal_rows([mesh.nodes.coordinates_field], 3, "length", str(mesh.unit))
    scopes = {}
    for role in ("pressure", "force", "support"):
        name = _resolve_scope(model, _scope_name(spec, provenance[role + "_scope"]))
        scope = model.metadata.named_selection(name)
        _require(str(scope.location) == "Nodal" and len(scope.ids) > 0,
                 "Empty or non-nodal " + role + " selection")
        scopes[role] = scope
    common = {"data_sources": model.metadata.data_sources,
              "time_scoping": [model.metadata.time_freq_support.n_sets],
              "bool_rotate_to_global": True, "server": model._server}
    displacement = _nodal_rows(
        dpf.operators.result.displacement(**common).outputs.fields_container(), 3, "length")
    reactions = _nodal_rows(
        dpf.operators.result.reaction_force(mesh_scoping=scopes["support"], **common)
        .outputs.fields_container(), 3, "force")
    pressure_name = _resolve_scope(model, _scope_name(spec, provenance["pressure_scope"]))
    stress = _nodal_rows(_equivalent_stress(dpf, model, pressure_name), 1, "pressure")
    _require(coordinates.keys() == displacement.keys(),
             "The displacement field does not cover every mesh node")
    support_ids = {int(i) for i in scopes["support"].ids}
    pressure_ids = {int(i) for i in scopes["pressure"].ids}
    _require(reactions.keys() == support_ids and support_ids <= coordinates.keys(),
             "The reaction field does not cover the complete support selection")
    _require(stress.keys() == pressure_ids and pressure_ids <= coordinates.keys(),
             "The stress field does not cover the complete pressure-pad selection")
    ids = sorted(coordinates)
    nodal = {"node_ids": ids, "coordinates_m": [coordinates[i] for i in ids],
             "displacement_m": [displacement[i] for i in ids],
             "support_node_ids": sorted(reactions),
             "reaction_force_N": [reactions[i] for i in sorted(reactions)],
             "pressure_node_ids": sorted(stress),
             "pressure_von_mises_Pa": [stress[i][0] for i in sorted(stress)]}
    nodal_path = run / "nodal-evidence.json"
    _write_json(nodal_path, nodal)
    record["nodal_evidence"] = str(nodal_path)
    record["hashes"].update(rst_sha256=before_hash, nodal_evidence_sha256=sha256_file(nodal_path))
    checks = record["checks"]
    checks.append(_check("rst_preserved", sha256_file(rst) == before_hash, path=str(rst)))
    type_counts = Counter(int(v) for v in mesh.elements.element_types_field.data)
    descriptors = [dpf.element_types.descriptor(kind) for kind in type_counts]
    solids = [item for item in descriptors if item is not None and item.is_solid]
    checks.append(_check("quadratic_solid_mesh", bool(solids) and all(
        item is not None for item in descriptors) and all(item.is_quadratic for item in solids),
        element_types=[{"id": k, "count": v, "name": d.name if d else None}
                       for (k, v), d in zip(type_counts.items(), descriptors, strict=True)]))
    back_nodes = {i for i, xyz in coordinates.items() if abs(xyz[0]) <= 1e-8}
    force_ids = {int(i) for i in scopes["force"].ids}
    scope_ok = (support_ids == back_nodes and force_ids <= coordinates.keys()
                and all(abs(coordinates[i][0] - 0.240) <= 1e-8 for i in force_ids)
                and all(abs(coordinates[i][2] - 0.188) <= 1e-8
                        and 0.130 - 1e-8 <= coordinates[i][0] <= 0.200 + 1e-8
                        and 0.005 - 1e-8 <= coordinates[i][1] <= 0.065 + 1e-8
                        for i in pressure_ids))
    checks.append(_check("physical_scopes", scope_ok, support_nodes=len(support_ids),
                         back_plane_nodes=len(back_nodes), force_nodes=len(force_ids),
                         pressure_nodes=len(pressure_ids)))
    reaction = _sum_vectors(reactions.values())
    moment = _sum_vectors(_cross(coordinates[i], vector) for i, vector in reactions.items())
    checks.extend([_balance("force_balance", reaction, expected["total_force_N"], FORCE_TOLERANCE, "N"),
                   _balance("moment_balance", moment, expected["total_moment_Nm"], MOMENT_TOLERANCE, "N*m")])
    fixed_maximum = max(_norm(displacement[i]) for i in support_ids)
    checks.append(_check("fixed_support_displacement", fixed_maximum <= 1e-12,
                         maximum_m=fixed_maximum, absolute_tolerance_m=1e-12))
    stresses = [row[0] for row in stress.values()]
    metrics = {"node_count": len(coordinates), "element_count": len(mesh.elements),
               "maximum_total_displacement_m": max(_norm(row) for row in displacement.values()),
               "pad_mean_uz_m": math.fsum(displacement[i][2] for i in pressure_ids) / len(pressure_ids),
               "pad_mean_von_mises_Pa": math.fsum(stresses) / len(stresses),
               "pad_p95_von_mises_Pa": _percentile(stresses, 0.95),
               "pad_node_count": len(stresses)}
    record["metrics"] = metrics
    summary = _read_json(run / "results-summary.json")
    globals_ = [summary["results"][r.id]["canonical_maximum"] for r in spec.requested_results
                if r.type.value == "total_deformation" and r.scope is None]
    checks.append(_check("independent_displacement_readback", bool(globals_) and all(
        math.isclose(float(value), metrics["maximum_total_displacement_m"], rel_tol=1e-8, abs_tol=1e-12)
        for value in globals_), independent_m=metrics["maximum_total_displacement_m"],
        compiler_m=globals_))
    checks.append(_check("mesh_counts", metrics["node_count"] == summary["node_count"] > 0
                         and metrics["element_count"] == summary["element_count"] > 0, **metrics))
    peaks = {r.id: summary["results"][r.id] for r in spec.requested_results
             if r.type.value == "equivalent_von_mises_stress" and r.scope is None}
    checks.append({"name": "global_stress_peak_review", "status": "WARN",
                   "evidence": {"global_peaks": peaks,
                                "reason": "Global peaks are reported only; no convergence or strength claim"}})


def _png_evidence(run: Path) -> dict:
    from PIL import Image

    metadata = _read_json(run / "mechanical-artifacts.json")
    items = []
    for name in IMAGE_NAMES:
        path = run / name
        matches = [item for item in metadata.get("visual_review", []) if item.get("name") == name]
        item: dict[str, Any] = {"name": name, "status": "FAIL", "export_records": matches}
        if path.is_file():
            data = path.read_bytes()
            header = (len(data) > 33 and data[:8] == b"\x89PNG\r\n\x1a\n"
                      and data[8:16] == b"\x00\x00\x00\x0dIHDR")
            width, height = struct.unpack(">II", data[16:24]) if header else (0, 0)
            item.update(bytes=len(data), width=width, height=height, sha256=sha256_file(path))
            if header and width > 0 and height > 0:
                try:
                    with Image.open(BytesIO(data), formats=("PNG",)) as image:
                        image.verify()
                    # verify checks the file structure; load also decompresses its pixels.
                    with Image.open(BytesIO(data), formats=("PNG",)) as image:
                        image.load()
                    item["fully_decoded"] = True
                    if len(matches) == 1 and matches[0]["status"] == "PASS":
                        item["status"] = "PASS"
                except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
                    item["fully_decoded"] = False
                    item["decode_error"] = str(exc)
        items.append(item)
    return _check("png_exports", all(item["status"] == "PASS" for item in items),
                  items=items, visual_review="NOT_RUN")


def _extract_in_worker(run: Path, spec_path: Path, provenance: dict, expected: dict) -> dict:
    # DPF's in-process server changes PYTHONPATH on this Windows host.
    # Keep its native runtime and environment out of pytest and later CLI launches.
    request = run / "dpf-extraction-request.json"
    result = run / "dpf-extraction-result.json"
    _write_json(request, {"spec_path": str(spec_path), "provenance": provenance,
                          "expected": expected})
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--extract", str(request)],
            cwd=ROOT, capture_output=True, check=False, timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        (run / "dpf-stdout.log").write_bytes(exc.stdout or b"")
        (run / "dpf-stderr.log").write_bytes(exc.stderr or b"")
        raise ValueError("Independent DPF worker timed out; CLI solve logs were preserved") from exc
    (run / "dpf-stdout.log").write_bytes(completed.stdout)
    (run / "dpf-stderr.log").write_bytes(completed.stderr)
    _require(completed.returncode == 0 and result.is_file(),
             "Independent DPF worker failed; inspect dpf-stderr.log")
    return _read_json(result)


def _run_case(study_dir: Path, case: tuple, base: dict, backend: str, properties: dict, provenance: dict) -> dict:
    case_id, mesh_mm, factor = case
    directory = study_dir / case_id
    directory.mkdir()
    run = directory / "run"
    expected = _expected_loads(properties, factor)
    record: dict[str, Any] = {"id": case_id, "mesh_mm": mesh_mm, "force_and_pressure_factor": factor,
                              "run_directory": str(run), "expected": expected, "checks": [],
                              "hashes": {}, "provenance": provenance}
    spec_path = directory / "simulation.yaml"
    document = _case_document(base, backend, mesh_mm, factor)
    spec_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    try:
        _require(os.getenv("ANSYS_AVAILABLE") == "1" and os.getenv("ANSYS_TEST_BACKEND") == backend
                 and backend in REAL_BACKENDS, "Real-execution opt-in changed during the study")
        _require(not run.exists(), "Every real solve requires a fresh run directory")
        completed = subprocess.run(
            [sys.executable, "-m", "ansys_skill.cli", "run", str(spec_path),
             "--out", str(run), "--execute", "--json"],
            cwd=ROOT, capture_output=True, check=False, timeout=TIMEOUT_SECONDS + 120,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        (directory / "cli-stdout.log").write_bytes(completed.stdout)
        (directory / "cli-stderr.log").write_bytes(completed.stderr)
        record["exit_code"] = completed.returncode
        payload = json.loads(completed.stdout.decode("utf-8", errors="replace"))
        record["cli"] = payload
        summary = _read_json(run / "results-summary.json")
        manifest = _read_json(run / "run-manifest.json")
        record["checks"].append(_check("real_solve", completed.returncode == 0
            and payload.get("status") == manifest.get("status") == "SOLVED"
            and all(item.get("synthetic") is False for item in (payload, summary, manifest))
            and manifest.get("execution_mode") == backend, exit_code=completed.returncode,
            cli_status=payload.get("status"), manifest_status=manifest.get("status"), backend=backend))
        verification = _read_json(run / "verification.json")
        verified = {item["name"]: item["status"] for item in verification["checks"]}
        mandatory = ("requested_results", "small_deformation", "mechanical_messages", "scope_resolution")
        record["checks"].append(_check("compiler_verification", verification["status"] != "FAIL"
            and all(verified.get(name) == "PASS" for name in mandatory), checks=verified))
        record["checks"].extend(_solver_input_checks(run))
        record["checks"].append(_face_geometry_check(run, properties, provenance))
        numeric = _extract_in_worker(run, spec_path, provenance, expected)
        record["checks"].extend(numeric.pop("checks"))
        record["hashes"].update(numeric.pop("hashes"))
        record.update(numeric)
    except subprocess.TimeoutExpired as exc:
        for name, data in (("cli-stdout.log", exc.stdout), ("cli-stderr.log", exc.stderr)):
            (directory / name).write_bytes(data or b"")
        record["stop_study"] = True
        record["checks"].append(_check("execution_timeout", False, error=str(exc)))
    except Exception as exc:
        record["checks"].append(_check("case_processing", False, error=str(exc), traceback=traceback.format_exc()))
    try:
        record["checks"].append(_png_evidence(run))
        required_files = ("results-summary.json", "verification.json", "run-manifest.json",
                          "mechanical-artifacts.json", "face-selection-report.json",
                          "normalized-simulation.yaml", "generated-mechanical.py",
                          "report.md", "text-to-ansys.mechdb")
        hashes = {name: sha256_file(run / name) for name in required_files}
        record["hashes"].update(hashes)
        geometry = Path(provenance["geometry_file"])
        preserved = (sha256_file(geometry) == sha256_file(run / "inputs" / geometry.name)
                     == provenance["geometry_sha256"]
                     and sha256_file(EXAMPLE / "geometry-properties.json") == provenance["reference_sha256"]
                     and sha256_file(EXAMPLE / "simulation.yaml") == provenance["source_spec_sha256"])
        record["checks"].append(_check("artifact_hashes", preserved, hashes=hashes, inputs_preserved=preserved))
    except Exception as exc:
        record["checks"].append(_check("artifact_capture", False, error=str(exc)))
    record["status"] = _status(record["checks"])
    _write_json(run / "engineering-checks.json", record)
    return record


def _convergence(runs: list[dict]) -> dict:
    checks = []
    result: dict[str, Any] = {"checks": checks, "series": {},
        "criterion": "Both 12-to-8 and 8-to-5 mm relative changes must meet the fixed tolerance",
        "stress_statistic": "Arithmetic nodal mean and linearly interpolated nodal p95 on the pressure pad; not area-weighted",
        "global_peak": "WARN: excluded from convergence acceptance"}
    try:
        mixed = [{r["id"]: r for r in runs}[name] for name, _, _ in CASES[:3]]
        metrics = [r["metrics"] for r in mixed]
        checks.append(_check("mesh_refinement", all(
            a[key] < b[key] for a, b in pairwise(metrics)
            for key in ("node_count", "element_count")),
            mesh_mm=[12, 8, 5], node_counts=[m["node_count"] for m in metrics],
            element_counts=[m["element_count"] for m in metrics]))
        for name, tolerance in (("maximum_total_displacement_m", DISPLACEMENT_TOLERANCE),
                                ("pad_mean_uz_m", DISPLACEMENT_TOLERANCE),
                                ("pad_mean_von_mises_Pa", STRESS_TOLERANCE),
                                ("pad_p95_von_mises_Pa", STRESS_TOLERANCE)):
            values = [m[name] for m in metrics]
            changes = [abs(b - a) / max(abs(b), 1e-30) for a, b in pairwise(values)]
            evidence = {"values": values, "relative_changes": changes, "relative_tolerance": tolerance}
            result["series"][name] = evidence
            checks.append(_check(name, all(v <= tolerance for v in changes), **evidence))
    except Exception as exc:
        checks.append(_check("convergence_evidence", False, error=str(exc)))
    result["status"] = _status(checks)
    return result


def _linearity(runs: list[dict]) -> dict:
    checks = []
    result: dict[str, Any] = {"checks": checks, "relationship": "u2 = 2*u1 - ug",
                              "relative_tolerance": LINEARITY_RELATIVE_TOLERANCE,
                              "absolute_tolerance_m": LINEARITY_ABSOLUTE_TOLERANCE_M}
    try:
        by_id = {r["id"]: r for r in runs}
        records = [by_id[name] for name in ("mixed_5mm", "gravity_5mm", "double_mechanical_5mm")]
        data = [_read_json(Path(r["nodal_evidence"])) for r in records]
        ids_equal = data[0]["node_ids"] == data[1]["node_ids"] == data[2]["node_ids"]
        checks.append(_check("identical_node_ids", ids_equal,
                             node_counts=[len(d["node_ids"]) for d in data]))
        if not ids_equal:
            result["status"] = "FAIL"
            result["checks"].append({"name": "full_field_linearity", "status": "NOT_RUN",
                                        "evidence": {"reason": "Node IDs differ; no remapping or interpolation is allowed"}})
            return result
        distances = [math.dist(a, b) for other in data[1:]
                     for a, b in zip(data[0]["coordinates_m"], other["coordinates_m"], strict=True)]
        maximum_distance = max(distances)
        aligned = maximum_distance <= COORDINATE_TOLERANCE_M
        checks.append(_check("identical_coordinates", aligned, maximum_difference_m=maximum_distance,
                             absolute_tolerance_m=COORDINATE_TOLERANCE_M))
        if not aligned:
            result["status"] = "FAIL"
            checks.append({"name": "full_field_linearity", "status": "NOT_RUN",
                           "evidence": {"reason": "Node coordinates differ; no field comparison performed"}})
            return result
        failures, squared_error, squared_reference = 0, [], []
        worst = {"error_m": -1.0}
        for node_id, u1, ug, u2 in zip(data[0]["node_ids"],
                *(d["displacement_m"] for d in data), strict=True):
            predicted = [2 * a - g for a, g in zip(u1, ug, strict=True)]
            error = math.dist(u2, predicted)
            reference = _norm(predicted)
            tolerance = LINEARITY_ABSOLUTE_TOLERANCE_M + LINEARITY_RELATIVE_TOLERANCE * reference
            failures += error > tolerance
            squared_error.append(error**2)
            squared_reference.append(reference**2)
            if error > worst["error_m"]:
                worst = {"node_id": node_id, "error_m": error, "tolerance_m": tolerance,
                         "actual_m": u2, "expected_m": predicted}
        reference_norm = math.sqrt(math.fsum(squared_reference))
        _require(reference_norm > 0, "A zero displacement field cannot validate this loaded bracket")
        checks.append(_check("full_field_linearity", failures == 0, failing_nodes=failures,
            compared_nodes=len(data[0]["node_ids"]), worst_node=worst,
            relative_l2_error=math.sqrt(math.fsum(squared_error)) / reference_norm))
    except Exception as exc:
        checks.append(_check("linearity_evidence", False, error=str(exc)))
    result["status"] = _status(checks)
    return result


@pytest.fixture(scope="module")
def bracket_study(tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest) -> dict:
    if os.getenv("ANSYS_AVAILABLE") != "1":
        pytest.skip("NOT_RUN: real bracket study requires ANSYS_AVAILABLE=1")
    directory = tmp_path_factory.mktemp("engineering-bracket")
    study: dict[str, Any] = {"status": "NOT_RUN", "checks": [], "runs": [],
                             "convergence": {"status": "NOT_RUN"}, "linearity": {"status": "NOT_RUN"},
                             "study_directory": str(directory)}
    summary_path = directory / "study-summary.json"
    _write_json(summary_path, study)
    try:
        _require(not hasattr(request.config, "workerinput") and not os.getenv("PYTEST_XDIST_WORKER"),
                 "Real ANSYS solves must run serially; disable pytest-xdist with -n 0")
        backend = os.getenv("ANSYS_TEST_BACKEND")
        _require(backend in REAL_BACKENDS, "Set ANSYS_TEST_BACKEND explicitly to a real backend")
        base, properties, provenance = _reference()
        study.update(backend=backend, geometry_properties=properties, provenance=provenance)
        study["checks"].append(_check("study_setup", True, backend=backend))
        for case in CASES:
            run = _run_case(directory, case, base, backend, properties, provenance)
            study["runs"].append(run)
            study["checks"].append({"name": run["id"], "status": run["status"]})
            study["status"] = _status(study["checks"])
            _write_json(summary_path, study)
            if run.get("stop_study"):
                break
        study["convergence"] = _convergence(study["runs"])
        study["linearity"] = _linearity(study["runs"])
        study["checks"].extend([_check("five_serial_runs", len(study["runs"]) == 5),
                                  {"name": "convergence", "status": study["convergence"]["status"]},
                                  {"name": "linearity", "status": study["linearity"]["status"]}])
    except Exception as exc:
        study["checks"].append(_check("study_setup", False, error=str(exc), traceback=traceback.format_exc()))
    study["status"] = _status(study["checks"])
    _write_json(summary_path, study)
    return study


def _assert_pass(checks: list[dict], names: tuple[str, ...], evidence_path: Path) -> None:
    statuses = {item["name"]: item["status"] for item in checks}
    failed = {name: statuses.get(name, "MISSING") for name in names if statuses.get(name) != "PASS"}
    assert not failed, f"{failed}; inspect {evidence_path}"


def _assert_study_ready(study: dict) -> None:
    _assert_pass(study["checks"], ("study_setup", "five_serial_runs"),
                 Path(study["study_directory"]) / "study-summary.json")


def test_real_bracket_solver_and_model_contract(bracket_study: dict) -> None:
    _assert_study_ready(bracket_study)
    for run in bracket_study["runs"]:
        _assert_pass(run["checks"], ("real_solve", "compiler_verification", "quadratic_solid_mesh",
            "solver_input_materials", "solver_input_element_types",
            "selected_face_geometry", "physical_scopes", "fixed_support_displacement", "mesh_counts",
            "independent_displacement_readback"), Path(run["run_directory"]) / "engineering-checks.json")


def test_real_bracket_force_and_moment_balance(bracket_study: dict) -> None:
    _assert_study_ready(bracket_study)
    for run in bracket_study["runs"]:
        _assert_pass(run["checks"], ("force_balance", "moment_balance"),
                     Path(run["run_directory"]) / "engineering-checks.json")


def test_real_bracket_mesh_convergence(bracket_study: dict) -> None:
    _assert_study_ready(bracket_study)
    _assert_pass(bracket_study["convergence"]["checks"], ("mesh_refinement",
        "maximum_total_displacement_m", "pad_mean_uz_m", "pad_mean_von_mises_Pa", "pad_p95_von_mises_Pa"),
        Path(bracket_study["study_directory"]) / "study-summary.json")


def test_real_bracket_gravity_corrected_linearity(bracket_study: dict) -> None:
    _assert_study_ready(bracket_study)
    _assert_pass(bracket_study["linearity"]["checks"],
                 ("identical_node_ids", "identical_coordinates", "full_field_linearity"),
                 Path(bracket_study["study_directory"]) / "study-summary.json")


def test_real_bracket_images_and_provenance(bracket_study: dict) -> None:
    _assert_study_ready(bracket_study)
    for run in bracket_study["runs"]:
        _assert_pass(run["checks"], ("png_exports", "artifact_hashes", "rst_preserved"),
                     Path(run["run_directory"]) / "engineering-checks.json")


if __name__ == "__main__":
    _require(os.getenv("ANSYS_AVAILABLE") == "1", "DPF worker requires ANSYS_AVAILABLE=1")
    _require(len(sys.argv) == 3 and sys.argv[1] == "--extract", "Expected --extract <request.json>")
    request_path = Path(sys.argv[2]).resolve(strict=True)
    request = _read_json(request_path)
    spec, _ = load_spec(Path(request["spec_path"]))
    numeric_record: dict[str, Any] = {"checks": [], "hashes": {}}
    try:
        _extract_numerics(request_path.parent, spec, request["provenance"],
                          request["expected"], numeric_record)
    except Exception as exc:
        numeric_record["checks"].append(_check("numeric_extraction", False,
                                               error=str(exc), traceback=traceback.format_exc()))
    _write_json(request_path.with_name("dpf-extraction-result.json"), numeric_record)
