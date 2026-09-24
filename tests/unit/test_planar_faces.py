from __future__ import annotations

import math

import pytest
from ansys_skill.study.planar_faces import measure_planar_face


def _line(start: tuple[float, float, float], end: tuple[float, float, float]) -> dict:
    return {
        "curve_type": "GeoCurveLineSegment",
        "points": [
            [a + (b - a) * i / 8 for a, b in zip(start, end, strict=True)]
            for i in range(9)
        ],
    }


def _arc(
    center: tuple[float, float, float], radius: float, start: float, end: float, axis: str = "z"
) -> dict:
    axes = tuple(index for index in range(3) if index != {"x": 0, "y": 1, "z": 2}[axis])
    def point(angle: float) -> list[float]:
        result = list(center)
        result[axes[0]] += radius * math.cos(angle)
        result[axes[1]] += radius * math.sin(angle)
        return result

    return {
        "curve_type": "GeoCurveCircularArc",
        "points": [point(start + (end - start) * i / 8) for i in range(9)],
    }


def _face(*, unit: str = "m", holes: list[list[dict]] | None = None) -> dict:
    scale = 1000 if unit == "mm" else 1
    corners = [(0., 0., 0.), (4., 0., 0.), (4., 3., 0.), (0., 3., 0.)]
    edges = [_line(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    for edge in edges:
        edge["points"] = [[value * scale for value in point] for point in edge["points"]]
    loops = [{"edges": edges}]
    for hole in holes or []:
        for edge in hole:
            edge["points"] = [[value * scale for value in point] for point in edge["points"]]
        loops.append({"edges": hole})
    return {"surface_type": "GeoSurfacePlane", "loops": loops}


def _measure(face: dict, unit: str = "m") -> dict:
    return measure_planar_face(face, axis="z", unit=unit, tolerance_m=1e-8)


def test_rectangle_area_and_centroid_are_analytic() -> None:
    result = _measure(_face())

    assert result["area_m2"] == pytest.approx(12)
    assert result["centroid_m"] == pytest.approx([2, 1.5, 0])
    assert len(result["boundary_summary"]["corners_m"]) == 4


@pytest.mark.parametrize("axis", ["x", "y"])
def test_rectangle_and_circle_work_in_each_supported_coordinate_plane(axis: str) -> None:
    corners = {
        "x": [(0, 0, 0), (0, 4, 0), (0, 4, 3), (0, 0, 3)],
        "y": [(0, 0, 0), (4, 0, 0), (4, 0, 3), (0, 0, 3)],
    }[axis]
    hole_center = (0, 2, 1.5) if axis == "x" else (2, 0, 1.5)
    face = {
        "surface_type": "GeoSurfacePlane",
        "loops": [
            {"edges": [_line(corners[i], corners[(i + 1) % 4]) for i in range(4)]},
                {"edges": [_arc(hole_center, 0.25, 0, 2 * math.pi, axis=axis)]},
        ],
    }

    result = measure_planar_face(face, axis=axis, unit="m", tolerance_m=1e-8)
    assert result["area_m2"] == pytest.approx(12 - math.pi * 0.25**2)
    expected_centroid = [0, 2, 1.5] if axis == "x" else [2, 0, 1.5]
    assert result["centroid_m"] == pytest.approx(expected_centroid)


def test_single_full_circle_edge_is_a_valid_hole_loop() -> None:
    face = _face(holes=[[_arc((2, 1.5, 0), 0.2, 0, 2 * math.pi)]])

    assert _measure(face)["area_m2"] == pytest.approx(12 - math.pi * 0.2**2)


def test_circle_hole_and_millimeter_units_use_analytic_moments() -> None:
    hole = [_arc((1., 1., 0.), 0.25, 0, math.pi), _arc((1., 1., 0.), 0.25, math.pi, 2 * math.pi)]
    result = _measure(_face(unit="mm", holes=[hole]), unit="mm")

    assert result["area_m2"] == pytest.approx(12 - math.pi * 0.25**2)
    assert result["centroid_m"] == pytest.approx(
        [(24 - math.pi * 0.25**2) / result["area_m2"],
         (18 - math.pi * 0.25**2) / result["area_m2"], 0]
    )


def test_edges_and_arc_directions_may_be_reversed_and_shuffled() -> None:
    hole = [_arc((2., 1.5, 0.), 0.2, 0, math.pi), _arc((2., 1.5, 0.), 0.2, math.pi, 2 * math.pi)]
    face = _face(holes=[hole])
    for loop in face["loops"]:
        loop["edges"] = [
            {"curve_type": edge["curve_type"], "points": edge["points"][::-1]}
            for edge in loop["edges"][::-1]
        ]

    result = _measure(face)
    assert result["area_m2"] == pytest.approx(12 - math.pi * 0.2**2)
    assert result["centroid_m"] == pytest.approx([2, 1.5, 0])


@pytest.mark.parametrize("defect", ["nonplanar", "open", "nonrectangular", "outside", "overlap", "half-circle"])
def test_invalid_boundaries_are_rejected(defect: str) -> None:
    face = _face()
    if defect == "nonplanar":
        face["loops"][0]["edges"][0]["points"][4][2] = 0.01
    elif defect == "open":
        face["loops"][0]["edges"].pop()
    elif defect == "nonrectangular":
        face["loops"][0]["edges"][1] = _line((4, 0, 0), (3.8, 3, 0))
    elif defect == "outside":
        face["loops"].append({"edges": [_arc((0.1, 1.5, 0), 0.2, 0, 2 * math.pi)]})
    elif defect == "overlap":
        face["loops"].extend([
            {"edges": [_arc((1, 1, 0), 0.3, 0, 2 * math.pi)]},
            {"edges": [_arc((1.4, 1, 0), 0.3, 0, 2 * math.pi)]},
        ])
    else:
        face["loops"].append({"edges": [_arc((2, 1.5, 0), 0.2, 0, math.pi)]})

    with pytest.raises(ValueError):
        _measure(face)


def test_repeated_semicircle_is_rejected_as_duplicate_boundary() -> None:
    face = _face()
    face["loops"].append(
        {"edges": [_arc((2, 1.5, 0), 0.2, 0, math.pi), _arc((2, 1.5, 0), 0.2, 0, math.pi)]}
    )

    with pytest.raises(ValueError):
        _measure(face)


def test_outer_loop_need_not_be_first() -> None:
    face = _face(holes=[[_arc((1, 1, 0), 0.25, 0, 2 * math.pi)]])
    expected = _measure(face)
    face["loops"].reverse()
    actual = _measure(face)
    assert actual["area_m2"] == pytest.approx(expected["area_m2"])
    assert actual["centroid_m"] == pytest.approx(expected["centroid_m"])


def test_reversed_unequal_arcs_cover_the_circle_once() -> None:
    hole = [_arc((1, 1, 0), 0.25, 0, math.pi / 3),
            _arc((1, 1, 0), 0.25, math.pi / 3, 2 * math.pi)]
    for edge in hole:
        edge["points"].reverse()
    actual = _measure(_face(holes=[hole]))
    assert actual["area_m2"] == pytest.approx(12 - math.pi * 0.25**2)
