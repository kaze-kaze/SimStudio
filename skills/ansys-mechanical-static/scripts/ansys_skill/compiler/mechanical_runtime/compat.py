# Mechanical-injected globals; compatible with IronPython 2.7.
class TextToAnsysError(RuntimeError):
    pass


class UnsupportedMechanicalApi(TextToAnsysError):
    pass


class MechanicalCompat(object):
    """All version-sensitive Mechanical object-model access lives here."""

    @staticmethod
    def open_project(input_path):
        global Model, DataModel
        project = ExtAPI.DataModel.Project
        if PLAN["mode"] == "template":
            project.Open(input_path)
        else:
            project.New()
        DataModel = ExtAPI.DataModel
        Model = DataModel.Project.Model

    @staticmethod
    def save_project():
        path = os.path.join(RUN_DIRECTORY, "text-to-ansys.mechdb")
        ExtAPI.DataModel.Project.SaveAs(path, True)
        return path

    @staticmethod
    def collect_solver_files():
        analysis = CREATED.get("analysis")
        if analysis is None:
            return [], []
        result_path = TEXT_TYPE(analysis.ResultFileName or "")
        solver_dir = TEXT_TYPE(analysis.SolverFilesDirectory or analysis.WorkingDir or "")
        ANALYSIS_INFO["solver_directory"] = solver_dir
        outputs = []
        for path in (result_path, os.path.join(solver_dir, "solve.out") if solver_dir else ""):
            if not path or not os.path.isfile(path):
                outputs.append([])
                continue
            destination_dir = os.path.join(RUN_DIRECTORY, "solver")
            if not os.path.isdir(destination_dir):
                os.makedirs(destination_dir)
            destination = os.path.join(destination_dir, os.path.basename(path))
            if os.path.normcase(os.path.abspath(path)) != os.path.normcase(os.path.abspath(destination)):
                shutil.copy2(path, destination)
            outputs.append([destination])
        return outputs[0], outputs[1]

    @staticmethod
    def global_coordinate_system():
        matches = [item for item in Model.CoordinateSystems.Children
                   if int(item.CoordinateSystemID) == 0]
        if len(matches) != 1:
            raise TextToAnsysError("Expected exactly one global coordinate system")
        return matches[0]

    @staticmethod
    def assert_in_analysis(obj, analysis):
        current = obj.Parent
        while current is not None:
            if current.ObjectId == analysis.ObjectId:
                return obj
            current = current.Parent
        raise TextToAnsysError("Object {!r} is not in the selected analysis".format(obj.Name))

    @staticmethod
    def assert_body_inventory():
        bodies = [body for body in MechanicalCompat.tree_bodies() if not body.Suppressed]
        expected = sorted(body["name"] for body in PLAN["bodies"])
        actual = sorted(TEXT_TYPE(body.Name) for body in bodies)
        if actual != expected or (PLAN["mode"] == "from_geometry" and len(bodies) != 1):
            raise TextToAnsysError("Active geometry bodies {} do not match declared bodies {}".format(actual, expected))
        return bodies

    @staticmethod
    def all_body_selection():
        return MechanicalCompat.selection_from_entities(
            [body.GetGeoBody() for body in MechanicalCompat.assert_body_inventory()]
        )

    @staticmethod
    def configure_result(result, item):
        result.Suppressed = False
        if item["type"] == "reaction_force":
            result.LocationMethod = Ansys.Mechanical.DataModel.Enums.LocationDefinitionMethod.BoundaryCondition
            result.BoundaryConditionSelection = CREATED["supports"][item["support"]]
            result.Orientation = MechanicalCompat.global_coordinate_system()
        else:
            result.ScopingMethod = (Ansys.Mechanical.DataModel.Enums.GeometryDefineByType.NamedSelection
                                    if item.get("scope") else Ansys.Mechanical.DataModel.Enums.GeometryDefineByType.GeometrySelection)
            result.Location = scope_location(item["scope"]) if item.get("scope") else MechanicalCompat.all_body_selection()
            result.CoordinateSystem = MechanicalCompat.global_coordinate_system()
            if item["type"] == "directional_deformation":
                MechanicalCompat.set_directional_axis(result, item["direction"])

    @staticmethod
    def assert_linear_material(body):
        import materials
        material = body.GetEngineeringDataMaterial()
        properties = list(materials.GetListMaterialProperties(material))
        names = ["".join(c for c in TEXT_TYPE(name).lower() if c.isalnum()) for name in properties]
        allowed = {"density", "elasticity", "isotropicelasticity",
                   "tensileyieldstrength", "compressiveyieldstrength",
                   "tensileultimatestrength", "compressiveultimatestrength",
                   "thermalconductivity", "isotropicthermalconductivity",
                   "specificheat", "specificheatconstantpressure",
                   "coefficientofthermalexpansion", "isotropicsecantcoefficientofthermalexpansion",
                   "sncurve", "strainlifeparameters", "alternatingstress", "strainlife"}
        unsupported = [name for name in names if name not in allowed]
        if unsupported or not ({"elasticity", "isotropicelasticity"} & set(names)):
            raise TextToAnsysError("Material {!r} has unsupported or unverified properties: {}".format(body.Material, properties))
        ANALYSIS_INFO.setdefault("material_properties", {})[TEXT_TYPE(body.Name)] = [TEXT_TYPE(name) for name in properties]

    @staticmethod
    def assert_model_contract(analysis):
        if len(list(Model.Analyses)) != 1:
            raise TextToAnsysError("Exactly one analysis is supported per model")
        allowed_loads = set(item["object_name"] for item in PLAN["loads"] + PLAN["supports"] if item.get("object_name"))
        allowed_types = {"analysissettings", "solution", "solutioninformation", "treegroupingfolder"}
        forbidden_types = {"contactregion", "joint", "spring", "commandsnippet", "pythoncode", "pythoncodeeventbased"}
        pending = [Model]
        while pending:
            obj = pending.pop()
            if bool(getattr(obj, "Suppressed", False)):
                continue
            kind = TEXT_TYPE(obj.GetType().Name).lower()
            if kind in forbidden_types:
                raise TextToAnsysError("Unsupported active model object: {} ({})".format(obj.Name, kind))
            pending.extend(list(obj.Children))
        if PLAN["mode"] == "template":
            pending = list(analysis.Children)
            while pending:
                obj = pending.pop()
                if bool(getattr(obj, "Suppressed", False)):
                    continue
                kind = TEXT_TYPE(obj.GetType().Name).lower()
                if kind == "solution":
                    continue
                if kind not in allowed_types and TEXT_TYPE(obj.Name) not in allowed_loads:
                    raise TextToAnsysError("Undeclared active analysis object: {} ({})".format(obj.Name, kind))
                pending.extend(list(obj.Children))

    @staticmethod
    def exact_object(name):
        matches = list(DataModel.GetObjectsByName(name))
        if len(matches) != 1:
            raise TextToAnsysError(
                "Expected exactly one Mechanical object named {!r}; found {}".format(
                    name, len(matches)
                )
            )
        return matches[0]

    @staticmethod
    def assert_object_type(obj, expected, label):
        try:
            type_name = TEXT_TYPE(obj.GetType().Name)
        except Exception as exc:
            raise UnsupportedMechanicalApi(
                "Mechanical object type inspection is unavailable for {}: {}".format(label, exc)
            )
        normalized = "".join(character for character in type_name.lower() if character.isalnum())
        if normalized not in expected:
            raise TextToAnsysError(
                "{} expected object type {}; found {!r}".format(
                    label, sorted(expected), type_name
                )
            )
        OBJECT_TYPES[label] = type_name
        return obj

    @staticmethod
    def input_path():
        for directory in (os.path.join(RUN_DIRECTORY, "inputs"), RUN_DIRECTORY):
            candidate = os.path.join(directory, PLAN["input"]["basename"])
            if os.path.isfile(candidate):
                return candidate
        raise TextToAnsysError("Compiled input snapshot is unavailable in {}".format(RUN_DIRECTORY))

    @staticmethod
    def tree_bodies():
        try:
            return list(
                DataModel.GetObjectsByType(
                    Ansys.Mechanical.DataModel.Enums.DataModelObjectCategory.Body
                )
            )
        except Exception as exc:
            raise UnsupportedMechanicalApi(
                "DataModel.GetObjectsByType(DataModelObjectCategory.Body) is unavailable: {}".format(exc)
            )

    @staticmethod
    def exact_tree_body(name):
        matches = [body for body in MechanicalCompat.tree_bodies() if TEXT_TYPE(body.Name) == name]
        if len(matches) != 1:
            raise TextToAnsysError(
                "Expected exactly one geometry body named {!r}; found {}".format(name, len(matches))
            )
        return matches[0]

    @staticmethod
    def geo_bodies():
        try:
            bodies = []
            for assembly in ExtAPI.DataModel.GeoData.Assemblies:
                for part in assembly.Parts:
                    bodies.extend(list(part.Bodies))
            return bodies
        except Exception as exc:
            raise UnsupportedMechanicalApi(
                "Geometry traversal API required by axis_extreme_face is unavailable: {}".format(exc)
            )

    @staticmethod
    def exact_geo_body(name):
        bodies = MechanicalCompat.geo_bodies()
        matches = [body for body in bodies if TEXT_TYPE(body.Name) == name] if name else bodies
        if len(matches) != 1:
            raise TextToAnsysError(
                "axis_extreme_face requires exactly one matching body; found {} for {!r}".format(
                    len(matches), name
                )
            )
        return matches[0]

    @staticmethod
    def face_data(face, geometry_unit):
        try:
            centroid = [float(value) for value in face.Centroid]
            area = float(face.Area)
            uv = face.ParamAtPoint(face.Centroid)
            normal = [float(value) for value in face.NormalAtParam(uv[0], uv[1])]
            return {
                "id": int(face.Id),
                "centroid": centroid,
                "centroid_unit": geometry_unit,
                "area": area,
                "area_unit": "{}^2".format(geometry_unit),
                "normal": normal,
            }
        except Exception as exc:
            raise UnsupportedMechanicalApi(
                "IGeoFace Centroid/Area/ParamAtPoint/NormalAtParam API is unavailable: {}".format(exc)
            )

    @staticmethod
    def selection_from_entities(entities):
        try:
            selection = ExtAPI.SelectionManager.CreateSelectionInfo(
                Ansys.ACT.Interfaces.Common.SelectionTypeEnum.GeometryEntities
            )
            selection.Entities = list(entities)
            return selection
        except Exception as exc:
            raise UnsupportedMechanicalApi(
                "Geometry entity selection API is unavailable: {}".format(exc)
            )

    @staticmethod
    def set_components(load, values):
        load.CoordinateSystem = MechanicalCompat.global_coordinate_system()
        load.DefineBy = Ansys.Mechanical.DataModel.Enums.LoadDefineBy.Components
        load.XComponent.Output.DiscreteValues = [Quantity(values[0])]
        load.YComponent.Output.DiscreteValues = [Quantity(values[1])]
        load.ZComponent.Output.DiscreteValues = [Quantity(values[2])]

    @staticmethod
    def set_directional_axis(result, axis):
        enum_name = {"x": "XAxis", "y": "YAxis", "z": "ZAxis"}[axis]
        try:
            result.NormalOrientation = getattr(
                Ansys.Mechanical.DataModel.Enums.NormalOrientationType, enum_name
            )
        except Exception as exc:
            raise UnsupportedMechanicalApi(
                "Directional deformation orientation API is unavailable: {}".format(exc)
            )

    @staticmethod
    def assert_static_structural(analysis):
        try:
            analysis_type = TEXT_TYPE(analysis.AnalysisType)
            physics_type = TEXT_TYPE(analysis.PhysicsType)
            analysis.AnalysisSettings.LargeDeflection = False
            large_deflection = bool(analysis.AnalysisSettings.LargeDeflection)
        except Exception as exc:
            raise UnsupportedMechanicalApi(
                "Analysis type or LargeDeflection API is unavailable: {}".format(exc)
            )
        if "static" not in analysis_type.lower() or "structural" not in physics_type.lower():
            raise TextToAnsysError(
                "Expected a static structural analysis; found AnalysisType={!r}, "
                "PhysicsType={!r}".format(analysis_type, physics_type)
            )
        if large_deflection:
            raise TextToAnsysError("LargeDeflection remained enabled; small-deformation solve blocked")
        return {
            "analysis_type": analysis_type,
            "physics_type": physics_type,
            "large_deflection": large_deflection,
        }
