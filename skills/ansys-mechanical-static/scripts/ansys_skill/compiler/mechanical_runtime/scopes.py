# Mechanical-injected globals; compatible with IronPython 2.7.
def scope_location(scope_id):
    if scope_id in CREATED_SCOPES:
        return CREATED_SCOPES[scope_id]
    scope = next(item for item in PLAN["scopes"] if item["id"] == scope_id)
    if scope["kind"] in ("named_selection", "object_name"):
        obj = MechanicalCompat.exact_object(scope["name"])
        if scope["kind"] == "named_selection":
            obj = MechanicalCompat.assert_object_type(
                obj, {"namedselection"}, "scope:{}".format(scope_id)
            )
            obj.SendToSolver = True
        CREATED_SCOPES[scope_id] = obj
        return obj
    if scope["kind"] != "axis_extreme_face":
        raise TextToAnsysError("Unsupported scope kind: {}".format(scope["kind"]))

    body = MechanicalCompat.exact_geo_body(scope.get("body"))
    axis_index = {"x": 0, "y": 1, "z": 2}[scope["axis"]]
    try:
        geometry_unit = TEXT_TYPE(ExtAPI.DataModel.GeoData.Unit)
        tolerance = float(
            units.ConvertUnit(
                float(scope["tolerance_canonical_m"]),
                fromUnit="m",
                toUnit=geometry_unit,
            )
        )
    except Exception as exc:
        raise UnsupportedMechanicalApi(
            "Geometry unit conversion required by axis_extreme_face is unavailable: {}".format(exc)
        )
    entries = [
        (face, MechanicalCompat.face_data(face, geometry_unit)) for face in body.Faces
    ]
    if not entries:
        raise TextToAnsysError("axis_extreme_face found no faces")
    coordinates = [entry[1]["centroid"][axis_index] for entry in entries]
    target = min(coordinates) if scope["extreme"] == "min" else max(coordinates)
    candidates = [
        entry for entry in entries if abs(entry[1]["centroid"][axis_index] - target) <= tolerance
    ]
    FACE_SELECTIONS.append(
        {
            "scope_id": scope_id,
            "axis": scope["axis"],
            "extreme": scope["extreme"],
            "target": target,
            "geometry_length_unit": geometry_unit,
            "tolerance_original": scope["tolerance"],
            "tolerance_canonical_m": scope["tolerance_canonical_m"],
            "tolerance_geometry_unit": tolerance,
            "candidates": [entry[1] for entry in entries],
            "matched": [entry[1] for entry in candidates],
        }
    )
    if len(candidates) != 1:
        raise TextToAnsysError(
            "axis_extreme_face {!r} expected one face; found {}".format(scope_id, len(candidates))
        )
    selection = MechanicalCompat.selection_from_entities([candidates[0][0]])
    named_selection = Model.AddNamedSelection()
    named_selection.Name = scope["dpf_named_selection"]
    named_selection.Location = selection
    named_selection.SendToSolver = True
    CREATED_SCOPES[scope_id] = named_selection
    return named_selection
