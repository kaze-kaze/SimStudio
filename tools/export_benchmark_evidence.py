"""Export and check saved engineering bracket evidence without launching ANSYS."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path("docs/reports/evidence/2026-09-06")
DEMO = Path("examples/gusseted-bracket/demo")
STUDY = Path("bracket-study-20260906-02/engineering-bracket0")
RECORDS = Path("engineering-bracket-20260906-01")
CASES = ("mixed_12mm", "mixed_8mm", "mixed_5mm", "gravity_5mm", "double_mechanical_5mm")
PRIMARY = "mixed_5mm"
IMAGE_NAMES = ("geometry.png", "underside.png", "mesh.png", "total-deformation.png", "equivalent-stress.png")
RESULT_FIELDS = ("canonical_maximum", "canonical_unit", "reported_maximum", "reported_unit",
                 "canonical_sum_vector", "canonical_sum_vector_unit", "location", "value_count")
RESULT_NAMES = {"total_deformation", "equivalent_stress", "mounting_reaction", "pad_z", "front_y", "pad_stress"}
HASH_FIELDS = {"generated_script_sha256", "input_sha256", "normalized_spec_sha256", "source_spec_sha256"}
NUMERIC_EVIDENCE = {
    "force_balance": ("applied", "reaction", "unit", "residual", "relative_residual", "relative_tolerance"),
    "moment_balance": ("applied", "reaction", "unit", "residual", "relative_residual", "relative_tolerance"),
    "fixed_support_displacement": ("maximum_m", "absolute_tolerance_m"),
    "small_deformation": ("ratio",),
}
METRICS = ("node_count", "element_count", "maximum_total_displacement_m", "pad_mean_uz_m",
           "pad_mean_von_mises_Pa", "pad_p95_von_mises_Pa", "pad_node_count")
PRIVATE_PATTERNS = (r"[A-Za-z]:[\\/]", r"/(?:Users|home|tmp|private)/", r"DESKTOP-[A-Za-z0-9]+",
                    r"(?i)ansyscl\.[^\s]+", r"(?i)licdebug\.[^\s]+", r"(?i)Bearer\s+[A-Za-z0-9_.-]{12,}",
                    r"AKIA[A-Z0-9]{16}", r"sk-[A-Za-z0-9_-]{24,}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def safe_text(text: str) -> None:
    if any(re.search(pattern, text) for pattern in PRIVATE_PATTERNS):
        raise ValueError("Private path or credential-like content in public evidence")


def write_json(path: Path, value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    safe_text(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def public_checks(checks: list[dict]) -> list[dict]:
    result = []
    for check in checks:
        item = {"name": check["name"], "status": check["status"]}
        if check["name"] in NUMERIC_EVIDENCE:
            evidence = check.get("evidence", {})
            item["evidence"] = {key: evidence[key] for key in NUMERIC_EVIDENCE[check["name"]] if key in evidence}
        result.append(item)
    return result


def public_case(case_id: str, summary: dict, verification: dict, manifest: dict, engineering: dict | None = None) -> dict:
    if summary.get("synthetic") is not False or manifest.get("synthetic") is not False:
        raise ValueError("A public real benchmark must not contain synthetic or unknown results")
    if manifest.get("status") != "SOLVED" or manifest.get("execution_mode") != "mechanical_batch":
        raise ValueError("This evidence export requires the observed solved batch run")
    if verification.get("status") != "WARN":
        raise ValueError("Preserve the recorded engineering WARN")
    item = {
        "id": case_id, "synthetic": False, "execution_mode": manifest["execution_mode"],
        "solver_status": manifest["status"], "verification_status": verification["status"],
        "started_at": manifest["started_at"], "ended_at": manifest["ended_at"],
        "node_count": summary["node_count"], "element_count": summary["element_count"],
        "results": {key: {field: value[field] for field in RESULT_FIELDS if field in value}
                    for key, value in summary["results"].items() if key in RESULT_NAMES},
        "checks": public_checks(verification["checks"]),
        "hashes": {key: value for key, value in manifest["hashes"].items() if key in HASH_FIELDS},
    }
    if engineering is not None:
        if engineering["id"] != case_id or any(c["status"] == "FAIL" for c in engineering["checks"]):
            raise ValueError("Failed or mismatched engineering evidence")
        item.update(mesh_mm=engineering["mesh_mm"],
                    force_and_pressure_factor=engineering["force_and_pressure_factor"],
                    metrics={key: engineering["metrics"][key] for key in METRICS},
                    engineering_checks=public_checks(engineering["checks"]))
    return item


def public_junit(source: Path) -> tuple[dict, list[dict]]:
    suite = ET.parse(source).getroot().find("testsuite")
    if suite is None:
        raise ValueError("Missing JUnit testsuite")
    metrics = {key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")}
    cases = []
    for case in suite.findall("testcase"):
        if any(case.find(key) is not None for key in ("failure", "error", "skipped")):
            raise ValueError("An unpassed case cannot be published as the passing baseline")
        cases.append({"classname": case.attrib["classname"], "name": case.attrib["name"],
                      "duration_seconds": float(case.attrib["time"]), "status": "PASS"})
    if metrics != {"tests": 5, "failures": 0, "errors": 0, "skipped": 0} or len(cases) != 5:
        raise ValueError("JUnit does not describe the five-case bracket study")
    metrics.update(duration_seconds=float(suite.attrib["time"]), started_at=suite.attrib["timestamp"])
    return metrics, cases


def public_study(study: dict) -> tuple[dict, dict]:
    if (study["status"] != "WARN" or study["convergence"]["status"] != "PASS"
            or study["linearity"]["status"] != "PASS"):
        raise ValueError("The bracket study has not passed its numerical checks")
    convergence = {"status": "PASS", "series": {
        name: {key: study["convergence"]["series"][name][key]
               for key in ("values", "relative_changes", "relative_tolerance")}
        for name in METRICS[2:6]}, "stress_weighting": "equal nodal weights; not area-weighted"}
    linear = study["linearity"]
    checks = {item["name"]: item for item in linear["checks"]}
    if any(item["status"] != "PASS" for item in checks.values()):
        raise ValueError("Incomplete linearity evidence")
    field = checks["full_field_linearity"]["evidence"]
    linearity = {"status": "PASS", "relationship": linear["relationship"],
                 "relative_tolerance": linear["relative_tolerance"],
                 "absolute_tolerance_m": linear["absolute_tolerance_m"],
                 "compared_nodes": field["compared_nodes"], "failing_nodes": field["failing_nodes"],
                 "relative_l2_error": field["relative_l2_error"],
                 "maximum_absolute_error_m": field["worst_node"]["error_m"],
                 "maximum_coordinate_difference_m": checks["identical_coordinates"]["evidence"]["maximum_difference_m"]}
    return convergence, linearity


def export(archive: Path, target: Path) -> None:
    study_path = archive / STUDY / "study-summary.json"
    study = read_json(study_path)
    if tuple(run["id"] for run in study["runs"]) != CASES:
        raise ValueError("Unexpected bracket run inventory")
    convergence, linearity = public_study(study)
    out, assets = target / EVIDENCE, target / DEMO / "assets"
    sources = []

    def record(path: Path) -> None:
        sources.append({"source_artifact": path.relative_to(archive).as_posix(), "sha256": sha256(path)})

    record(study_path)
    cases = []
    for entry in study["runs"]:
        run = archive / STUDY / entry["id"] / "run"
        paths = [run / name for name in ("results-summary.json", "verification.json", "run-manifest.json")]
        for path in paths:
            if sha256(path) != entry["hashes"][path.name]:
                raise ValueError("Recorded source artifact hash mismatch")
            record(path)
        cases.append(public_case(entry["id"], *(read_json(path) for path in paths), entry))
    suite_path = archive / RECORDS / "engineering-02-junit.xml"
    suite, tests = public_junit(suite_path)
    record(suite_path)
    offline = archive / RECORDS / "offline-final-pytest.stdout.log"
    match = re.search(r"(\d+) passed, (\d+) skipped in ([0-9.]+)s", offline.read_text(encoding="utf-8-sig"))
    if match is None:
        raise ValueError("Missing recorded offline-suite totals")
    record(offline)
    recheck_path = archive / RECORDS / "png-decode-verification.json"
    recheck = read_json(recheck_path)
    if (recheck["status"] != "PASS" or recheck["image_count"] != 15
            or recheck["source_summary_sha256"] != sha256(study_path)):
        raise ValueError("Missing complete image-decoding verification")
    record(recheck_path)
    properties = study["geometry_properties"]
    geometry = target / "examples/gusseted-bracket/gusseted-bracket.step"
    if sha256(geometry) != properties["geometry_sha256"]:
        raise ValueError("Public geometry differs from the recorded source")
    document = {
        "schema_version": 1, "recorded_on": "2026-09-06", "synthetic": False,
        "evidence_kind": "saved_real_bracket_study; not a new solve or a live service",
        "primary_case": PRIMARY,
        "environment": {"os": "Windows 11 AMD64", "mechanical": "ANSYS Student 2026 R1",
                        "python": "3.13.2", "pymechanical": "0.13.2", "pydpf": "0.16.1",
                        "dpf_server": "11.0 InProcessServer", "source": "docs/reports/mechanical-test-2026-09-06.md"},
        "suite": suite,
        "offline_baseline": {"passed": int(match[1]), "skipped": int(match[2]),
                             "duration_seconds": float(match[3]), "kind": "recorded before primary-example migration"},
        "fixture": {"dimensions_mm": properties["bounding_box_mm"], "force_N": [1000, 1500, -500],
                    "pressure_MPa": 0.8, "pressure_area_mm2": properties["pressure_area_mm2"],
                    "mass_kg": properties["volume_mm3"] * 1e-9 * 7850, "gravity_m_s2": 9.80665,
                    "material": "Structural Steel", "youngs_modulus_GPa": 200, "density_kg_m3": 7850,
                    "poissons_ratio": 0.3, "mesh_sizes_mm": [12, 8, 5], "element_order": "quadratic",
                    "mounting_hole_count": 8, "fixed_face": "X-min", "source": "examples/gusseted-bracket/simulation.yaml",
                    "geometry_sha256": properties["geometry_sha256"]},
        "cases": cases, "convergence": convergence, "linearity": linearity,
        "limits": {"stress_singularity_review": "WARN", "mesh_convergence": "PASS",
                   "gravity_corrected_linearity": "PASS", "safety_factor": "NOT_RUN",
                   "automatic_visual_review": "NOT_RUN", "remote_transport_authentication": "NOT_RUN"},
    }
    # Re-exported Z-up images are bound to the exact unchanged, solved fine-mesh project.
    view_process = archive / RECORDS / "fine-view-export-process.json"
    view = read_json(view_process)
    primary = next(entry for entry in study["runs"] if entry["id"] == PRIMARY)
    if (view["returncode"] != 0 or view["project_hash_before"] != view["project_hash_after"]
            or view["project_hash_before"] != primary["hashes"]["text-to-ansys.mechdb"]):
        raise ValueError("View exports are not bound to the unchanged fine-mesh project")
    record(view_process)
    from PIL import Image
    assets.mkdir(parents=True, exist_ok=True)
    for name in IMAGE_NAMES:
        source = archive / RECORDS / "fine-views" / name
        with Image.open(source, formats=("PNG",)) as image:
            image.verify()
        with Image.open(source, formats=("PNG",)) as image:
            image.load()
        record(source)
        shutil.copyfile(source, assets / name)
    write_json(out / "summary.json", document)
    write_json(out / "cases.json", tests)
    js = "// Generated by tools/export_benchmark_evidence.py; saved real results only.\n"
    js += "window.SIMSTUDIO_BENCHMARK = " + json.dumps(document, ensure_ascii=False, allow_nan=False) + ";\n"
    safe_text(js)
    (target / DEMO / "evidence.js").write_text(js, encoding="utf-8", newline="\n")
    published = [out / name for name in ("summary.json", "cases.json")]
    published += [assets / name for name in IMAGE_NAMES] + [target / DEMO / "evidence.js"]
    write_json(out / "provenance.json", {
        "schema_version": 1, "recorded_on": "2026-09-06", "sources": sources,
        "transformation": "tools/export_benchmark_evidence.py",
        "policy": "Field allowlist; exclude host paths, logs and licensing details. Preserve measured numbers and check states.",
        "images": "Five unmodified PNG exports from the unchanged fine-mesh bracket project. Images used courtesy of ANSYS, Inc.",
        "published_files": [{"path": path.relative_to(target).as_posix(), "sha256": sha256(path)} for path in published],
        "source_archives": "Full solve records remain local and are not redistributed.",
    })


def check(target: Path) -> dict:
    out = target / EVIDENCE
    if any(out.glob("*.log")) or any(out.glob("*.xml")):
        raise ValueError("Raw test logs and JUnit records belong in the local archive")
    provenance = read_json(out / "provenance.json")
    expected = {(EVIDENCE / name).as_posix() for name in ("summary.json", "cases.json")}
    expected |= {(DEMO / "assets" / name).as_posix() for name in IMAGE_NAMES} | {(DEMO / "evidence.js").as_posix()}
    if {item["path"] for item in provenance["published_files"]} != expected:
        raise ValueError("Unexpected public artifact inventory")
    for item in provenance["published_files"]:
        path = (target / item["path"]).resolve()
        if not path.is_relative_to(target.resolve()) or sha256(path) != item["sha256"]:
            raise ValueError("Public artifact hash mismatch")
    for path in [*out.glob("*.json"), target / DEMO / "evidence.js"]:
        safe_text(path.read_text(encoding="utf-8"))
    summary = read_json(out / "summary.json")
    if (summary["synthetic"] is not False or tuple(c["id"] for c in summary["cases"]) != CASES
            or summary["primary_case"] != PRIMARY):
        raise ValueError("Invalid real bracket summary")
    geometry = target / "examples/gusseted-bracket/gusseted-bracket.step"
    if sha256(geometry) != summary["fixture"]["geometry_sha256"]:
        raise ValueError("Public geometry hash mismatch")
    for case in summary["cases"]:
        if (case["synthetic"] is not False or case["verification_status"] != "WARN"
                or case["solver_status"] != "SOLVED" or case["execution_mode"] != "mechanical_batch"
                or any(c["status"] == "FAIL" for c in case["engineering_checks"])):
            raise ValueError("Do not turn the recorded engineering WARN into a PASS")
    if summary["convergence"]["status"] != "PASS" or summary["linearity"]["status"] != "PASS":
        raise ValueError("Missing passing numerical study")
    cases = read_json(out / "cases.json")
    suite = summary["suite"]
    if (len(cases) != 5 or suite["tests"] != len(cases)
            or any(suite[name] != 0 for name in ("failures", "errors", "skipped"))
            or len({case["name"] for case in cases}) != len(cases)
            or any(case["status"] != "PASS" or case["duration_seconds"] < 0 for case in cases)):
        raise ValueError("Public test summary differs from the recorded five-case study")
    return {"status": "PASS", "published_files": len(provenance["published_files"]),
            "real_cases": len(cases), "solves": len(summary["cases"]), "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Local folder containing the recorded study and its process records")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root for export/check")
    args = parser.parse_args()
    try:
        if args.archive is not None:
            export(args.archive.resolve(), args.root.resolve())
        print(json.dumps(check(args.root.resolve())))
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
