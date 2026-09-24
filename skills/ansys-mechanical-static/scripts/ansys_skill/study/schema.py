"""Strict, unit-qualified specifications for a controlled design study."""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from ansys_skill.errors import SpecValidationError
from ansys_skill.schema import StrictModel
from ansys_skill.units import normalize_quantity

FEATURE_NAMES = ("plate_thickness", "hole_diameter", "fillet_radius")
REQUIRED_NUMERICAL_CHECKS = (
    "mechanical_messages", "requested_results", "small_deformation", "reaction_balance",
)


class ParameterSpec(StrictModel):
    lower: str
    upper: str
    baseline: str

    @model_validator(mode="after")
    def check_interval(self) -> ParameterSpec:
        low, high, base = (normalize_quantity(value, "length").magnitude
                           for value in (self.lower, self.upper, self.baseline))
        if not 0 < low < high or not low <= base <= high:
            raise ValueError("Require 0 < lower < upper and baseline inside the interval")
        return self


class MaterialEvidence(StrictModel):
    engineering_data_name: str = Field(min_length=1)
    density: str
    property_source: str = Field(min_length=10)

    @model_validator(mode="after")
    def check_density(self) -> MaterialEvidence:
        if normalize_quantity(self.density, "density").magnitude <= 0:
            raise ValueError("Density must be positive")
        return self


class TargetSpec(StrictModel):
    result_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    dimension: Literal["length", "pressure"]
    unit: str
    limit: str
    acceptance_source: str = Field(min_length=10)
    absolute_tolerance: str
    relative_tolerance: float = Field(default=0.05, gt=0, lt=1, allow_inf_nan=False)
    reference_scale: str
    mesh_relative_tolerance: float = Field(default=0.05, gt=0, lt=1, allow_inf_nan=False)
    required_checks: list[str] = Field(default_factory=lambda: list(REQUIRED_NUMERICAL_CHECKS))
    require_stress_review: bool = False

    @model_validator(mode="after")
    def check_quantities(self) -> TargetSpec:
        normalize_quantity(f"1 {self.unit}", self.dimension)
        for value in (self.limit, self.absolute_tolerance, self.reference_scale):
            if normalize_quantity(value, self.dimension).magnitude <= 0:
                raise ValueError("Target limits, scales and absolute tolerances must be positive")
        if not self.required_checks or len(set(self.required_checks)) != len(self.required_checks):
            raise ValueError("Required checks must be a non-empty unique list")
        missing = set(REQUIRED_NUMERICAL_CHECKS) - set(self.required_checks)
        if missing:
            raise ValueError(f"Required numerical checks cannot be removed: {sorted(missing)}")
        if self.dimension == "pressure" and not self.require_stress_review:
            raise ValueError("Stress targets require a recorded singularity review")
        return self

    def canonical(self) -> dict:
        return {
            "result_id": self.result_id, "dimension": self.dimension,
            "unit": normalize_quantity(self.limit, self.dimension).unit,
            "display_unit": self.unit,
            **{key: normalize_quantity(getattr(self, key), self.dimension).magnitude
               for key in ("limit", "absolute_tolerance", "reference_scale")},
            "relative_tolerance": self.relative_tolerance,
            "mesh_relative_tolerance": self.mesh_relative_tolerance,
            "acceptance_source": self.acceptance_source,
        }


class SamplingSpec(StrictModel):
    method: Literal["latin_hypercube"] = "latin_hypercube"
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    train_samples: int = Field(default=24, ge=6, le=10000)
    test_samples: int = Field(default=8, ge=3, le=10000)
    include_corners: bool = True


class MeshStudySpec(StrictModel):
    sizes: list[str] = Field(default_factory=lambda: ["12 mm", "8 mm", "5 mm"], min_length=3)
    element_order: Literal["linear", "quadratic"] = "quadratic"

    @model_validator(mode="after")
    def check_refinement(self) -> MeshStudySpec:
        sizes = [normalize_quantity(value, "length").magnitude for value in self.sizes]
        if any(x <= 0 for x in sizes) or any(a <= b for a, b in itertools.pairwise(sizes)):
            raise ValueError("At least three positive mesh sizes must strictly decrease")
        return self


class BudgetSpec(StrictModel):
    max_solver_calls: int = Field(default=400, ge=1, le=100000)
    max_wall_seconds: int = Field(default=86400, ge=60, le=2592000)
    retries_per_job: int = Field(default=1, ge=0, le=5)


class ModelOptions(StrictModel):
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    cv_folds: int = Field(default=4, ge=3, le=10)
    max_normalized_distance: float = Field(default=0.4, gt=0, le=1, allow_inf_nan=False)
    max_relative_std: float = Field(default=0.15, gt=0, le=1, allow_inf_nan=False)


class OptimizationSpec(StrictModel):
    candidate_pool: int = Field(default=256, ge=16, le=100000)
    batch_size: int = Field(default=3, ge=1, le=100)
    max_rounds: int = Field(default=3, ge=0, le=100)
    verification_candidates: int = Field(default=3, ge=1, le=100)
    improvement_tolerance: float = Field(default=0.005, ge=0, lt=1, allow_inf_nan=False)
    compare_direct_search: bool = True


class StudySpec(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
    description: str = Field(min_length=1)
    geometry: Literal["gusseted_bracket"] = "gusseted_bracket"
    base_simulation: str
    parameters: dict[str, ParameterSpec]
    material: MaterialEvidence
    targets: dict[str, TargetSpec] = Field(min_length=1)
    sampling: SamplingSpec = Field(default_factory=SamplingSpec)
    mesh: MeshStudySpec = Field(default_factory=MeshStudySpec)
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    model: ModelOptions = Field(default_factory=ModelOptions)
    optimization: OptimizationSpec = Field(default_factory=OptimizationSpec)

    @model_validator(mode="after")
    def check_design(self) -> StudySpec:
        if set(self.parameters) != set(FEATURE_NAMES):
            raise ValueError(f"This geometry requires exactly {FEATURE_NAMES}")
        if not self.base_simulation or Path(self.base_simulation).suffix not in {".yaml", ".yml"}:
            raise ValueError("base_simulation must reference a YAML simulation specification")
        if any(not key.isidentifier() for key in self.targets):
            raise ValueError("Target names must be identifiers")
        if len({target.result_id for target in self.targets.values()}) != len(self.targets):
            raise ValueError("Targets must refer to distinct result IDs")
        if self.initial_solver_calls() > self.budget.max_solver_calls:
            raise ValueError("Solver budget cannot cover the baseline, training, test and mesh plan")
        return self

    def bounds(self) -> dict[str, list[float]]:
        return {name: [normalize_quantity(getattr(self.parameters[name], key), "length").magnitude
                       for key in ("lower", "upper")] for name in FEATURE_NAMES}

    def baseline(self) -> dict[str, float]:
        return {name: normalize_quantity(self.parameters[name].baseline, "length").magnitude
                for name in FEATURE_NAMES}

    def initial_solver_calls(self) -> int:
        count = 1 + self.sampling.train_samples + self.sampling.test_samples
        if self.sampling.include_corners:
            count += 2 ** len(FEATURE_NAMES)
        return count * len(self.mesh.sizes)

    def corner_parameters(self) -> list[dict[str, float]]:
        bounds = self.bounds()
        return [dict(zip(FEATURE_NAMES, values, strict=True))
                for values in itertools.product(*(bounds[name] for name in FEATURE_NAMES))]


def load_study(path: str | Path) -> StudySpec:
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return StudySpec.model_validate(document)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise SpecValidationError(f"Cannot load study: {exc}") from exc
