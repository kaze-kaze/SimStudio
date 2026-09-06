# Mechanical-injected globals; compatible with IronPython 2.7.
def collect_messages():
    return MechanicalCompat.messages()


def export_current_image(filename):
    settings = Ansys.Mechanical.Graphics.GraphicsImageExportSettings()
    settings.Resolution = (
        Ansys.Mechanical.DataModel.Enums.GraphicsResolutionType.EnhancedResolution
    )
    settings.Background = Ansys.Mechanical.DataModel.Enums.GraphicsBackgroundType.White
    settings.CurrentGraphicsDisplay = True
    settings.Width = 1280
    settings.Height = 720
    ExtAPI.Graphics.ExportImage(
        os.path.join(RUN_DIRECTORY, filename),
        Ansys.Mechanical.DataModel.Enums.GraphicsImageExportFormat.PNG,
        settings,
    )


def export_images():
    states = []
    if not PLAN["output"].get("export_images"):
        return [{"name": "visual_review", "status": "NOT_RUN", "reason": "disabled"}]
    try:
        Model.Mesh.Activate()
        export_current_image("mesh.png")
        states.append({"name": "mesh.png", "status": "PASS"})
    except Exception as exc:
        states.append({"name": "mesh.png", "status": "NOT_RUN", "reason": TEXT_TYPE(exc)})
    for result_type, filename in (
        ("total_deformation", "total-deformation.png"),
        ("equivalent_von_mises_stress", "equivalent-stress.png"),
    ):
        item = next((x for x in PLAN["requested_results"] if x["type"] == result_type), None)
        if not item or item["id"] not in CREATED["results"]:
            states.append({"name": filename, "status": "NOT_RUN", "reason": "result not requested"})
            continue
        try:
            CREATED["results"][item["id"]].Activate()
            export_current_image(filename)
            states.append({"name": filename, "status": "PASS"})
        except Exception as exc:
            states.append({"name": filename, "status": "NOT_RUN", "reason": TEXT_TYPE(exc)})
    return states


def write_artifacts(status, error=None):
    try:
        result_files, solve_logs = MechanicalCompat.collect_solver_files()
    except Exception as exc:
        result_files, solve_logs = [], []
        ANALYSIS_INFO["artifact_error"] = TEXT_TYPE(exc)
    if status == "SOLVED" and not result_files:
        status = "FAILED"
        error = {"type": "MissingResultFile",
                 "message": "Solve produced no collectable RST: {}".format(ANALYSIS_INFO.get("artifact_error", "check solver messages"))}
    payload = {
        "status": status,
        "error": error,
        "face_selections": FACE_SELECTIONS,
        "analysis": ANALYSIS_INFO,
        "mechanical_product_version": ANALYSIS_INFO.get("mechanical_product_version"),
        "object_types": OBJECT_TYPES,
        "run_directory": RUN_DIRECTORY,
        "project_file": os.path.join(RUN_DIRECTORY, "text-to-ansys.mechdb")
        if PLAN["output"].get("save_project") and os.path.isfile(os.path.join(RUN_DIRECTORY, "text-to-ansys.mechdb")) else None,
        "solver_messages": collect_messages(),
        "result_files": result_files,
        "solve_logs": solve_logs,
        "visual_review": export_images() if status == "SOLVED" else [],
    }
    for filename, data in (("mechanical-artifacts.json", payload),
                           ("face-selection-report.json", FACE_SELECTIONS)):
        with open(os.path.join(RUN_DIRECTORY, filename), "wb") as stream:
            stream.write(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True).encode("utf-8"))
    return payload
