"""Unified PASS/WARN/FAIL/NOT_RUN status model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class Check:
    name: str
    status: CheckStatus
    message: str
    evidence: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        if data["evidence"] is None:
            del data["evidence"]
        return data


def aggregate_checks(checks: list[Check]) -> CheckStatus:
    statuses = {check.status for check in checks}
    if CheckStatus.FAIL in statuses:
        return CheckStatus.FAIL
    if CheckStatus.WARN in statuses:
        return CheckStatus.WARN
    if statuses and statuses == {CheckStatus.NOT_RUN}:
        return CheckStatus.NOT_RUN
    if CheckStatus.NOT_RUN in statuses:
        return CheckStatus.WARN
    return CheckStatus.PASS


def checks_payload(checks: list[Check]) -> dict[str, object]:
    return {
        "status": aggregate_checks(checks).value,
        "checks": [check.as_dict() for check in checks],
    }
