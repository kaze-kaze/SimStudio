"""Versioned, strict simulation specification."""

from __future__ import annotations

import json
import math
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ansys_skill.errors import SpecValidationError, UnsupportedFeatureError
from ansys_skill.units import normalize_direction, normalize_quantity, vector_magnitude

CURRENT_SCHEMA_VERSION = "1.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Mode(StrEnum):
    TEMPLATE = "template"
    FROM_GEOMETRY = "from_geometry"


class ScopeKind(StrEnum):
    NAMED_SELECTION = "named_selection"
    OBJECT_NAME = "object_name"
    AXIS_EXTREME_FACE = "axis_extreme_face"


class MaterialSource(StrEnum):
    ENGINEERING_DATA = "engineering_data"
    ISOTROPIC = "isotropic"


class AssumptionSource(StrEnum):
    USER = "user"
    TEMPLATE = "template"
    PROGRAM = "program"
    ENGINEERING_DEFAULT = "engineering_default"


class ResultType(StrEnum):
    TOTAL_DEFORMATION = "total_deformation"
    DIRECTIONAL_DEFORMATION = "directional_deformation"
    EQUIVALENT_VON_MISES_STRESS = "equivalent_von_mises_stress"
    REACTION_FORCE = "reaction_force"
    SOLVER_MESSAGES = "solver_messages"
    NODE_COUNT = "node_count"
    ELEMENT_COUNT = "element_count"


class ProjectSpec(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class InputSpec(StrictModel):
    project_file: str | None = None
    geometry_file: str | None = None


class UnitSpec(StrictModel):
    length: str = "m"
    force: str = "N"
    stress: str = "Pa"
    mass: str = "kg"
    time: str = "s"

    @field_validator("length", "force", "stress", "mass", "time")
    @classmethod
    def validate_unit(cls, value: str, info: ValidationInfo) -> str:
        dimensions = {
            "length": "length",
            "force": "force",
            "stress": "pressure",
            "mass": "mass",
            "time": "time",
        }
        normalize_quantity(f"1 {value}", dimensions[info.field_name])
        return value


class CoordinateSystemSpec(StrictModel):
    name: str = "Global Coordinate System"
    kind: Literal["global"] = "global"


class ScopeSpec(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    kind: ScopeKind
    name: str | None = None
    body: str | None = None
    axis: Literal["x", "y", "z"] | None = None
    extreme: Literal["min", "max"] | None = None
    tolerance: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ScopeSpec:
        if self.kind in {ScopeKind.NAMED_SELECTION, ScopeKind.OBJECT_NAME}:
            if not self.name:
                raise ValueError(f"{self.kind.value} requires name")
            if any(
                value is not None
                for value in (self.body, self.axis, self.extreme, self.tolerance)
            ):
                raise ValueError(
                    f"{self.kind.value} cannot define body/axis/extreme/tolerance"
                )
        elif self.kind is ScopeKind.AXIS_EXTREME_FACE:
            if self.name is not None:
                raise ValueError("axis_extreme_face cannot define name")
            if not self.axis or not self.extreme or not self.tolerance:
                raise ValueError("axis_extreme_face requires axis, extreme, and tolerance")
            quantity = normalize_quantity(self.tolerance, "length")
            if quantity.magnitude <= 0:
                raise ValueError("axis_extreme_face tolerance must be positive")
        return self


class BodySpec(StrictModel):
    name: str = Field(min_length=1)
    material: str = Field(min_length=1)


class MaterialSpec(StrictModel):
    name: str = Field(min_length=1)
    source: MaterialSource
    engineering_data_name: str | None = None
    youngs_modulus: str | None = None
    poissons_ratio: float | None = Field(default=None, gt=-1.0, lt=0.5)
    density: str | None = None

    @model_validator(mode="after")
    def validate_material(self) -> MaterialSpec:
        if self.source is MaterialSource.ENGINEERING_DATA:
            if not self.engineering_data_name:
                raise ValueError("engineering_data material requires engineering_data_name")
            if any(
                value is not None
                for value in (self.youngs_modulus, self.poissons_ratio, self.density)
            ):
                raise ValueError("engineering_data material cannot define isotropic properties")
        else:
            if not self.youngs_modulus or self.poissons_ratio is None:
                raise ValueError("isotropic material requires youngs_modulus and poissons_ratio")
            if normalize_quantity(self.youngs_modulus, "pressure").magnitude <= 0:
                raise ValueError("youngs_modulus must be positive")
            if self.density is not None and normalize_quantity(self.density, "density").magnitude <= 0:
                raise ValueError("density must be positive")
        return self


class AnalysisSpec(StrictModel):
    type: Literal["linear_static_structural"]
    deformation: Literal["small"] = "small"
    object_name: str | None = None


class MeshSpec(StrictModel):
    global_element_size: str
    element_order: Literal["program_controlled", "linear", "quadratic"] = "program_controlled"

    @field_validator("global_element_size")
    @classmethod
    def validate_size(cls, value: str) -> str:
        if normalize_quantity(value, "length").magnitude <= 0:
            raise ValueError("global_element_size must be positive")
        return value


class SupportSpec(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    type: Literal["fixed_support"]
    scope: str
    object_name: str | None = None


class VectorComponents(StrictModel):
    x: str
    y: str
    z: str

    def values(self) -> list[str]:
        return [self.x, self.y, self.z]


class LoadSpec(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    type: Literal["force", "pressure", "gravity"]
    scope: str | None = None
    object_name: str | None = None
    components: VectorComponents | None = None
    magnitude: str | None = None
    direction: list[float] | None = None

    @model_validator(mode="after")
    def validate_load(self) -> LoadSpec:
        if self.type in {"force", "pressure"} and not self.scope:
            raise ValueError(f"{self.type} requires scope")
        if self.type == "pressure":
            if not self.magnitude or self.components is not None or self.direction is not None:
                raise ValueError("pressure requires magnitude only")
            if normalize_quantity(self.magnitude, "pressure").magnitude == 0:
                raise ValueError("pressure must be non-zero")
        elif self.type == "force":
            by_components = self.components is not None
            by_direction = self.magnitude is not None or self.direction is not None
            if by_components == by_direction:
                raise ValueError("force requires either components or magnitude plus direction")
            if self.components is not None:
                if vector_magnitude(self.components.values(), "force") == 0:
                    raise ValueError("force components must be non-zero")
            else:
                if self.magnitude is None or self.direction is None:
                    raise ValueError("force requires both magnitude and direction")
                if normalize_quantity(self.magnitude, "force").magnitude <= 0:
                    raise ValueError("force magnitude must be positive")
                normalize_direction(self.direction)
        else:
            if self.scope is not None:
                raise ValueError("gravity is global and cannot define scope")
            if self.components is not None or self.magnitude is None or self.direction is None:
                raise ValueError(
                    "gravity requires standard magnitude plus an axis-aligned direction"
                )
            magnitude = normalize_quantity(self.magnitude, "acceleration").magnitude
            if not math.isclose(magnitude, 9.80665, rel_tol=1e-6, abs_tol=1e-8):
                raise ValueError(
                    "EarthGravity magnitude must be the explicit standard 9.80665 m/s^2"
                )
            direction = normalize_direction(self.direction)
            axis_aligned = sum(abs(value) > 1e-9 for value in direction) == 1 and any(
                math.isclose(abs(value), 1.0, abs_tol=1e-9) for value in direction
            )
            if not axis_aligned:
                raise ValueError("EarthGravity direction must align with one global axis")
        return self


class RequestedResultSpec(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    type: ResultType
    scope: str | None = None
    object_name: str | None = None
    direction: Literal["x", "y", "z"] | None = None
    support: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> RequestedResultSpec:
        metadata_results = {
            ResultType.SOLVER_MESSAGES,
            ResultType.NODE_COUNT,
            ResultType.ELEMENT_COUNT,
        }
        if self.type is ResultType.DIRECTIONAL_DEFORMATION:
            if not self.direction:
                raise ValueError("directional_deformation requires direction")
            if self.support is not None:
                raise ValueError("directional_deformation cannot define support")
        elif self.type is ResultType.REACTION_FORCE:
            if not self.support:
                raise ValueError("reaction_force requires support id")
            if self.scope is not None or self.direction is not None:
                raise ValueError("reaction_force derives scope from support")
        elif self.type in metadata_results:
            if any(
                value is not None
                for value in (self.scope, self.object_name, self.direction, self.support)
            ):
                raise ValueError(f"{self.type.value} cannot define tree or scope fields")
        elif self.direction is not None or self.support is not None:
            raise ValueError(f"{self.type.value} cannot define direction or support")
        return self


class CantileverValidationSpec(StrictModel):
    enabled: bool = False
    span: str | None = None
    second_moment_of_area: str | None = None
    load_magnitude: str | None = None
    youngs_modulus: str | None = None
    result_id: str | None = None
    relative_tolerance: float = Field(default=0.15, gt=0, lt=1)

    @model_validator(mode="after")
    def validate_cantilever(self) -> CantileverValidationSpec:
        if self.enabled:
            required = {
                "span": self.span,
                "second_moment_of_area": self.second_moment_of_area,
                "load_magnitude": self.load_magnitude,
                "youngs_modulus": self.youngs_modulus,
                "result_id": self.result_id,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(f"cantilever validation missing: {', '.join(missing)}")
            for name, dimension in {
                "span": "length",
                "second_moment_of_area": "second_moment",
                "load_magnitude": "force",
                "youngs_modulus": "pressure",
            }.items():
                if normalize_quantity(getattr(self, name), dimension).magnitude <= 0:
                    raise ValueError(f"cantilever {name} must be positive")
        return self


class ValidationPolicySpec(StrictModel):
    reaction_balance_relative_tolerance: float = Field(default=0.05, gt=0, lt=1)
    small_deformation_warn_ratio: float = Field(default=0.02, gt=0, allow_inf_nan=False)
    small_deformation_fail_ratio: float = Field(default=0.1, gt=0, allow_inf_nan=False)
    characteristic_length: str | None = None
    cantilever: CantileverValidationSpec = Field(default_factory=CantileverValidationSpec)

    @model_validator(mode="after")
    def validate_policy(self) -> ValidationPolicySpec:
        if self.small_deformation_fail_ratio <= self.small_deformation_warn_ratio:
            raise ValueError("small deformation fail ratio must exceed warn ratio")
        if self.characteristic_length is not None and normalize_quantity(self.characteristic_length, "length").magnitude <= 0:
            raise ValueError("characteristic_length must be positive")
        return self


class AssumptionSpec(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    source: AssumptionSource


class OutputSpec(StrictModel):
    export_images: bool = True
    save_project: bool = True


class ExecutionSpec(StrictModel):
    backend: Literal["pymechanical_remote", "fake"] = "pymechanical_remote"
    host: str = "127.0.0.1"
    port: int | None = Field(default=None, ge=1, le=65535)
    allow_remote: bool = False
    transport_mode: Literal["insecure", "wnua", "mtls"] = "insecure"
    certs_dir: str | None = None
    start_instance: Literal["auto", "yes", "no"] = "auto"
    timeout_seconds: int = Field(default=1800, ge=30, le=86400)
    cleanup_owned_instance: bool = True

    @model_validator(mode="after")
    def validate_connection(self) -> ExecutionSpec:
        local_hosts = {"127.0.0.1", "localhost", "::1"}
        remote = self.host not in local_hosts
        if remote and not self.allow_remote:
            raise ValueError("non-local Mechanical host requires allow_remote: true")
        if remote and self.transport_mode == "insecure":
            raise ValueError(
                "non-local Mechanical host requires authenticated transport: wnua or mtls"
            )
        if remote and self.start_instance == "yes":
            raise ValueError("start_instance: yes is supported only for localhost")
        if self.transport_mode == "mtls" and not self.certs_dir:
            raise ValueError("mtls transport requires certs_dir")
        return self


class SimulationSpec(StrictModel):
    schema_version: Literal["1.0"]
    project: ProjectSpec
    mode: Mode
    inputs: InputSpec
    units: UnitSpec = Field(default_factory=UnitSpec)
    coordinate_systems: list[CoordinateSystemSpec] = Field(
        default_factory=lambda: [CoordinateSystemSpec()]
    )
    bodies: list[BodySpec] = Field(min_length=1)
    materials: list[MaterialSpec] = Field(min_length=1)
    scopes: list[ScopeSpec] = Field(min_length=1)
    analysis: AnalysisSpec
    mesh: MeshSpec
    supports: list[SupportSpec] = Field(min_length=1)
    loads: list[LoadSpec] = Field(min_length=1)
    requested_results: list[RequestedResultSpec] = Field(min_length=1)
    validation: ValidationPolicySpec = Field(default_factory=ValidationPolicySpec)
    assumptions: list[AssumptionSpec] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    output: OutputSpec = Field(default_factory=OutputSpec)
    execution: ExecutionSpec = Field(default_factory=ExecutionSpec)

    @model_validator(mode="after")
    def validate_cross_references(self) -> SimulationSpec:
        if self.mode is Mode.TEMPLATE:
            if not self.inputs.project_file or self.inputs.geometry_file:
                raise ValueError("template mode requires project_file and forbids geometry_file")
            if not self.analysis.object_name:
                raise ValueError("template mode requires analysis.object_name")
        else:
            if not self.inputs.geometry_file or self.inputs.project_file:
                raise ValueError(
                    "from_geometry mode requires geometry_file and forbids project_file"
                )
            if self.analysis.object_name:
                raise ValueError("from_geometry analysis cannot define object_name")
            if len(self.bodies) != 1:
                raise ValueError("from_geometry v1 supports exactly one body")

        self._assert_unique("scope", [item.id for item in self.scopes])
        self._assert_unique("material", [item.name for item in self.materials])
        self._assert_unique("body", [item.name for item in self.bodies])
        self._assert_unique("support", [item.id for item in self.supports])
        self._assert_unique("load", [item.id for item in self.loads])
        self._assert_unique("result", [item.id for item in self.requested_results])

        scope_ids = {item.id for item in self.scopes}
        scopes_by_id = {item.id: item for item in self.scopes}
        material_names = {item.name for item in self.materials}
        support_ids = {item.id for item in self.supports}
        supports_by_id = {item.id: item for item in self.supports}
        for body in self.bodies:
            if body.material not in material_names:
                raise ValueError(
                    f"body {body.name!r} references unknown material {body.material!r}"
                )
        for support in self.supports:
            if support.scope not in scope_ids:
                raise ValueError(
                    f"support {support.id!r} references unknown scope {support.scope!r}"
                )
            if self.mode is Mode.TEMPLATE and not support.object_name:
                raise ValueError(f"template support {support.id!r} requires object_name")
            if self.mode is Mode.FROM_GEOMETRY and support.object_name:
                raise ValueError(f"from_geometry support {support.id!r} forbids object_name")
        for load in self.loads:
            if load.scope and load.scope not in scope_ids:
                raise ValueError(f"load {load.id!r} references unknown scope {load.scope!r}")
            if self.mode is Mode.TEMPLATE and not load.object_name:
                raise ValueError(f"template load {load.id!r} requires object_name")
            if self.mode is Mode.FROM_GEOMETRY and load.object_name:
                raise ValueError(f"from_geometry load {load.id!r} forbids object_name")
        tree_results = {
            ResultType.TOTAL_DEFORMATION,
            ResultType.DIRECTIONAL_DEFORMATION,
            ResultType.EQUIVALENT_VON_MISES_STRESS,
            ResultType.REACTION_FORCE,
        }
        for result in self.requested_results:
            if result.scope and result.scope not in scope_ids:
                raise ValueError(f"result {result.id!r} references unknown scope {result.scope!r}")
            if result.support and result.support not in support_ids:
                raise ValueError(
                    f"result {result.id!r} references unknown support {result.support!r}"
                )
            if (
                self.mode is Mode.TEMPLATE
                and result.type in tree_results
                and not result.object_name
            ):
                raise ValueError(f"template result {result.id!r} requires object_name")
            if self.mode is Mode.FROM_GEOMETRY and result.object_name:
                raise ValueError(f"from_geometry result {result.id!r} forbids object_name")
            if result.scope and scopes_by_id[result.scope].kind is ScopeKind.OBJECT_NAME:
                raise ValueError(
                    f"result {result.id!r} requires a named_selection or axis_extreme_face scope"
                )
            if result.type is ResultType.REACTION_FORCE:
                support = supports_by_id[result.support]
                if scopes_by_id[support.scope].kind is ScopeKind.OBJECT_NAME:
                    raise ValueError(
                        f"reaction result {result.id!r} requires its support to use a "
                        "named_selection or axis_extreme_face scope"
                    )
        if self.validation.cantilever.enabled:
            displacement_ids = {
                result.id for result in self.requested_results
                if result.type in {ResultType.TOTAL_DEFORMATION, ResultType.DIRECTIONAL_DEFORMATION}
            }
            if self.validation.cantilever.result_id not in displacement_ids:
                raise ValueError("cantilever result_id must reference a requested displacement result")
        return self

    @staticmethod
    def _assert_unique(label: str, values: list[str]) -> None:
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            raise ValueError(f"duplicate {label} identifiers: {', '.join(duplicates)}")

    def assert_execution_ready(self) -> None:
        if self.open_questions:
            raise SpecValidationError(
                "Real execution is blocked while open_questions is non-empty",
                details={"open_questions": self.open_questions},
            )
        isotropic = [
            material.name
            for material in self.materials
            if material.source is MaterialSource.ISOTROPIC
        ]
        if isotropic:
            raise UnsupportedFeatureError(
                "Creating new isotropic Engineering Data materials is not enabled because the "
                "stable Mechanical material-authoring API has not been integration-tested",
                details={"materials": isotropic},
            )


def migrate_document(raw: dict[str, Any]) -> dict[str, Any]:
    version = raw.get("schema_version")
    if version == CURRENT_SCHEMA_VERSION:
        return raw
    if version is None:
        raise SpecValidationError("simulation.yaml must define schema_version")
    raise SpecValidationError(
        f"Unsupported schema_version {version!r}; supported version is {CURRENT_SCHEMA_VERSION}"
    )


def load_spec(path: str | Path) -> tuple[SimulationSpec, dict[str, Any]]:
    spec_path = Path(path)
    try:
        raw = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SpecValidationError(f"Unable to read simulation specification: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SpecValidationError(f"Invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise SpecValidationError("simulation.yaml root must be a mapping")
    migrated = migrate_document(raw)
    try:
        spec = SimulationSpec.model_validate(migrated)
    except ValidationError as exc:
        raise SpecValidationError(
            "Simulation specification validation failed",
            details={"errors": json.loads(exc.json(include_url=False))},
        ) from exc
    return spec, migrated


def normalized_document(spec: SimulationSpec) -> dict[str, Any]:
    return spec.model_dump(mode="json", exclude_none=True)


def dump_normalized_yaml(spec: SimulationSpec) -> str:
    return yaml.safe_dump(
        normalized_document(spec),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def write_json_schema(path: str | Path) -> None:
    schema = SimulationSpec.model_json_schema()
    Path(path).write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check_finite_number(value: object, label: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise SpecValidationError(f"{label} must be numeric") from exc
    if not math.isfinite(numeric):
        raise SpecValidationError(f"{label} must be finite")
    return numeric
