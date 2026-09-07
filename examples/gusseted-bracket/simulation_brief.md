# Gusseted equipment bracket — simulation brief

## Objective and source

Exercise the deterministic Mechanical linear-static workflow on an original, redistributable
engineering regression fixture. The dimensions, nominal loads, and ideal support below are authored
test inputs (`engineering_default`), not measurements or production requirements.

## Geometry, material, and boundary conditions

- Source: `generate_geometry.py`; outputs: `gusseted-bracket.step` and `geometry-properties.json`.
- One connected steel solid, 240 mm reach, 160 mm width, 188 mm overall height.
- Backing plate: 16 mm thick and 180 mm tall. Shelf: 20 mm thick at Z = 160–180 mm.
- Two 12 mm ribs centered at Y = -45 and +45 mm; rib profiles have R6 corners.
- R10 wall/shelf inside bend; eight diameter-14 mm mounting holes.
- Raised 70 by 60 by 8 mm bearing pad, centered at X = 165, Y = 35 mm.
- Exact imported body: `GussetedBracket|Solid`; material: installed `Structural Steel`.
- Global coordinates: X along reach, Y across width, Z upward; results reported in mm, N, MPa.
- Clamp the unique X-min rear face. The ideal backing carries all translation and rotation.
- Apply force [1000, 1500, -500] N on the unique X-max front face at [240, 0, 170] mm.
- Apply 0.8 MPa inward pressure to the unique Z-max pad face: 3360 N along -Z,
  resultant at [165, 35, 188] mm. Eccentricity and lateral force introduce torsion and bending.
- Apply Earth gravity along -Z. Use CAD volume and center of mass for independent weight/moment checks.
- Material reference for the fixture: E = 200 GPa, Poisson ratio = 0.3, density = 7850 kg/m^3;
  compare these with Mechanical's actual Engineering Data inventory.

## Study and observable acceptance

1. Validate and compile the specification; inspect face matching and preserve input hashes.
2. Run combined loads on 12, 8, and 5 mm quadratic meshes. Each solve must be genuine and
   expose finite requested DPF results with nonempty mesh counts and valid result units.
3. For every run, sum support nodal reactions and moments `sum(r cross R)` about the global
   origin. Compare with force, pressure-area resultant, and CAD mass/centroid gravity.
   Relative tolerances: 0.5% force, 1% moment. Check actual selected face areas and centers.
4. Require increasing mesh counts. For both 12 to 8 mm and 8 to 5 mm, maximum displacement and
   mean pad displacement change at most 5%; pad mean and 95th-percentile stress change at most 10%.
   Pad statistics use equal nodal weights, not an area-weighted surface integration.
   Report global stress maxima separately; their convergence is not a strength criterion.
5. At 5 mm, solve gravity alone and twice the mechanical loads with unchanged gravity.
   Align displacement fields by node ID and coordinates and verify `u(2P+G) = 2u(P+G) - u(G)`.
   This checks the entire displacement field, not ratios of maxima at possibly different nodes.
6. Confirm small deformation, save native projects/RST, export and review mesh, deformation,
   and equivalent-stress PNGs. Retain failed runs and their diagnostics.

## Model assumptions and exclusions

The rear-face clamp is an idealized rigid mounting interface. Hole geometry is retained, but individual
bolt forces, preload, slip, backing flexibility, and contact are not inferred. Ribs, plates, and the pad
transfer load as one continuous solid; weld stresses and defects are not represented. The study tests
linear elasticity and small displacement. It does not calculate fatigue, buckling, plasticity, a weld
rating, or a certified allowable load. Local fixed-edge and load-transition stress peaks require
separate engineering interpretation.

## Open questions

None for executing this explicitly defined regression fixture.
