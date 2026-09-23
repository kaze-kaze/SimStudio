"""Redistributable, explicit study inputs available in installed wheels."""

from __future__ import annotations

from pathlib import Path

import yaml

from ansys_skill.paths import require_fresh_run_dir
from ansys_skill.schema import SimulationSpec
from ansys_skill.study.schema import StudySpec
from ansys_skill.study.storage import atomic_text


def example_simulation() -> dict:
    body = "GussetedBracket|Solid"
    return {
        "schema_version": "1.0",
        "project": {"name": "bracket-design-study",
                    "description": "Authored linear-elastic design study; acceptance limits are demonstration inputs."},
        "mode": "from_geometry", "inputs": {"geometry_file": "geometry.step"},
        "units": {"length": "mm", "force": "N", "stress": "MPa", "mass": "kg", "time": "s"},
        "bodies": [{"name": body, "material": "steel"}],
        "materials": [{"name": "steel", "source": "engineering_data",
                       "engineering_data_name": "Structural Steel"}],
        "scopes": [{"id": name, "kind": "axis_extreme_face", "body": body,
                    "axis": axis, "extreme": extreme, "tolerance": "0.001 mm"}
                   for name, axis, extreme in (("mounting_face", "x", "min"),
                       ("front_face", "x", "max"), ("bearing_pad", "z", "max"))],
        "analysis": {"type": "linear_static_structural", "deformation": "small"},
        "mesh": {"global_element_size": "8 mm", "element_order": "quadratic"},
        "supports": [{"id": "mounting_support", "type": "fixed_support", "scope": "mounting_face"}],
        "loads": [
            {"id": "equipment_force", "type": "force", "scope": "front_face",
             "components": {"x": "1000 N", "y": "1500 N", "z": "-500 N"}},
            {"id": "bearing_pressure", "type": "pressure", "scope": "bearing_pad", "magnitude": "0.8 MPa"},
            {"id": "self_weight", "type": "gravity", "magnitude": "9.80665 m/s^2", "direction": [0, 0, -1]},
        ],
        "requested_results": [
            {"id": "total_deformation", "type": "total_deformation"},
            {"id": "pad_z", "type": "directional_deformation", "scope": "bearing_pad", "direction": "z"},
            {"id": "equivalent_stress", "type": "equivalent_von_mises_stress"},
            {"id": "mounting_reaction", "type": "reaction_force", "support": "mounting_support"},
            {"id": "node_count", "type": "node_count"},
            {"id": "element_count", "type": "element_count"},
            {"id": "solver_messages", "type": "solver_messages"},
        ],
        "validation": {"reaction_balance_relative_tolerance": 0.005,
                       "small_deformation_warn_ratio": 0.01, "small_deformation_fail_ratio": 0.05,
                       "characteristic_length": "240 mm", "cantilever": {"enabled": False}},
        "assumptions": [
            {"text": "Authored demonstration geometry and loads; this is not a supplied production design.", "source": "engineering_default"},
            {"text": "Rear face is fixed to an ideal rigid backing; bolts, welds and contact compliance are not modeled.", "source": "engineering_default"},
            {"text": "One continuous isotropic solid; small-deformation linear elasticity must remain valid.", "source": "engineering_default"},
            {"text": "Global equivalent stress includes fixed-edge peaks and requires a mesh-specific engineering review before training.", "source": "engineering_default"},
        ],
        "open_questions": [], "output": {"export_images": True, "save_project": True},
        "execution": {"backend": "mechanical_batch", "timeout_seconds": 600},
    }


def example_study() -> dict:
    return {
        "schema_version": "1.0", "name": "bracket-lightweighting",
        "description": "Surrogate-assisted mass reduction for an authored single-solid bracket.",
        "geometry": "gusseted_bracket", "base_simulation": "base-simulation.yaml",
        "parameters": {
            "plate_thickness": {"lower": "14 mm", "upper": "24 mm", "baseline": "20 mm"},
            "hole_diameter": {"lower": "10 mm", "upper": "18 mm", "baseline": "14 mm"},
            "fillet_radius": {"lower": "6 mm", "upper": "14 mm", "baseline": "10 mm"},
        },
        "material": {"engineering_data_name": "Structural Steel", "density": "7850 kg/m^3",
                     "property_source": "Demonstration density; require agreement with each saved Mechanical solver input."},
        "targets": {
            "displacement": {"result_id": "total_deformation", "dimension": "length",
                             "unit": "mm", "limit": "0.025 mm", "absolute_tolerance": "0.0002 mm",
                             "reference_scale": "0.02 mm",
                             "acceptance_source": "Authored serviceability exercise informed by the recorded baseline; not a production requirement."},
            "stress": {"result_id": "equivalent_stress", "dimension": "pressure",
                       "unit": "MPa", "limit": "10 MPa", "absolute_tolerance": "0.1 MPa",
                       "reference_scale": "9 MPa", "require_stress_review": True,
                       "mesh_relative_tolerance": 0.1,
                       "acceptance_source": "Authored 10 MPa response constraint, not a material allowable or strength approval; singularity review is mandatory."},
        },
    }


def init_study(directory: Path) -> dict:
    require_fresh_run_dir(directory)
    study = StudySpec.model_validate(example_study())
    simulation = SimulationSpec.model_validate(example_simulation())
    directory.mkdir(parents=True, exist_ok=True)
    atomic_text(directory / "study.yaml", yaml.safe_dump(study.model_dump(mode="json"), sort_keys=False))
    atomic_text(directory / "base-simulation.yaml",
                yaml.safe_dump(simulation.model_dump(mode="json", exclude_none=True), sort_keys=False))
    return {"status": "INITIALIZED", "directory": str(directory.resolve()),
            "files": ["study.yaml", "base-simulation.yaml"], "solver_started": False}
