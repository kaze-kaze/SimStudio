"""Bound client waits without making interpreter exit wait for a stuck RPC."""

from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Queue
from threading import Thread
from typing import TypeVar

T = TypeVar("T")


def call_with_timeout(operation: Callable[[], T], seconds: float) -> T:
    result: Queue = Queue(maxsize=1)

    def invoke() -> None:
        try:
            result.put((True, operation()))
        except Exception as exc:
            result.put((False, exc))

    Thread(target=invoke, name="text-to-ansys-rpc", daemon=True).start()
    try:
        success, value = result.get(timeout=seconds)
    except Empty as exc:
        raise TimeoutError("Mechanical client operation timed out") from exc
    if not success:
        raise value
    return value
