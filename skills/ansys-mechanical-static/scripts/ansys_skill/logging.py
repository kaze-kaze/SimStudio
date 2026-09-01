"""Small stderr-only progress logger."""

from __future__ import annotations

import sys
from datetime import UTC, datetime


def progress(message: str) -> None:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", file=sys.stderr)
