# Shared phase timer; keep this module compatible with IronPython 2.7.
import time
from contextlib import contextmanager

PHASE_TIMING_CLOCK = "time.time"


def empty_phase_timings(names):
    return dict((name, {"status": "NOT_RUN", "elapsed_seconds": None}) for name in names)


def start_phase_timer():
    return time.time()


def record_phase_timing(timings, name, started):
    try:
        elapsed = max(0.0, time.time() - started)
        timings[name] = {"status": "RECORDED", "elapsed_seconds": elapsed}
    except Exception:
        # A timer failure must not replace the operation's original exception.
        return


@contextmanager
def timed_phase(timings, name):
    started = start_phase_timer()
    try:
        yield
    finally:
        record_phase_timing(timings, name, started)
