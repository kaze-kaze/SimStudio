"""Small standard-library phase timer for the CLI process."""

from __future__ import annotations

import time

if callable(getattr(time, "monotonic", None)):
    CLOCK_SOURCE = "time.monotonic"
    _clock = time.monotonic
else:
    CLOCK_SOURCE = "time.time"
    _clock = time.time


def start_timer() -> float | None:
    try:
        return _clock()
    except Exception:
        return None


def phase_record(started: float | None) -> dict[str, object] | None:
    if started is None:
        return None
    try:
        elapsed = max(0.0, _clock() - started)
    except Exception:
        return None
    return {"status": "RECORDED", "elapsed_seconds": elapsed}
