# Cantilever benchmark

View the [saved real demonstration](demo/index.html) without installing ANSYS. It includes the
original mesh, deformation and stress images, the recorded numerical checks, and input downloads.
Read the [test report](../../docs/reports/mechanical-test-2026-09-06.md) or
[简体中文报告](../../docs/reports/mechanical-test-2026-09-06.zh-CN.md) for methods and limits.

This is a redistributable single-solid rectangular cantilever benchmark. The editable geometry source
is `generate_geometry.py`; `cantilever.step` is the generated neutral CAD fixture used by offline
validation and compilation.

Geometry and load:

- length `L = 200 mm` along +X
- width `b = 20 mm` along Y
- height `h = 40 mm` along Z
- explicit `Structural Steel`, analytical `E = 200 GPa`
- STEP product `CantileverBeam`; exact imported v261 body name `CantileverBeam|Solid`
- fixed X-min face
- `F = 1000 N` in -Z on the X-max face
- `I = b h^3 / 12 = 106666.6666667 mm^4`
- Euler-Bernoulli tip displacement `F L^3 / (3 E I) = 0.125 mm`

Offline workflow:

```bash
ansys-sim validate examples/cantilever/simulation.yaml --json
ansys-sim compile examples/cantilever/simulation.yaml --out build/cantilever --json
ansys-sim run examples/cantilever/simulation.yaml \
  --out build/cantilever-dry-run \
  --json
```

Real execution requires a supported ANSYS Mechanical installation, license, matching body import name,
and optional PyAnsys dependencies. Start with `ansys-sim doctor --json`; then add `--execute` only on an
execution host.

The recorded Windows Student 2026 R1 acceptance uses an explicit `mechanical_batch` backend.
See [Windows testing](../../docs/windows-testing.md) to create a working specification and run
the serial numerical, image, raw-RST, and template acceptance suite. The original example retains
the `pymechanical_remote` selection; batch is never an implicit fallback after a failed connection.
