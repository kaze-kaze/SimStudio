"""Account active study work without counting idle review time or nested solver work twice."""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

from ansys_skill.study.project import save_project


@contextmanager
def account_subactivity(manifest: dict, phase: str):
    """Measure a child of an already timed activity without adding it to the total twice."""
    started = time.monotonic()
    try:
        yield
    finally:
        record = manifest.setdefault("phase_timings", {}).setdefault(
            phase, {"status": "RECORDED", "elapsed_seconds": 0.0, "calls": 0})
        record["elapsed_seconds"] += max(0.0, time.monotonic() - started)
        record["calls"] += 1


@contextmanager
def account_activity(root: Path, manifest: dict, phase: str):
    """Record one non-solver activity while its caller holds the study write lock."""
    started = time.monotonic()
    try:
        yield
    finally:
        duration = max(0.0, time.monotonic() - started)
        manifest["elapsed_seconds"] = manifest.get("elapsed_seconds", 0.0) + duration
        record = manifest.setdefault("phase_timings", {}).setdefault(
            phase, {"status": "RECORDED", "elapsed_seconds": 0.0, "calls": 0})
        record["elapsed_seconds"] += duration
        record["calls"] += 1
        save_project(root, manifest)
