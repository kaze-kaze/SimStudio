from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest
from ansys_skill.errors import SpecValidationError
from ansys_skill.study import bundles
from ansys_skill.study.bundles import export_bundle, import_bundle
from ansys_skill.study.project import create_plan, save_project
from ansys_skill.study.storage import read_json
from ansys_skill.study.templates import init_study


@pytest.fixture
def planned_study(tmp_path: Path) -> Path:
    pytest.importorskip("scipy", reason="Study planning requires the optional study dependency")
    source = tmp_path / "specification"
    root = tmp_path / "study"
    init_study(source)
    create_plan(source / "study.yaml", root)
    return root


def _add_prepared_sample(root: Path) -> tuple[dict, dict]:
    manifest = read_json(root / "study-manifest.json")
    sample = manifest["samples"][0]
    sample_dir = root / "samples" / sample["sample_id"]
    sample_dir.mkdir(parents=True)
    geometry = sample_dir / "geometry.step"
    geometry.write_bytes(b"prepared geometry fixture")
    sample["geometry"] = {"geometry_sha256": hashlib.sha256(geometry.read_bytes()).hexdigest()}
    sample["status"] = "GEOMETRY_READY"
    for job in sample["jobs"]:
        relative = f"samples/{sample['sample_id']}/mesh-{job['mesh_index']}.yaml"
        spec = root / relative
        spec.write_text(f"prepared mesh {job['mesh_index']}\n", encoding="utf-8")
        job["specification"] = relative
        job["spec_sha256"] = hashlib.sha256(spec.read_bytes()).hexdigest()
    save_project(root, manifest)
    return manifest, sample


def _bundle_members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as package:
        return {name: package.read(name) for name in package.namelist() if not name.endswith("/")}


def _rewrite_bundle(path: Path, transform) -> None:
    entries = _bundle_members(path)
    transformed = transform(entries)
    with zipfile.ZipFile(path, "w") as package:
        for name, payload in transformed.items():
            package.writestr(name, payload)


def test_real_zip_roundtrip_keeps_prepared_samples_and_raw_result_paths(planned_study, tmp_path):
    root = planned_study
    manifest, sample = _add_prepared_sample(root)

    solved = manifest["samples"][0]["jobs"][0]
    run_relative = f"samples/{sample['sample_id']}/mesh-0/attempt-001/run"
    run_dir = root / run_relative
    run_dir.mkdir(parents=True)
    (run_dir / "quality.json").write_text('{"status":"PASS"}\n', encoding="utf-8")
    (run_dir / "solver.log").write_text(
        "private solver path C:\\Mechanical\\run.log\n", encoding="utf-8"
    )
    raw_run_manifest = json.dumps(
        {"result_files": ["quality.json"], "workdir": "C:\\private\\solver"},
        indent=1,
    )
    (run_dir / "run-manifest.json").write_text(raw_run_manifest, encoding="utf-8")
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in run_dir.iterdir()
    }
    solved["attempts"] = [
        {"attempt": 1, "path": run_relative, "status": "SOLVED", "hashes": hashes}
    ]
    manifest["status"] = "PARTIAL"
    manifest["solver_calls"] = 1
    save_project(root, manifest)

    bundle = tmp_path / "handoff.zip"
    exported = export_bundle(root, bundle, kind="results")
    archive_manifest = json.loads(_bundle_members(bundle)["bundle-manifest.json"])
    assert exported["status"] == "EXPORTED"
    assert archive_manifest["kind"] == "results"
    assert archive_manifest["study_id"] == manifest["study_id"]
    assert set(archive_manifest["files"]) == set(_bundle_members(bundle)) - {"bundle-manifest.json"}

    restored = tmp_path / "restored"
    imported = import_bundle(bundle, restored, expected_study_id=manifest["study_id"])
    assert imported["status"] == "IMPORTED"
    assert imported["study_fingerprint"] == manifest["study_fingerprint"]
    assert (restored / run_relative / "run-manifest.json").read_text(
        encoding="utf-8"
    ) == raw_run_manifest
    assert (restored / run_relative / "solver.log").is_file()
    assert (restored / "samples" / sample["sample_id"] / "geometry.step").is_file()
    restored_manifest = read_json(restored / "study-manifest.json")
    relative_result = restored_manifest["samples"][0]["jobs"][0]["attempts"][0]["path"]
    run_record = json.loads((restored / relative_result / "run-manifest.json").read_text())
    assert (restored / relative_result / run_record["result_files"][0]).is_file()
    assert not (restored / "bundle-version.json").exists()
    assert list(tmp_path.glob(".restored.import-*")) == []


def test_task_contains_inputs_plan_and_complete_prepared_samples(planned_study, tmp_path):
    root = planned_study
    _add_prepared_sample(root)

    bundle = tmp_path / "task.zip"
    export_bundle(root, bundle)
    restored = tmp_path / "task-restored"
    import_bundle(bundle, restored)
    restored_manifest = read_json(restored / "study-manifest.json")
    ready_sample = restored_manifest["samples"][0]
    assert ready_sample["status"] == "GEOMETRY_READY"
    assert (restored / "samples" / ready_sample["sample_id"] / "geometry.step").is_file()
    for job in ready_sample["jobs"]:
        assert (restored / job["specification"]).is_file()
    unprepared = restored_manifest["samples"][-1]
    assert unprepared.get("geometry") is None
    assert not (restored / "samples" / unprepared["sample_id"]).exists()


def test_import_rejects_corrupted_payload_and_leaves_no_staging(planned_study, tmp_path):
    archive_path = tmp_path / "corrupt.zip"
    export_bundle(planned_study, archive_path)

    def corrupt(entries):
        entries["study-plan.json"] = entries["study-plan.json"] + b"tampered"
        return entries

    _rewrite_bundle(archive_path, corrupt)
    destination = tmp_path / "bad-import"
    with pytest.raises(SpecValidationError, match="hash mismatch"):
        import_bundle(archive_path, destination)
    assert not destination.exists()
    assert list(tmp_path.glob(".bad-import.import-*")) == []


def test_import_cleans_staging_after_post_extraction_failure(planned_study, tmp_path, monkeypatch):
    archive_path = tmp_path / "complete.zip"
    export_bundle(planned_study, archive_path)
    destination = tmp_path / "interrupted-import"

    def fail_validation(*args, **kwargs):
        raise SpecValidationError("simulated validation interruption")

    monkeypatch.setattr("ansys_skill.study.bundles._validate_manifest_references", fail_validation)
    with pytest.raises(SpecValidationError, match="simulated validation interruption"):
        import_bundle(archive_path, destination)
    assert not destination.exists()
    assert list(tmp_path.glob(".interrupted-import.import-*")) == []


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../escape.txt",
        "/absolute.txt",
        "C:/drive.txt",
        "samples\\escape.txt",
        "samples/file:stream",
        "samples/CON.txt",
        "samples/trailing./file.txt",
    ],
)
def test_import_rejects_unsafe_paths_before_extracting(planned_study, tmp_path, unsafe_name):
    archive_path = tmp_path / "unsafe.zip"
    export_bundle(planned_study, archive_path)

    def add_unsafe(entries):
        return {**entries, unsafe_name: b"escape"}

    _rewrite_bundle(archive_path, add_unsafe)
    destination = tmp_path / "unsafe-import"
    with pytest.raises(SpecValidationError):
        import_bundle(archive_path, destination)
    assert not destination.exists()
    assert list(tmp_path.glob(".unsafe-import.import-*")) == []


def test_import_rejects_duplicate_and_casefold_colliding_entries(planned_study, tmp_path):
    archive_path = tmp_path / "collision.zip"
    export_bundle(planned_study, archive_path)
    entries = _bundle_members(archive_path)
    with zipfile.ZipFile(archive_path, "w") as package:
        for name, payload in entries.items():
            package.writestr(name, payload)
        package.writestr("STUDY.yaml", entries["study.yaml"])

    destination = tmp_path / "collision-import"
    with pytest.raises(SpecValidationError, match="colliding"):
        import_bundle(archive_path, destination)
    assert not destination.exists()


@pytest.mark.parametrize("duplicate_name", ["study.yaml", "STUDY.yaml"])
def test_import_rejects_duplicate_zip_names(planned_study, tmp_path, duplicate_name):
    archive_path = tmp_path / "duplicate.zip"
    export_bundle(planned_study, archive_path)
    entries = _bundle_members(archive_path)
    with zipfile.ZipFile(archive_path, "w") as package:
        for name, payload in entries.items():
            package.writestr(name, payload)
        package.writestr(duplicate_name, entries["study.yaml"])

    destination = tmp_path / "duplicate-import"
    with pytest.raises(SpecValidationError, match=r"Duplicate|colliding"):
        import_bundle(archive_path, destination)
    assert not destination.exists()


def test_import_rejects_unhashed_extra_file(planned_study, tmp_path):
    archive_path = tmp_path / "extra.zip"
    export_bundle(planned_study, archive_path)
    _rewrite_bundle(archive_path, lambda entries: {**entries, "extra.txt": b"extra"})

    destination = tmp_path / "extra-import"
    with pytest.raises(SpecValidationError, match="file list"):
        import_bundle(archive_path, destination)
    assert not destination.exists()


def test_import_rejects_zip_symlinks(planned_study, tmp_path):
    archive_path = tmp_path / "link.zip"
    export_bundle(planned_study, archive_path)
    entries = _bundle_members(archive_path)
    with zipfile.ZipFile(archive_path, "w") as package:
        for name, payload in entries.items():
            if name != "bundle-manifest.json":
                package.writestr(name, payload)
        link = zipfile.ZipInfo("samples/linked")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        package.writestr(link, "../../outside")
        forged = json.loads(entries["bundle-manifest.json"])
        forged["files"]["samples/linked"] = hashlib.sha256(b"../../outside").hexdigest()
        package.writestr("bundle-manifest.json", json.dumps(forged))

    destination = tmp_path / "link-import"
    with pytest.raises(SpecValidationError, match="links"):
        import_bundle(archive_path, destination)
    assert not destination.exists()


def test_import_requires_a_new_destination_and_expected_identity(planned_study, tmp_path):
    archive_path = tmp_path / "fresh.zip"
    exported = export_bundle(planned_study, archive_path)
    existing = tmp_path / "existing"
    existing.mkdir()
    marker = existing / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(SpecValidationError, match="new directory"):
        import_bundle(archive_path, existing)
    with pytest.raises(SpecValidationError, match="expected_study_id"):
        import_bundle(archive_path, tmp_path / "wrong-id", expected_study_id="other-study")
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "wrong-id").exists()
    assert exported["study_id"]


def test_bundle_size_limits_fail_without_leaving_artifacts(planned_study, tmp_path, monkeypatch):
    output = tmp_path / "oversize.zip"
    monkeypatch.setattr(bundles, "MAX_BUNDLE_SIZE_BYTES", 32)
    with pytest.raises(SpecValidationError, match="size limit"):
        export_bundle(planned_study, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".oversize.zip.*.tmp"))

    monkeypatch.setattr(bundles, "MAX_BUNDLE_SIZE_BYTES", 20 * 1024**3)
    export_bundle(planned_study, output)
    monkeypatch.setattr(bundles, "MAX_BUNDLE_SIZE_BYTES", 32)
    destination = tmp_path / "oversize-import"
    with pytest.raises(SpecValidationError, match="size limit"):
        import_bundle(output, destination)
    assert not destination.exists()
    assert list(tmp_path.glob(".oversize-import.import-*")) == []


@pytest.mark.parametrize("locked", ["lock", "running", "owned-process"])
def test_export_rejects_locked_running_or_owned_process(planned_study, tmp_path, locked):
    if locked == "lock":
        (planned_study / ".study.lock").write_text("{}", encoding="utf-8")
    elif locked == "running":
        manifest = read_json(planned_study / "study-manifest.json")
        manifest["status"] = "RUNNING"
        (planned_study / "study-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    else:
        owner = planned_study / "samples" / "one" / "owned-process.json"
        owner.parent.mkdir(parents=True)
        owner.write_text('{"pid": 10, "host": "local", "ended_at": null}', encoding="utf-8")

    with pytest.raises(SpecValidationError, match=r"lock|RUNNING|owned process"):
        export_bundle(planned_study, tmp_path / "rejected.zip")
    assert not (tmp_path / "rejected.zip").exists()


def test_export_omits_local_environment_credentials_and_refuses_overwrite(planned_study, tmp_path):
    (planned_study / ".env").write_text("TOKEN=private", encoding="utf-8")
    (planned_study / "credentials.json").write_text('{"token":"private"}', encoding="utf-8")
    archive_path = tmp_path / "private.zip"
    result = export_bundle(planned_study, archive_path)
    names = set(_bundle_members(archive_path))
    assert not any(name.startswith(".env") or name == "credentials.json" for name in names)
    version = json.loads(_bundle_members(archive_path)["bundle-version.json"])
    assert version["distribution"] == "private_handoff_only"
    assert result["status"] == "EXPORTED"
    with pytest.raises(SpecValidationError, match="already exists"):
        export_bundle(planned_study, archive_path)
    assert not list(tmp_path.glob(".private.zip.*.tmp"))


def test_export_includes_finished_owned_process_and_private_solver_logs(planned_study, tmp_path):
    owner = planned_study / "samples" / "one" / "owned-process.json"
    owner.parent.mkdir(parents=True)
    owner.write_text('{"pid": 10, "host": "local", "ended_at": "done"}', encoding="utf-8")
    log = owner.parent / "mechanical-batch-stdout.log"
    log.write_text("private handoff log", encoding="utf-8")

    archive_path = tmp_path / "private-handoff.zip"
    export_bundle(planned_study, archive_path, kind="results")
    entries = _bundle_members(archive_path)
    assert entries["samples/one/owned-process.json"] == owner.read_bytes()
    assert entries["samples/one/mechanical-batch-stdout.log"] == log.read_bytes()
