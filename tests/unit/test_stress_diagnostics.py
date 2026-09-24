from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace as NS

import pytest
from ansys_skill.postprocessing.dpf import inspect_result_file
from ansys_skill.postprocessing.stress_diagnostics import (
    collect_global_stress_diagnostics,
)
from ansys_skill.schema import load_spec


def _fixture(
    tmp_path: Path, *, nodal_location: str = "Nodal", nodal_values: list[float] | None = None
):
    rst = tmp_path / "result.rst"
    rst.write_bytes(b"small DPF fixture")
    coordinates = NS(
        unit="mm",
        scoping=NS(ids=list(range(1, 25))),
        data=[[node_id, 2 * node_id, 3 * node_id] for node_id in range(1, 25)],
    )
    elements = {101: NS(type="tet10", node_ids=list(range(1, 11)))}
    elements.update(
        {element_id: NS(type="tet4", node_ids=[1, 2, 3, 4]) for element_id in range(202, 223)}
    )

    class NodeCollection:
        coordinates_field = coordinates

        def __len__(self):
            return len(coordinates.scoping.ids)

    class ElementCollection:
        def __len__(self):
            return len(elements)

        @staticmethod
        def element_by_id(element_id: int):
            return elements[element_id]

    mesh = NS(
        unit="mm",
        nodes=NodeCollection(),
        elements=ElementCollection(),
    )
    model = NS(
        _server=object(),
        metadata=NS(
            meshed_region=mesh,
            data_sources=object(),
            time_freq_support=NS(n_sets=7),
            available_named_selections=["TTA_SCOPE_LOAD_FACE"],
            named_selection=lambda name: {"scope": name},
        ),
    )
    nodal = NS(
        location=nodal_location,
        unit="MPa",
        scoping=NS(ids=list(range(1, 25))),
        data=(list(map(float, range(1, 25))) if nodal_values is None else nodal_values),
    )

    class ElementalNodalField:
        location = "ElementalNodal"
        unit = "MPa"
        scoping = NS(ids=[101, *range(202, 223)])

        @staticmethod
        def get_entity_data_by_id(element_id: int):
            if element_id == 101:
                return [10.0, 11.0, 12.0, 13.0]
            return [float(element_id - 200), float(element_id - 199)]

    calls = []
    scoped_nodal = NS(
        location=nodal_location,
        unit="MPa",
        scoping=NS(ids=[1]),
        data=[1.0],
    )

    def operator(field, *, scoped_field=None):
        def build(**kwargs):
            calls.append(kwargs)
            selected = scoped_field if kwargs.get("mesh_scoping") is not None else field
            return NS(outputs=NS(fields_container=lambda: [selected]))

        return build

    dpf = NS(
        operators=NS(
            result=NS(
                stress_eqv_as_mechanical=operator(nodal, scoped_field=scoped_nodal),
                stress_von_mises=operator(ElementalNodalField()),
            ),
        ),
        Model=lambda _path: model,
    )
    return rst, dpf, model, calls


def test_global_stress_diagnostics_records_units_locations_and_true_extrema(tmp_path):
    rst, dpf, model, calls = _fixture(tmp_path)
    diagnostics = collect_global_stress_diagnostics(rst, dpf, model)

    assert diagnostics["status"] == "COMPLETED"
    assert diagnostics["scope"] == "global"
    assert diagnostics["result_file_sha256"] == hashlib.sha256(b"small DPF fixture").hexdigest()
    assert diagnostics["last_result_set"] == 7
    assert calls[0]["requested_location"] == "Nodal"
    assert calls[0]["time_scoping"] == [7]
    assert calls[0]["server"] is model._server
    assert "mesh_scoping" not in calls[0]
    assert calls[1]["requested_location"] == "ElementalNodal"
    assert calls[1]["time_scoping"] == [7]
    assert calls[1]["server"] is model._server
    assert "mesh_scoping" not in calls[1]
    assert diagnostics["nodal"]["location"] == "Nodal"
    assert diagnostics["nodal"]["maximum"]["node_id"] == 24
    assert diagnostics["nodal"]["maximum"]["coordinate_m"] == pytest.approx([0.024, 0.048, 0.072])
    assert diagnostics["nodal"]["maximum"]["raw_max"] == 24.0
    assert diagnostics["nodal"]["maximum"]["raw_max_unit"] == "MPa"
    assert diagnostics["nodal"]["maximum"]["value_Pa"] == 24_000_000.0
    assert len(diagnostics["nodal"]["top_20"]) == 20
    assert diagnostics["elemental_nodal"]["location"] == "ElementalNodal"
    assert len(diagnostics["elemental_nodal"]["top_20"]) == 20
    tet10 = next(
        item for item in diagnostics["elemental_nodal"]["top_20"] if item["element_id"] == 101
    )
    assert len(tet10["raw_stress_values"]) == 4
    assert len(tet10["node_ids"]) == 10
    assert len(tet10["node_coordinates_m"]) == 10
    assert tet10["value_node_mapping"].startswith("unassigned")
    assert diagnostics["elemental_nodal"]["maximum"]["raw_max"] == 23.0
    assert diagnostics["elemental_nodal"]["maximum"]["raw_max_unit"] == "MPa"
    assert diagnostics["last_result_set"] == 7


def test_element_values_are_not_mapped_to_tet10_nodes(tmp_path):
    rst, dpf, model, _ = _fixture(tmp_path)
    diagnostics = collect_global_stress_diagnostics(rst, dpf, model)

    serialized = json.dumps(diagnostics, allow_nan=False)
    assert diagnostics["status"] == "COMPLETED"
    assert "singularity" not in serialized.lower()
    tet10 = next(
        item for item in diagnostics["elemental_nodal"]["top_20"] if item["element_id"] == 101
    )
    assert tet10["raw_stress_values"] == [10.0, 11.0, 12.0, 13.0]
    assert len(tet10["node_ids"]) == 10
    assert tet10["value_node_mapping"].startswith("unassigned")


def test_nodal_location_mismatch_is_explicit_not_run(tmp_path):
    rst, dpf, model, _ = _fixture(tmp_path, nodal_location="ElementalNodal")
    diagnostics = collect_global_stress_diagnostics(rst, dpf, model)

    assert diagnostics["status"] == "NOT_RUN"
    assert "Expected nodal Mechanical-averaged stress" in diagnostics["reason"]


@pytest.mark.parametrize(
    ("values", "reason"),
    [([], "one-to-one"), ([float("nan")], "non-finite")],
)
def test_empty_or_non_finite_stress_is_not_recorded_as_success(
    tmp_path: Path, values: list[float], reason: str
):
    rst, dpf, model, _ = _fixture(tmp_path, nodal_values=values)
    diagnostics = collect_global_stress_diagnostics(rst, dpf, model)

    assert diagnostics["status"] == "NOT_RUN"
    assert diagnostics["reason"]
    assert reason in diagnostics["reason"]
    assert "nodal" not in diagnostics
    assert "elemental_nodal" not in diagnostics


def test_inspection_attaches_global_diagnostics_even_for_a_scoped_stress_request(
    valid_spec_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    rst, dpf, model, calls = _fixture(tmp_path)
    ansys = ModuleType("ansys")
    ansys.__path__ = []
    ansys_dpf = ModuleType("ansys.dpf")
    ansys_dpf.core = dpf
    monkeypatch.setitem(sys.modules, "ansys", ansys)
    monkeypatch.setitem(sys.modules, "ansys.dpf", ansys_dpf)

    base_spec, _ = load_spec(valid_spec_path)
    stress_request = next(
        item
        for item in base_spec.requested_results
        if item.type.value == "equivalent_von_mises_stress"
    ).model_copy(update={"scope": "load_face"})
    spec = base_spec.model_copy(update={"requested_results": [stress_request]})

    summary = inspect_result_file(rst, spec)

    assert summary["status"] == "POSTPROCESSED"
    assert summary["synthetic"] is False
    assert summary["global_stress_diagnostics"]["status"] == "COMPLETED"
    assert summary["global_stress_diagnostics"]["scope"] == "global"
    eqv_calls = [call for call in calls if call.get("requested_location") == "Nodal"]
    assert len(eqv_calls) == 2
    assert eqv_calls[0]["mesh_scoping"] == {"scope": "TTA_SCOPE_LOAD_FACE"}
    assert "mesh_scoping" not in eqv_calls[1]
    assert eqv_calls[1]["server"] is model._server


def test_diagnostics_failure_keeps_real_postprocessing_and_reports_not_run(
    valid_spec_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    rst, dpf, _model, _calls = _fixture(tmp_path)
    original_operator = dpf.operators.result.stress_von_mises

    def failed_diagnostics_operator(**kwargs):
        if kwargs.get("requested_location") == "ElementalNodal":
            raise RuntimeError("fixture DPF diagnostic failure")
        return original_operator(**kwargs)

    dpf.operators.result.stress_von_mises = failed_diagnostics_operator
    ansys = ModuleType("ansys")
    ansys.__path__ = []
    ansys_dpf = ModuleType("ansys.dpf")
    ansys_dpf.core = dpf
    monkeypatch.setitem(sys.modules, "ansys", ansys)
    monkeypatch.setitem(sys.modules, "ansys.dpf", ansys_dpf)

    base_spec, _ = load_spec(valid_spec_path)
    stress_request = next(
        item
        for item in base_spec.requested_results
        if item.type.value == "equivalent_von_mises_stress"
    )
    spec = base_spec.model_copy(update={"requested_results": [stress_request]})

    summary = inspect_result_file(rst, spec)

    assert summary["status"] == "POSTPROCESSED"
    assert summary["synthetic"] is False
    assert summary["global_stress_diagnostics"]["status"] == "NOT_RUN"
    assert "fixture DPF diagnostic failure" in summary["global_stress_diagnostics"]["reason"]
    assert summary["results"]["equivalent_stress"]["canonical_maximum"] == 24_000_000.0
