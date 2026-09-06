from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest
from ansys_skill.cli import _find_result_file, _real_postprocess
from ansys_skill.errors import PostprocessingError
from ansys_skill.postprocessing.dpf import _equivalent_stress, _evaluate, _resolve_scope
from ansys_skill.postprocessing.fields import field_summary
from ansys_skill.schema import load_spec


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (["TTA_SCOPE_LOAD_FACE"], "TTA_SCOPE_LOAD_FACE"),
        ([], None),
        (["LOAD_FACE", "load_face"], None),
    ],
)
def test_named_selection_is_resolved_against_actual_rst_names(available, expected):
    model = NS(metadata=NS(available_named_selections=available))
    name = "tta_scope_load_face" if expected else "load_face"
    if expected:
        assert _resolve_scope(model, name) == expected
    else:
        with pytest.raises(PostprocessingError, match="Expected one"):
            _resolve_scope(model, name)


def test_stress_requests_nodal_values_before_reporting_entity_ids():
    events = []

    class Provider:
        def on_named_selection(self, name):
            events.append(name)
            return self

        def on_location(self, location):
            events.append(location)
            return self

        @property
        def on_last_time_freq(self):
            return self

        def eval(self):
            return ["field"]

    assert _evaluate(Provider(), "TIP", nodal=True) == ["field"]
    assert events == ["TIP", "Nodal"]
    field = NS(unit="Pa", location="ElementalNodal", data=[1.0, 2.0], scoping=NS(ids=[10]))
    with pytest.raises(PostprocessingError, match="one-to-one"):
        field_summary([field], dimension="pressure")


@pytest.mark.parametrize("scope", [None, "TIP"])
def test_equivalent_stress_is_derived_from_tensor_with_mechanical_averaging(scope):
    calls = []
    field = NS(unit="Pa", location="Nodal", data=[10.0], scoping=NS(ids=[42]))

    def operator(**kwargs):
        calls.append(kwargs)
        return NS(outputs=NS(fields_container=lambda: [field]))

    model = NS(results=NS(stress=object()), _server=object(), metadata=NS(
        data_sources=object(), time_freq_support=NS(n_sets=3),
        named_selection=lambda name: (name, [42]),
    ))
    dpf = NS(operators=NS(result=NS(stress_eqv_as_mechanical=operator)))
    fields = _equivalent_stress(dpf, model, scope)
    assert calls == [{
        "data_sources": model.metadata.data_sources, "time_scoping": [3],
        "mesh_scoping": ("TIP", [42]) if scope else None,
        "requested_location": "Nodal", "server": model._server,
    }]
    assert field_summary(fields, dimension="pressure")["scoping_id"] == 42


def test_recorded_result_takes_precedence_over_project_copy(tmp_path):
    result = tmp_path / "solver/file.rst"
    result.parent.mkdir()
    result.write_bytes(b"current result")
    (tmp_path / "project-copy.rst").write_bytes(b"same solve, project copy")
    (tmp_path / "mechanical-artifacts.json").write_text(
        json.dumps({"result_files": ["solver/file.rst"]})
    )
    assert _find_result_file(tmp_path) == result


def test_image_export_is_not_visual_review(tmp_path, valid_spec_path, monkeypatch):
    from ansys_skill import cli

    spec, _ = load_spec(valid_spec_path)
    (tmp_path / "file.rst").write_bytes(b"fixture")
    (tmp_path / "mechanical-artifacts.json").write_text(
        json.dumps({"visual_review": [{"name": "mesh.png", "status": "PASS"}]})
    )
    monkeypatch.setattr(cli, "inspect_result_file", lambda *_: {"results": {}})
    _, verification = _real_postprocess(tmp_path, spec, [])
    checks = {item["name"]: item["status"] for item in verification["checks"]}
    assert checks["image_export"] == "PASS"
    assert checks["visual_review"] == "NOT_RUN"
