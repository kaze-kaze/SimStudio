"""Export a small, field-allowlisted public snapshot of the recorded benchmark.

This tool reads saved evidence only. It cannot start Mechanical or inspect an RST.
"""
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
DEMO = Path("examples/cantilever/demo")
FINAL = "windows-acceptance-final-20260906"
RUNS = {
    "cantilever": "real-cantilever0",
    "pressure": "test_real_pressure0",
    "gravity": "test_real_gravity0",
    "template_mechdat": "test_real_template_synchroniza0",
    "template_mechdb": "test_real_template_synchroniza1",
}
IMAGE_NAMES = ("mesh.png", "total-deformation.png", "equivalent-stress.png")
RESULT_FIELDS = (
    "canonical_maximum", "canonical_unit", "reported_maximum", "reported_unit",
    "canonical_sum_vector", "canonical_sum_vector_unit", "location", "value_count",
)
NUMERIC_EVIDENCE = {
    "reaction_balance": ("relative_residual", "relative_tolerance", "applied_force_N", "reaction_force_N"),
    "cantilever_analytical": ("actual_m", "expected_m", "relative_error", "relative_tolerance"),
    "small_deformation": ("ratio",),
}
PRIVATE_PATTERNS = (
    r"[A-Za-z]:[\\/]", r"/(?:Users|home|tmp|private)/",
    r"DESKTOP-[A-Za-z0-9]+", r"(?i)ansyscl\.[^\s]+",
    r"(?i)licdebug\.[^\s]+", r"(?i)Bearer\s+[A-Za-z0-9_.-]{12,}",
    r"AKIA[A-Z0-9]{16}", r"sk-[A-Za-z0-9_-]{24,}",
)


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
    path.write_text(text, encoding="utf-8")


def public_case(case_id: str, summary: dict, verification: dict, manifest: dict) -> dict:
    if summary.get("synthetic") is not False or manifest.get("synthetic") is not False:
        raise ValueError("A public real benchmark must not contain synthetic or unknown results")
    if manifest.get("status") != "SOLVED" or manifest.get("execution_mode") != "mechanical_batch":
        raise ValueError("This dated evidence export requires the observed solved batch run")
    results = {
        key: {field: value[field] for field in RESULT_FIELDS if field in value}
        for key, value in summary["results"].items()
        if key in {"tip_z", "tip_x", "total_deformation", "equivalent_stress", "fixed_reaction"}
    }
    checks = []
    for check in verification["checks"]:
        item = {"name": check["name"], "status": check["status"]}
        if check["name"] in NUMERIC_EVIDENCE:
            evidence = check.get("evidence", {})
            item["evidence"] = {k: evidence[k] for k in NUMERIC_EVIDENCE[check["name"]] if k in evidence}
        checks.append(item)
    return {
        "id": case_id, "synthetic": False, "execution_mode": manifest["execution_mode"],
        "solver_status": manifest["status"], "verification_status": verification["status"],
        "started_at": manifest["started_at"], "ended_at": manifest["ended_at"],
        "node_count": summary["node_count"], "element_count": summary["element_count"],
        "results": results, "checks": checks, "hashes": manifest["hashes"],
    }


def public_junit(source: Path) -> tuple[ET.Element, dict, list[dict]]:
    original = ET.parse(source).getroot().find("testsuite")
    if original is None:
        raise ValueError("Missing JUnit testsuite")
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", {
        key: original.attrib[key]
        for key in ("name", "tests", "failures", "errors", "skipped", "time", "timestamp")
    })
    cases = []
    for case in original.findall("testcase"):
        attrs = {k: case.attrib[k] for k in ("classname", "name", "time")}
        if any(case.find(k) is not None for k in ("failure", "error", "skipped")):
            raise ValueError("The final suite contains an unpassed case; do not publish it as the passing baseline")
        ET.SubElement(suite, "testcase", attrs)
        cases.append({"classname": attrs["classname"], "name": attrs["name"],
                      "duration_seconds": float(attrs["time"]), "status": "PASS"})
    metrics = {k: int(suite.attrib[k]) for k in ("tests", "failures", "errors", "skipped")}
    if metrics != {"tests": 9, "failures": 0, "errors": 0, "skipped": 0} or len(cases) != 9:
        raise ValueError("Final JUnit count does not match the dated nine-case baseline")
    metrics.update(duration_seconds=float(suite.attrib["time"]), started_at=suite.attrib["timestamp"])
    return root, metrics, cases


def export(archive: Path, target: Path) -> None:
    build = archive / "raw/build"
    out = target / EVIDENCE
    assets = target / DEMO / "assets"
    out.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    sources = []

    def record(path: Path) -> None:
        sources.append({"source_artifact": path.relative_to(build).as_posix(), "sha256": sha256(path)})

    cases = []
    for case_id, directory in RUNS.items():
        run = build / FINAL / directory / "run"
        paths = [run / name for name in ("results-summary.json", "verification.json", "run-manifest.json")]
        cases.append(public_case(case_id, *(read_json(p) for p in paths)))
        for p in paths:
            record(p)
    junit = build / (FINAL + ".xml")
    xml, suite, tests = public_junit(junit)
    record(junit)
    ET.indent(xml)
    xml_text = ET.tostring(xml, encoding="unicode") + "\n"
    safe_text(xml_text)
    (out / "junit.xml").write_text(xml_text, encoding="utf-8")
    log = build / "offline-final.log"
    text = log.read_text(encoding="utf-8")
    safe_text(text)
    match = re.search(r"(\d+) passed, (\d+) skipped in ([0-9.]+)s", text)
    if match is None:
        raise ValueError("Missing recorded offline-suite totals")
    (out / "offline.log").write_bytes(log.read_bytes())
    record(log)
    document = {
        "schema_version": 1, "recorded_on": "2026-09-06", "synthetic": False,
        "evidence_kind": "saved_real_benchmark; not a new solve or a live service",
        "environment": {
            "os": "Windows 11 AMD64", "mechanical": "ANSYS Student 2026 R1",
            "file_version": "26,2026,13,1", "python": "3.13.2",
            "pymechanical": "0.13.2", "pydpf": "0.16.1", "dpf_server": "11.0 InProcessServer",
            "source": "docs/windows-acceptance-2026-09-06.md",
        },
        "suite": suite,
        "offline_baseline": {"passed": int(match[1]), "skipped": int(match[2]), "duration_seconds": float(match[3]),
                             "skip_details": {"real_opt_in": 9, "native_symlink_permission": 2}},
        "fixture": {"dimensions_mm": [200, 20, 40], "force_N": [0, 0, -1000],
                    "material": "Structural Steel", "youngs_modulus_GPa": 200,
                    "second_moment_of_area_mm4": 106666.6666667, "element_size_mm": 10,
                    "element_order": "program_controlled", "fixed_face": "X-min", "load_face": "X-max",
                    "source": "examples/cantilever/simulation.yaml"},
        "cases": cases,
        "limits": {"initial_local_grpc": "FAIL", "remote_transport_authentication": "NOT_RUN",
                   "mesh_convergence": "NOT_RUN", "safety_factor": "NOT_RUN", "automatic_visual_review": "NOT_RUN"},
    }
    write_json(out / "summary.json", document)
    write_json(out / "cases.json", tests)
    for name in IMAGE_NAMES:
        source = build / FINAL / RUNS["cantilever"] / "run" / name
        record(source)
        shutil.copyfile(source, assets / name)
    js = "// Generated by tools/export_benchmark_evidence.py; saved real results only.\n"
    js += "window.SIMSTUDIO_BENCHMARK = " + json.dumps(document, ensure_ascii=False, allow_nan=False) + ";\n"
    (target / DEMO / "evidence.js").write_text(js, encoding="utf-8")
    published = [out / n for n in ("summary.json", "cases.json", "junit.xml", "offline.log")]
    published += [assets / n for n in IMAGE_NAMES] + [target / DEMO / "evidence.js"]
    write_json(out / "provenance.json", {
        "schema_version": 1, "recorded_on": "2026-09-06", "sources": sources,
        "transformation": "tools/export_benchmark_evidence.py",
        "policy": "Field allowlist; remove hostname, absolute paths, free-form logs and process/license details. Preserve numbers and check states.",
        "images": "Three unmodified PNG files from the repository-authored cantilever benchmark. Images used courtesy of ANSYS, Inc.",
        "published_files": [{"path": p.relative_to(target).as_posix(), "sha256": sha256(p)} for p in published],
        "source_archives": "Original full records are retained locally and are not redistributed.",
    })


def check(target: Path) -> dict:
    out = target / EVIDENCE
    provenance = read_json(out / "provenance.json")
    for item in provenance["published_files"]:
        path = (target / item["path"]).resolve()
        if not path.is_relative_to(target.resolve()) or sha256(path) != item["sha256"]:
            raise ValueError("Public artifact hash mismatch")
    for path in [*out.glob("*.json"), *out.glob("*.xml"), *out.glob("*.log"), target / DEMO / "evidence.js"]:
        safe_text(path.read_text(encoding="utf-8"))
    summary = read_json(out / "summary.json")
    if summary["synthetic"] is not False or len(summary["cases"]) != 5:
        raise ValueError("Invalid real benchmark summary")
    for case in summary["cases"]:
        if case["synthetic"] is not False or case["verification_status"] != "WARN":
            raise ValueError("Do not turn the recorded engineering WARN into a PASS")
    _, suite, cases = public_junit(out / "junit.xml")
    if suite != summary["suite"] or cases != read_json(out / "cases.json"):
        raise ValueError("Public JUnit and summary differ")
    return {"status": "PASS", "published_files": len(provenance["published_files"]),
            "real_cases": len(cases), "solves": len(summary["cases"]), "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Local evidence archive to export; never distributed")
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
