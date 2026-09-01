# text-to-ansys

`text-to-ansys` is a plugin-level Codex Skill and deterministic Python CLI for reviewable ANSYS
Mechanical linear static structural workflows. It turns a natural-language engineering request into
a human-readable brief and strict `simulation.yaml`, then compiles saved Mechanical scripts, checks
the environment, optionally executes through PyMechanical, inspects results through PyDPF, and
produces verification and reporting artifacts.

It is an AI-assisted simulation compiler, not a replacement for a qualified CAE engineer. It does
not provide engineering certification, regulatory compliance, design approval, or final sign-off.

## Fixed workflow

```text
user request
  -> simulation_brief.md
  -> simulation.yaml
  -> strict schema and engineering preflight
  -> normalized-simulation.yaml + mechanical-plan.json
  -> generated-mechanical.py
  -> doctor / optional explicit Mechanical solve
  -> PyDPF postprocessing
  -> numerical checks + visual review
  -> report.md + JSON + CSV + run-manifest.json
```

The editable specification and compiler source are the facts of record. Generated scripts and solver
outputs are reproducible artifacts; fixes belong in the specification or compiler, followed by a
rerun.

## Supported in v0.1

- template workflows starting from an exact `.mechdat`/`.mechdb` path
- simple single-body STEP/STP geometry import
- linear static structural analysis with small deformation
- exact Mechanical object names and named selections
- strictly unique `axis_extreme_face` selection for simple single-body geometry
- exact Engineering Data material names
- fixed support, force, pressure, and gravity
- global element size
- total/directional deformation, equivalent von Mises stress, reaction force, messages, and mesh counts
- deterministic compile/dry-run without ANSYS
- optional PyMechanical gRPC execution and PyDPF result inspection
- force-only reaction balance, small-deformation, result completeness, and cantilever analytical checks

Custom isotropic material properties are accepted by the schema for future migration, but real
execution is deliberately blocked until material-authoring behavior is verified against a live,
supported Mechanical version.

## Explicitly unsupported

The v1 Skill does not run Fluent, CFX, explicit dynamics, LS-DYNA, transient, nonlinear material,
plasticity, large deformation, buckling, fatigue, fracture, topology optimization, automatic contact
inference, arbitrary multi-body assemblies, or safety-factor calculations without yield strength. It
does not infer materials, supports, load scopes, or safety factors from vague prose. Out-of-scope
requests must be split or routed to a future independent Skill.

## Install the CLI

Base installation requires no ANSYS package or license:
Python 3.11 through 3.13 is supported so the base CLI and optional PyDPF workflow share one official
compatibility range.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Install the optional official PyAnsys clients only on a machine that will inspect or run real results:

```bash
python -m pip install -e ".[ansys]"
```

This does not download or install ANSYS Mechanical and does not accept a commercial license. The user
must provide a valid, compatible ANSYS installation and license.

## First offline run

```bash
ansys-sim doctor --json
ansys-sim validate examples/cantilever/simulation.yaml --json
ansys-sim compile examples/cantilever/simulation.yaml --out build/cantilever --json
ansys-sim run examples/cantilever/simulation.yaml --out build/cantilever-dry-run --json
```

Dry-run is the default. A real Mechanical process is started or contacted only with an explicit
`--execute` and only when the specification is execution-ready:

```bash
ANSYS_AVAILABLE=1 ansys-sim run examples/cantilever/simulation.yaml \
  --out build/cantilever-real \
  --execute \
  --json
```

`ANSYS_AVAILABLE=1` is the repository's integration-test opt-in convention; the CLI still relies on
`doctor`, the configured connection, the product installation, and the real license state.

## CLI

- `ansys-sim doctor [--json] [--strict]`
- `ansys-sim init <directory>`
- `ansys-sim validate <simulation.yaml> [--json]`
- `ansys-sim compile <simulation.yaml> --out <directory> [--json]`
- `ansys-sim run <simulation.yaml> [--out <directory>] [--execute] [--json]`
- `ansys-sim inspect <run-directory-or-rst> [--json]`
- `ansys-sim report <run-directory> [--json]`

stdout contains machine-readable JSON. Progress and diagnostics go to stderr. Stable exit codes are
0 success, 2 specification/engineering validation, 3 environment/license, 4 Mechanical/solve,
5 postprocessing, and 6 verification.

## Plugin and Skill

The repository root is the plugin root and `.codex-plugin/plugin.json` points to the single source of
truth under `skills/ansys-mechanical-static`. No duplicate Skill tree or release symlink is required.

For local Codex plugin development, use a clean checkout so ignored virtual environments, build
outputs, and caches are not copied into Codex's local plugin cache. The following commands were
verified with `codex-cli 0.151.0-alpha.7.2`; replace the path with the absolute path to that clean
checkout:

```bash
codex plugin marketplace add /absolute/path/to/text-to-ansys --json
codex plugin add text-to-ansys@text-to-ansys-local --json
codex plugin list --json
```

Start a new task after installation so Skill discovery is refreshed. The repository's automated
validation checks both manifests without modifying the user's Codex configuration.

## Safety and licensing

This project is not an ANSYS product and has no affiliation with ANSYS. It does not distribute ANSYS
binaries, license files, commercial material libraries, project fixtures, or result files. Users are
responsible for license compliance, model correctness, data protection, and engineering review. See
`SECURITY.md`, `NOTICE`, and the Skill's `engineering-safety.md` reference.
