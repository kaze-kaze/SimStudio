"""Isolated DPF extraction worker for reaction resultants and moments."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from ansys_skill.postprocessing.dpf import _resolve_scope, _scope_name
from ansys_skill.schema import SimulationSpec
from ansys_skill.units import normalize_quantity


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("Expected a numeric component")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Expected a finite component")
    return result


def _vector(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("Expected a three-component vector")
    return [_number(component) for component in value]


def _sum_vectors(vectors: list[list[float]]) -> list[float]:
    return [math.fsum(vector[index] for vector in vectors) for index in range(3)]


def _cross(left: list[float], right: list[float]) -> list[float]:
    return [left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0]]


def extract_reaction_evidence(rst_path: Path, simulation: SimulationSpec) -> dict[str, list[float]]:
    """Read the last-set nodal reactions in global coordinates and sum their moments."""
    if not rst_path.is_file() or rst_path.stat().st_size <= 0:
        raise ValueError("RST is missing or empty")
    # Importing DPF can modify process environment variables on Windows. This module only runs
    # in a dedicated child process so the study collector and later Mechanical runs are isolated.
    from ansys.dpf import core as dpf

    model = dpf.Model(str(rst_path))
    mesh = model.metadata.meshed_region
    coordinate_field = mesh.nodes.coordinates_field
    coordinate_unit = str(mesh.unit).strip()
    raw_coordinates = (coordinate_field.data.tolist() if hasattr(coordinate_field.data, "tolist")
                       else list(coordinate_field.data))
    coordinate_ids = list(coordinate_field.scoping.ids)
    if len(raw_coordinates) != len(coordinate_ids) or not coordinate_unit:
        raise ValueError("DPF coordinates lack one-to-one IDs or units")
    coordinates: dict[int, list[float]] = {}
    for node_id, row in zip(coordinate_ids, raw_coordinates, strict=True):
        node = int(node_id)
        if node in coordinates:
            raise ValueError("DPF returned duplicate mesh node IDs")
        coordinates[node] = [normalize_quantity(f"{_number(value)} {coordinate_unit}", "length").magnitude
                             for value in _vector(row)]

    common = {"data_sources": model.metadata.data_sources,
              "time_scoping": [model.metadata.time_freq_support.n_sets],
              "bool_rotate_to_global": True, "server": model._server}
    reactions: dict[int, list[float]] = {}
    for support in simulation.supports:
        name = _resolve_scope(model, _scope_name(simulation, support.scope))
        scope = model.metadata.named_selection(name)
        fields = dpf.operators.result.reaction_force(
            mesh_scoping=scope, **common
        ).outputs.fields_container()
        support_nodes: set[int] = set()
        for field in fields:
            if str(field.location) != "Nodal":
                raise ValueError("DPF reaction field is not nodal")
            force_unit = str(field.unit or "").strip()
            if not force_unit:
                raise ValueError("DPF reaction field unit is missing")
            scale = normalize_quantity(f"1 {force_unit}", "force").magnitude
            raw_rows = field.data.tolist() if hasattr(field.data, "tolist") else list(field.data)
            node_ids = list(field.scoping.ids)
            if len(raw_rows) != len(node_ids):
                raise ValueError("DPF reaction rows do not map one-to-one to node IDs")
            for node_id, row in zip(node_ids, raw_rows, strict=True):
                node = int(node_id)
                if node in support_nodes or node in reactions or node not in coordinates:
                    raise ValueError("DPF reaction nodes are duplicate or absent from mesh coordinates")
                support_nodes.add(node)
                reactions[node] = [component * scale for component in _vector(row)]
        if not support_nodes:
            raise ValueError("DPF returned an empty support reaction field")

    reaction = _sum_vectors(list(reactions.values()))
    moment = _sum_vectors([_cross(coordinates[node], vector)
                           for node, vector in reactions.items()])
    return {"reaction_force_N": reaction, "reaction_moment_Nm": moment}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        request = json.loads(arguments.request.read_text(encoding="utf-8"))
        if not isinstance(request, dict) or not isinstance(request.get("simulation"), dict):
            raise ValueError("Worker request has an invalid structure")
        simulation = SimulationSpec.model_validate(request["simulation"])
        payload = extract_reaction_evidence(Path(request["rst_path"]), simulation)
        arguments.result.write_text(json.dumps(payload, allow_nan=False) + "\n", encoding="utf-8")
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
