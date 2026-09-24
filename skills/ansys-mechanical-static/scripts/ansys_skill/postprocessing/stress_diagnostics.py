"""Bounded global stress evidence extracted from a real Mechanical RST with PyDPF."""

from __future__ import annotations

import heapq
import math
from pathlib import Path
from typing import Any

from ansys_skill.manifest import sha256_file
from ansys_skill.units import normalize_quantity

_TOP_COUNT = 20


def _as_list(value: Any) -> list[Any]:
    return value.tolist() if hasattr(value, "tolist") else list(value)


def _flat_numbers(value: Any) -> list[float]:
    raw = value.tolist() if hasattr(value, "tolist") else value
    if isinstance(raw, (list, tuple)):
        flattened: list[float] = []
        for item in raw:
            flattened.extend(_flat_numbers(item))
        return flattened
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("DPF stress data contains a non-numeric value")
    number = float(raw)
    if not math.isfinite(number):
        raise ValueError("DPF stress data contains a non-finite value")
    return [number]


def _unit_scale(unit: Any, dimension: str) -> tuple[str, float]:
    text = str(unit or "").strip()
    if not text:
        raise ValueError(f"DPF {dimension} field unit is missing")
    normalized = normalize_quantity(f"1 {text}", dimension)
    return text, normalized.magnitude


def _coordinates(model: Any) -> dict[int, list[float]]:
    mesh = model.metadata.meshed_region
    field = mesh.nodes.coordinates_field
    node_ids = [int(item) for item in field.scoping.ids]
    rows = _as_list(field.data)
    if not node_ids or len(rows) != len(node_ids):
        raise ValueError("DPF mesh coordinates do not map one-to-one to node IDs")
    _, scale = _unit_scale(mesh.unit, "length")
    result: dict[int, list[float]] = {}
    for node_id, raw_row in zip(node_ids, rows, strict=True):
        if node_id in result:
            raise ValueError("DPF mesh coordinates contain duplicate node IDs")
        row = _flat_numbers(raw_row)
        if len(row) != 3:
            raise ValueError("DPF mesh coordinate is not a three-component point")
        point = [value * scale for value in row]
        if not all(math.isfinite(value) for value in point):
            raise ValueError("DPF mesh coordinates overflow canonical units")
        result[node_id] = point
    return result


def _top_nodes(
    dpf: Any, model: Any, coordinates: dict[int, list[float]], result_set: int
) -> dict[str, Any]:
    fields = list(
        dpf.operators.result.stress_eqv_as_mechanical(
            data_sources=model.metadata.data_sources,
            time_scoping=[result_set],
            requested_location="Nodal",
            server=model._server,
        ).outputs.fields_container()
    )
    heap: list[tuple[float, int, dict[str, Any]]] = []
    seen: set[int] = set()
    units: set[str] = set()
    count = 0
    for field in fields:
        location = str(field.location)
        if location != "Nodal":
            raise ValueError(f"Expected nodal Mechanical-averaged stress; received {location!r}")
        unit, scale = _unit_scale(field.unit, "pressure")
        units.add(unit)
        values = _flat_numbers(field.data)
        ids = [int(item) for item in field.scoping.ids]
        if not values or len(values) != len(ids):
            raise ValueError("DPF nodal stress values do not map one-to-one to node IDs")
        for node_id, raw_value in zip(ids, values, strict=True):
            if node_id in seen or node_id not in coordinates:
                raise ValueError("DPF nodal stress has duplicate or unmapped node IDs")
            seen.add(node_id)
            canonical = raw_value * scale
            if not math.isfinite(canonical):
                raise ValueError("DPF nodal stress overflows canonical units")
            count += 1
            record = {
                "node_id": node_id,
                "coordinate_m": coordinates[node_id],
                "raw_value": raw_value,
                "raw_unit": unit,
                "stress_Pa": canonical,
            }
            entry = (canonical, -node_id, record)
            if len(heap) < _TOP_COUNT:
                heapq.heappush(heap, entry)
            elif entry[:2] > heap[0][:2]:
                heapq.heapreplace(heap, entry)
    if not heap:
        raise ValueError("DPF nodal stress field is empty")
    ranked = sorted(heap, key=lambda item: (-item[0], -item[1]))
    maximum = ranked[0][2]
    return {
        "location": "Nodal",
        "units": sorted(units),
        "value_count": count,
        "maximum": {
            "node_id": maximum["node_id"],
            "coordinate_m": maximum["coordinate_m"],
            "raw_max": maximum["raw_value"],
            "raw_max_unit": maximum["raw_unit"],
            "value_Pa": maximum["stress_Pa"],
        },
        "top_20": [item[2] for item in ranked],
    }


def _top_elements(
    dpf: Any, model: Any, coordinates: dict[int, list[float]], result_set: int
) -> dict[str, Any]:
    fields = list(
        dpf.operators.result.stress_von_mises(
            data_sources=model.metadata.data_sources,
            requested_location="ElementalNodal",
            time_scoping=[result_set],
            server=model._server,
        ).outputs.fields_container()
    )
    mesh = model.metadata.meshed_region
    heap: list[tuple[float, int, dict[str, Any]]] = []
    seen: set[int] = set()
    units: set[str] = set()
    count = 0
    for field in fields:
        location = str(field.location)
        if location != "ElementalNodal":
            raise ValueError(f"Expected unaveraged ElementalNodal stress; received {location!r}")
        unit, scale = _unit_scale(field.unit, "pressure")
        units.add(unit)
        element_ids = [int(item) for item in field.scoping.ids]
        if not element_ids:
            continue
        for element_id in element_ids:
            if element_id in seen:
                raise ValueError("DPF elemental-nodal stress contains duplicate element IDs")
            seen.add(element_id)
            raw_values = _flat_numbers(field.get_entity_data_by_id(element_id))
            if not raw_values:
                raise ValueError("DPF elemental-nodal stress contains an empty element array")
            values_pa = [value * scale for value in raw_values]
            if not all(math.isfinite(value) for value in values_pa):
                raise ValueError("DPF elemental-nodal stress overflows canonical units")
            element = mesh.elements.element_by_id(element_id)
            node_ids = [int(item) for item in element.node_ids]
            if not node_ids or any(node not in coordinates for node in node_ids):
                raise ValueError("DPF element references a node without mesh coordinates")
            maximum_index = max(range(len(values_pa)), key=values_pa.__getitem__)
            maximum_pa = values_pa[maximum_index]
            count += 1
            record = {
                "element_id": element_id,
                "element_type": str(element.type),
                "raw_max": raw_values[maximum_index],
                "raw_unit": unit,
                "maximum_Pa": maximum_pa,
                "raw_stress_values": raw_values,
                "node_ids": node_ids,
                "node_coordinates_m": [coordinates[node] for node in node_ids],
                "value_node_mapping": "unassigned; values are retained in DPF local order",
            }
            entry = (maximum_pa, -element_id, record)
            if len(heap) < _TOP_COUNT:
                heapq.heappush(heap, entry)
            elif entry[:2] > heap[0][:2]:
                heapq.heapreplace(heap, entry)
    if not heap:
        raise ValueError("DPF elemental-nodal stress field is empty")
    ranked = sorted(heap, key=lambda item: (-item[0], -item[1]))
    maximum = ranked[0][2]
    return {
        "location": "ElementalNodal",
        "units": sorted(units),
        "element_count": count,
        "maximum": {
            "element_id": maximum["element_id"],
            "raw_max": maximum["raw_max"],
            "raw_max_unit": maximum["raw_unit"],
            "value_Pa": maximum["maximum_Pa"],
        },
        "top_20": [item[2] for item in ranked],
    }


def collect_global_stress_diagnostics(rst_path: Path, dpf: Any, model: Any) -> dict[str, Any]:
    """Return bounded all-model stress evidence, or an explicit NOT_RUN record."""
    digest: str | None = None
    result_set: int | None = None
    try:
        if not rst_path.is_file() or rst_path.stat().st_size <= 0:
            raise ValueError("RST is missing or empty")
        digest = sha256_file(rst_path)
        result_set = int(model.metadata.time_freq_support.n_sets)
        if result_set < 1:
            raise ValueError("DPF result has no result sets")
        coordinates = _coordinates(model)
        nodal = _top_nodes(dpf, model, coordinates, result_set)
        elemental_nodal = _top_elements(dpf, model, coordinates, result_set)
        if sha256_file(rst_path) != digest:
            raise ValueError("RST changed during stress diagnostics")
        return {
            "status": "COMPLETED",
            "scope": "global",
            "result_file_sha256": digest,
            "last_result_set": result_set,
            "nodal_definition": "stress_eqv_as_mechanical",
            "elemental_nodal_definition": "stress_von_mises",
            "nodal": nodal,
            "elemental_nodal": elemental_nodal,
        }
    except Exception as exc:
        return {
            "status": "NOT_RUN",
            "scope": "global",
            "result_file_sha256": digest,
            "last_result_set": result_set,
            "reason": f"{type(exc).__name__}: {exc}",
        }
