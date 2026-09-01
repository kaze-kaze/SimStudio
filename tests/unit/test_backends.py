from __future__ import annotations

from pathlib import Path

import ansys_skill.backends.pymechanical as pymechanical_module
import pytest
from ansys_skill.backends.fake import FakeMechanicalBackend
from ansys_skill.backends.pymechanical import PyMechanicalRemoteBackend
from ansys_skill.errors import MechanicalExecutionError
from ansys_skill.schema import load_spec


def test_fake_backend_is_explicitly_synthetic(valid_spec_path: Path, tmp_path: Path) -> None:
    spec, _ = load_spec(valid_spec_path)
    outcome = FakeMechanicalBackend().execute(
        spec, valid_spec_path, tmp_path, tmp_path / "generated.py"
    )
    assert outcome.synthetic is True
    assert outcome.status == "SYNTHETIC"
    assert "NOT AN ANSYS SOLVE" in (tmp_path / "solve.out").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("path", "expected_name"),
    [
        (r"C:\Mechanical Jobs\run 1\model.step", "model.step"),
        ("/var/tmp/run 1/model.step", "model.step"),
    ],
)
def test_remote_path_parsing(path: str, expected_name: str) -> None:
    assert pymechanical_module._remote_basename(path) == expected_name


def test_remote_workdir_sentinel_is_required(tmp_path: Path) -> None:
    class Mechanical:
        def run_python_script_from_file(self, _path: str) -> str:
            return "no sentinel"

    with pytest.raises(MechanicalExecutionError, match="sentinel"):
        PyMechanicalRemoteBackend._create_remote_workdir(Mechanical(), tmp_path)


@pytest.mark.parametrize("stage", ["startup", "solve"])
def test_fake_backend_failure_stages(stage: str, valid_spec_path: Path, tmp_path: Path) -> None:
    spec, _ = load_spec(valid_spec_path)
    with pytest.raises(MechanicalExecutionError, match="Synthetic"):
        FakeMechanicalBackend(fail_stage=stage).execute(
            spec, valid_spec_path, tmp_path, tmp_path / "generated.py"
        )


def test_pymechanical_startup_failure_is_wrapped(
    monkeypatch: pytest.MonkeyPatch, valid_spec_path: Path, tmp_path: Path
) -> None:
    spec, _ = load_spec(valid_spec_path)

    class BrokenCompat:
        def launch(self, _spec: object) -> object:
            raise RuntimeError("cannot launch")

        def connect(self, _spec: object) -> object:
            raise RuntimeError("cannot connect")

    monkeypatch.setattr(
        pymechanical_module,
        "doctor_report",
        lambda _spec: {"can_execute": True},
    )
    monkeypatch.setattr(pymechanical_module, "PyMechanicalCompat", BrokenCompat)
    with pytest.raises(MechanicalExecutionError, match="startup/connection"):
        PyMechanicalRemoteBackend().execute(
            spec, valid_spec_path, tmp_path, tmp_path / "generated.py"
        )


def test_pymechanical_timeout_force_closes_owned_instance(
    monkeypatch: pytest.MonkeyPatch, valid_spec_path: Path, tmp_path: Path
) -> None:
    spec, _ = load_spec(valid_spec_path)
    exit_calls: list[bool] = []
    shutdown_calls: list[tuple[bool, bool]] = []

    class Mechanical:
        version = "261"

        def run_python_script_from_file(self, *_args: object) -> str:
            return "bootstrap"

        def exit(self, force: bool = False) -> None:
            exit_calls.append(force)

    mechanical = Mechanical()

    class Compat:
        def launch(self, _spec: object) -> Mechanical:
            return mechanical

        def connect(self, _spec: object) -> Mechanical:
            return mechanical

    class Future:
        def result(self, timeout: int) -> None:
            del timeout
            raise pymechanical_module.FutureTimeoutError

        def cancel(self) -> bool:
            return True

    class Executor:
        def __init__(self, max_workers: int) -> None:
            assert max_workers == 1

        def submit(self, *_args: object) -> Future:
            return Future()

        def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
            shutdown_calls.append((wait, cancel_futures))

    monkeypatch.setattr(pymechanical_module, "doctor_report", lambda _spec: {"can_execute": True})
    monkeypatch.setattr(pymechanical_module, "PyMechanicalCompat", Compat)
    monkeypatch.setattr(pymechanical_module, "ThreadPoolExecutor", Executor)

    with pytest.raises(MechanicalExecutionError, match="exceeded"):
        PyMechanicalRemoteBackend().execute(
            spec, valid_spec_path, tmp_path, tmp_path / "generated.py"
        )

    assert exit_calls[0] is True
    assert shutdown_calls == [(False, True)]
