# Windows acceptance testing

Local batch execution was tested on ANSYS Student Mechanical 2026 R1 on 2026-09-06. This
installation's gRPC connection failed during handshake. Use the explicit batch workflow below for
the recorded execution path, and read the [acceptance record](windows-acceptance-2026-09-06.md).
Other installations, service packs, CAD importers, and licenses require their own acceptance.

## Python and offline checks

The base offline CLI supports Python 3.11–3.13. The optional `ansys` extra supports
Python 3.12–3.13; Python 3.13 is recommended. PyMechanical 0.13.2 declares
`Requires-Python: >=3.12,<4.0`, so installing that extra on Python 3.11 fails.

Create a Windows environment rather than copying another machine's environment:

```powershell
git clone https://github.com/kaze-kaze/SimStudio.git
cd SimStudio
py -3.13 -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev,ansys]"
./.venv/Scripts/python.exe -m pip check
./.venv/Scripts/ruff.exe check .
./.venv/Scripts/python.exe -m pytest -q -m "not ansys_integration"
```

Calling the environment executables directly avoids changing the PowerShell activation policy.
Offline-only users can choose Python 3.11/3.12 and install `.[dev]` without the optional clients.
Installing clients does not install Mechanical or provide a license.

The two real symbolic-link checks report `NOT_RUN` when Windows denies link creation with
`WinError 1314`. Their original rejection assertions still run on a host with that privilege.
Other symbolic-link errors are not hidden.

## Prepare an explicit batch specification

Create a run-specific copy of the benchmark with `execution.backend: mechanical_batch`.
Absolute geometry paths keep the copy independent of its new directory; existing copies are not overwritten.

```powershell
@'
from pathlib import Path
import yaml
source = Path("examples/cantilever/simulation.yaml").resolve()
document = yaml.safe_load(source.read_text(encoding="utf-8"))
document["inputs"]["geometry_file"] = str((source.parent / document["inputs"]["geometry_file"]).resolve())
document["execution"]["backend"] = "mechanical_batch"
target = Path("build/windows-inputs/simulation.yaml")
target.parent.mkdir(parents=True, exist_ok=True)
with target.open("x", encoding="utf-8") as stream:
    yaml.safe_dump(document, stream, sort_keys=False)
'@ | ./.venv/Scripts/python.exe -
./.venv/Scripts/python.exe -m ansys_skill.cli doctor --json
./.venv/Scripts/python.exe -m ansys_skill.cli validate build/windows-inputs/simulation.yaml --json
./.venv/Scripts/python.exe -m ansys_skill.cli run build/windows-inputs/simulation.yaml --out build/windows-dry-01 --json
```

The last command must return `DRY_RUN` and start no Mechanical process. Review the normalized
specification, plan, saved script, and input snapshot. Use a new or empty output directory for every run.
Standalone `doctor` describes the default gRPC setup; `run` additionally records a doctor report
for the selected backend. Neither environment discovery nor an open TCP port proves a successful solve.

## Explicitly run the installed solver

This command starts Mechanical and can consume its installed license. Use it only for an explicitly
requested real solve after reviewing the specification:

```powershell
./.venv/Scripts/python.exe -m ansys_skill.cli run build/windows-inputs/simulation.yaml --out build/windows-real-01 --execute --json
./.venv/Scripts/python.exe -m ansys_skill.cli inspect build/windows-real-01 --json
./.venv/Scripts/python.exe -m ansys_skill.cli report build/windows-real-01 --json
```

Batch starts and exits a task-owned local Windows process, captures stdout/stderr, and uses no gRPC
connection. It rejects a remote host, a configured port, `start_instance: no`, certificates, or
settings that request keeping the instance alive. Batch is never an automatic fallback from gRPC.

Require `synthetic: false` and inspect `verification.json`, not just the executable exit code or
`SOLVED` label. The cantilever requires `PASS` for requested results, reaction balance,
small deformation, and the analytical comparison. Its benchmark is:

- tip Z displacement about `-0.125 mm`, with 15% relative analytical tolerance;
- applied force `-1000 N` along Z;
- support reaction about `+1000 N` along Z, within 5% relative force-balance tolerance.

Stress-singularity review remains `WARN`. Safety factor and automatic visual review remain
`NOT_RUN`. Image export is reported separately; opening an RST or exporting an image is not design approval.

## Automated real acceptance

The suite performs five serial solves: the cantilever, pressure, gravity, and two template formats.
It also checks all three PNGs, raw-RST inspection, report regeneration, input hashes, and saved
Mechanical object settings. Enable real tests explicitly and restore both environment variables:

```powershell
$previousAnsysAvailable = $env:ANSYS_AVAILABLE
$previousTestBackend = $env:ANSYS_TEST_BACKEND
try {
    $env:ANSYS_AVAILABLE = "1"
    $env:ANSYS_TEST_BACKEND = "mechanical_batch"
    ./.venv/Scripts/python.exe -m pytest -q -m ansys_integration --basetemp build/windows-integration-01 --junitxml=build/windows-integration-01.xml
}
finally {
    $env:ANSYS_AVAILABLE = $previousAnsysAvailable
    $env:ANSYS_TEST_BACKEND = $previousTestBackend
}
```

Choose a fresh `--basetemp` directory: pytest owns and may clear it. Never use existing results
or user files as the base directory. Keep these tests serial; parallel pytest workers are rejected
before starting Mechanical. With no explicit `ANSYS_TEST_BACKEND`, the test backend remains
`pymechanical_remote`; `fake` is rejected. Use gRPC only on an independently verified host.

## Template and failure evidence

The automated template cases create isolated `.mechdat` and `.mechdb` fixtures from the solved
benchmark. A fully defined rotated coordinate system, wrong load components, wrong result axis/scope,
and an alternate reaction support are deliberately configured. After compilation and solving, a fresh
Mechanical process reads the saved output and verifies global coordinates, the requested components,
Z direction, load-face scope, and fixed-support reaction binding. Source and snapshot hashes must agree.

Saved results must be cleared before their locations can be updated. Generated solver data is cleared
only in the isolated working copy. Unknown active loads, contacts, command/Python objects, and
unverified material properties remain rejected.

Retain failed run directories. Diagnostics include `environment.json`, `run-manifest.json`,
`mechanical-artifacts.json`, the batch stdout/stderr logs, `face-selection-report.json`, and
`solver/solve.out` when reached. Mechanical messages include source object names/types so empty
localized error text still identifies its origin. Do not discard an error to force verification to pass.

Exit codes: `2` specification, `3` environment, `4` Mechanical/transfer, `5` DPF, `6` verification.
Do not publish proprietary geometry, results, license details, certificates, or private paths.
