# Contributing

Use Python 3.11–3.13 for the base CLI and offline tests. The optional ANSYS clients require
Python 3.12–3.13 within this project's supported range; Python 3.13 is recommended for real runs.
Record any compatibility change in the official API map.
For a licensed Windows acceptance run, see [Windows testing](docs/windows-testing.md).

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

For changes to the public demonstration, follow [the site build and visual QA guide](docs/site/README.md).
Keep the English and [Chinese README](README.zh-CN.md) aligned. New APIs need their exact version
and signature recorded in the official API map; changes to evidence must preserve provenance.

Report reproducible defects through the issue template. For a new physics scope or a breaking
interface change, discuss the proposal in an issue before expanding the v1 Skill.
