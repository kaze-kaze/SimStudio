from __future__ import annotations

import builtins
import hashlib
import importlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from ansys_skill.errors import EnvironmentUnavailableError, SpecValidationError
from ansys_skill.study import geometry

BASE_PARAMETERS = {
    "plate_thickness": 0.020,
    "hole_diameter": 0.014,
    "fillet_radius": 0.010,
}


@pytest.fixture
def cad_dependency():
    return pytest.importorskip("build123d")


def _parameters(thickness_mm: float, hole_mm: float, fillet_mm: float) -> dict[str, float]:
    return {
        "plate_thickness": thickness_mm / 1000.0,
        "hole_diameter": hole_mm / 1000.0,
        "fillet_radius": fillet_mm / 1000.0,
    }


@pytest.mark.parametrize(
    "parameters",
    [
        BASE_PARAMETERS,
        _parameters(14, 10, 6),
        _parameters(24, 10, 14),
        _parameters(24, 18, 6),
        _parameters(14, 18, 14),
    ],
    ids=(
        "baseline",
        "minimum-corner",
        "thick-plate-large-root",
        "large-holes-thick-plate",
        "thin-plate-large-root",
    ),
)
def test_builds_baseline_and_supported_boundary_corners(
    tmp_path: Path, parameters: dict[str, float], cad_dependency
) -> None:
    result = geometry.build_geometry(parameters, tmp_path)

    assert result["generator"] == "gusseted_bracket"
    assert result["generator_version"] == "1"
    assert result["parameters"] == parameters
    assert result["body_name"] == "GussetedBracket|Solid"
    assert result["solid_count"] == 1
    assert result["volume_m3"] > 0
    assert result["mass_kg"] == pytest.approx(result["volume_m3"] * 7850.0)
    assert result["bounding_box_m"] == pytest.approx([0.240, 0.160, 0.188], abs=1e-9)
    assert set(result["scopes"]) == {"mounting_face", "front_face", "bearing_pad"}
    assert all(scope["unique_face_count"] == 1 for scope in result["scopes"].values())
    assert result["geometry_file"] == "geometry.step"
    assert len(result["geometry_sha256"]) == 64
    assert (tmp_path / "geometry.step").stat().st_size > 0
    properties_text = (tmp_path / "geometry-properties.json").read_text()
    assert json.loads(properties_text) == result
    assert str(tmp_path) not in properties_text
    assert "GussetedBracket" in (tmp_path / "geometry.step").read_text(encoding="utf-8")
    assert hashlib.sha256((tmp_path / "geometry.step").read_bytes()).hexdigest() == result[
        "geometry_sha256"
    ]


def test_summary_reports_cad_mass_center_and_unique_scope_face_data(cad_dependency) -> None:
    summary = geometry.geometry_summary(BASE_PARAMETERS)

    assert summary["volume_m3"] > 0
    assert summary["mass_kg"] == pytest.approx(summary["volume_m3"] * 7850.0)
    assert len(summary["center_of_mass_m"]) == 3
    assert all(math.isfinite(value) for value in summary["center_of_mass_m"])
    assert summary["volume_m3"] == pytest.approx(0.0015322805291252618, rel=1e-10)
    assert summary["center_of_mass_m"] == pytest.approx(
        [0.08328807660328462, 0.0007674834846797668, 0.13417855048933333], abs=2e-11
    )
    assert summary["bounding_box_m"] == pytest.approx([0.240, 0.160, 0.188], abs=1e-9)
    assert set(summary["scopes"]) == {"mounting_face", "front_face", "bearing_pad"}

    mounting = summary["scopes"]["mounting_face"]
    front = summary["scopes"]["front_face"]
    pad = summary["scopes"]["bearing_pad"]
    assert (mounting["axis"], mounting["extreme"]) == ("x", "min")
    assert (front["axis"], front["extreme"]) == ("x", "max")
    assert (pad["axis"], pad["extreme"]) == ("z", "max")
    for scope in (mounting, front, pad):
        assert scope["unique_face_count"] == 1
        assert scope["area_m2"] > 0
        assert len(scope["centroid_m"]) == 3
        assert len(scope["normal"]) == 3
        assert math.sqrt(sum(component**2 for component in scope["normal"])) == pytest.approx(1.0)
        assert scope["tolerance_m"] == pytest.approx(1e-6)
    assert mounting["centroid_m"][0] == pytest.approx(0.0, abs=1e-9)
    assert mounting["normal"] == pytest.approx([-1.0, 0.0, 0.0], abs=1e-9)
    assert front["centroid_m"] == pytest.approx([0.240, 0.0, 0.170], abs=1e-9)
    assert front["area_m2"] == pytest.approx(0.160 * 0.020)
    assert front["normal"] == pytest.approx([1.0, 0.0, 0.0], abs=1e-9)
    assert pad["centroid_m"] == pytest.approx([0.165, 0.035, 0.188], abs=1e-9)
    assert pad["area_m2"] == pytest.approx(0.070 * 0.060)
    assert pad["normal"] == pytest.approx([0.0, 0.0, 1.0], abs=1e-9)


def test_volume_changes_with_thickness_hole_diameter_and_root_radius(cad_dependency) -> None:
    baseline = geometry.geometry_summary(BASE_PARAMETERS)["volume_m3"]
    thicker = geometry.geometry_summary(_parameters(22, 14, 10))["volume_m3"]
    larger_holes = geometry.geometry_summary(_parameters(20, 16, 10))["volume_m3"]
    larger_root = geometry.geometry_summary(_parameters(20, 14, 12))["volume_m3"]

    assert thicker > baseline
    assert larger_holes < baseline
    assert larger_root != pytest.approx(baseline, rel=1e-8)


@pytest.mark.parametrize(
    "parameters",
    [
        {"plate_thickness": 0.020, "hole_diameter": 0.014},
        {**BASE_PARAMETERS, "extra": 0.001},
        {**BASE_PARAMETERS, "hole_diameter": math.nan},
        {**BASE_PARAMETERS, "plate_thickness": math.inf},
        {**BASE_PARAMETERS, "fillet_radius": True},
        _parameters(13.9, 14, 10),
        _parameters(24.1, 14, 10),
        _parameters(20, 9.9, 10),
        _parameters(20, 14, 14.1),
    ],
)
def test_invalid_or_unsupported_geometry_parameters_fail(parameters: dict[str, float]) -> None:
    with pytest.raises(SpecValidationError):
        geometry.validate_parameters(parameters)


def test_interacting_dimensions_enforce_minimum_root_to_hole_wall() -> None:
    geometry.validate_parameters(_parameters(24, 18, 10))

    with pytest.raises(SpecValidationError, match="at least 5 mm is required"):
        geometry.validate_parameters(_parameters(24, 18, 14))


def test_parameter_bound_accepts_one_ulp_rounding_and_normalizes_to_limit() -> None:
    rounded_hole_limit = math.nextafter(0.018, math.inf)
    parameters = {**BASE_PARAMETERS, "hole_diameter": rounded_hole_limit}

    geometry.validate_parameters(parameters)

    normalized = geometry._validated_parameters(parameters)
    assert normalized["hole_diameter"] == 0.018


def test_parameter_bound_rejects_values_beyond_one_ulp_tolerance() -> None:
    beyond_hole_limit = math.nextafter(math.nextafter(0.018, math.inf), math.inf)
    parameters = {**BASE_PARAMETERS, "hole_diameter": beyond_hole_limit}

    with pytest.raises(SpecValidationError, match=r"between 0.01 and 0.018 m"):
        geometry.validate_parameters(parameters)


@pytest.mark.parametrize(
    ("is_valid", "expected"),
    [
        (True, True),
        (False, False),
        (lambda: True, True),
        (lambda: False, False),
    ],
)
def test_shape_validity_supports_property_and_method_apis(is_valid, expected: bool) -> None:
    assert geometry._shape_is_valid(SimpleNamespace(is_valid=is_valid)) is expected


def test_custom_density_is_explicit_and_used_for_mass(cad_dependency) -> None:
    summary = geometry.geometry_summary(BASE_PARAMETERS, density_kg_m3=2700.0)

    assert summary["density_kg_m3"] == 2700.0
    assert summary["mass_kg"] == pytest.approx(summary["volume_m3"] * 2700.0)


@pytest.mark.parametrize("density", [0.0, -1.0, math.nan, math.inf, True])
def test_invalid_density_fails_before_cad_construction(density: float) -> None:
    with pytest.raises(SpecValidationError, match="Density"):
        geometry.geometry_summary(BASE_PARAMETERS, density_kg_m3=density)


def test_module_import_does_not_import_optional_cad_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def reject_build123d(name, *args, **kwargs):
        if name == "build123d" or name.startswith("build123d."):
            raise ModuleNotFoundError("blocked optional dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_build123d)
    reloaded = importlib.reload(geometry)

    assert callable(reloaded.validate_parameters)


def test_missing_cad_dependency_has_environment_error(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def reject_build123d(name, *args, **kwargs):
        if name == "build123d" or name.startswith("build123d."):
            raise ModuleNotFoundError("blocked optional dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_build123d)
    with pytest.raises(EnvironmentUnavailableError, match="optional build123d"):
        geometry.geometry_summary(BASE_PARAMETERS)
