"""Analytic area and centroid for the controlled planar study faces."""

from __future__ import annotations

import itertools
import math
from typing import Any

from ansys_skill.units import normalize_quantity

_LINE_TYPES = {"GeoCurveLine", "GeoCurveLineSegment"}
_CIRCLE_TYPES = {"GeoCurveCircle", "GeoCurveCircularArc"}
_AXES = {"x": 0, "y": 1, "z": 2}


def boundaries_match(actual: dict, expected: dict, tolerance_m: float) -> bool:
    """Match every corner and circular hole once, independent of enumeration order."""
    def match_items(left: list, right: list, agrees) -> bool:
        if len(left) != len(right):
            return False
        remaining = list(right)
        for item in left:
            matches = [index for index, other in enumerate(remaining) if agrees(item, other)]
            if len(matches) != 1:
                return False
            remaining.pop(matches[0])
        return True

    return (match_items(actual["corners_m"], expected["corners_m"],
                        lambda a, b: math.dist(a, b) <= tolerance_m)
            and match_items(actual["holes"], expected["holes"],
                            lambda a, b: math.dist(a["center_m"], b["center_m"]) <= tolerance_m
                            and abs(a["radius_m"] - b["radius_m"]) <= tolerance_m))


def _fail(message: str) -> None:
    raise ValueError(message)


def _length(value: Any, unit: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Boundary coordinates must be numeric")
    try:
        return normalize_quantity(f"{value} {unit}", "length").magnitude
    except Exception as exc:
        raise ValueError(f"Invalid length value: {value!r}") from exc


def _distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.dist(a, b)


def _ordered_edges(edges: list[dict[str, Any]], tolerance: float) -> list[tuple[dict[str, Any], bool]]:
    """Order a degree-two endpoint graph; bool says whether to reverse edge samples."""
    if not edges:
        _fail("A boundary loop must contain edges")
    endpoints = [(edge["points"][0], edge["points"][-1]) for edge in edges]
    nodes: list[tuple[float, ...]] = []

    def node_for(point: tuple[float, ...]) -> int:
        matches = [i for i, node in enumerate(nodes) if _distance(point, node) <= tolerance]
        if len(matches) > 1:
            _fail("Boundary endpoints ambiguously overlap")
        if matches:
            return matches[0]
        nodes.append(point)
        return len(nodes) - 1

    links = [(node_for(start), node_for(end)) for start, end in endpoints]
    adjacency: dict[int, list[int]] = {i: [] for i in range(len(nodes))}
    for index, (start, end) in enumerate(links):
        adjacency[start].append(index)
        adjacency[end].append(index)
    if any(len(linked) != 2 for linked in adjacency.values()):
        _fail("Boundary loop is open or has branching/duplicate edges")

    first_start, first_end = links[0]
    ordered: list[tuple[dict[str, Any], bool]] = [(edges[0], False)]
    used: set[int] = {0}
    node = first_end
    while len(used) < len(edges):
        candidates = list(dict.fromkeys(index for index in adjacency[node] if index not in used))
        if len(candidates) != 1:
            _fail("Boundary edges do not form one simple closed loop")
        index = candidates[0]
        start, end = links[index]
        reverse = node == end
        ordered.append((edges[index], reverse))
        used.add(index)
        node = start if reverse else end
    if node != first_start:
        _fail("Boundary loop is not closed")
    return ordered


def _line_data(edge: dict[str, Any], tolerance: float) -> tuple[float, ...]:
    points = edge["points"]
    start, end = points[0], points[-1]
    length = _distance(start, end)
    if length <= tolerance:
        _fail("Degenerate line edge")
    direction = tuple((b - a) / length for a, b in zip(start, end, strict=True))
    projections = []
    for point in points:
        delta = tuple(p - a for p, a in zip(point, start, strict=True))
        projection = _dot(delta, direction)
        closest = tuple(a + direction[i] * projection for i, a in enumerate(start))
        if _distance(point, closest) > tolerance:
            _fail("Line edge samples are not collinear")
        projections.append(projection)
    if any(value < -tolerance or value > length + tolerance for value in projections) or any(
        later < earlier - tolerance for earlier, later in itertools.pairwise(projections)
    ):
        _fail("Line edge samples do not follow the endpoint parameter direction")
    return start


def _dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _circle(
    points: list[tuple[float, ...]],
    tolerance: float,
    plane_axes: tuple[int, int],
    normal_axis: int,
) -> tuple[tuple[float, ...], float]:
    # Pick the widest sampled triangle to avoid fitting from nearly coincident arc points.
    best: tuple[float, tuple[float, ...], float] | None = None
    for a, b, c in itertools.combinations(points, 3):
        ax, ay = (a[i] for i in plane_axes)
        bx, by = (b[i] for i in plane_axes)
        cx, cy = (c[i] for i in plane_axes)
        determinant = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        span = max(_distance(a, b), _distance(b, c), _distance(c, a))
        if abs(determinant) <= max(tolerance, span * 1e-12) * span:
            continue
        aa, bb, cc = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
        center2 = (
            (aa * (by - cy) + bb * (cy - ay) + cc * (ay - by)) / determinant,
            (aa * (cx - bx) + bb * (ax - cx) + cc * (bx - ax)) / determinant,
        )
        radius = math.dist(center2, tuple(a[i] for i in plane_axes))
        if best is None or abs(determinant) > best[0]:
            best = (abs(determinant), center2, radius)
    if best is None:
        _fail("Circular boundary is degenerate")
    _, center2, radius = best
    if radius <= tolerance or any(
        abs(math.dist(tuple(point[i] for i in plane_axes), center2) - radius) > tolerance
        for point in points
    ):
        _fail("Circular edge samples do not lie on one circle")
    center = list(points[0])
    center[plane_axes[0]], center[plane_axes[1]] = center2
    center[normal_axis] = points[0][normal_axis]
    return tuple(center), radius


def measure_planar_face(
    boundary: dict[str, Any], *, axis: str, unit: str, tolerance_m: float
) -> dict[str, Any]:
    """Measure a planar rectangle with circular holes using analytic area moments."""
    if axis not in _AXES:
        _fail("axis must be one of 'x', 'y', or 'z'")
    if not isinstance(boundary, dict) or boundary.get("surface_type") != "GeoSurfacePlane":
        _fail("Only GeoSurfacePlane boundaries are supported")
    tolerance = _length(tolerance_m, "m")
    if not math.isfinite(tolerance) or tolerance <= 0:
        _fail("tolerance_m must be finite and positive")
    axis_index = _AXES[axis]
    loops = boundary.get("loops")
    if not isinstance(loops, list) or not 1 <= len(loops) <= 5:
        _fail("A controlled planar face requires one outer loop and at most four holes")

    parsed: list[list[dict[str, Any]]] = []
    plane_coordinate: float | None = None
    for loop in loops:
        if not isinstance(loop, dict) or not isinstance(loop.get("edges"), list):
            _fail("Each loop must contain an edge list")
        if not 1 <= len(loop["edges"]) <= 16:
            _fail("Controlled boundary loops must have between one and sixteen edges")
        edges = []
        for edge in loop["edges"]:
            if not isinstance(edge, dict):
                _fail("Invalid boundary edge")
            curve = edge.get("curve_type")
            if curve not in _LINE_TYPES | _CIRCLE_TYPES:
                _fail(f"Unsupported boundary curve: {curve!r}")
            raw_points = edge.get("points")
            if not isinstance(raw_points, list) or len(raw_points) != 9:
                _fail("Each edge must provide exactly nine parameter samples")
            points = []
            for point in raw_points:
                if not isinstance(point, (list, tuple)) or len(point) != 3:
                    _fail("Each sampled point must have three coordinates")
                converted = tuple(_length(value, unit) for value in point)
                if not all(math.isfinite(value) for value in converted):
                    _fail("Boundary coordinates must be finite")
                if plane_coordinate is None:
                    plane_coordinate = converted[axis_index]
                elif abs(converted[axis_index] - plane_coordinate) > tolerance:
                    _fail("Boundary is not planar on the requested axis")
                points.append(converted)
            edges.append({"curve_type": curve, "points": points})
        parsed.append(edges)

    outer_indices = [index for index, edges in enumerate(parsed)
                     if len(edges) == 4 and all(edge["curve_type"] in _LINE_TYPES for edge in edges)]
    if len(outer_indices) != 1:
        _fail("There must be exactly one four-edge rectangular outer boundary")
    outer_index = outer_indices[0]
    outer = _ordered_edges(parsed[outer_index], tolerance)
    for edge, _ in outer:
        _line_data(edge, tolerance)
    corners = []
    for edge, reverse in outer:
        points = edge["points"]
        corners.append(points[-1] if reverse else points[0])
    sides = [tuple(b[i] - a[i] for i in range(3)) for a, b in zip(corners, corners[1:] + corners[:1], strict=True)]
    lengths = [math.sqrt(_dot(side, side)) for side in sides]
    if min(lengths) <= tolerance:
        _fail("Rectangle has a degenerate side")
    if any(
        abs(_dot(sides[i], sides[(i + 1) % 4]))
        > tolerance * max(lengths[i], lengths[(i + 1) % 4])
        for i in range(4)
    ):
        _fail("Outer boundary is not rectangular")
    if _distance(corners[0], corners[2]) <= tolerance or _distance(corners[1], corners[3]) <= tolerance:
        _fail("Rectangle is degenerate")
    for i in range(2):
        if math.sqrt(sum((sides[i][j] + sides[i + 2][j]) ** 2 for j in range(3))) > tolerance * 2:
            _fail("Opposite rectangle sides do not agree")
    rectangle_area = lengths[0] * lengths[1]
    rectangle_centroid = tuple(sum(point[i] for point in corners) / 4 for i in range(3))

    holes = []
    for loop_index, loop_edges in enumerate(parsed):
        if loop_index == outer_index:
            continue
        ordered = _ordered_edges(loop_edges, tolerance)
        if any(edge["curve_type"] not in _CIRCLE_TYPES for edge, _ in ordered):
            _fail("Hole boundaries must contain only circular edges")
        plane_axes = tuple(index for index in range(3) if index != axis_index)
        center, radius = _circle(
            [p for edge, _ in ordered for p in edge["points"]],
            tolerance,
            plane_axes,
            axis_index,
        )
        sweep = 0.0
        angular_intervals: list[tuple[float, float]] = []
        for edge, reverse in ordered:
            points = edge["points"][::-1] if reverse else edge["points"]
            for a, b in itertools.pairwise(points):
                aa = math.atan2(a[plane_axes[1]] - center[plane_axes[1]], a[plane_axes[0]] - center[plane_axes[0]])
                ab = math.atan2(b[plane_axes[1]] - center[plane_axes[1]], b[plane_axes[0]] - center[plane_axes[0]])
                delta = (ab - aa + math.pi) % (2 * math.pi) - math.pi
                sweep += abs(delta)
                start = (aa if delta >= 0 else ab) % (2 * math.pi)
                end = start + abs(delta)
                if end <= 2 * math.pi:
                    angular_intervals.append((start, end))
                else:
                    angular_intervals.extend(((start, 2 * math.pi), (0.0, end - 2 * math.pi)))
        angular_tolerance = max(1e-9, tolerance / radius * 4)
        angular_intervals.sort()
        if any(
            current[0] < previous[1] - angular_tolerance
            for previous, current in itertools.pairwise(angular_intervals)
        ):
            _fail("Circular loop contains repeated or overlapping arc segments")
        if not math.isclose(sweep, 2 * math.pi, rel_tol=0.0, abs_tol=max(1e-5, tolerance / radius * 8)):
            _fail("Circular loop must cover exactly one complete circle")
        holes.append({"center_m": center, "radius_m": radius})

    # The rectangle basis also supports rectangles rotated within the selected plane.
    u = tuple(value / lengths[0] for value in sides[0])
    v = tuple(value / lengths[1] for value in sides[1])
    origin = corners[0]
    for hole in holes:
        delta = tuple(hole["center_m"][i] - origin[i] for i in range(3))
        x, y, radius = _dot(delta, u), _dot(delta, v), hole["radius_m"]
        if min(x, y, lengths[0] - x, lengths[1] - y) < radius - tolerance:
            _fail("Circular hole lies outside the outer rectangle")
    for a, b in itertools.combinations(holes, 2):
        if _distance(a["center_m"], b["center_m"]) <= a["radius_m"] + b["radius_m"] + tolerance:
            _fail("Circular holes overlap or repeat")

    area = rectangle_area - sum(math.pi * hole["radius_m"] ** 2 for hole in holes)
    if area <= tolerance * tolerance:
        _fail("Planar face has degenerate remaining area")
    moment = [rectangle_area * value for value in rectangle_centroid]
    for hole in holes:
        hole_area = math.pi * hole["radius_m"] ** 2
        for index in range(3):
            moment[index] -= hole_area * hole["center_m"][index]
    return {
        "area_m2": area,
        "centroid_m": [value / area for value in moment],
        "boundary_summary": {"corners_m": [list(point) for point in corners], "holes": holes},
    }
