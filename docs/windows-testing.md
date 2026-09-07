# Windows acceptance testing

The primary acceptance example is the [twin-rib equipment bracket](../examples/gusseted-bracket/README.md).
The September 6, 2026 study recorded **5 passed integration tests across 5 serial real solves
in 208.16 seconds** on ANSYS Student Mechanical 2026 R1 using explicit `mechanical_batch`.
Read the [formal test report](reports/mechanical-test-2026-09-06.md). The preceding offline
baseline was **252 passed, 20 skipped**; it is not a new result from this presentation replacement.
An earlier local gRPC handshake failed and was not retested by the bracket study. Other
installations, service packs, CAD importers, licenses, and versions require their own acceptance.

The public [JSON summary](reports/evidence/2026-09-06/summary.json),
[case details](reports/evidence/2026-09-06/cases.json), and
[provenance](reports/evidence/2026-09-06/provenance.json) are data attachments to the formal report.
Original JUnit and local execution logs are retained only in the ignored local archive.

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

## Validate and dry-run the bracket

The committed STEP and CAD properties are ready to use. The specification already selects local
`execution.backend: mechanical_batch` and a nominal **8 mm quadratic mesh**. CAD dependencies
are required only when regenerating geometry. If copying the specification to another directory,
update `inputs.geometry_file` to the original STEP's absolute path.

```powershell
./.venv/Scripts/python.exe -m ansys_skill.cli doctor --json
./.venv/Scripts/python.exe -m ansys_skill.cli validate examples/gusseted-bracket/simulation.yaml --json
./.venv/Scripts/python.exe -m ansys_skill.cli compile examples/gusseted-bracket/simulation.yaml --out build/bracket-compile-01 --json
./.venv/Scripts/python.exe -m ansys_skill.cli run examples/gusseted-bracket/simulation.yaml --out build/bracket-dry-01 --json
```

The last command must return `DRY_RUN` and start no Mechanical process. Review the normalized
specification, plan, saved script, and input snapshot. Use a new or empty output directory for every run.
Standalone `doctor` describes the default gRPC setup; `run` additionally records a doctor report
for the selected backend. Neither environment discovery nor an open TCP port proves a successful solve.

## Explicitly run the installed solver

This command starts Mechanical and can consume its installed license. Use it only for an explicitly
requested real solve after reviewing the specification:

```powershell
./.venv/Scripts/python.exe -m ansys_skill.cli run examples/gusseted-bracket/simulation.yaml --out build/bracket-real-01 --execute --json
./.venv/Scripts/python.exe -m ansys_skill.cli inspect build/bracket-real-01 --json
./.venv/Scripts/python.exe -m ansys_skill.cli report build/bracket-real-01 --json
```

Batch starts and exits a task-owned local Windows process, captures stdout/stderr, and uses no gRPC
connection. It rejects a remote host, a configured port, `start_instance: no`, certificates, or
settings that request keeping the instance alive. Batch is never an automatic fallback from gRPC.

The command above solves the nominal **8 mm** combined-load case. It does not reproduce the
complete study or the **5 mm** cover image; use the next section for all five solves.

Require `synthetic: false` and inspect `verification.json`, not just the exit code or `SOLVED`.
CLI requested-results and small-deformation checks must pass. Mixed-load CLI `reaction_balance`
and disabled `cantilever_analytical` remain `NOT_RUN`; the study supplies separate independent
force and moment checks. Stress-singularity review remains `WARN`. Safety factor and automatic
visual review remain `NOT_RUN`; the recorded manual image review is separate.

## Automated real acceptance

The primary study runs three combined-load cases on **12 / 8 / 5 mm quadratic meshes**, then
gravity-only and doubled force/pressure cases on the 5 mm mesh. Gravity stays constant. It checks
force and moment balance from CAD properties, material values and element types from solver input,
selected face geometry, fixed support, input hashes, native PNGs, and full-field linearity.

Run only the bracket entry serially, with explicit opt-in and a fresh output directory:

```powershell
$previousAnsysAvailable = $env:ANSYS_AVAILABLE
$previousTestBackend = $env:ANSYS_TEST_BACKEND
try {
    $env:ANSYS_AVAILABLE = "1"
    $env:ANSYS_TEST_BACKEND = "mechanical_batch"
    ./.venv/Scripts/python.exe -m pytest -q tests/integration/test_engineering_bracket.py --basetemp build/bracket-study-01 --junitxml=build/bracket-study-01.xml
}
finally {
    $env:ANSYS_AVAILABLE = $previousAnsysAvailable
    $env:ANSYS_TEST_BACKEND = $previousTestBackend
}
```

Choose a fresh `--basetemp` directory: pytest owns and may clear it. Never use existing results
or user files as the base directory. Keep these tests serial; parallel pytest workers are rejected
before starting Mechanical. The bracket study requires an explicit real backend and rejects
`fake`. Use gRPC only on an independently verified host. Ordinary offline `pytest -q` skips real
integrations and starts no solver.

## Engineering acceptance and retained outputs

| Case | Mesh | Loads |
| --- | --- | --- |
| `mixed_12mm` | 12 mm | Three-component force + eccentric pressure + self-weight |
| `mixed_8mm` | 8 mm | Same combined loads |
| `mixed_5mm` | 5 mm | Same combined loads; primary presentation case |
| `gravity_5mm` | 5 mm | Self-weight only |
| `double_mechanical_5mm` | 5 mm | Twice force and pressure; unchanged self-weight |

Force and moment relative tolerances are **0.5% and 1%**. Both 12 → 8 and 8 → 5 mm changes
must meet **5%** for maximum total and pad mean Z displacement, and **10%** for pad mean and
95th-percentile equivalent stress. Pad statistics weight nodes equally, not by area.

Full-field linearity compares `u(2P+G) = 2u(P+G) - u(G)` at matching node IDs and coordinates
with per-node tolerance `1e-12 m + 1e-6 × ||predicted displacement||`. Do not simply double maxima
containing gravity. Global stress peaks remain review quantities, excluded from strength acceptance.

Each run retains `engineering-checks.json`, ordinary CLI reports, RST, a saved Mechanical project,
and solver logs. The study root contains `study-summary.json`. The development extra includes
Pillow for complete PNG structure verification and pixel decoding of the three native images
per case. Retain separate manual-review evidence without changing automatic `visual_review`.

## DPF isolation and historical diagnostics

Independent DPF extraction runs in its own Python process. In the first bracket-study attempt,
in-process DPF initialization changed the parent Python environment to the product's bundled
Python 3.10 paths. The next Python 3.13 CLI failed with `AssertionError: SRE module mismatch`.
The worker isolates those changes and retains separate `dpf-stdout.log` and `dpf-stderr.log`
files; solve logs are kept separately. A single successful solve did not expose this sequencing bug.

The former public cantilever demonstration is replaced by the bracket. Its beam model remains
only as the internal analytical regression fixture `tests/fixtures/cantilever`. Earlier real
cantilever and `.mechdat` / `.mechdb` template-synchronization acceptance are historical records,
not extra cases in this five-test bracket study.

Retain failed run directories. Diagnostics include `environment.json`, `run-manifest.json`,
`mechanical-artifacts.json`, the batch stdout/stderr logs, `face-selection-report.json`, and
`solver/solve.out` when reached. Mechanical messages include source object names/types so empty
localized error text still identifies its origin. Do not discard an error to force verification to pass.

Exit codes: `2` specification, `3` environment, `4` Mechanical/transfer, `5` DPF, `6` verification.
Do not publish proprietary geometry, results, license details, certificates, or private paths.
