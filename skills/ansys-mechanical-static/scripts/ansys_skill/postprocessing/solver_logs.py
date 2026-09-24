"""Extract bounded MAPDL message blocks from explicitly recorded solve logs."""

from __future__ import annotations

import re
from pathlib import Path

_MAX_LOG_BYTES = 8 * 1024 * 1024
# MAPDL diagnostics use exactly three stars around a severity token. Longer
# banners and free-form headings also occur throughout a normal solve log.
_BANNER = re.compile(
    r"^\s*(?P<raw_header>\*{3}(?!\*)\s+(?P<severity>[A-Za-z][A-Za-z0-9_-]*)"
    r"\s+\*{3}(?!\*))(?P<tail>.*)$"
)
_SECTION_BANNER = re.compile(r"^\s*\*{3,}")
_KNOWN_SEVERITIES = {"INFO", "WARNING", "ERROR", "FATAL"}
_NON_MESSAGE_BANNERS = {"NOTE"}


def read_solver_messages(
    run_dir: Path, declared_logs: object
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Read only declared in-run logs and return messages plus per-path availability."""
    if declared_logs is None:
        return [], []
    if not isinstance(declared_logs, list):
        availability = [{"path": "<solve_logs>", "status": "UNKNOWN", "reason": "declared solve_logs is not a list"}]
        return [
            {
                "severity": "UNKNOWN",
                "text": "Declared solver logs could not be inspected: solve_logs is not a list",
                "source": "<solve_logs>",
                "path": "<solve_logs>",
            }
        ], availability

    root = run_dir.resolve()
    messages: list[dict[str, object]] = []
    availability: list[dict[str, str]] = []
    seen: set[str] = set()
    for declared in declared_logs:
        if not isinstance(declared, str) or not declared:
            availability.append({"path": str(declared), "status": "UNKNOWN", "reason": "invalid declared log path"})
            continue
        relative = Path(declared)
        key = relative.as_posix()
        if key in seen:
            continue
        seen.add(key)
        if relative.is_absolute() or ".." in relative.parts:
            availability.append({"path": declared, "status": "UNKNOWN", "reason": "log path is not run-relative"})
            continue
        path = root / relative
        try:
            current = root
            for component in relative.parts:
                current = current / component
                if current.is_symlink():
                    raise OSError("symbolic links are not allowed in declared log paths")
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            if not resolved.is_file():
                raise OSError("declared log is not a regular file")
            with resolved.open("rb") as stream:
                data = stream.read(_MAX_LOG_BYTES + 1)
            truncated = len(data) > _MAX_LOG_BYTES
            data = data[:_MAX_LOG_BYTES]
            text = data.decode("utf-8", errors="replace")
            decode_issue = "\ufffd" in text
            messages.extend(_parse_blocks(text, declared))
            status = "UNKNOWN" if truncated or decode_issue else "READ"
            reason = ("log exceeded bounded read size" if truncated else "log contains undecodable bytes") if status == "UNKNOWN" else ""
            availability.append({"path": declared, "status": status, **({"reason": reason} if reason else {})})
        except (OSError, ValueError) as exc:
            availability.append({"path": declared, "status": "UNKNOWN", "reason": str(exc)})

    for item in availability:
        if item["status"] == "UNKNOWN":
            messages.append(
                {
                    "severity": "UNKNOWN",
                    "text": f"Solver log could not be fully inspected: {item.get('reason', 'unknown read failure')}",
                    "source": item["path"],
                    "path": item["path"],
                }
            )
    return messages, availability


def merge_solver_messages(
    run_dir: Path, mechanical_messages: object, declared_logs: object
) -> tuple[object, list[dict[str, str]]]:
    """Merge log evidence while retaining missing Mechanical message evidence."""
    log_messages, availability = read_solver_messages(run_dir, declared_logs)
    if isinstance(mechanical_messages, list):
        return [*mechanical_messages, *log_messages], availability
    if declared_logs is None:
        return mechanical_messages, availability
    missing_mechanical = {
        "severity": "UNKNOWN",
        "text": "Mechanical message evidence is unavailable",
        "source": "Mechanical message API",
    }
    return [missing_mechanical, *log_messages], availability


def _parse_blocks(text: str, source: str) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    current_severity: str | None = None
    current_line = 0
    lines: list[str] = []

    def finish() -> None:
        if current_severity is not None:
            body = "\n".join(line.rstrip() for line in lines).strip()
            item = {
                "severity": current_severity,
                "text": body,
                "source": source,
                "path": source,
                "line": current_line,
            }
            if current_severity == "UNKNOWN":
                item["raw_header"] = raw_header
                item["raw_severity"] = raw_severity
            messages.append(item)

    raw_header = ""
    raw_severity = ""
    for number, line in enumerate(text.splitlines(), start=1):
        match = _BANNER.match(line)
        if match:
            finish()
            raw_severity = match.group("severity").strip()
            normalized_severity = raw_severity.upper()
            if not normalized_severity:
                current_severity = None
                lines = []
                continue
            if normalized_severity in _NON_MESSAGE_BANNERS:
                current_severity = None
                lines = []
                continue
            current_severity = (
                normalized_severity if normalized_severity in _KNOWN_SEVERITIES else "UNKNOWN"
            )
            current_line = number
            raw_header = line
            header = re.sub(r"\s+ELAPSED TIME\s*=.*$", "", match.group("tail"), flags=re.I).strip()
            lines = [header] if header else []
        elif _SECTION_BANNER.match(line):
            finish()
            current_severity = None
            lines = []
        elif current_severity is not None:
            if not line.strip():
                finish()
                current_severity = None
                lines = []
            else:
                lines.append(line)
    finish()
    return messages
