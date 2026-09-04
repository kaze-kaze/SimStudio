from __future__ import annotations

import sys
from types import ModuleType
from types import SimpleNamespace as NS

import pytest


def tree_object(name, kind, parent=None, **attributes):
    return NS(
        Name=name,
        ObjectId=id(name),
        Parent=parent,
        Children=[],
        Suppressed=False,
        GetType=lambda: NS(Name=kind),
        **attributes,
    )


def test_force_explicitly_uses_global_coordinates(mechanical_runtime):
    env = mechanical_runtime({})
    global_cs = NS(CoordinateSystemID=0)
    env.update(
        Model=NS(CoordinateSystems=NS(Children=[global_cs])),
        Quantity=lambda value: value,
        Ansys=NS(Mechanical=NS(DataModel=NS(Enums=NS(LoadDefineBy=NS(Components="Components"))))),
    )
    force = NS(
        CoordinateSystem="rotated",
        XComponent=NS(Output=NS()),
        YComponent=NS(Output=NS()),
        ZComponent=NS(Output=NS()),
    )
    env["MechanicalCompat"].set_components(force, ["1 [N]", "0 [N]", "0 [N]"])
    assert force.CoordinateSystem is global_cs
    assert force.XComponent.Output.DiscreteValues == ["1 [N]"]


@pytest.mark.parametrize("scope", [None, "tip"])
def test_template_results_are_synchronized(mechanical_runtime, scope):
    plan = {
        "mode": "template",
        "requested_results": [
            {
                "id": "direction",
                "type": "directional_deformation",
                "object_name": "Direction",
                "direction": "z",
            },
            {
                "id": "reaction",
                "type": "reaction_force",
                "object_name": "Reaction",
                "support": "shared",
            },
        ],
    }
    env = mechanical_runtime(plan)
    if scope:
        plan["requested_results"][0]["scope"] = scope
        env["PLAN"] = plan
        env["scope_location"] = lambda _: "tip selection"
    analysis = tree_object("Analysis", "Analysis")
    solution = tree_object("Solution", "Solution", analysis)
    analysis.Solution = solution
    direction = tree_object(
        "Direction",
        "DirectionalDeformation",
        solution,
        NormalOrientation="XAxis",
        Location="old scope",
        ScopingMethod="old method",
    )
    reaction = tree_object(
        "Reaction", "ForceReaction", solution, BoundaryConditionSelection="old support"
    )
    support = tree_object("Support", "FixedSupport", analysis)
    objects = {"Direction": direction, "Reaction": reaction}
    env.update(
        DataModel=NS(GetObjectsByName=lambda name: [objects[name]]),
        Model=NS(CoordinateSystems=NS(Children=[NS(CoordinateSystemID=0)]), Geometry=NS()),
        Ansys=NS(
            Mechanical=NS(
                DataModel=NS(
                    Enums=NS(
                        NormalOrientationType=NS(ZAxis="ZAxis"),
                        GeometryDefineByType=NS(
                            GeometrySelection="GeometrySelection", NamedSelection="NamedSelection"
                        ),
                        LocationDefinitionMethod=NS(BoundaryCondition="BoundaryCondition"),
                    )
                )
            )
        ),
    )
    env["CREATED"]["supports"] = {"shared": support}
    env["CREATED"]["loads"] = {"shared": NS()}
    env["MechanicalCompat"].all_body_selection = lambda: "all bodies"
    env["apply_results"](analysis)
    assert direction.NormalOrientation == "ZAxis"
    assert direction.Location == ("tip selection" if scope else "all bodies")
    assert reaction.BoundaryConditionSelection is support
    assert env["CREATED"]["results"]["reaction"] is reaction


def test_template_object_must_belong_to_selected_analysis(mechanical_runtime):
    env = mechanical_runtime({})
    analysis = tree_object("selected", "Analysis")
    other = tree_object("other", "Analysis")
    load = tree_object("Force", "Force", other)
    with pytest.raises(env["TextToAnsysError"], match="selected analysis"):
        env["MechanicalCompat"].assert_in_analysis(load, analysis)


def test_project_open_uses_remote_globals_and_refreshes_model(mechanical_runtime):
    env = mechanical_runtime({"mode": "template"})
    calls = []
    project = NS(Open=lambda path: calls.append(path), Model=NS())
    data_model = NS(Project=project)
    env.update(ExtAPI=NS(DataModel=data_model), Model="old model", DataModel="old data model")
    env["MechanicalCompat"].open_project("template.mechdat")
    assert calls == ["template.mechdat"]
    assert env["Model"] is project.Model
    assert env["DataModel"] is data_model


def test_extra_geometry_body_is_rejected(mechanical_runtime):
    env = mechanical_runtime({"mode": "from_geometry", "bodies": [{"name": "Beam"}]})
    env["MechanicalCompat"].tree_bodies = lambda: [
        tree_object("Beam", "Body"),
        tree_object("extra", "Body"),
    ]
    with pytest.raises(env["TextToAnsysError"], match="bodies"):
        env["MechanicalCompat"].assert_body_inventory()


def test_artifacts_use_analysis_paths_and_unicode_run_directory(mechanical_runtime, tmp_path):
    env = mechanical_runtime({"output": {"save_project": False, "export_images": False}})
    solver = tmp_path / "external solver"
    solver.mkdir()
    (solver / "file.rst").write_bytes(b"offline fixture")
    (solver / "solve.out").write_text("solver log")
    run = tmp_path / "测试 results"
    run.mkdir()
    env["RUN_DIRECTORY"] = str(run)
    env["CREATED"]["analysis"] = NS(
        ResultFileName=str(solver / "file.rst"), SolverFilesDirectory=str(solver)
    )
    env["ExtAPI"] = NS(Application=NS(Messages=[]))
    payload = env["write_artifacts"]("SOLVED")
    assert payload["status"] == "SOLVED"
    assert payload["result_files"] == [str(run / "solver/file.rst")]
    assert (run / "solver/file.rst").read_bytes() == b"offline fixture"
    assert (run / "mechanical-artifacts.json").read_text(encoding="utf-8")


def test_early_failure_preserves_original_error(mechanical_runtime, tmp_path):
    env = mechanical_runtime({"output": {}})
    env["RUN_DIRECTORY"] = str(tmp_path)
    env["CREATED"]["analysis"] = NS()
    error = {"type": "UnsupportedMechanicalApi", "message": "original error"}
    payload = env["write_artifacts"]("FAILED", error)
    assert payload["error"] == error
    assert payload["result_files"] == []


@pytest.mark.parametrize("extra", [None, "Bilinear Isotropic Hardening"])
def test_material_inventory_rejects_nonlinear_properties(mechanical_runtime, monkeypatch, extra):
    env = mechanical_runtime({})
    properties = ["Density", "Elasticity"] + ([extra] if extra else [])
    module = ModuleType("materials")
    module.GetListMaterialProperties = lambda _: properties
    monkeypatch.setitem(sys.modules, "materials", module)
    body = NS(Name="Beam", Material="Steel", GetEngineeringDataMaterial=lambda: object())
    if extra:
        with pytest.raises(env["TextToAnsysError"], match="unsupported"):
            env["MechanicalCompat"].assert_linear_material(body)
    else:
        env["MechanicalCompat"].assert_linear_material(body)
        assert env["ANALYSIS_INFO"]["material_properties"]["Beam"] == properties


@pytest.mark.parametrize("extra_kind", [None, "Force", "ContactRegion"])
def test_actual_model_rejects_undeclared_or_unsupported_objects(mechanical_runtime, extra_kind):
    env = mechanical_runtime({"mode": "template", "loads": [], "supports": []})
    model = tree_object("Model", "Model")
    analysis = tree_object("Static Structural", "Analysis", model)
    model.Analyses = [analysis]
    model.Children = [analysis]
    if extra_kind:
        analysis.Children = [tree_object("undeclared", extra_kind, analysis)]
    env["Model"] = model
    if extra_kind:
        with pytest.raises(env["TextToAnsysError"], match=r"U(?:nsupported|ndeclared)"):
            env["MechanicalCompat"].assert_model_contract(analysis)
    else:
        env["MechanicalCompat"].assert_model_contract(analysis)
