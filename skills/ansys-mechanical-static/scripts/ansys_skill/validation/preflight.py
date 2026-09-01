"""Offline specification and engineering preflight checks."""

from __future__ import annotations

from pathlib import Path

from ansys_skill.paths import resolve_input_path
from ansys_skill.schema import MaterialSource, Mode, ScopeKind, SimulationSpec
from ansys_skill.validation.statuses import Check, CheckStatus

SUPPORTED_GEOMETRY_SUFFIXES = {
    ".step",
    ".stp",
}
SUPPORTED_TEMPLATE_SUFFIXES = {".mechdat", ".mechdb"}


def preflight_checks(spec: SimulationSpec, spec_path: Path) -> list[Check]:
    checks: list[Check] = [
        Check("schema_complete", CheckStatus.PASS, "Schema and cross-references are valid"),
        Check(
            "analysis_supported",
            CheckStatus.PASS,
            "Linear static structural analysis with small deformation is selected",
        ),
        Check("body_materials", CheckStatus.PASS, "Every body references a declared material"),
        Check("supports_present", CheckStatus.PASS, "At least one support is defined"),
        Check("loads_present", CheckStatus.PASS, "At least one non-zero load is defined"),
        Check("mesh_size", CheckStatus.PASS, "Global element size is positive and unit-qualified"),
    ]

    input_value = (
        spec.inputs.project_file if spec.mode is Mode.TEMPLATE else spec.inputs.geometry_file
    )
    input_path = resolve_input_path(spec_path, input_value)
    assert input_path is not None
    allowed = (
        SUPPORTED_TEMPLATE_SUFFIXES if spec.mode is Mode.TEMPLATE else SUPPORTED_GEOMETRY_SUFFIXES
    )
    if not input_path.is_file():
        checks.append(
            Check(
                "input_file",
                CheckStatus.FAIL,
                f"Input file does not exist: {input_path}",
            )
        )
    elif input_path.suffix.lower() not in allowed:
        checks.append(
            Check(
                "input_file",
                CheckStatus.FAIL,
                f"Input format {input_path.suffix!r} is not enabled for {spec.mode.value}",
                {"supported_suffixes": sorted(allowed)},
            )
        )
    else:
        checks.append(
            Check(
                "input_file",
                CheckStatus.PASS,
                f"Input file exists and has an enabled suffix: {input_path.name}",
            )
        )

    if spec.open_questions:
        checks.append(
            Check(
                "open_questions",
                CheckStatus.WARN,
                "Real execution is blocked until all open questions are resolved",
                {"questions": spec.open_questions},
            )
        )
    else:
        checks.append(Check("open_questions", CheckStatus.PASS, "No open questions remain"))

    isotropic = [
        material.name for material in spec.materials if material.source is MaterialSource.ISOTROPIC
    ]
    if isotropic:
        checks.append(
            Check(
                "material_authoring",
                CheckStatus.WARN,
                "Custom isotropic material authoring is schema-valid but blocked for real "
                "execution until the stable Mechanical API is integration-tested",
                {"materials": isotropic},
            )
        )
    else:
        checks.append(
            Check(
                "material_authoring",
                CheckStatus.PASS,
                "Materials use exact Engineering Data names",
            )
        )

    runtime_scopes = [
        scope.id
        for scope in spec.scopes
        if scope.kind in {ScopeKind.NAMED_SELECTION, ScopeKind.OBJECT_NAME}
    ]
    axis_scopes = [scope.id for scope in spec.scopes if scope.kind is ScopeKind.AXIS_EXTREME_FACE]
    if runtime_scopes or axis_scopes:
        checks.append(
            Check(
                "scope_resolution",
                CheckStatus.NOT_RUN,
                "Exact object and face uniqueness is checked inside Mechanical before meshing",
                {"runtime_scopes": runtime_scopes, "axis_extreme_scopes": axis_scopes},
            )
        )
    return checks
