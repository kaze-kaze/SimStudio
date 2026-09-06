# Official API map

Package research: **2026-09-04**. Live local acceptance: **2026-09-06**, using Windows 11 and
ANSYS Student Mechanical 2026 R1 (executable file version `26,2026,13,1`). Sources are official
documentation, installed package metadata, and saved real-run evidence. "Package-verified" means
an import/signature inspection; "live batch tested" means the installed licensed product ran the
API through a saved script. Neither label implies remote gRPC acceptance.

## Packages and versions

| Package | v0.1 range | Local evidence | Official source |
|---|---|---|---|
| `ansys-mechanical-core` | `>=0.13.2,<0.14` | 0.13.2 installed on CPython 3.13.2; signatures inspected; local gRPC failed as recorded below | https://mechanical.docs.pyansys.com/version/stable/ and https://pypi.org/project/ansys-mechanical-core/ |
| `ansys-dpf-core` | `>=0.16.1,<0.17` | 0.16.1 read real v261 RST data through DPF Server 11.0 | https://dpf.docs.pyansys.com/version/stable/ and https://pypi.org/project/ansys-dpf-core/ |
| `ansys-mechanical-stubs` | transitive | 0.1.13, including v242/v251/v252/v261 stubs, inspected | https://scripting.mechanical.docs.pyansys.com/version/stable/ |

The base CLI supports Python 3.11–3.13 independently of the optional clients. Installed
PyMechanical 0.13.2 metadata declares `Requires-Python: >=3.12,<4.0`; installing the `ansys` extra
on Python 3.11 failed during acceptance setup. Use Python 3.12–3.13 for that extra; the tested
interpreter is CPython 3.13.2. The Mechanical product itself is a separate licensed installation.

Sources:

- https://mechanical.docs.pyansys.com/version/stable/getting_started/index.html
- https://dpf.docs.pyansys.com/version/stable/getting_started/index.html

## Local batch API and acceptance

The explicit `mechanical_batch` backend uses the official Windows command-line script entry point:

```text
AnsysWBU.exe -DSApplet -AppModeMech -b -script <generated-mechanical.py> -x
```

The working directory is the isolated compiled run directory. The same fixed Mechanical runtime
and input snapshot are used by both real backends. Process stdout/stderr, structured artifacts,
the actual `Project.ProductVersion`, and input/script hashes are retained. A script can report
`FAILED` while the executable returns `0`, so the backend requires both a successful process
exit and a `SOLVED` artifact with real RST files. Timeout cleanup targets only its own process tree.

This backend is Windows-local-only and explicitly selected; it is never a fallback after gRPC
failure. Both `run` modes still require `--execute` to start a product. See
[`docs/reports/mechanical-test-2026-09-06.md`](../../../docs/reports/mechanical-test-2026-09-06.md)
for numerical results, test coverage, and the remaining transport limitations.

Official command-line implementation/reference:
https://mechanical.docs.pyansys.com/version/stable/api/ansys/mechanical/core/run/index.html

## PyMechanical client API

Package-verified signatures from `ansys-mechanical-core==0.13.2`:

```text
launch_mechanical(allow_input=True, exec_file=None, batch=True, loglevel='ERROR',
  log_file=False, log_mechanical=None, additional_switches=None, additional_envs=None,
  start_timeout=120, port=None, ip=None, host=None, start_instance=None,
  verbose_mechanical=False, clear_on_connect=False, cleanup_on_exit=True, version=None,
  keep_connection_alive=True, backend='mechanical', transport_mode=None, certs_dir=None,
  grpc_options=None, start_license=None, read_only=False)
connect_to_mechanical(ip=None, port=None, loglevel='ERROR', log_file=False,
  log_mechanical=None, connect_timeout=120, clear_on_connect=False,
  cleanup_on_exit=False, keep_connection_alive=True, transport_mode=None,
  certs_dir=None, grpc_options=None)
Mechanical.run_python_script_from_file(self, file_path, enable_logging=False,
  log_level='WARNING', progress_interval=2000)
Mechanical.upload(self, file_name, file_location_destination=None, chunk_size=1048576,
  progress_bar=True)
Mechanical.download(self, files, target_dir=None, chunk_size=262144, progress_bar=None,
  recursive=False)
Mechanical.exit(self, force=False)
Mechanical.version -> connected product version string, for example `261`
```

Official class/source pages:

- https://mechanical.docs.pyansys.com/version/stable/api/ansys/mechanical/core/mechanical/Mechanical.html
- https://mechanical.docs.pyansys.com/version/stable/user_guide/remote_session/overview.html
- https://mechanical.docs.pyansys.com/version/stable/api/ansys/mechanical/core/index.html

The `pymechanical_remote` backend uses remote-session gRPC. The saved script uses Mechanical's `Model`, `DataModel`,
`ExtAPI`, and `Quantity` globals; it does not use the Python embedding `App` class. Project operations
refresh `Model` and `DataModel` after opening or creating the project.

The 2026-09-04 review re-inspected PyMechanical 0.13.2 and PyDPF 0.16.1 on Python 3.13.
`run_python_script_from_file` returns the last statement's value, not stdout. Work-directory and
result protocols therefore end in a string expression. Generated sources remain IronPython-compatible,
use Unicode path literals, and do not rely on Python 3's recursive `glob`. Live localized-template
tests require the `unicode` constructor explicitly; deriving it with `type(u"")` can instead
encode Chinese Mechanical object names and fail in IronPython.

`find_mechanical()` discovers the product in its standard installation directory without launching it.
The resulting executable is also supplied to `launch_mechanical(exec_file=...)`. The client CLI
executable `ansys-mechanical` is not evidence that the commercial product is installed.

Remote downloads use explicit lists of full server paths and the returned local filenames, including
Windows-to-POSIX filename normalization. Required download failures preserve their diagnostics and the
server workspace. These contracts have offline regression tests, not live server verification.

## Transport and security

Official PyMechanical documentation defines `insecure`, `wnua`, and `mtls`, and requires the client
and server to use the same explicit mode. Its current table lists all Mechanical 2026 R1 service
packs; Mechanical 2025 R2 SP03+ for `insecure`, WNUA, and mTLS; Mechanical 2025 R1 SP04+ and 2024 R2
SP05+ for `insecure` and WNUA only. Earlier product versions retain legacy gRPC behavior but do not
support the `transport_mode` argument. `wnua` is Windows-only. mTLS uses `certs_dir` and the documented
certificate layout.

Source: https://mechanical.docs.pyansys.com/version/stable/user_guide/remote_session/overview.html

Implementation status: localhost defaults to explicit `insecure`; non-local hosts require explicit
`allow_remote: true` plus authenticated transport. Doctor rejects WNUA on non-Windows clients and
missing mTLS certificate directories. On the tested Student 2026 R1 installation, the local
Mechanical gRPC server listened and checked out a license, but closed the HTTP/2 connection during
handshake. The original real test failed after 604 seconds with CLI exit `4`. Legacy startup,
WNUA-client, and grpcio 1.71.0 probes also failed; no compatible gRPC path is claimed from these runs.
Authentication, remote upload/download, and gRPC timeout cleanup remain **NOT_RUN** as live acceptance
items. Local batch success must not be reported as gRPC success.

## Mechanical scripting object model

The compiler/runtime uses these documented entry points:

| Purpose | Entry point | Evidence | Current verification |
|---|---|---|---|
| open template | `ExtAPI.DataModel.Project.Open(path)` | v261 Project documentation and stubs | documented/package-inspected; live batch tested (2026 R1) |
| new project | `ExtAPI.DataModel.Project.New()` | v261 Project documentation and stubs | documented/package-inspected; live batch tested (2026 R1) |
| import geometry | `Model.AddGeometryImportGroup().AddGeometryImport()` and `GeometryImport.Import(path, Format.Automatic, GeometryImportPreferences())` | official example/stubs | package stubs inspected; live batch tested (2026 R1) |
| add analysis | `Model.AddStaticStructuralAnalysis()` | official example/stubs | package stubs inspected; live batch tested (2026 R1) |
| verify analysis | `AnalysisType == Static`, `PhysicsType == Mechanical`, `AnalysisSettings.LargeDeflection = False` | v261 scripting stubs | package stubs inspected; live batch tested (2026 R1) |
| exact names | `DataModel.GetObjectsByName(name)` | scripting object model | generated runtime requires exactly one; live batch tested (2026 R1) |
| object types | `.GetType().Name` centralized in `MechanicalCompat` | .NET object model used by Mechanical scripting | generated runtime enforces exact template type names; live batch tested (2026 R1) |
| exact bodies | `DataModel.GetObjectsByType(DataModelObjectCategory.Body)` | scripting object model/stubs | stubs inspected; live batch tested (2026 R1) |
| material assignment | `body.Material = exact_engineering_data_name` | official material assignment example | documented/example; live batch tested (2026 R1) |
| fixed support | `analysis.AddFixedSupport()` | official example/stubs | documented/example; live batch tested (2026 R1) |
| force | `analysis.AddForce()`, `LoadDefineBy.Components`, component `DiscreteValues` | official example/stubs | documented/example; live batch tested (2026 R1) |
| pressure | `analysis.AddPressure()`, `Magnitude.Output.DiscreteValues` | scripting stubs | package stubs inspected; live batch tested (2026 R1) |
| gravity | `analysis.AddEarthGravity()`, `Direction` with `GravityOrientationType`, global coordinates | scripting stubs | package stubs inspected; live batch tested (2026 R1) |
| mesh | `Model.Mesh.ElementSize`, `Model.Mesh.ElementOrder`, `Model.Mesh.GenerateMesh()` | official 2026 R1 example/stubs | size and generation live tested; explicit element-order override remains NOT_RUN |
| results | `Solution.AddTotalDeformation()`, `AddDirectionalDeformation()`, `AddEquivalentStress()`, `AddForceReaction()` | scripting stubs | package stubs inspected; live batch tested (2026 R1) |
| solve | `analysis.Solve(True)` | official example/stubs | documented/example; live batch tested (2026 R1) |
| save | `ExtAPI.DataModel.Project.SaveAs(path, True)` | v261 Project signature | documented/package-inspected; live batch tested (2026 R1) |
| solver files | `Analysis.ResultFileName`, `SolverFilesDirectory`, `WorkingDir` | v261 Analysis stubs | package-inspected; live batch tested (2026 R1) |
| global coordinates | `CoordinateSystem.CoordinateSystemID == 0`, `Force.CoordinateSystem`, result `CoordinateSystem` / reaction `Orientation` | v261 stubs | package-inspected; live batch tested (2026 R1) |
| template ownership | object `Parent`, `ObjectId`, `Children`, `Suppressed` | v261 stubs and native `ANSYSAnalysisSettings` inventory | package-inspected; live batch tested (2026 R1) |
| result scope | `Location` drives Geometry/Component scoping; `NormalOrientation`, `LocationMethod`, `BoundaryConditionSelection` | v261 stubs | package-inspected; live batch tested (2026 R1) |
| material inventory | `Body.GetEngineeringDataMaterial()`, `materials.GetListMaterialProperties(...)` | Ansys employee example and v261 body stubs | documented/package-inspected; live batch tested (2026 R1) |
| image export | `GraphicsImageExportSettings()` and `ExtAPI.Graphics.ExportImage(path, PNG, settings)` | PyMechanical embedding helper/v261 stubs | package source and stubs inspected; live batch tested (2026 R1); failure becomes `NOT_RUN` |
| product/messages | `Project.ProductVersion`, `Application.Messages`, `Severity`, `DisplayString`, `Source` | installed v261 API | live batch tested; message sources identify empty localized errors |

Sources:

- https://developer.synopsys.com/blog/pymechanical-cheat-sheet
- https://scripting.mechanical.docs.pyansys.com/version/stable/api/ansys/mechanical/stubs/v261/Ansys/ACT/Automation/Mechanical/Project.html
- https://discuss.ansys.com/discussion/35/can-you-provide-an-example-of-using-the-materials-module-in-mechanical
- https://scripting.mechanical.docs.pyansys.com/version/stable/api/ansys/mechanical/stubs/v261/index.html
- https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/act_script/act_script_examples_create_mat_assign.html
- https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/act_script/act_script_demo_coupled_field_001.html

v0.1 enables only `.step` and `.stp`. The committed STEP fixture was imported successfully on the
tested v261 installation. Its exact imported tree/body name is `CantileverBeam|Solid`, while the
STEP product is named `CantileverBeam`. Other CAD interfaces and import naming rules are not implied
by this acceptance. Preserve exact-name failures instead of renaming or guessing a body.

## Geometry entity selection

The strict selector uses:

- `ExtAPI.DataModel.GeoData.Assemblies -> Parts -> Bodies -> Faces`
- `IGeoFace.Centroid`, `IGeoFace.Area`, `ParamAtPoint(point)`, and `NormalAtParam(u, v)`
- `ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)`
- `selection.Entities = [face]`
- `ExtAPI.DataModel.GeoData.Unit` and `units.ConvertUnit(...)` to convert the canonical selector
  tolerance into the geometry database length unit before centroid comparison

Official sources:

- https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/act_ref/act_ref_api_geometry_igeoface.html
- https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/act_script/act_script_examples_crea_geo_sel.html
- https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/act_script/act_script_examples_geo_data_and_sel.html
- https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/act_script/act_script_examples_distance_two_faces.html
- https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/act_script/act_script_examples_coordinate_system_math.html

This path is **live batch tested** for the committed single-solid beam. The report records
centroids with their geometry length unit, areas with the derived area unit, and both canonical and
geometry-unit selector tolerances. Runtime failures are explicit unsupported errors; no topology-order
or raw-ID fallback is allowed.

## PyDPF

Package-verified constructors:

```text
ansys.dpf.core.Model(data_sources=None, server=None)
ansys.dpf.core.DataSources(result_path=None, data_sources=None, server=None, key='')
```

Documented runtime path:

- `model = dpf.Model(rst_path)`
- `model.metadata.meshed_region` and node/element collections
- `model.results.displacement.on_last_time_freq.eval()`
- result field `data`, `unit`, `location`, and `scoping.ids`
- stored result providers including `displacement`, `stress`, and `reaction_force`
- `dpf.operators.result.stress_eqv_as_mechanical(...)` for derived equivalent stress

Sources:

- https://dpf.docs.pyansys.com/version/stable/api/ansys/dpf/core/model/Model.html
- https://dpf.docs.pyansys.com/version/stable/user_guide/result_types.html
- https://dpf.docs.pyansys.com/version/stable/user_guide/read_data.html

Current live evidence uses PyDPF 0.16.1 and the installed v261 DPF Server 11.0. The normal Mechanical
RST exposes the stored `stress` tensor, not a `model.results.stress_eqv_von_mises` provider. The
compiler's postprocessor now calls `stress_eqv_as_mechanical` with the last result-set ID, explicit
`Nodal` output, and an optional resolved named-selection scoping. Its 38.0902173163 MPa beam maximum
agrees with Mechanical's exported equivalent-stress plot. Field rows and node IDs are one-to-one.

Displacement, directional displacement, equivalent stress, and reaction extraction are live tested.
Reaction extraction requires `reaction_force`; `nodal_force` is never substituted. Named selections
are resolved uniquely against the actual RST inventory. Raw-RST inspection and report regeneration
are also tested without the original specification. Pressure/gravity resultant checks remain
`NOT_RUN` in the general validator; their acceptance tests independently compare `p A` and `rho V g`.

The workflow uses the official client-managed local server selected by `dpf.Model`, with no separate
remote DPF configuration. Remote DPF authentication and transport are outside this live evidence.

## Codex Skill/plugin contract

The repository uses one plugin root (`.codex-plugin/plugin.json`) and one Skill source under `skills/`.
`SKILL.md` contains discriminating frontmatter and progressive references; `agents/openai.yaml` contains
quoted interface strings and a default prompt that names `$ansys-mechanical-static`.

Sources:

- https://developers.openai.com/codex/skills
- https://developers.openai.com/codex/plugins
