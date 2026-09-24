"""Controlled parameterization of the gusseted equipment bracket CAD fixture."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from ansys_skill.errors import EnvironmentUnavailableError, SpecValidationError

GENERATOR = "gusseted_bracket"
GENERATOR_VERSION = "1"
BODY_NAME = "GussetedBracket|Solid"
_PARAMETER_LIMITS_M = {
    "plate_thickness": (0.014, 0.024),
    "hole_diameter": (0.010, 0.018),
    "fillet_radius": (0.006, 0.014),
}
_EXPECTED_PARAMETERS = frozenset(_PARAMETER_LIMITS_M)
_DEFAULT_DENSITY_KG_M3 = 7850.0
_MIN_WALL_MM = 5.0
_SCOPE_TOLERANCE_MM = 0.001
_MM_PER_M = 1000.0


def _validated_parameters(parameters: dict[str, float]) -> dict[str, float]:
    if not isinstance(parameters, dict):
        raise SpecValidationError("Geometry parameters must be a mapping")

    supplied = set(parameters)
    missing = sorted(_EXPECTED_PARAMETERS - supplied)
    unexpected = sorted(supplied - _EXPECTED_PARAMETERS, key=str)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected {', '.join(map(str, unexpected))}")
        raise SpecValidationError(
            "Geometry parameters must contain exactly the required keys: " + "; ".join(details)
        )

    normalized: dict[str, float] = {}
    for name, (minimum, maximum) in _PARAMETER_LIMITS_M.items():
        value = parameters[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SpecValidationError(f"Geometry parameter {name!r} must be a finite number in meters")
        try:
            value = float(value)
        except (OverflowError, ValueError) as exc:
            raise SpecValidationError(f"Geometry parameter {name!r} must be finite") from exc
        if not math.isfinite(value):
            raise SpecValidationError(f"Geometry parameter {name!r} must be finite")
        minimum_floor = math.nextafter(minimum, -math.inf)
        maximum_ceiling = math.nextafter(maximum, math.inf)
        if not minimum_floor <= value <= maximum_ceiling:
            raise SpecValidationError(
                f"Geometry parameter {name!r} must be between {minimum:g} and {maximum:g} m"
            )
        normalized[name] = min(max(value, minimum), maximum)

    thickness_mm = normalized["plate_thickness"] * _MM_PER_M
    hole_radius_mm = normalized["hole_diameter"] * _MM_PER_M / 2.0
    root_radius_mm = normalized["fillet_radius"] * _MM_PER_M
    clearances_mm = {
        "upper mounting hole to root fillet": 50.0 - thickness_mm - root_radius_mm - hole_radius_mm,
        "mounting hole to plate side edge": 20.0 - hole_radius_mm,
        "equipment hole to bearing pad": 15.0 - hole_radius_mm,
    }
    for feature, clearance in clearances_mm.items():
        if clearance < _MIN_WALL_MM - 1e-9:
            raise SpecValidationError(
                f"Geometry parameters leave only {clearance:.3g} mm between the {feature}; "
                f"at least {_MIN_WALL_MM:g} mm is required"
            )
    return normalized


def _validated_density(density_kg_m3: float) -> float:
    if isinstance(density_kg_m3, bool) or not isinstance(density_kg_m3, (int, float)):
        raise SpecValidationError("Density must be a finite positive number in kg/m^3")
    try:
        density = float(density_kg_m3)
    except (OverflowError, ValueError) as exc:
        raise SpecValidationError("Density must be finite") from exc
    if not math.isfinite(density) or density <= 0:
        raise SpecValidationError("Density must be finite and positive")
    return density


def validate_parameters(parameters: dict[str, float]) -> None:
    """Validate the supported SI dimensions and their interacting clearances."""
    _validated_parameters(parameters)


def _vector_components(vector: Any) -> tuple[float, float, float]:
    return float(vector.X), float(vector.Y), float(vector.Z)


def _shape_is_valid(shape: Any) -> bool:
    validity = shape.is_valid
    return bool(validity() if callable(validity) else validity)


def _build_bracket(parameters: dict[str, float]) -> Any:
    try:
        from build123d import Align, Box, Cylinder, Plane, Polygon, Pos, extrude, fillet
    except (ImportError, OSError) as exc:
        raise EnvironmentUnavailableError(
            "The optional build123d CAD dependency is unavailable; install the cad-fixture extra"
        ) from exc

    thickness_mm = parameters["plate_thickness"] * _MM_PER_M
    hole_diameter_mm = parameters["hole_diameter"] * _MM_PER_M
    root_radius_mm = parameters["fillet_radius"] * _MM_PER_M
    plate_top_mm = 180.0
    plate_bottom_mm = plate_top_mm - thickness_mm

    try:
        back = Box(16, 160, 180, align=(Align.MIN, Align.CENTER, Align.MIN))
        shelf = Pos(16, 0, plate_bottom_mm) * Box(
            224, 160, thickness_mm, align=(Align.MIN, Align.CENTER, Align.MIN)
        )
        bracket = back + shelf

        root_edges = [
            edge
            for edge in bracket.edges()
            if abs(edge.center().X - 16) < 1e-6
            and abs(edge.center().Z - plate_bottom_mm) < 1e-6
        ]
        if len(root_edges) != 1:
            raise SpecValidationError(
                f"Expected one wall-to-plate root edge before filleting; found {len(root_edges)}"
            )
        bracket = fillet(root_edges, radius=root_radius_mm)

        rib_profile = Polygon(
            (16, 20), (220, plate_bottom_mm), (16, plate_bottom_mm), align=None
        )
        rib_profile = fillet(rib_profile.vertices(), radius=6)
        rib = extrude(Plane.XZ * rib_profile, amount=12)
        for y_position in (-39, 51):
            bracket += Pos(0, y_position, 0) * rib

        for y_position in (-60, 60):
            for z_position in (40, 130):
                bracket -= Pos(8, y_position, z_position) * Cylinder(
                    hole_diameter_mm / 2.0, 20, rotation=(0, 90, 0)
                )
            equipment_hole_center_z = (plate_bottom_mm + plate_top_mm) / 2.0
            for x_position in (70, 215):
                bracket -= Pos(x_position, y_position, equipment_hole_center_z) * Cylinder(
                    hole_diameter_mm / 2.0, thickness_mm + 4
                )

        bracket += Pos(130, 5, plate_top_mm) * Box(
            70, 60, 8, align=(Align.MIN, Align.MIN, Align.MIN)
        )
        bracket = bracket.clean()
        solids = list(bracket.solids())
        if len(solids) != 1:
            raise SpecValidationError(f"Bracket CAD must contain exactly one solid; found {len(solids)}")
        if not _shape_is_valid(bracket):
            raise SpecValidationError("Bracket CAD is invalid after the requested features")
        bracket.label = "GussetedBracket"
        return bracket
    except SpecValidationError:
        raise
    except Exception as exc:
        raise SpecValidationError(
            "CAD construction failed for the validated bracket dimensions "
            f"({type(exc).__name__}: {exc})"
        ) from exc


def _planar_boundary_summary(face: Any) -> dict[str, Any]:
    from build123d import GeomType

    outer = face.outer_wire()
    if (face.geom_type != GeomType.PLANE or len(outer.edges()) != 4
            or any(edge.geom_type != GeomType.LINE for edge in outer.edges())):
        raise SpecValidationError("Controlled scope must have a planar rectangular outer boundary")
    corners = sorted([component * 1e-3 for component in _vector_components(vertex)]
                     for vertex in outer.vertices())
    if len(corners) != 4:
        raise SpecValidationError("Controlled scope must have four distinct outer vertices")
    holes = []
    for wire in face.inner_wires():
        edges = list(wire.edges())
        if not edges or any(edge.geom_type != GeomType.CIRCLE for edge in edges):
            raise SpecValidationError("Controlled scope inner boundaries must be circular")
        center = _vector_components(edges[0].arc_center)
        radius = float(edges[0].radius)
        if any(math.dist(center, _vector_components(edge.arc_center)) > 1e-6
               or abs(float(edge.radius) - radius) > 1e-6 for edge in edges):
            raise SpecValidationError("A controlled scope hole must lie on one circle")
        holes.append({"center_m": [component * 1e-3 for component in center],
                      "radius_m": radius * 1e-3})
    return {"corners_m": corners, "holes": sorted(holes, key=lambda hole: hole["center_m"])}


def _geometry_summary(
    bracket: Any,
    parameters: dict[str, float],
    density_kg_m3: float,
) -> dict[str, Any]:
    from build123d import CenterOf

    solid = bracket.solids()[0]
    faces = list(solid.faces())
    selector_definitions = {
        "mounting_face": ("x", "min"),
        "front_face": ("x", "max"),
        "bearing_pad": ("z", "max"),
    }
    axis_indices = {"x": 0, "y": 1, "z": 2}
    scopes: dict[str, dict[str, Any]] = {}

    for scope_name, (axis, extreme) in selector_definitions.items():
        axis_index = axis_indices[axis]
        face_centers = [face.center(CenterOf.MASS) for face in faces]
        center_components = [_vector_components(center) for center in face_centers]
        coordinates = [center[axis_index] for center in center_components]
        target = min(coordinates) if extreme == "min" else max(coordinates)
        matching_indices = [
            index
            for index, coordinate in enumerate(coordinates)
            if abs(coordinate - target) <= _SCOPE_TOLERANCE_MM
        ]
        if len(matching_indices) != 1:
            raise SpecValidationError(
                f"Scope {scope_name!r} ({axis}={extreme}) must match exactly one CAD face; "
                f"found {len(matching_indices)}"
            )

        face_index = matching_indices[0]
        face = faces[face_index]
        center = face_centers[face_index]
        normal_vector = face.normal_at(center)
        normal_components = _vector_components(normal_vector)
        normal_length = math.sqrt(sum(component**2 for component in normal_components))
        if not math.isfinite(normal_length) or normal_length <= 0:
            raise SpecValidationError(f"Scope {scope_name!r} resolved to a face without a valid normal")
        scopes[scope_name] = {
            "area_m2": float(face.area) * 1e-6,
            "centroid_m": [component * 1e-3 for component in center_components[face_index]],
            "normal": [component / normal_length for component in normal_components],
            "axis": axis,
            "extreme": extreme,
            "tolerance_m": _SCOPE_TOLERANCE_MM * 1e-3,
            "unique_face_count": 1,
            "boundary_summary": _planar_boundary_summary(face),
        }

    volume_m3 = float(solid.volume) * 1e-9
    center_of_mass = _vector_components(solid.center(CenterOf.MASS))
    bounding_box = bracket.bounding_box().size
    dimensions_m = [component * 1e-3 for component in _vector_components(bounding_box)]
    expected_dimensions_m = [0.240, 0.160, 0.188]
    if any(
        not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9)
        for actual, expected in zip(dimensions_m, expected_dimensions_m, strict=True)
    ):
        raise SpecValidationError(
            f"Bracket CAD dimensions must remain {expected_dimensions_m} m; got {dimensions_m} m"
        )

    return {
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "parameters": dict(parameters),
        "density_kg_m3": density_kg_m3,
        "volume_m3": volume_m3,
        "mass_kg": volume_m3 * density_kg_m3,
        "center_of_mass_m": [component * 1e-3 for component in center_of_mass],
        "bounding_box_m": dimensions_m,
        "body_name": BODY_NAME,
        "solid_count": 1,
        "scopes": scopes,
    }


def geometry_summary(
    parameters: dict[str, float], density_kg_m3: float = _DEFAULT_DENSITY_KG_M3
) -> dict[str, Any]:
    """Build the real CAD solid and return its geometry-derived SI properties."""
    normalized = _validated_parameters(parameters)
    density = _validated_density(density_kg_m3)
    bracket = _build_bracket(normalized)
    return _geometry_summary(bracket, normalized, density)


def build_geometry(
    parameters: dict[str, float],
    output_dir: Path,
    *,
    density_kg_m3: float = _DEFAULT_DENSITY_KG_M3,
) -> dict[str, Any]:
    """Export the controlled bracket as STEP and write its SI property evidence."""
    normalized = _validated_parameters(parameters)
    density = _validated_density(density_kg_m3)
    bracket = _build_bracket(normalized)
    properties = _geometry_summary(bracket, normalized, density)
    properties["geometry_file"] = "geometry.step"

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".geometry-stage-", dir=destination) as stage_name:
        stage = Path(stage_name)
        staged_step = stage / "geometry.step"
        staged_properties = stage / "geometry-properties.json"
        try:
            from build123d import export_step

            export_step(bracket, staged_step)
        except (ImportError, OSError) as exc:
            raise EnvironmentUnavailableError(
                "The CAD environment could not export the bracket STEP file"
            ) from exc
        except Exception as exc:
            raise SpecValidationError(
                f"STEP export failed ({type(exc).__name__}: {exc})"
            ) from exc
        if not staged_step.is_file() or staged_step.stat().st_size == 0:
            raise SpecValidationError("CAD export did not produce a non-empty geometry.step file")

        properties["geometry_sha256"] = hashlib.sha256(staged_step.read_bytes()).hexdigest()
        staged_properties.write_text(
            json.dumps(properties, allow_nan=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(staged_step, destination / "geometry.step")
        os.replace(staged_properties, destination / "geometry-properties.json")
    return properties
