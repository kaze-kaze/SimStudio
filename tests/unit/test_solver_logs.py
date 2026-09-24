from __future__ import annotations

from pathlib import Path

import pytest
from ansys_skill.postprocessing import solver_logs
from ansys_skill.validation.evidence import message_check
from ansys_skill.validation.statuses import CheckStatus


def test_reads_realistic_multiline_mapdl_warnings_and_preserves_sources(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "solver").mkdir(parents=True)
    (run_dir / "other").mkdir()
    (run_dir / "solver" / "solve.out").write_text(
        (
            " *** WARNING ***                         ELAPSED TIME = 5.1 TIME= 20:09:23\n"
            " Element shape checking is currently inactive. Issue SHPP,ON or\n"
            " SHPP,WARN to reactivate, if desired.\n\n"
            " Ordinary solve output after the warning.\n"
            " *** NOTE *** ELAPSED TIME = 5.2 TIME= 20:09:23\n"
            " *** WARNING ***                         ELAPSED TIME = 5.3 TIME= 20:09:24\n"
            " Material number 2 should normally have at least one MP or one TB command.\n"
        ),
        encoding="utf-8",
    )
    (run_dir / "other" / "solve.out").write_text(
        " *** ERROR *** ELAPSED TIME = 7.0\n Solver failed\n", encoding="utf-8"
    )

    messages, availability = solver_logs.read_solver_messages(
        run_dir, ["solver/solve.out", "solver/solve.out", "other/solve.out"]
    )

    assert [(item["severity"], item["line"]) for item in messages] == [
        ("WARNING", 1),
        ("WARNING", 7),
        ("ERROR", 1),
    ]
    assert "SHPP,WARN" in messages[0]["text"]
    assert "warning messages were found" not in messages[0]["text"]
    assert "Ordinary solve output" not in messages[0]["text"]
    assert messages[0]["path"] == "solver/solve.out"
    assert messages[2]["path"] == "other/solve.out"
    assert [entry["path"] for entry in availability] == [
        "solver/solve.out",
        "other/solve.out",
    ]
    check = message_check({"solver_messages": messages})
    assert check.status is CheckStatus.FAIL
    assert check.evidence["warning_count"] == 2


def test_fatal_message_fails_existing_message_check() -> None:
    check = message_check({"solver_messages": [{"severity": "FATAL", "text": "abort"}]})
    assert check.status is CheckStatus.FAIL
    assert check.evidence["error_count"] == 1


def test_unknown_mapdl_banner_is_preserved_and_warns(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "solver").mkdir(parents=True)
    (run_dir / "solver" / "solve.out").write_text(
        "  *** SEVERE *** ELAPSED TIME = 2.0 TIME= 10:00:00\n solver condition\n\n",
        encoding="utf-8",
    )

    messages, availability = solver_logs.read_solver_messages(run_dir, ["solver/solve.out"])

    assert len(messages) == 1
    assert messages[0]["severity"] == "UNKNOWN"
    assert messages[0]["raw_severity"] == "SEVERE"
    assert messages[0]["raw_header"] == "  *** SEVERE *** ELAPSED TIME = 2.0 TIME= 10:00:00"
    assert messages[0]["text"] == "solver condition"
    assert messages[0]["source"] == "solver/solve.out"
    assert messages[0]["path"] == "solver/solve.out"
    assert messages[0]["line"] == 1
    assert availability == [{"path": "solver/solve.out", "status": "READ"}]
    check = message_check({"solver_messages": messages})
    assert check.status is CheckStatus.WARN
    assert check.evidence["unknown_count"] == 1


@pytest.mark.parametrize(
    ("banner", "expected"),
    [("INFO", "INFO"), ("WARNING", "WARNING"), ("ERROR", "ERROR"), ("FATAL", "FATAL")],
)
def test_known_mapdl_severities_keep_their_classification(banner: str, expected: str) -> None:
    messages = solver_logs._parse_blocks(f" *** {banner} ***\n detail\n", "solver/solve.out")
    assert len(messages) == 1
    assert messages[0]["severity"] == expected


def test_real_mapdl_section_headings_are_not_unknown_severities() -> None:
    text = (
        " ***** MAPDL COMMAND LINE ARGUMENTS *****\n batch flags\n\n"
        " *** MAPDL - ENGINEERING ANALYSIS SYSTEM RELEASE 2026 R1 ***\n\n"
        " *********** Send Named Selection as Node Component ***********\n"
        " ************************* SOLUTION ********************************\n"
        " *** WARNING *** ELAPSED TIME = 5.179 TIME= 20:09:23\n shape checking inactive\n\n"
        " *** SELECTION OF ELEMENT TECHNOLOGIES FOR APPLICABLE ELEMENTS ***\n\n"
        " ***** ROUTINE COMPLETED ***** ELAPSED TIME = 6.035\n"
        " *** SEVERE ***\n retain an unfamiliar diagnostic\n"
    )
    messages = solver_logs._parse_blocks(text, "solver/solve.out")
    assert [message["severity"] for message in messages] == ["WARNING", "UNKNOWN"]
    assert messages[0]["text"] == "shape checking inactive"
    assert messages[1]["raw_severity"] == "SEVERE"


@pytest.mark.parametrize(
    ("severity", "expected"),
    [("INFO", CheckStatus.PASS), ("WARNING", CheckStatus.PASS),
     ("ERROR", CheckStatus.FAIL), ("FATAL", CheckStatus.FAIL),
     ("SEVERE", CheckStatus.WARN), ("MessageSeverity.Error", CheckStatus.FAIL)],
)
def test_message_check_preserves_known_severities_and_warns_on_unknown(
    severity: str, expected: CheckStatus
) -> None:
    check = message_check({"solver_messages": [{"severity": severity, "text": "fixture"}]})
    assert check.status is expected


@pytest.mark.parametrize("declared", [["missing/solve.out"], ["../outside.out"]])
def test_unavailable_declared_log_is_unknown_not_silently_empty(
    tmp_path: Path, declared: list[str]
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    messages, availability = solver_logs.read_solver_messages(run_dir, declared)

    assert messages[0]["severity"] == "UNKNOWN"
    assert availability[0]["status"] == "UNKNOWN"
    assert message_check(
        {"solver_messages": messages, "solver_log_availability": availability}
    ).status is CheckStatus.WARN


def test_rejects_symlink_and_marks_bounded_read_as_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, create_symlink
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    outside = tmp_path / "outside.out"
    outside.write_text(" *** WARNING ***\nexternal\n", encoding="utf-8")
    create_symlink(run_dir / "linked.out", outside)
    (run_dir / "large.out").write_text(" *** WARNING ***\nlong text\n", encoding="utf-8")
    monkeypatch.setattr(solver_logs, "_MAX_LOG_BYTES", 8)

    messages, availability = solver_logs.read_solver_messages(
        run_dir, ["linked.out", "large.out"]
    )

    assert [item["status"] for item in availability] == ["UNKNOWN", "UNKNOWN"]
    assert sum(item["severity"] == "UNKNOWN" for item in messages) == 2


def test_undeclared_legacy_logs_remain_unchecked(tmp_path: Path) -> None:
    messages, availability = solver_logs.read_solver_messages(tmp_path, None)
    assert messages == []
    assert availability == []


def test_declared_log_type_error_is_unknown() -> None:
    messages, availability = solver_logs.read_solver_messages(Path.cwd(), "solver/solve.out")
    assert messages[0]["severity"] == "UNKNOWN"
    assert availability[0]["status"] == "UNKNOWN"


@pytest.mark.parametrize("mechanical_messages", [None, "unavailable"])
def test_missing_mechanical_messages_stay_unknown_when_mapdl_has_only_warnings(
    tmp_path: Path, mechanical_messages: object
) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "solver").mkdir(parents=True)
    (run_dir / "solver" / "solve.out").write_text(
        " *** WARNING *** ELAPSED TIME = 1.0\n warning details\n\n ordinary output\n",
        encoding="utf-8",
    )

    messages, availability = solver_logs.merge_solver_messages(
        run_dir, mechanical_messages, ["solver/solve.out"]
    )

    check = message_check(
        {"solver_messages": messages, "solver_log_availability": availability}
    )
    assert check.status is CheckStatus.WARN
    assert check.evidence["warning_count"] == 1
    assert check.evidence["unknown_count"] == 1


def test_mapdl_error_fails_even_when_mechanical_messages_are_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "solver").mkdir(parents=True)
    (run_dir / "solver" / "solve.out").write_text(
        " *** ERROR *** ELAPSED TIME = 1.0\n solve failed\n\n", encoding="utf-8"
    )
    messages, availability = solver_logs.merge_solver_messages(
        run_dir, None, ["solver/solve.out"]
    )
    check = message_check(
        {"solver_messages": messages, "solver_log_availability": availability}
    )
    assert check.status is CheckStatus.FAIL
