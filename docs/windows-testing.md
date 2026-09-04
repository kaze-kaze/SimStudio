# Windows acceptance testing

This guide uses PowerShell, Python 3.13, and a separately installed, licensed ANSYS Mechanical.
Mechanical 2026 R1 is the first acceptance target for the current runtime. Offline tests do not
prove that a particular product version, service pack, CAD importer, or license works.

## Install and run the offline checks

Use a checkout containing the workflow fixes. Uncommitted changes on another computer are not
included in `git clone`. Do not copy that computer's `.venv`; create a Windows environment.

```powershell
git clone https://github.com/kaze-kaze/SimStudio.git
cd SimStudio
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ansys]"
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest -q -m "not ansys_integration"
```

Calling the environment's executables directly avoids changing PowerShell's activation policy.
Installing the optional clients does not install Mechanical or supply a license.

```powershell
.\.venv\Scripts\python.exe -m ansys_skill.cli doctor --json
.\.venv\Scripts\python.exe -m ansys_skill.cli validate examples/cantilever/simulation.yaml --json
.\.venv\Scripts\python.exe -m ansys_skill.cli run examples/cantilever/simulation.yaml --out build/windows-dry-01 --json
```

The last command must return `DRY_RUN`; no solver or Mechanical network connection is started.
Inspect the generated plan, input snapshot, script, and report before proceeding. Use a new or empty
output directory for every compile/run; reusing `windows-dry-01` is intentionally refused.

## Explicitly run the licensed benchmark

This step starts Mechanical and can consume a commercial license. Run it only after reviewing the
specification and obtaining permission to use the installed solver.

```powershell
.\.venv\Scripts\python.exe -m ansys_skill.cli doctor --strict --json
.\.venv\Scripts\python.exe -m ansys_skill.cli run examples/cantilever/simulation.yaml --out build/windows-real-01 --execute --json
```

The result should contain `synthetic: false`. Inspect `verification.json`, not just the process exit
code or the `SOLVED` label. At minimum, require `PASS` for requested results, reaction balance,
small deformation, and the cantilever analytical comparison. The current benchmark uses:

- tip Z displacement: approximately `-0.125 mm`, with a 15% relative analytical tolerance;
- applied force: `-1000 N` along Z;
- support reaction: approximately `+1000 N` along Z, with a 5% force-balance tolerance.

Stress-singularity review can remain `WARN`. Safety factor and actual visual review remain
`NOT_RUN`; image export is reported separately and is not engineering approval.

```powershell
.\.venv\Scripts\python.exe -m ansys_skill.cli inspect build/windows-real-01 --json
.\.venv\Scripts\python.exe -m ansys_skill.cli report build/windows-real-01 --json
```

Alternatively, the automated acceptance test performs its own additional licensed solve and checks
the numerical acceptance conditions. Enable it explicitly and reset the opt-in afterward:

```powershell
$env:ANSYS_AVAILABLE = "1"
.\.venv\Scripts\python.exe -m pytest -q -m ansys_integration --basetemp build/windows-integration-01
$env:ANSYS_AVAILABLE = "0"
```

Choose a fresh `--basetemp` directory: pytest owns and may clear that directory. Do not point it at
existing simulation results or user files.

## Template and failure checks

Make a separate copy of a trusted `.mechdat`/`.mechdb` template before testing. The current guard
expects one analysis, declared active bodies, exact object names, and verified linear materials.
Contacts, joints, springs, command/Python objects, and undeclared active analysis objects are blocked.
Clear the example's open questions only after checking all inputs and names.

For a template regression, begin with a force using a rotated coordinate system and a directional
result using another axis; verify that the saved output uses the YAML's global force and requested
result axis. Verify the reaction result points to the configured support. The source template should
remain unchanged because execution opens the compiled input snapshot.

If a run fails, retain the complete output directory. Useful diagnostics include `environment.json`,
`run-manifest.json`, `mechanical-artifacts.json`, `face-selection-report.json`, and `solver/solve.out`
when those stages were reached. A missing or unverified material-property API must be investigated
against the installed version, not bypassed by deleting the guard.

Exit codes: `2` specification, `3` environment, `4` Mechanical/transfer, `5` DPF, `6` verification.
Do not publish proprietary CAD, RST files, license information, certificates, or private paths in
public issues. Report the product/service-pack version and a redacted error first.
