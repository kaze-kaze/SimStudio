# Mechanical-injected globals; compatible with IronPython 2.7.
def prepare_model():
    input_path = MechanicalCompat.input_path()
    MechanicalCompat.open_project(input_path)
    if PLAN["mode"] == "template":
        analysis = MechanicalCompat.exact_object(PLAN["analysis"]["object_name"])
    else:
        geometry_import = Model.AddGeometryImportGroup().AddGeometryImport()
        preferences = Ansys.ACT.Mechanical.Utilities.GeometryImportPreferences()
        geometry_import.Import(
            input_path,
            Ansys.Mechanical.DataModel.Enums.GeometryImportPreference.Format.Automatic,
            preferences,
        )
        analysis = Model.AddStaticStructuralAnalysis()
        analysis.Name = "text-to-ansys static structural"
    ANALYSIS_INFO.update(MechanicalCompat.assert_static_structural(analysis))
    CREATED["analysis"] = analysis
    MechanicalCompat.assert_body_inventory()
    MechanicalCompat.assert_model_contract(analysis)
    return analysis


def apply_materials():
    for body_plan in PLAN["bodies"]:
        if body_plan["material_source"] != "engineering_data":
            raise UnsupportedMechanicalApi(
                "Custom material authoring is intentionally disabled in v1"
            )
        body = MechanicalCompat.exact_tree_body(body_plan["name"])
        body.Material = body_plan["material_name"]
        MechanicalCompat.assert_linear_material(body)


def apply_mesh():
    Model.Mesh.ElementSize = Quantity(PLAN["mesh"]["global_element_size"])
    order = PLAN["mesh"]["element_order"]
    if order != "program_controlled":
        try:
            Model.Mesh.ElementOrder = getattr(
                Ansys.Mechanical.DataModel.Enums.ElementOrder,
                "Linear" if order == "linear" else "Quadratic",
            )
        except Exception as exc:
            raise UnsupportedMechanicalApi("Mesh element-order API is unavailable: {}".format(exc))
    Model.Mesh.GenerateMesh()


def apply_supports(analysis):
    for item in PLAN["supports"]:
        if PLAN["mode"] == "template":
            support = MechanicalCompat.assert_object_type(
                MechanicalCompat.exact_object(item["object_name"]),
                {"fixedsupport"},
                "support:{}".format(item["id"]),
            )
            MechanicalCompat.assert_in_analysis(support, analysis)
        else:
            support = analysis.AddFixedSupport()
            support.Name = item["id"]
        support.Location = scope_location(item["scope"])
        support.Suppressed = False
        CREATED["supports"][item["id"]] = support


def apply_loads(analysis):
    for item in PLAN["loads"]:
        if PLAN["mode"] == "template":
            expected = {
                "force": {"force"},
                "pressure": {"pressure"},
                "gravity": {"earthgravity"},
            }[item["type"]]
            load = MechanicalCompat.assert_object_type(
                MechanicalCompat.exact_object(item["object_name"]),
                expected,
                "load:{}".format(item["id"]),
            )
            MechanicalCompat.assert_in_analysis(load, analysis)
        elif item["type"] == "force":
            load = analysis.AddForce()
        elif item["type"] == "pressure":
            load = analysis.AddPressure()
        elif item["type"] == "gravity":
            load = analysis.AddEarthGravity()
        else:
            raise TextToAnsysError("Unsupported load type: {}".format(item["type"]))
        if PLAN["mode"] != "template":
            load.Name = item["id"]
        if item.get("scope"):
            load.Location = scope_location(item["scope"])
        load.Suppressed = False
        if item["type"] == "force":
            MechanicalCompat.set_components(load, item["components"])
        elif item["type"] == "gravity":
            load.CoordinateSystem = MechanicalCompat.global_coordinate_system()
            load.Direction = getattr(
                Ansys.Mechanical.DataModel.Enums.GravityOrientationType,
                item["gravity_orientation"],
            )
        else:
            load.Magnitude.Output.DiscreteValues = [Quantity(item["magnitude"])]
        CREATED["loads"][item["id"]] = load


def apply_results(analysis):
    solution = analysis.Solution
    for item in PLAN["requested_results"]:
        if item["type"] in ("solver_messages", "node_count", "element_count"):
            continue
        if PLAN["mode"] == "template":
            expected = {
                "total_deformation": {"totaldeformation"},
                "directional_deformation": {"directionaldeformation"},
                "equivalent_von_mises_stress": {"equivalentstress"},
                "reaction_force": {"forcereaction"},
            }[item["type"]]
            result = MechanicalCompat.assert_object_type(
                MechanicalCompat.exact_object(item["object_name"]),
                expected,
                "result:{}".format(item["id"]),
            )
            MechanicalCompat.assert_in_analysis(result, analysis)
        elif item["type"] == "total_deformation":
            result = solution.AddTotalDeformation()
        elif item["type"] == "directional_deformation":
            result = solution.AddDirectionalDeformation()
        elif item["type"] == "equivalent_von_mises_stress":
            result = solution.AddEquivalentStress()
        elif item["type"] == "reaction_force":
            result = solution.AddForceReaction()
        else:
            raise TextToAnsysError("Unsupported result type: {}".format(item["type"]))
        if PLAN["mode"] != "template":
            result.Name = item["id"]
        MechanicalCompat.configure_result(result, item)
        CREATED["results"][item["id"]] = result
