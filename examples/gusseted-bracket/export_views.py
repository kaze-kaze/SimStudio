# ruff: noqa: F821
# Fixed Mechanical-injected script; run only against a task-owned saved project.
import json
import os

if os.environ.get("ANSYS_AVAILABLE") != "1":
    raise RuntimeError("View export requires explicit ANSYS_AVAILABLE=1")

output = os.path.abspath(os.environ["BRACKET_VIEW_OUTPUT"])
if os.path.exists(output):
    raise RuntimeError("Use a new output directory for view exports")
os.makedirs(output)
ExtAPI.DataModel.Project.Open(os.environ["BRACKET_VIEW_PROJECT"])
model = ExtAPI.DataModel.Project.Model
camera = ExtAPI.Graphics.Camera
camera.UpVector = Ansys.ACT.Math.Vector3D(0, 0, 1)
camera.ViewVector = Ansys.ACT.Math.Vector3D(1, -1, 0.6)
camera.SetFit(None)
settings = Ansys.Mechanical.Graphics.GraphicsImageExportSettings()
settings.Resolution = Ansys.Mechanical.DataModel.Enums.GraphicsResolutionType.EnhancedResolution
settings.Background = Ansys.Mechanical.DataModel.Enums.GraphicsBackgroundType.White
settings.CurrentGraphicsDisplay = True
settings.Width = 1600
settings.Height = 1000
records = []


def capture(obj, name, show_mesh):
    obj.Activate()
    ExtAPI.Graphics.ViewOptions.ShowMesh = show_mesh
    ExtAPI.Graphics.ExportImage(
        os.path.join(output, name),
        Ansys.Mechanical.DataModel.Enums.GraphicsImageExportFormat.PNG,
        settings,
    )
    records.append({"file": name, "status": "PASS"})


capture(model.Geometry, "geometry.png", False)
capture(model.Mesh, "mesh.png", True)
for name, filename in [("total_deformation", "total-deformation.png"),
                       ("equivalent_stress", "equivalent-stress.png")]:
    matches = list(ExtAPI.DataModel.GetObjectsByName(name))
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one result: " + name)
    capture(matches[0], filename, False)
camera.ViewVector = Ansys.ACT.Math.Vector3D(1, -1, -0.5)
camera.SetFit(None)
capture(model.Geometry, "underside.png", False)
with open(os.path.join(output, "view-exports.json"), "wb") as stream:
    stream.write(json.dumps({"status": "PASS", "images": records,
                             "project_saved": False, "solver_started": False},
                            indent=2).encode("utf-8"))
# No Save/SaveAs or Solve: source project and solved data remain untouched.
