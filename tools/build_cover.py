"""Compose the README's vector cover from the recorded, unchanged Mechanical PNG."""
from __future__ import annotations

import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build() -> Path:
    evidence = json.loads((ROOT / "docs/reports/evidence/2026-09-06/summary.json").read_text(encoding="utf-8"))
    case = next(case for case in evidence["cases"] if case["id"] == evidence["primary_case"])
    if case["id"] != "mixed_5mm" or case["synthetic"] is not False:
        raise ValueError("Real benchmark evidence required")
    displacement = case["results"]["total_deformation"]
    stress = case["results"]["equivalent_stress"]
    if displacement["reported_unit"] != "mm" or stress["reported_unit"] != "MPa":
        raise ValueError("Cover requires reported displacement in mm and stress in MPa")
    change = evidence["convergence"]["series"]["maximum_total_displacement_m"]
    dimensions = " &#215; ".join(f"{value:g}" for value in evidence["fixture"]["dimensions_mm"])
    image = base64.b64encode((ROOT / "examples/gusseted-bracket/demo/assets/total-deformation.png").read_bytes()).decode("ascii")
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1600" height="900" viewBox="0 0 1600 900">
<title>SimStudio: clear inputs, real results, traceable evidence</title>
<desc>Recorded ANSYS Student 2026 R1 twin-rib bracket, mixed-load 5 mm quadratic mesh. Five real solves and three mesh sizes. Images used courtesy of ANSYS, Inc. Engineering verification remains WARN.</desc>
<rect width="1600" height="900" fill="#fff"/><rect width="470" height="900" fill="#153c47"/>
<g font-family="Segoe UI,Arial,sans-serif">
<rect x="44" y="48" width="53" height="53" rx="11" fill="#fff"/>
<text x="58" y="89" fill="#153c47" font-size="42" font-weight="600">S</text>
<text x="112" y="89" fill="#fff" font-size="43" font-weight="700" letter-spacing="-1.8">SimStudio</text>
<text x="44" y="195" fill="#acd3d3" font-size="15" letter-spacing="2">REVIEWABLE SIMULATION</text>
<g fill="#fff" font-size="52" font-weight="600" letter-spacing="-2">
<text x="44" y="270">Clear inputs.</text><text x="44" y="334">Real results.</text>
<text x="44" y="398" fill="#98dcd0">Traceable</text><text x="44" y="462" fill="#98dcd0">evidence.</text></g>
<g fill="#c3d8df" font-size="22"><text x="44" y="525">From an engineering</text><text x="44" y="560">specification to ANSYS</text><text x="44" y="595">Mechanical linear static</text><text x="44" y="630">analysis.</text></g>
<path d="M44 732H426" stroke="#52727b"/><g fill="#d0e1e5" font-size="18"><text x="44" y="775">Specify → compile → review</text><text x="44" y="810">Execute → extract → verify</text></g>
<text x="44" y="860" font-size="15" fill="#a6c7d0" letter-spacing=".5">OPEN SOURCE · MIT · ALPHA</text>
<text x="510" y="62" font-size="17" fill="#15323f" font-weight="600" letter-spacing="1">TWIN-RIB BRACKET / {case["mesh_mm"]:g} mm</text>
<text x="1560" y="62" text-anchor="end" font-size="16" fill="#526773">{dimensions} mm · Force + pressure + gravity</text>
<path d="M510 86H1560" stroke="#dbe4e7"/>
<image x="502" y="98" width="1064" height="598.5" preserveAspectRatio="xMidYMid meet" xlink:href="data:image/png;base64,{image}"/>
<text x="510" y="721" font-size="14" fill="#526773">{case["node_count"]:,} nodes · {case["element_count"]:,} elements · Quadratic</text>
<text x="1560" y="721" text-anchor="end" font-size="14" fill="#526773">Images used courtesy of ANSYS, Inc.</text>
<rect x="502" y="746" width="1066" height="111" rx="8" fill="#f1f6f7"/>
<g fill="#526773" font-size="14"><text x="528" y="774">MAX TOTAL DISPLACEMENT</text><text x="932" y="774">MAX EQUIVALENT STRESS</text><text x="1240" y="774">8 → 5 mm DISPLACEMENT CHANGE</text></g>
<g fill="#15323f" font-size="33" font-weight="600" letter-spacing="-1"><text x="528" y="816">{displacement["reported_maximum"]:.6f}<tspan dx="7" font-size="18" font-weight="400"> mm</tspan></text><text x="932" y="816">{stress["reported_maximum"]:.6f}<tspan dx="7" font-size="18" font-weight="400"> MPa</tspan></text><text x="1240" y="816">{change["relative_changes"][-1] * 100:.4f}<tspan dx="7" font-size="18" font-weight="400"> %</tspan></text></g>
<g fill="#526773" font-size="13"><text x="528" y="842">Combined loads · fine mesh</text><text x="932" y="842">Reported peak · review required</text><text x="1240" y="842">{change["relative_tolerance"] * 100:g}% mesh-change tolerance</text></g>
<text x="510" y="883" font-size="13" fill="#526773">{evidence["suite"]["tests"]} recorded tests · {len(evidence["fixture"]["mesh_sizes_mm"])} mesh sizes · Student 2026 R1 · 2026-09-06</text>
<text x="1560" y="883" text-anchor="end" font-size="13" font-weight="600" fill="#915509">Engineering review: WARN</text>
</g></svg>'''
    target = ROOT / "docs/assets/overview.svg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(svg, encoding="utf-8", newline="\n")
    return target


if __name__ == "__main__":
    print(build())
