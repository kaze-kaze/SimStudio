"""Check public source-package contents and reject private solver artifacts."""
from __future__ import annotations

import argparse
import json
import stat
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

PUBLIC_ROOT = "docs/reports/evidence/2026-09-06/"
EXAMPLE = "examples/gusseted-bracket/"
DEMO = EXAMPLE + "demo/"
REQUIRED = {
    "LICENSE", "NOTICE", "README.md", "README.zh-CN.md", "CHANGELOG.md",
    "docs/site/index.html", "docs/site/site.css", "docs/site/report.html",
    "docs/assets/overview.png", "tools/build_site.py",
    "tools/export_benchmark_evidence.py",
    "tools/check_distribution.py", "docs/reports/mechanical-test-2026-09-06.md",
    "docs/reports/mechanical-test-2026-09-06.zh-CN.md",
    *(EXAMPLE + name for name in (
        "README.md", "simulation.yaml", "simulation_brief.md", "gusseted-bracket.step",
        "geometry-properties.json", "generate_geometry.py", "export_views.py",
    )),
    *("tests/fixtures/cantilever/" + name for name in (
        "README.md", "simulation.yaml", "simulation_brief.md", "cantilever.step",
        "expected.json", "generate_geometry.py",
    )),
    *(PUBLIC_ROOT + name for name in ("summary.json", "cases.json", "provenance.json")),
    *(DEMO + name for name in ("index.html", "style.css", "demo.js", "evidence.js", "README.md")),
    *(DEMO + "assets/" + name for name in (
        "geometry.png", "underside.png", "mesh.png", "total-deformation.png", "equivalent-stress.png",
    )),
}
PRIVATE_DIRECTORIES = {
    "test-records", "build", "solver", ".venv", "__pycache__", ".git",
    ".pytest_cache", ".ruff_cache",
}
PRIVATE_SUFFIXES = {
    ".mechdb", ".mechdat", ".rst", ".rth", ".rdb", ".db", ".cdb", ".dat",
    ".out", ".err", ".full", ".emat", ".esav", ".mode", ".mntr", ".dsdb",
    ".wbpj", ".wbpz", ".exe", ".dll", ".pyc", ".pyo", ".zip", ".gz", ".tar", ".7z", ".log",
}


def _unsafe_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        not path.parts or path.is_absolute() or ".." in path.parts
        or "\\" in name or ":" in name
        or any(ord(character) < 32 for character in name)
        or any(part != part.rstrip(" .") for part in path.parts)
        or bool({part.casefold() for part in path.parts} & PRIVATE_DIRECTORIES)
        or path.suffix.lower() in PRIVATE_SUFFIXES
        or path.name.lower().startswith(("ansyscl.", "licdebug."))
        or path.name.casefold() in {"junit.xml", "release-preparation.md"}
        or path.name.casefold().startswith("windows-acceptance-")
    )


def _members(path: Path) -> list[tuple[str, bool, bool]]:
    """Read names and types without extracting files or following archive links."""
    if path.suffix.lower() in {".whl", ".zip"}:
        with zipfile.ZipFile(path) as archive:
            entries = []
            for member in archive.infolist():
                mode = stat.S_IFMT(member.external_attr >> 16)
                directory = member.is_dir()
                regular = not directory and mode in {0, stat.S_IFREG}
                entries.append((member.orig_filename, regular, directory and mode in {0, stat.S_IFDIR}))
            return entries
    with tarfile.open(path) as archive:
        return [(member.name, member.isfile(), member.isdir()) for member in archive.getmembers()]


def inspect(path: Path) -> dict:
    kind = "wheel" if path.suffix.lower() == ".whl" else (
        "source_zip" if path.suffix.lower() == ".zip" else "sdist"
    )
    names = []
    forbidden = []
    roots = set()
    seen = set()
    for raw_name, regular, directory in _members(path):
        # Validate the complete member name before removing the source-package root.
        if _unsafe_path(raw_name) or not (regular or directory):
            forbidden.append(raw_name)
            continue
        parts = PurePosixPath(raw_name).parts
        if kind != "wheel":
            roots.add(parts[0])
            if len(roots) > 1 or (regular and len(parts) < 2):
                forbidden.append(raw_name)
                continue
            parts = parts[1:]
        if directory:
            continue
        name = PurePosixPath(*parts).as_posix()
        if name.casefold() in seen:
            forbidden.append(raw_name)
        seen.add(name.casefold())
        names.append(name)
        if kind == "wheel" and not (
            (parts[0] == "ansys_skill" and PurePosixPath(name).suffix == ".py")
            or parts[0].endswith(".dist-info")
        ):
            forbidden.append(raw_name)
    missing = sorted(({"ansys_skill/cli.py"} if kind == "wheel" else REQUIRED) - set(names))
    if missing or forbidden:
        raise ValueError(json.dumps({"missing": missing, "forbidden": forbidden}))
    return {"file": path.name, "kind": kind, "files": len(names), "status": "PASS",
            "scope": "CLI only" if kind == "wheel" else "source, reports, public evidence, static demo, site sources"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    paths = sorted([*args.directory.glob("*.whl"), *args.directory.glob("*.tar.gz"),
                    *args.directory.glob("*.zip")])
    if not paths:
        parser.error("No wheel, sdist, or source ZIP found")
    try:
        print(json.dumps({"status": "PASS", "artifacts": [inspect(p) for p in paths]}))
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
