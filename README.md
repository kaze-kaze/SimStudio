<div align="center">
  <h1>SimStudio</h1>
  <p><strong>From engineering intent to auditable ANSYS Mechanical results.</strong></p>
  <p>Codex Skill · Deterministic simulation compiler · <code>ansys-sim</code> CLI</p>
  <p>
    <a href="https://github.com/kaze-kaze/SimStudio/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://github.com/kaze-kaze/SimStudio/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI on main"></a>
    <img src="https://img.shields.io/badge/Python-3.11--3.13-3776AB?logo=python&amp;logoColor=white" alt="Base CLI: Python 3.11–3.13">
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-2EA44F" alt="MIT License"></a>
    <img src="https://img.shields.io/badge/Status-Alpha-F59E0B" alt="Alpha">
  </p>
  <p>
    <strong>English</strong> · <a href="README.zh-CN.md">简体中文</a><br>
    <a href="https://kaze-kaze.github.io/SimStudio/">Website</a> ·
    <a href="https://kaze-kaze.github.io/SimStudio/examples/cantilever/demo/">Explore the example</a> ·
    <a href="https://kaze-kaze.github.io/SimStudio/docs/reports/mechanical-test-2026-09-06.html">Test report</a> ·
    <a href="#quick-start">Quick start</a>
  </p>
</div>

[![SimStudio — recorded ANSYS Mechanical cantilever results](docs/assets/overview.png)](https://kaze-kaze.github.io/SimStudio/examples/cantilever/demo/)

Images used courtesy of ANSYS, Inc. Cover assembled from recorded results; engineering verification remains **WARN**.

**SimStudio** turns a reviewed engineering request into an explicit `simulation.yaml`, saved Mechanical scripts, traceable run manifests, numerical checks, and reports. The Python package is **`text-to-ansys`**; its command is **`ansys-sim`**. The Codex Skill structures the request, and the deterministic compiler makes the resulting setup inspectable and repeatable.

- **Review before solving.** Units, materials, supports, loads, scopes, and assumptions are explicit.
- **Start offline.** Validate, compile, and dry-run without ANSYS or a license. Real execution requires `--execute`.
- **Keep the evidence.** Inspect saved results through PyDPF and distinguish `PASS`, `WARN`, `FAIL`, and `NOT_RUN`.

## A real example, with its limits

A **200 × 20 × 40 mm** steel cantilever, fixed at X-min, carries **−1000 N along Z** at X-max. The input uses exact `Structural Steel`, a **10 mm** global mesh size, and `program_controlled` element order. The analytical reference uses **E = 200 GPa**.

The **September 6, 2026** acceptance record contains **9 passed cases across 5 real solves** on Windows 11 with ANSYS Student Mechanical 2026 R1, CPython 3.13.2, PyMechanical 0.13.2, and PyDPF 0.16.1. The explicitly selected backend was `mechanical_batch`. All five runs are non-synthetic; **all five retain overall engineering status `WARN`**.

| Force cantilever — recorded quantity | Result |
| --- | ---: |
| Mesh | 1,077 nodes · 160 elements |
| Tip Z displacement | −0.127583 mm |
| Euler–Bernoulli reference magnitude | 0.125 mm |
| Analytical deviation / allowed tolerance | 2.0664% / 15% |
| Maximum total displacement | 0.128951 mm |
| Maximum nodal-averaged equivalent stress | 38.0902 MPa |
| Support reaction Z, summed over support nodes | +1000.000000009 N |

Tip Z is the largest absolute Z component among 37 load-face nodes, with its sign retained. The support reaction is a vector sum, not the maximum single-node reaction. Peak stress still requires an engineering review of stress concentrations and mesh convergence.

<details>
<summary><strong>View the original mesh and result plots</strong></summary>

### Mesh
![Recorded cantilever mesh](examples/cantilever/demo/assets/mesh.png)

Images used courtesy of ANSYS, Inc. Recorded mesh: 1,077 nodes and 160 elements.

### Total deformation
![Recorded cantilever total deformation](examples/cantilever/demo/assets/total-deformation.png)

Images used courtesy of ANSYS, Inc. Plot units: m; maximum approximately 0.128951 mm.

### Equivalent stress
![Recorded cantilever equivalent stress](examples/cantilever/demo/assets/equivalent-stress.png)

Images used courtesy of ANSYS, Inc. Plot units: Pa; maximum approximately 38.0902 MPa. Engineering status: `WARN`.

</details>

The nine cases cover force, pressure, gravity, `.mechdat` / `.mechdb` template synchronization, three PNG exports, and raw-RST inspection with report regeneration. The [static example](https://kaze-kaze.github.io/SimStudio/examples/cantilever/demo/) displays saved evidence without running a solver. Read the [full report](docs/reports/mechanical-test-2026-09-06.md) for tolerances, failures, and provenance; inspect the [input specification](examples/cantilever/simulation.yaml) and [public evidence](docs/reports/evidence/2026-09-06/summary.json) to trace the numbers.

## How it works

1. **Describe and review** — the Skill records engineering intent, assumptions, and open questions in `simulation_brief.md` and a strict, unit-aware `simulation.yaml`.
2. **Validate and compile** — schema and engineering preflight checks produce a deterministic Mechanical plan and saved script. Exact object names and unique scopes keep selections explicit.
3. **Dry-run, then explicitly execute** — inspect the plan offline; request `--execute` only on a prepared Mechanical host with a valid license.
4. **Inspect and report** — PyDPF extracts numerical results; checks, reports, and input hashes preserve what ran and what remains unverified.

The specification, compiler source, and reference documents are the sources of truth. Fix them and regenerate outputs. User-supplied Python and prose are never executed as source code.

## Quick start

### 1. Install the CLI

The base CLI supports **Python 3.11–3.13**. Use **Python 3.13** if you also plan to install the optional ANSYS clients, which require **Python 3.12–3.13** within this project's supported range.

```bash
git clone https://github.com/kaze-kaze/SimStudio.git
cd SimStudio
python -m venv .venv
```

Activate the environment with `source .venv/bin/activate` on Linux/macOS or `.\.venv\Scripts\Activate.ps1` in PowerShell, then install:

```bash
python -m pip install -e .
```

For Windows setup without changing PowerShell's activation policy, use the direct executable commands in [Windows testing](docs/windows-testing.md).

### 2. Try the cantilever offline

```bash
ansys-sim doctor --json
ansys-sim validate examples/cantilever/simulation.yaml --json
ansys-sim compile examples/cantilever/simulation.yaml --out build/cantilever-compile --json
ansys-sim run examples/cantilever/simulation.yaml --out build/cantilever-dry-run --json
```

The final command returns `DRY_RUN` and starts no Mechanical process. `doctor` can report unavailable solver components on an offline machine. Use a **new or empty output directory** for every compile/run.

Review `normalized-simulation.yaml`, `mechanical-plan.json`, and `generated-mechanical.py`; the dry-run also saves `execution-plan.json`, `verification.json`, `results-summary.json`, `report.md`, and `run-manifest.json`, plus an `inputs/` snapshot. A dry-run does not establish numerical solver results.

### 3. Run Mechanical explicitly

On a separately provisioned and licensed host:

```bash
python -m pip install -e ".[ansys]"
```

Follow [Windows testing](docs/windows-testing.md) to create `build/windows-inputs/simulation.yaml`, preserve the geometry path, and explicitly set `execution.backend: mechanical_batch`. Validate and dry-run that copy before solving:

```bash
ansys-sim run build/windows-inputs/simulation.yaml --out build/windows-real-01 --execute --json
ansys-sim inspect build/windows-real-01 --json
ansys-sim report build/windows-real-01 --json
```

The original example selects `pymechanical_remote`. Its first recorded gRPC attempt failed during handshake; batch success does not verify gRPC. Batch is an explicit local Windows choice, never an automatic fallback. Installing the clients does not install Mechanical or provide a license. See [execution details](skills/ansys-mechanical-static/references/mechanical-execution.md) for other configurations and their requirements.

## Everyday operations

| Command | Purpose |
| --- | --- |
| `ansys-sim init <directory>` | Create a starter specification and brief |
| `ansys-sim doctor --json` | Diagnose the environment and default transport |
| `ansys-sim validate <spec> --json` | Check schema, units, references, and engineering constraints |
| `ansys-sim compile <spec> --out <directory> --json` | Save plans, scripts, and a manifest |
| `ansys-sim run <spec> --out <directory> --json` | Dry-run; add `--execute` for an explicitly requested solve |
| `ansys-sim inspect <run-directory-or-rst> --json` | Inspect saved run data or an RST file |
| `ansys-sim report <run-directory> --json` | Regenerate reports from saved artifacts |

With `--json`, stdout is machine-readable; progress goes to stderr. Exit codes: `0` success, `2` specification/engineering validation, `3` environment/license, `4` Mechanical/solve, `5` postprocessing, `6` verification.

### Use with Codex

The repository includes the [`ansys-mechanical-static` Skill](skills/ansys-mechanical-static/SKILL.md) and a [local plugin marketplace](.agents/plugins/marketplace.json). Following the existing local-development setup, replace the path with your checkout's absolute path:

```bash
codex plugin marketplace add /absolute/path/to/SimStudio --json
codex plugin add text-to-ansys@text-to-ansys-local --json
codex plugin list --json
```

Start a new Codex task to refresh Skill discovery. For the included fixture, try:

> Prepare a dry-run for examples/cantilever/simulation.yaml. Review the units, fixed support, −1000 N Z load, mesh, and analytical comparison. Show the generated plan and unresolved checks.

## Scope and verification boundaries

**v0.1 scope:** Mechanical linear static structural analysis with small deformation; exact-name `.mechdat` / `.mechdb` templates or one simple STEP/STP solid; fixed supports, forces, pressure, gravity, global mesh sizing, deformation, equivalent stress, and reaction results. Custom isotropic material properties can be represented in the schema, but live material authoring remains blocked pending verification.

Fluent/CFX, nonlinear or transient physics, contact inference, arbitrary assemblies, modal analysis, buckling, fatigue, fracture, and design certification are outside this Skill. See the [supported-scope contract](skills/ansys-mechanical-static/references/supported-scope.md).

| State | Meaning and recorded limits |
| --- | --- |
| `PASS` | A check ran and met its stated condition. The recorded suite passed 9 cases; this is not design approval. |
| `WARN` | Engineering review is required. All five runs retain `stress_singularity_review: WARN`. |
| `FAIL` | A required condition failed. The initial gRPC attempt failed and remains unresolved. |
| `NOT_RUN` | A check was unavailable or not exercised. Missing evidence is never treated as a pass. |

Safety factor (no specified yield strength), visual engineering review, remote execution, and raw-RST engineering validation/specification recovery remain `NOT_RUN`. Pressure/gravity passed independent benchmark assertions, while their generic `reaction_balance` and `cantilever_analytical` checks remain `NOT_RUN`. Mesh convergence, explicit element-order variants, and other Mechanical versions remain unverified. Image-export checks establish usable files, not completed visual engineering review.

SimStudio supports engineering review; it does not provide certification, design approval, or final engineering sign-off. See the [validation policy](skills/ansys-mechanical-static/references/validation-policy.md) and [recorded limitations](docs/reports/mechanical-test-2026-09-06.md#warn-and-not_run).

## Contribute and learn more

Start with [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md). Run the relevant focused checks, then:

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest -q
```

Ordinary tests require no ANSYS, license, or network. Real tests require explicit `ANSYS_AVAILABLE=1`; reproduce the recorded batch suite serially using [Windows testing](docs/windows-testing.md). Report unrun integrations as `NOT_RUN`, preserve acceptance criteria, and fix sources before regenerating artifacts.

- [Schema reference](skills/ansys-mechanical-static/references/schema-reference.md) · [Template example](examples/template-mode/README.md)
- [Official API map](skills/ansys-mechanical-static/references/official-api-map.md) · [Roadmap](ROADMAP.md)
- [Release preparation](docs/release-preparation.md) · [Security reporting](SECURITY.md)

## License and attribution

[MIT](LICENSE). SimStudio is independent open-source software, not affiliated with, endorsed by, or sponsored by ANSYS, Inc. or its affiliates. ANSYS, Mechanical, and Workbench are trademarks of their respective owners. See [NOTICE](NOTICE) for attribution and redistribution details. Do not publish proprietary models, solver archives, license data, credentials, or private paths in issues or contributions.
