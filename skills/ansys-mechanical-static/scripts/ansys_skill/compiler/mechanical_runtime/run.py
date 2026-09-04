# Mechanical-injected globals; compatible with IronPython 2.7.
outcome = None
try:
    analysis = prepare_model()
    apply_materials()
    for scope in PLAN["scopes"]:
        scope_location(scope["id"])
    apply_supports(analysis)
    apply_loads(analysis)
    apply_results(analysis)
    apply_mesh()
    if PLAN["output"].get("save_project"):
        MechanicalCompat.save_project()
    analysis.Solution.ClearGeneratedData()
    analysis.Solve(True)
    if PLAN["output"].get("save_project"):
        MechanicalCompat.save_project()
    outcome = write_artifacts("SOLVED")
except Exception as exc:
    outcome = write_artifacts(
        "FAILED",
        {"type": type(exc).__name__, "message": TEXT_TYPE(exc), "traceback": traceback.format_exc()},
    )

SENTINEL + json.dumps(outcome, sort_keys=True)
