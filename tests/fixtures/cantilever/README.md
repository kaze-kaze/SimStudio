# Cantilever regression fixture

This internal fixture preserves the analytical beam contract used by schema, compiler, validation,
and isolated force, pressure, gravity, template, image, and raw-RST regressions. The main engineering
example and saved demonstration use the
[gusseted equipment bracket](../../../examples/gusseted-bracket/README.md).

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
ansys-sim validate tests/fixtures/cantilever/simulation.yaml --json
ansys-sim compile tests/fixtures/cantilever/simulation.yaml --out build/cantilever --json
ansys-sim run tests/fixtures/cantilever/simulation.yaml \
  --out build/cantilever-dry-run \
  --json
```

Real execution requires a supported ANSYS Mechanical installation, license, matching body import name,
and optional PyAnsys dependencies. Start with `ansys-sim doctor --json`; then add `--execute` only on an
execution host.

The serial regressions in `tests/integration/test_ansys_real.py` require `ANSYS_AVAILABLE=1` and
accept an explicit `ANSYS_TEST_BACKEND=mechanical_batch` selection. This fixture retains
`pymechanical_remote` in its source specification; batch is never an implicit fallback after a
failed connection. See [Windows testing](../../../docs/windows-testing.md) for local setup.
