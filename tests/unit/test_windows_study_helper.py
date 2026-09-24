from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tools" / "run_study_windows.ps1"
FINGERPRINT = "windows-helper-test-fingerprint"


@pytest.fixture(scope="module")
def powershell() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if executable is None:
        pytest.skip("PowerShell is not installed (pwsh/powershell unavailable)")
    return executable


@pytest.fixture
def helper_context(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    stub_root = tmp_path / "temporary Python stub package"
    package = stub_root / "ansys_skill"
    study_package = package / "study"
    study_package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (study_package / "__init__.py").write_text("", encoding="utf-8")
    (study_package / "storage.py").write_text(
        "import os\n"
        "def code_fingerprint():\n"
        "    return os.environ['STUDY_HELPER_FINGERPRINT']\n",
        encoding="utf-8",
    )
    (package / "cli.py").write_text(
        "import json, os, sys\n"
        "with open(os.environ['STUDY_HELPER_CALLS'], 'w', encoding='utf-8') as stream:\n"
        "    json.dump(sys.argv[1:], stream)\n"
        "raise SystemExit(int(os.environ.get('STUDY_HELPER_EXIT', '0')))\n",
        encoding="utf-8",
    )

    study_path = tmp_path / "Imported Study With Spaces"
    study_path.mkdir()
    (study_path / "study-manifest.json").write_text(
        json.dumps({"code_fingerprint": FINGERPRINT}), encoding="utf-8"
    )
    calls_path = tmp_path / "recorded CLI argv.json"
    env = os.environ.copy()
    env["STUDY_HELPER_CALLS"] = str(calls_path)
    env["STUDY_HELPER_FINGERPRINT"] = FINGERPRINT
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(stub_root), env.get("PYTHONPATH")) if part
    )
    return study_path, calls_path, env


def run_helper(
    powershell: str,
    study_path: Path,
    env: dict[str, str],
    *,
    execute: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [
        powershell,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(HELPER),
        str(study_path),
        "-Python",
        sys.executable,
    ]
    if execute:
        command.append("-Execute")
    return subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)


def test_default_invocation_stays_dry_run_and_preserves_study_path(
    powershell: str, helper_context: tuple[Path, Path, dict[str, str]]
) -> None:
    study_path, calls_path, env = helper_context

    result = run_helper(powershell, study_path, env)

    assert result.returncode == 0, result.stderr
    assert json.loads(calls_path.read_text(encoding="utf-8")) == [
        "study",
        "run",
        str(study_path.resolve()),
        "--resume",
        "--json",
    ]


def test_execute_switch_is_forwarded_only_when_explicit(
    powershell: str, helper_context: tuple[Path, Path, dict[str, str]]
) -> None:
    study_path, calls_path, env = helper_context

    result = run_helper(powershell, study_path, env, execute=True)

    assert result.returncode == 0, result.stderr
    assert json.loads(calls_path.read_text(encoding="utf-8")) == [
        "study",
        "run",
        str(study_path.resolve()),
        "--execute",
        "--resume",
        "--json",
    ]


def test_child_process_exit_code_is_preserved(
    powershell: str, helper_context: tuple[Path, Path, dict[str, str]]
) -> None:
    study_path, calls_path, env = helper_context
    env["STUDY_HELPER_EXIT"] = "23"

    result = run_helper(powershell, study_path, env)

    assert result.returncode == 23
    assert calls_path.exists()


def test_fingerprint_mismatch_does_not_start_study_cli(
    powershell: str, helper_context: tuple[Path, Path, dict[str, str]]
) -> None:
    study_path, calls_path, env = helper_context
    env["STUDY_HELPER_FINGERPRINT"] = "different-installed-code"

    result = run_helper(powershell, study_path, env)

    assert result.returncode == 2
    assert "does not match this study" in result.stderr
    assert not calls_path.exists()
