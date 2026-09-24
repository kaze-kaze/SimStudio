"""Windows process probes shared by batch execution and study recovery."""

from __future__ import annotations

import os

from ansys_skill.errors import SpecValidationError


def windows_process_alive(pid: int) -> bool:
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
                if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                    raise SpecValidationError("Cannot finish inspecting the Windows process tree")
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
    return any(windows_process_alive(pid) for pid in _windows_process_tree_pids(root_pid))
