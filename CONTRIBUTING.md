# Contributing

Use Python 3.11–3.13. This shared range covers both the base package and the optional PyDPF workflow;
record any compatibility change in the official API map.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
ruff check .
pytest -q
```

To regenerate the neutral cantilever STEP fixture:

```bash
python -m pip install -e ".[cad-fixture]"
python examples/cantilever/generate_geometry.py
```

Do not commit ANSYS projects, result files, logs containing private paths, license data, or vendor
material databases. Real integration tests must use `@pytest.mark.ansys_integration` and require an
explicit `ANSYS_AVAILABLE=1` opt-in.

Before submitting a change, inspect the diff, run the offline suite, validate the Skill and plugin
manifest, and report any real integration that was not run.
