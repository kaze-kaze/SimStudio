from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from ansys_skill.compiler.mechanical import compile_simulation, render_script
from ansys_skill.schema import load_spec


def test_deterministic_compilation(valid_spec_path: Path, tmp_path: Path) -> None:
    spec, _ = load_spec(valid_spec_path)
    first = compile_simulation(spec, valid_spec_path, tmp_path / "first")
    second = compile_simulation(spec, valid_spec_path, tmp_path / "second")
    first_script = Path(first["generated_script"]).read_bytes()
    second_script = Path(second["generated_script"]).read_bytes()
    assert first_script == second_script
    compile(first_script, "generated-mechanical.py", "exec")


def test_compiler_does_not_embed_brief_or_arbitrary_python(
    valid_spec_path: Path, tmp_path: Path
) -> None:
    spec, _ = load_spec(valid_spec_path)
    artifacts = compile_simulation(spec, valid_spec_path, tmp_path / "run")
    script = Path(artifacts["generated_script"]).read_text(encoding="utf-8")
    assert "Euler-Bernoulli beam theory is an approximate benchmark" not in script
    assert "eval(" not in script
    assert "exec(" not in script
    assert "base64.b64decode" in script
    assert "ExtAPI.DataModel.GeoData.Unit" in script
    assert "units.ConvertUnit" in script
    assert 'if PLAN["mode"] != "template":\n            load.Name' in script
    assert 'if PLAN["mode"] != "template":\n            result.Name' in script
    assert "assert_static_structural" in script
    assert "analysis.AnalysisType" in script
    assert "analysis.PhysicsType" in script
    assert "analysis.AnalysisSettings.LargeDeflection = False" in script
    assert "assert_object_type" in script
    assert "namedselection" in script
    assert "fixedsupport" in script
    assert "equivalentstress" in script
    assert "GraphicsImageExportSettings()" in script
    assert "GraphicsResolutionType.EnhancedResolution" in script
    assert "settings,\n    )" in script


def test_manifest_hashes_and_artifacts(valid_spec_path: Path, tmp_path: Path) -> None:
    spec, _ = load_spec(valid_spec_path)
    artifacts = compile_simulation(spec, valid_spec_path, tmp_path / "run")
    manifest = json.loads(Path(artifacts["manifest"]).read_text(encoding="utf-8"))
    script_path = Path(artifacts["generated_script"])
    expected = hashlib.sha256(script_path.read_bytes()).hexdigest()
    assert manifest["hashes"]["generated_script_sha256"] == expected
    assert manifest["instance_owned_by_run"] is None
    assert manifest["remote_workdir"] is None
    assert "generated-mechanical.py" in manifest["artifacts"]
    assert "mechanical-plan.json" in manifest["artifacts"]


def test_windows_and_unicode_path_is_data_not_source() -> None:
    plan = {
        "plan_version": "1.0",
        "mode": "template",
        "input": {
            "absolute_path": "C:\\Program Files\\ANSYS Inc\\模型.mechdat",
            "basename": "模型.mechdat",
            "source_spec_directory": "C:\\work",
        },
    }
    script = render_script(plan)
    match = re.search(r'base64\.b64decode\("([^"]+)"\)', script)
    assert match is not None
    decoded = json.loads(base64.b64decode(match.group(1)).decode("utf-8"))
    assert decoded == plan
    compile(script, "generated.py", "exec")
