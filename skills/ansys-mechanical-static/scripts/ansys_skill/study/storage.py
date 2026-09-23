"""Atomic, portable study artifacts and single-writer locking."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import socket
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ansys_skill.errors import SpecValidationError
from ansys_skill.manifest import sha256_file, utc_now


def canonical_hash(document: object) -> str:
    data = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def read_json(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"),
                            parse_constant=lambda value: _reject_constant(value))
    except (OSError, ValueError) as exc:
        raise SpecValidationError(f"Cannot read {path.name}: {exc}") from exc
    if not isinstance(result, dict):
        raise SpecValidationError(f"{path.name} must contain a JSON object")
    return result


def _reject_constant(value: str):
    raise ValueError(f"Non-finite JSON number: {value}")


def atomic_json(path: Path, document: dict) -> None:
    data = json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"
    atomic_text(path, data)


def atomic_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise SpecValidationError(f"Refusing symbolic-link artifact: {path.name}")
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def recovery_guard(root: Path):
    """Serialize explicit lock recovery against new study writers."""
    guard = root / ".study.recovery.lock"
    token = os.urandom(16).hex()
    try:
        descriptor = os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        record = read_json(guard)
        if record.get("host") != socket.gethostname():
            raise SpecValidationError(
                "Cannot prove that a recovery owner on another host is stopped"
            ) from None
        pid = record.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            raise SpecValidationError("Recovery ownership evidence has no valid PID") from None
        if process_alive(pid):
            raise SpecValidationError("Another study recovery is still running") from None
        if read_json(guard).get("token") != record.get("token"):
            raise SpecValidationError(
                "Recovery guard changed while checking its owner"
            ) from None
        guard.unlink()
        try:
            descriptor = os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise SpecValidationError("Another study recovery acquired the guard") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "host": socket.gethostname(),
                       "created_at": utc_now(), "token": token}, stream)
        yield token
    finally:
        if guard.is_file() and read_json(guard).get("token") == token:
            guard.unlink()


@contextmanager
def study_lock(root: Path, *, recovery_token: str | None = None):
    """Never steal a lock implicitly, including one from another host."""
    guard = root / ".study.recovery.lock"
    if guard.exists():
        try:
            guard_record = read_json(guard)
        except SpecValidationError as exc:
            raise SpecValidationError("Study recovery is in progress; cannot acquire the study lock") from exc
        if recovery_token is None or guard_record.get("token") != recovery_token:
            raise SpecValidationError("Study recovery is in progress; cannot acquire the study lock")
    elif recovery_token is not None:
        raise SpecValidationError("Study recovery guard was lost before lock acquisition")
    lock = root / ".study.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise SpecValidationError("Study is locked; inspect the owner before explicit recovery",
                                  details={"lock": str(lock)}) from exc
    token = os.urandom(16).hex()
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "host": socket.gethostname(),
                       "created_at": utc_now(), "token": token}, stream)
        yield
    finally:
        if lock.is_file() and read_json(lock).get("token") == token:
            lock.unlink()


def recover_lock(root: Path, *, recovery_token: str) -> dict:
    guard = root / ".study.recovery.lock"
    if not guard.is_file() or read_json(guard).get("token") != recovery_token:
        raise SpecValidationError("Explicit recovery guard is missing or changed")
    lock = root / ".study.lock"
    record = read_json(lock)
    if record.get("host") != socket.gethostname():
        raise SpecValidationError("Cannot prove that a lock owner on another host is stopped")
    pid = record.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        raise SpecValidationError("Invalid lock owner PID")
    if process_alive(pid):
        raise SpecValidationError("Lock owner is still running")
    for owner_path in study_process_owner_paths(root):
        owner = read_json(owner_path)
        if owned_process_alive(owner):
            raise SpecValidationError("An owned solver process tree is still running")
    current = read_json(lock)
    if current.get("token") != record.get("token"):
        raise SpecValidationError("Study lock changed during explicit recovery")
    lock.unlink()
    return {"status": "LOCK_RECOVERED", "previous_owner": record}


def process_alive(pid: int) -> bool:
    """Query liveness without sending a terminating signal on Windows."""
    if os.name == "nt":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        raise SpecValidationError("Cannot verify whether the process owner is stopped") from exc
    except OSError as exc:
        raise SpecValidationError("Cannot verify whether the process owner is stopped") from exc
    return True


def _windows_process_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return False
        raise SpecValidationError("Cannot inspect Windows process owner")
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise SpecValidationError("Cannot read Windows process status")
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)


def process_group_alive(process_group_id: int) -> bool:
    """Check a POSIX session created for one owned CLI process."""
    if os.name == "nt":
        raise SpecValidationError("Windows process groups cannot prove solver-tree liveness")
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        raise SpecValidationError("Cannot verify whether the owned process group is stopped") from exc
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        raise SpecValidationError("Cannot inspect the owned process group") from exc
    return True


def _windows_process_tree_pids(root_pid: int) -> list[int]:
    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise SpecValidationError("Cannot inspect the Windows process tree")
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(ProcessEntry32W)
        if not kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise SpecValidationError("Cannot read the Windows process tree")
        parents = {}
        while True:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                break
        tree = {root_pid}
        while True:
            descendants = {pid for pid, parent in parents.items() if parent in tree}
            expanded = tree | descendants
            if expanded == tree:
                return sorted(tree)
            tree = expanded
    finally:
        kernel.CloseHandle(snapshot)


def windows_process_tree_alive(root_pid: int) -> bool:
    if os.name != "nt":
        raise SpecValidationError("Windows process-tree inspection is unavailable on this platform")
    return any(process_alive(pid) for pid in _windows_process_tree_pids(root_pid))


def owned_process_alive(owner: dict) -> bool:
    """Fail closed unless the owner record identifies its full process tree."""
    if owner.get("host") != socket.gethostname():
        raise SpecValidationError("Cannot verify an owned process tree from another host")
    pid = owner.get("pid")
    if owner.get("launch_status") == "FAILED" and owner.get("tree_verified") is True:
        return False
    if not isinstance(pid, int) or pid <= 0:
        raise SpecValidationError("Process ownership evidence has no valid PID; cannot automatically recover")
    if os.name == "nt":
        if owner.get("process_tree") != "windows-parent-tree":
            raise SpecValidationError("Process ownership evidence lacks Windows tree scope; cannot automatically recover")
        if owner.get("tree_verified") is True:
            return False
        return windows_process_tree_alive(pid)
    if owner.get("process_tree") != "posix-session":
        raise SpecValidationError("Process ownership evidence lacks POSIX session scope; cannot automatically recover")
    process_group_id = owner.get("process_group_id")
    if not isinstance(process_group_id, int) or process_group_id <= 0:
        raise SpecValidationError("Process ownership evidence has no process-group ID; cannot automatically recover")
    if owner.get("tree_verified") is True:
        return False
    return process_alive(pid) or process_group_alive(process_group_id)


def study_process_owner_paths(root: Path) -> list[Path]:
    return sorted(root.glob("samples/**/attempt-*/owned-process.json"))


def artifact_hashes(directory: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise SpecValidationError("Study artifacts cannot contain symbolic links")
        if path.is_file() and not path.name.startswith(".write-"):
            hashes[path.relative_to(directory).as_posix()] = sha256_file(path)
    return hashes


def verify_hashes(directory: Path, hashes: dict[str, str]) -> None:
    if not hashes:
        raise SpecValidationError("Artifact integrity record is empty")
    if artifact_hashes(directory) != hashes:
        raise SpecValidationError("Artifact set is missing, changed, or contains unrecorded files")


def code_fingerprint() -> str:
    package = Path(__file__).resolve().parents[1]
    return canonical_hash({path.relative_to(package).as_posix(): hashlib.sha256(
                               path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                           for path in sorted(package.rglob("*.py"))})
