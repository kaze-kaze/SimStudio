"""Private, integrity-checked ZIP handoff for portable study tasks and results.

Solver logs may contain machine-specific paths and other private details. Bundles are for
direct handoff only and are not public release artifacts. Result JSON is preserved byte for
byte; consumers should locate quality evidence through relative paths in each run manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Literal

from ansys_skill.errors import SpecValidationError
from ansys_skill.manifest import sha256_file
from ansys_skill.study.project import load_project
from ansys_skill.study.storage import read_json

SCHEMA_VERSION = "1.0"
MAX_BUNDLE_SIZE_BYTES = 20 * 1024**3
MAX_BUNDLE_FILES = 100_000
MAX_MANIFEST_BYTES = 16 * 1024**2
_REQUIRED_FILES = {
    "study.yaml",
    "base-simulation.yaml",
    "study-manifest.json",
    "study-plan.json",
}
_BUNDLE_METADATA = {"bundle-manifest.json", "bundle-version.json"}
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul"}
_WINDOWS_NUMBERED_RESERVED = re.compile(r"^(?:com|lpt)[1-9¹²³]$", re.IGNORECASE)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_FILENAMES = {
    "credentials",
    "credentials.json",
    "auth.json",
    "secret.json",
    "secrets.json",
    ".netrc",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "private_key",
    "private_key.pem",
    "token",
    "token.json",
}
_SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
_LOCAL_ONLY_DIRECTORIES = {
    ".aws",
    ".azure",
    ".git",
    ".kube",
    ".ssh",
    ".venv",
    "__pycache__",
}


def export_bundle(
    root: Path, destination: Path, *, kind: Literal["task", "results"] = "task"
) -> dict:
    """Write a new ZIP containing the portable study tree and a SHA-256 inventory.

    Both kinds preserve the source directory layout. A task may contain samples that have
    not yet been prepared; the Windows runner can rebuild those samples. The two bundle
    metadata files live only in the ZIP envelope and are removed on import.
    """
    if kind not in {"task", "results"}:
        raise SpecValidationError("Bundle kind must be 'task' or 'results'")
    source = _source_root(root)
    _assert_quiescent(source)
    manifest = _validate_study(source)
    _validate_manifest_references(source, manifest)
    output = _new_output_path(destination)
    try:
        output.relative_to(source)
    except ValueError:
        pass
    else:
        raise SpecValidationError("Bundle destination cannot be inside the study directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    files = _source_files(source)
    names = {path.relative_to(source).as_posix() for path in files}
    missing = _REQUIRED_FILES - names
    if missing:
        raise SpecValidationError(f"Study bundle is missing required files: {sorted(missing)}")
    reserved_names = {name.casefold() for name in _BUNDLE_METADATA}
    if any(name.casefold() in reserved_names for name in names):
        raise SpecValidationError("Study root contains reserved bundle metadata files")
    _check_source_size(files)

    package_version = manifest.get("package_version")
    version_record = {
        "schema_version": SCHEMA_VERSION,
        "package": "text-to-ansys",
        "package_version": package_version if isinstance(package_version, str) else "source",
        "study_schema_version": manifest.get("schema_version"),
        "distribution": "private_handoff_only",
    }
    version_bytes = _json_bytes(version_record)
    hashes: dict[str, str] = {}
    temporary_path: Path | None = None
    published = False
    try:
        temporary_path = output.parent / f".{output.name}.{secrets.token_hex(12)}.tmp"
        fd = os.open(temporary_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        total_size = 0
        with zipfile.ZipFile(temporary_path, "w", allowZip64=True) as package:
            for path in files:
                name = path.relative_to(source).as_posix()
                info = _zip_info(name)
                digest = hashlib.sha256()
                with path.open("rb") as input_stream, package.open(info, "w") as output_stream:
                    for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                        total_size += len(chunk)
                        if total_size > MAX_BUNDLE_SIZE_BYTES:
                            raise SpecValidationError("Study exceeds the bundle size limit")
                        digest.update(chunk)
                        output_stream.write(chunk)
                hashes[name] = digest.hexdigest()

            package.writestr(_zip_info("bundle-version.json"), version_bytes)
            hashes["bundle-version.json"] = hashlib.sha256(version_bytes).hexdigest()
            if len(hashes) > MAX_BUNDLE_FILES:
                raise SpecValidationError("Study exceeds the bundle file-count limit")
            bundle_manifest = {
                "schema_version": SCHEMA_VERSION,
                "kind": kind,
                "study_id": manifest["study_id"],
                "study_fingerprint": manifest["study_fingerprint"],
                "code_fingerprint": manifest["code_fingerprint"],
                "files": dict(sorted(hashes.items())),
            }
            manifest_bytes = _json_bytes(bundle_manifest)
            if len(manifest_bytes) > MAX_MANIFEST_BYTES:
                raise SpecValidationError("bundle-manifest.json exceeds its size limit")
            package.writestr(_zip_info("bundle-manifest.json"), manifest_bytes)
        if temporary_path.stat().st_size > MAX_BUNDLE_SIZE_BYTES:
            raise SpecValidationError("Study ZIP exceeds the bundle size limit")
        _assert_quiescent(source)
        _assert_source_unchanged(source, files, hashes)
        try:
            os.link(temporary_path, output)
            published = True
        except FileExistsError as exc:
            raise SpecValidationError(f"Bundle destination already exists: {output}") from exc
        temporary_path.unlink(missing_ok=True)
        temporary_path = None
    except (zipfile.BadZipFile, OSError) as exc:
        if published:
            output.unlink(missing_ok=True)
        raise SpecValidationError(f"Cannot create study bundle: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return {
        "status": "EXPORTED",
        "kind": kind,
        "study_id": manifest["study_id"],
        "study_fingerprint": manifest["study_fingerprint"],
        "code_fingerprint": manifest["code_fingerprint"],
        "path": str(output),
    }


def import_bundle(
    archive: Path, destination: Path, *, expected_study_id: str | None = None
) -> dict:
    """Validate a ZIP completely in sibling staging, then atomically install a new study."""
    source_archive = Path(archive).expanduser()
    if source_archive.is_symlink() or not source_archive.is_file():
        raise SpecValidationError(
            f"Bundle archive does not exist or is a symbolic link: {source_archive}"
        )
    if source_archive.stat().st_size > MAX_BUNDLE_SIZE_BYTES:
        raise SpecValidationError("Study ZIP exceeds the bundle size limit")
    target = _new_destination_path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise SpecValidationError(f"Import destination must be a new directory: {target}")

    try:
        with zipfile.ZipFile(source_archive, "r") as package:
            members, bundle_manifest = _inspect_archive(package)
            if expected_study_id is not None and bundle_manifest["study_id"] != expected_study_id:
                raise SpecValidationError(
                    "Bundle study_id does not match expected_study_id",
                    details={
                        "expected_study_id": expected_study_id,
                        "actual_study_id": bundle_manifest["study_id"],
                    },
                )
            version_record = _strict_json(
                package.read(members["bundle-version.json"]), "bundle-version.json"
            )
            with tempfile.TemporaryDirectory(
                prefix=f".{target.name}.import-", dir=target.parent
            ) as staging_name:
                staging = Path(staging_name)
                _extract_and_verify(package, members, bundle_manifest, staging)
                study_manifest = _validate_study(staging)
                _validate_version_record(version_record, bundle_manifest, study_manifest)
                _assert_quiescent(staging)
                _validate_manifest_references(staging, study_manifest)
                if (
                    study_manifest["study_id"] != bundle_manifest["study_id"]
                    or study_manifest["study_fingerprint"] != bundle_manifest["study_fingerprint"]
                    or study_manifest["code_fingerprint"] != bundle_manifest["code_fingerprint"]
                ):
                    raise SpecValidationError("Bundle identity does not match study-manifest.json")
                if target.exists() or target.is_symlink():
                    raise SpecValidationError(
                        f"Import destination must be a new directory: {target}"
                    )
                os.rename(staging, target)
    except SpecValidationError:
        raise
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        OSError,
        EOFError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise SpecValidationError(f"Cannot import study bundle: {exc}") from exc

    return {
        "status": "IMPORTED",
        "kind": bundle_manifest["kind"],
        "study_id": bundle_manifest["study_id"],
        "study_fingerprint": bundle_manifest["study_fingerprint"],
        "code_fingerprint": bundle_manifest["code_fingerprint"],
        "path": str(target),
    }


def _source_root(path: Path) -> Path:
    source = Path(path).expanduser()
    if source.is_symlink() or not source.is_dir():
        raise SpecValidationError(f"Study root must be a real directory: {source}")
    return source.resolve()


def _new_output_path(path: Path) -> Path:
    output = Path(path).expanduser()
    if output.exists() or output.is_symlink():
        raise SpecValidationError(f"Bundle destination already exists: {output}")
    if not output.name or output.name in {".", ".."}:
        raise SpecValidationError(f"Bundle destination must be a file path: {output}")
    parent = output.parent.resolve()
    return parent / output.name


def _new_destination_path(path: Path) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise SpecValidationError(f"Import destination must be a new directory: {target}")
    if not target.name or target.name in {".", ".."}:
        raise SpecValidationError(f"Import destination must be a directory path: {target}")
    return target.parent.resolve() / target.name


def _validate_study(root: Path) -> dict:
    try:
        _, _, manifest = load_project(root, check_code=False)
        if not isinstance(manifest.get("code_fingerprint"), str) or not _SHA256.fullmatch(
            manifest["code_fingerprint"]
        ):
            raise SpecValidationError("Study code_fingerprint must be a SHA-256 value")
        plan = read_json(root / "study-plan.json")
        if plan.get("study_id") != manifest.get("study_id"):
            raise SpecValidationError("study-plan.json does not match study-manifest.json")
        if not isinstance(manifest.get("study_id"), str) or not manifest["study_id"]:
            raise SpecValidationError("Study manifest has no study_id")
        if not isinstance(manifest.get("study_fingerprint"), str) or not _SHA256.fullmatch(
            manifest["study_fingerprint"]
        ):
            raise SpecValidationError("Study fingerprint must be a SHA-256 value")
        return manifest
    except SpecValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise SpecValidationError(f"Study manifest is invalid: {exc}") from exc


def _assert_quiescent(root: Path) -> None:
    lock = root / ".study.lock"
    if lock.exists() or lock.is_symlink():
        raise SpecValidationError("Cannot bundle a study while .study.lock exists")

    if root.is_dir() and not root.is_symlink():
        manifest_path = root / "study-manifest.json"
        if manifest_path.is_file() and _has_running_status(read_json(manifest_path)):
            raise SpecValidationError(
                "Cannot bundle a study with a RUNNING record in study-manifest.json"
            )

    files = _source_files(root)
    for path in files:
        if path.name == ".study.lock":
            raise SpecValidationError("Cannot bundle a study containing .study.lock")
        if path.name == "owned-process.json":
            owner = read_json(path)
            if not owner.get("ended_at"):
                raise SpecValidationError(
                    f"Cannot bundle a study with an unfinished owned process: {path.relative_to(root)}"
                )


def _has_running_status(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("status") == "RUNNING":
            return True
        return any(_has_running_status(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_running_status(item) for item in value)
    return False


def _source_files(root: Path) -> list[Path]:
    files: list[Path] = []

    def raise_walk_error(error: OSError) -> None:
        raise error

    for directory, child_directories, child_files in os.walk(
        root, topdown=True, onerror=raise_walk_error, followlinks=False
    ):
        current = Path(directory)
        kept_directories = []
        for name in sorted(child_directories):
            child = current / name
            if child.is_symlink():
                raise SpecValidationError(
                    f"Study artifacts cannot contain symbolic links: {child.relative_to(root)}"
                )
            if _is_local_only_directory(name):
                continue
            if not child.is_dir():
                raise SpecValidationError(
                    f"Study entry is not a directory: {child.relative_to(root)}"
                )
            kept_directories.append(name)
        child_directories[:] = kept_directories
        for name in sorted(child_files):
            path = current / name
            relative = path.relative_to(root)
            if path.is_symlink():
                raise SpecValidationError(
                    f"Study artifacts cannot contain symbolic links: {relative}"
                )
            if name == ".study.lock":
                raise SpecValidationError("Cannot bundle a study containing .study.lock")
            if _is_private_credential(relative):
                continue
            if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                raise SpecValidationError(f"Study artifacts must be regular files: {relative}")
            _validate_member_name(relative.as_posix(), is_directory=False)
            files.append(path)
    file_spellings: dict[str, str] = {}
    component_spellings: dict[str, str] = {}
    for path in files:
        name = path.relative_to(root).as_posix()
        _, key = _validate_member_name(name, is_directory=False)
        if key in file_spellings:
            raise SpecValidationError(
                f"Duplicate or casefold-colliding study paths: {file_spellings[key]} and {name}"
            )
        file_spellings[key] = name
        prefix_key = ""
        prefix_name = ""
        for component in name.split("/"):
            component_key = unicodedata.normalize("NFC", component).casefold()
            prefix_key = f"{prefix_key}/{component_key}" if prefix_key else component_key
            prefix_name = f"{prefix_name}/{component}" if prefix_name else component
            previous = component_spellings.get(prefix_key)
            if previous is not None and previous != prefix_name:
                raise SpecValidationError(
                    f"Casefold-colliding study path components: {previous} and {prefix_name}"
                )
            component_spellings[prefix_key] = prefix_name
    for key, name in file_spellings.items():
        components = key.split("/")
        for depth in range(1, len(components)):
            parent = "/".join(components[:depth])
            if parent in file_spellings:
                raise SpecValidationError(f"Study file is also used as a directory: {name}")
    return files


def _is_local_only_directory(name: str) -> bool:
    return name.casefold() in _LOCAL_ONLY_DIRECTORIES


def _is_private_credential(relative: Path) -> bool:
    parts = [part.casefold() for part in relative.parts]
    if any(part in {".env", ".aws", ".azure", ".kube", ".ssh"} for part in parts):
        return True
    filename = parts[-1]
    if filename in {".env.example", ".env.sample", ".env.template"}:
        return False
    if filename == ".env" or filename.startswith(".env."):
        return True
    return filename in _SECRET_FILENAMES or Path(filename).suffix in _SECRET_SUFFIXES


def _check_source_size(files: list[Path]) -> None:
    if len(files) + 1 > MAX_BUNDLE_FILES:
        raise SpecValidationError("Study exceeds the bundle file-count limit")
    if sum(path.stat().st_size for path in files) > MAX_BUNDLE_SIZE_BYTES:
        raise SpecValidationError("Study exceeds the bundle size limit")


def _assert_source_unchanged(
    root: Path, initial_files: list[Path], expected_hashes: dict[str, str]
) -> None:
    current_files = _source_files(root)
    initial = {path.relative_to(root).as_posix(): path.stat() for path in initial_files}
    current = {path.relative_to(root).as_posix(): path.stat() for path in current_files}
    if initial.keys() != current.keys():
        raise SpecValidationError("Study files changed while the bundle was being written")
    for name, before in initial.items():
        after = current[name]
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ino,
        ):
            raise SpecValidationError(f"Study file changed while bundling: {name}")
        if sha256_file(root / name) != expected_hashes[name]:
            raise SpecValidationError(f"Study file changed while bundling: {name}")


def _validate_member_name(name: str, *, is_directory: bool) -> tuple[str, str]:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise SpecValidationError("ZIP contains an empty or invalid path")
    try:
        name.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise SpecValidationError("ZIP paths must contain valid Unicode") from exc
    if "\\" in name or name.startswith("/") or ":" in name:
        raise SpecValidationError(f"Unsafe ZIP path: {name!r}")
    if any(character in name for character in '<>"|?*'):
        raise SpecValidationError(f"Windows-incompatible ZIP path: {name!r}")
    normalized_name = name[:-1] if is_directory and name.endswith("/") else name
    if not normalized_name or normalized_name.endswith("/"):
        raise SpecValidationError(f"Unsafe ZIP path: {name!r}")
    components = normalized_name.split("/")
    if any(not component or component in {".", ".."} for component in components):
        raise SpecValidationError(f"Unsafe ZIP path: {name!r}")
    for component in components:
        if component.endswith((".", " ")):
            raise SpecValidationError(f"Windows-incompatible ZIP path: {name!r}")
        device = component.split(".", 1)[0].casefold()
        if device in (
            _WINDOWS_RESERVED | {"conin$", "conout$"}
        ) or _WINDOWS_NUMBERED_RESERVED.fullmatch(device):
            raise SpecValidationError(f"Reserved Windows name in ZIP path: {name!r}")
    key = "/".join(unicodedata.normalize("NFC", part).casefold() for part in components)
    return normalized_name, key


def _inspect_archive(package: zipfile.ZipFile) -> tuple[dict[str, zipfile.ZipInfo], dict]:
    infos = package.infolist()
    if not infos or len(infos) > MAX_BUNDLE_FILES + 1:
        raise SpecValidationError("ZIP has no files or exceeds the bundle file-count limit")
    if sum(info.file_size for info in infos) > MAX_BUNDLE_SIZE_BYTES:
        raise SpecValidationError("Study ZIP exceeds the bundle size limit")

    members: dict[str, zipfile.ZipInfo] = {}
    member_keys: dict[str, str] = {}
    spellings: dict[str, str] = {}
    for info in infos:
        if info.is_dir():
            raise SpecValidationError(f"Unexpected ZIP directory entry: {info.filename}")
        name, key = _validate_member_name(info.filename, is_directory=False)
        if _is_private_credential(Path(name)):
            raise SpecValidationError(f"Environment credentials are forbidden in bundles: {name}")
        if key in member_keys:
            raise SpecValidationError(f"Duplicate or casefold-colliding ZIP path: {name}")
        if info.flag_bits & 0x1:
            raise SpecValidationError(f"Encrypted ZIP entries are not supported: {name}")
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise SpecValidationError(f"Unsupported ZIP compression method: {name}")
        mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if file_type not in {0, stat.S_IFREG}:
            raise SpecValidationError(f"ZIP links and special files are forbidden: {name}")
        if info.external_attr & 0x0400:
            raise SpecValidationError(f"ZIP reparse points are forbidden: {name}")
        members[name] = info
        member_keys[key] = name
        parent_key = ""
        for component in name.split("/"):
            component_key = unicodedata.normalize("NFC", component).casefold()
            full_key = f"{parent_key}/{component_key}" if parent_key else component_key
            original_prefix = (
                component if not parent_key else f"{spellings[parent_key]}/{component}"
            )
            previous = spellings.get(full_key)
            if previous is not None and previous != original_prefix:
                raise SpecValidationError(
                    f"Casefold-colliding ZIP path components: {previous} and {original_prefix}"
                )
            spellings[full_key] = original_prefix
            parent_key = full_key
    for key, name in member_keys.items():
        components = key.split("/")
        if any("/".join(components[:depth]) in member_keys for depth in range(1, len(components))):
            raise SpecValidationError(f"ZIP file is also used as a directory: {name}")

    manifest_info = members.get("bundle-manifest.json")
    if manifest_info is None:
        raise SpecValidationError("ZIP is missing root bundle-manifest.json")
    if manifest_info.file_size > MAX_MANIFEST_BYTES:
        raise SpecValidationError("bundle-manifest.json exceeds its size limit")
    try:
        manifest = _strict_json(package.read(manifest_info), "bundle-manifest.json")
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise SpecValidationError(f"Cannot read bundle-manifest.json: {exc}") from exc
    expected_keys = {
        "schema_version",
        "kind",
        "study_id",
        "study_fingerprint",
        "code_fingerprint",
        "files",
    }
    if set(manifest) != expected_keys:
        raise SpecValidationError("bundle-manifest.json has an unsupported schema")
    kind = manifest["kind"]
    if (
        manifest["schema_version"] != SCHEMA_VERSION
        or not isinstance(kind, str)
        or kind not in {"task", "results"}
    ):
        raise SpecValidationError("Unsupported study bundle schema or kind")
    for field in ("study_fingerprint", "code_fingerprint"):
        if not isinstance(manifest[field], str) or not _SHA256.fullmatch(manifest[field]):
            raise SpecValidationError(f"bundle-manifest.json has an invalid {field}")
    if not isinstance(manifest["study_id"], str) or not manifest["study_id"]:
        raise SpecValidationError("bundle-manifest.json has an invalid study_id")
    file_hashes = manifest["files"]
    if not isinstance(file_hashes, dict) or not file_hashes:
        raise SpecValidationError("bundle-manifest.json has no file hashes")
    normalized_hash_names = set()
    for name, digest in file_hashes.items():
        if not isinstance(name, str) or name == "bundle-manifest.json":
            raise SpecValidationError(f"Invalid bundle file entry: {name!r}")
        normalized_name, key = _validate_member_name(name, is_directory=False)
        if normalized_name != name or key in normalized_hash_names:
            raise SpecValidationError(f"Duplicate or non-canonical bundle file name: {name}")
        normalized_hash_names.add(key)
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise SpecValidationError(f"Invalid SHA-256 value for bundle file: {name}")
    archived_payloads = set(members) - {"bundle-manifest.json"}
    if set(file_hashes) != archived_payloads:
        missing = sorted(archived_payloads - set(file_hashes))
        extra = sorted(set(file_hashes) - archived_payloads)
        raise SpecValidationError(
            f"Bundle file list does not match ZIP entries (unhashed={missing}, absent={extra})"
        )
    if not archived_payloads >= _REQUIRED_FILES:
        raise SpecValidationError("ZIP is missing required study files")
    version_info = members.get("bundle-version.json")
    if version_info is None:
        raise SpecValidationError("ZIP is missing bundle-version.json")
    if version_info.file_size > MAX_MANIFEST_BYTES:
        raise SpecValidationError("bundle-version.json exceeds its size limit")
    return members, manifest


def _extract_and_verify(
    package: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo], manifest: dict, staging: Path
) -> None:
    expected_hashes = manifest["files"]
    extracted_size = 0
    for name, info in members.items():
        if name == "bundle-manifest.json":
            continue
        write_payload = name != "bundle-version.json"
        target = staging.joinpath(*name.split("/")) if write_payload else None
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            for parent in target.parents:
                if parent == staging.parent:
                    break
                if parent == staging or staging in parent.parents:
                    os.chmod(parent, 0o700)
        digest = hashlib.sha256()
        try:
            with package.open(info, "r") as input_stream:
                if target is None:
                    for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                        extracted_size += len(chunk)
                        if extracted_size > MAX_BUNDLE_SIZE_BYTES:
                            raise SpecValidationError("Study ZIP exceeds the bundle size limit")
                        digest.update(chunk)
                else:
                    with target.open("xb") as output_stream:
                        for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                            extracted_size += len(chunk)
                            if extracted_size > MAX_BUNDLE_SIZE_BYTES:
                                raise SpecValidationError("Study ZIP exceeds the bundle size limit")
                            digest.update(chunk)
                            output_stream.write(chunk)
                        output_stream.flush()
                        os.fsync(output_stream.fileno())
                    os.chmod(target, 0o600)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise SpecValidationError(f"Cannot extract ZIP entry {name}: {exc}") from exc
        if digest.hexdigest() != expected_hashes[name]:
            raise SpecValidationError(f"Bundle file hash mismatch: {name}")


def _validate_version_record(version: dict, bundle: dict, study: dict) -> None:
    expected_keys = {
        "schema_version",
        "package",
        "package_version",
        "study_schema_version",
        "distribution",
    }
    if set(version) != expected_keys:
        raise SpecValidationError("bundle-version.json has an unsupported schema")
    if (
        version["schema_version"] != SCHEMA_VERSION
        or version["package"] != "text-to-ansys"
        or version["distribution"] != "private_handoff_only"
        or version["study_schema_version"] != study.get("schema_version")
        or not isinstance(version["package_version"], str)
        or version["package_version"]
        != (
            study.get("package_version")
            if isinstance(study.get("package_version"), str)
            else "source"
        )
        or bundle["code_fingerprint"] != study.get("code_fingerprint")
    ):
        raise SpecValidationError("Bundle version record does not match the study")


def _json_bytes(document: dict) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _strict_json(data: bytes, name: str) -> dict:
    def unique_object(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"Invalid JSON number: {value}")

    try:
        document = json.loads(
            data.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise SpecValidationError(f"Cannot parse {name}: {exc}") from exc
    if not isinstance(document, dict):
        raise SpecValidationError(f"{name} must contain a JSON object")
    return document


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    return info


def _validate_manifest_references(root: Path, manifest: dict) -> None:
    samples = manifest.get("samples")
    if not isinstance(samples, list):
        raise SpecValidationError("Study manifest samples must be a list")
    for sample in samples:
        if not isinstance(sample, dict):
            raise SpecValidationError("Study sample record must be an object")
        sample_id = sample.get("sample_id")
        if not isinstance(sample_id, str):
            raise SpecValidationError("Study sample has no sample_id")
        _validate_member_name(f"samples/{sample_id}/record", is_directory=False)
        sample_root = root / "samples" / sample_id
        geometry = sample.get("geometry")
        prepared = sample.get("status") in {"GEOMETRY_READY", "DRY_RUN", "SOLVED"}
        if prepared and geometry is None:
            raise SpecValidationError(f"Prepared sample is missing geometry: {sample_id}")
        if geometry is not None:
            if not isinstance(geometry, dict) or not isinstance(
                geometry.get("geometry_sha256"), str
            ):
                raise SpecValidationError(f"Invalid geometry record for sample {sample_id}")
            geometry_path = sample_root / "geometry.step"
            if (
                not geometry_path.is_file()
                or geometry_path.is_symlink()
                or sha256_file(geometry_path) != geometry["geometry_sha256"]
            ):
                raise SpecValidationError(f"Prepared geometry is missing or changed: {sample_id}")
        jobs = sample.get("jobs")
        if not isinstance(jobs, list):
            raise SpecValidationError(f"Study jobs must be a list: {sample_id}")
        for job in jobs:
            if not isinstance(job, dict):
                raise SpecValidationError(f"Study job must be an object: {sample_id}")
            specification = job.get("specification")
            spec_digest = job.get("spec_sha256")
            if (specification is None) != (spec_digest is None):
                raise SpecValidationError(f"Incomplete prepared job record: {sample_id}")
            if specification is not None:
                relative, _ = _validate_member_name(specification, is_directory=False)
                spec_path = root.joinpath(*relative.split("/"))
                if (
                    not spec_path.is_file()
                    or spec_path.is_symlink()
                    or not isinstance(spec_digest, str)
                    or sha256_file(spec_path) != spec_digest
                ):
                    raise SpecValidationError(
                        f"Prepared simulation is missing or changed: {relative}"
                    )
            elif prepared:
                raise SpecValidationError(
                    f"Prepared sample is missing a mesh specification: {sample_id}"
                )
            for collection_name in ("attempts", "previews"):
                records = job.get(collection_name, [])
                if not isinstance(records, list):
                    raise SpecValidationError(f"Study {collection_name} must be a list")
                for record in records:
                    if not isinstance(record, dict):
                        raise SpecValidationError(
                            f"Study {collection_name} entry must be an object"
                        )
                    relative = record.get("path")
                    if relative is not None:
                        relative, _ = _validate_member_name(relative, is_directory=False)
                    hashes = record.get("hashes", {})
                    if not isinstance(hashes, dict):
                        raise SpecValidationError("Run artifact hashes must be an object")
                    if record.get("status") == "SOLVED" and (not relative or not hashes):
                        raise SpecValidationError(
                            "Solved attempt is missing its artifact inventory"
                        )
                    if hashes:
                        if not relative:
                            raise SpecValidationError(
                                "Run artifact hashes have no recorded run path"
                            )
                        run_path = root.joinpath(*relative.split("/"))
                        for name, digest in hashes.items():
                            artifact_name, _ = _validate_member_name(name, is_directory=False)
                            artifact = run_path.joinpath(*artifact_name.split("/"))
                            if (
                                not artifact.is_file()
                                or artifact.is_symlink()
                                or not isinstance(digest, str)
                                or not _SHA256.fullmatch(digest)
                                or sha256_file(artifact) != digest
                            ):
                                raise SpecValidationError(
                                    f"Run artifact is missing or changed: {relative}/{name}"
                                )
