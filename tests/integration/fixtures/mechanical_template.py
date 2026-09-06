# ruff: noqa: F821
# Fixed Mechanical-injected script for opt-in template acceptance and readback.
import json
import os


def exact(name):
    matches = list(ExtAPI.DataModel.GetObjectsByName(name))
    if len(matches) != 1:
        raise RuntimeError("Expected one object named " + name)
    return matches[0]


ExtAPI.DataModel.Project.Open(os.environ["TTA_TEMPLATE_SOURCE"])
model = ExtAPI.DataModel.Project.Model
analysis = exact("text-to-ansys static structural")
force = exact("tip_force")
direction = exact("tip_z")
reaction = exact("fixed_reaction")
if os.environ.get("TTA_TEMPLATE_SEED") == "1":
    coordinates = model.CoordinateSystems.AddCoordinateSystem()
    coordinates.Name = "Acceptance Rotated Coordinates"
    coordinates.OriginDefineBy = Ansys.Mechanical.DataModel.Enums.CoordinateSystemAlignmentType.Fixed
    coordinates.OriginX = Quantity("0 [m]")
    coordinates.OriginY = Quantity("0 [m]")
    coordinates.OriginZ = Quantity("0 [m]")
    coordinates.RotateX(90)
    force.CoordinateSystem = coordinates
    force.XComponent.Output.DiscreteValues = [Quantity("100 [N]")]
    force.ZComponent.Output.DiscreteValues = [Quantity("0 [N]")]
    direction.CoordinateSystem = coordinates
    direction.NormalOrientation = Ansys.Mechanical.DataModel.Enums.NormalOrientationType.XAxis
    direction.Location = exact("TTA_SCOPE_FIXED_FACE")
    other_support = analysis.AddFixedSupport()
    other_support.Name = "Acceptance unused support"
    other_support.Location = exact("TTA_SCOPE_LOAD_FACE")
    other_support.Suppressed = True
    reaction.BoundaryConditionSelection = other_support
    reaction.Orientation = coordinates
    ExtAPI.DataModel.Project.SaveAs(os.environ["TTA_TEMPLATE_DESTINATION"], True)

evidence = {
    "product_version": str(ExtAPI.DataModel.Project.ProductVersion),
    "extra_coordinate_state": str(exact("Acceptance Rotated Coordinates").ObjectState),
    "force_coordinate_system": int(force.CoordinateSystem.CoordinateSystemID),
    "force_components_N": [float(component.Output.DiscreteValues[0].Value)
                           for component in [force.XComponent, force.YComponent, force.ZComponent]],
    "direction_coordinate_system": int(direction.CoordinateSystem.CoordinateSystemID),
    "direction_axis": str(direction.NormalOrientation),
    "direction_scope": str(direction.Location.Name),
    "direction_scoping_method": str(direction.ScopingMethod),
    "reaction_support": str(reaction.BoundaryConditionSelection.Name),
    "reaction_coordinate_system": int(reaction.Orientation.CoordinateSystemID),
    "reaction_location_method": str(reaction.LocationMethod),
}
with open(os.environ["TTA_TEMPLATE_EVIDENCE"], "wb") as stream:
    stream.write(json.dumps(evidence, indent=2, sort_keys=True).encode("utf-8"))
