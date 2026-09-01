# Official API map

Research date: **2026-09-01**. Sources are official OpenAI, PyAnsys, ANSYS Developer/Help, and package
distribution metadata. "Package-verified" means the Python package imported and its signature was
inspected locally. "Integration-tested" requires a real compatible Mechanical/DPF server and license.

## Packages and versions

| Package | v0.1 range | Local evidence | Official source |
|---|---|---|---|
| `ansys-mechanical-core` | `>=0.13.2,<0.14` | 0.13.2 installed in a temporary CPython 3.14.6 environment; signatures below inspected | https://mechanical.docs.pyansys.com/version/stable/ and https://pypi.org/project/ansys-mechanical-core/ |
| `ansys-dpf-core` | `>=0.16.1,<0.17` | 0.16.1 imported in the same environment; no local DPF server/RST was available | https://dpf.docs.pyansys.com/version/stable/ and https://pypi.org/project/ansys-dpf-core/ |
| `ansys-mechanical-stubs` | transitive | 0.1.13, including v242/v251/v252/v261 stubs, inspected | https://scripting.mechanical.docs.pyansys.com/version/stable/ |

PyMechanical's official installation page lists Python 3.10–3.14 and client-package support on
Windows, Linux, and macOS. The Mechanical product is supported only on Windows/Linux. PyDPF's
published compatibility table currently lists Python 3.10–3.13. Although the 0.16.1 client imported
during package inspection on local Python 3.14, that is not an official compatibility claim. The
published project therefore requires Python 3.11–3.13, while keeping the base installation independent
of both optional packages.

Sources:

- https://mechanical.docs.pyansys.com/version/stable/getting_started/index.html
- https://dpf.docs.pyansys.com/version/stable/getting_started/index.html

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

The backend uses remote-session gRPC only. Embedded mode is not a real-execution backend in v0.1, but
the saved script runs inside Mechanical and therefore uses the embedded `App`, `Model`, `DataModel`,
`ExtAPI`, and `Quantity` globals.

## Transport and security

Official PyMechanical documentation defines `insecure`, `wnua`, and `mtls`, and requires the client
and server to use the same explicit mode. Its current table lists all Mechanical 2026 R1 service
packs; Mechanical 2025 R2 SP03+ for `insecure`, WNUA, and mTLS; Mechanical 2025 R1 SP04+ and 2024 R2
SP05+ for `insecure` and WNUA only. Earlier product versions retain legacy gRPC behavior but do not
support the `transport_mode` argument. `wnua` is Windows-only. mTLS uses `certs_dir` and the documented
certificate layout.

Source: https://mechanical.docs.pyansys.com/version/stable/user_guide/remote_session/overview.html

Implementation status: localhost defaults to explicit `insecure`; non-local hosts require explicit
`allow_remote: true` plus WNUA or mTLS. Doctor rejects WNUA on non-Windows clients and missing mTLS
certificate directories. Argument signatures are package-verified. No local Mechanical server
existed, so authentication, upload/download, timeout cancellation, and ownership cleanup are **not
integration-tested** in the current environment.

## Mechanical scripting object model

The compiler/runtime uses these documented entry points:

| Purpose | Entry point | Evidence | Current verification |
|---|---|---|---|
| open template | `App.open(path)` | PyMechanical static-structural example opens `.mechdat` | documented/example; not live tested |
| new project | `App.new()` | official remote examples | documented/example; not live tested |
| import geometry | `Model.AddGeometryImportGroup().AddGeometryImport()` and `GeometryImport.Import(path, Format.Automatic, GeometryImportPreferences())` | official example/stubs | package stubs inspected; not live tested |
| add analysis | `Model.AddStaticStructuralAnalysis()` | official example/stubs | package stubs inspected; not live tested |
| verify analysis | `Analysis.AnalysisType`, `Analysis.PhysicsType`, `Analysis.AnalysisSettings.LargeDeflection = False` | v261 scripting stubs | package stubs inspected; not live tested |
| exact names | `DataModel.GetObjectsByName(name)` | scripting object model | generated runtime requires exactly one; not live tested |
| object types | `.GetType().Name` centralized in `MechanicalCompat` | .NET object model used by Mechanical scripting | generated runtime enforces exact template type names; not live tested |
| exact bodies | `DataModel.GetObjectsByType(DataModelObjectCategory.Body)` | scripting object model/stubs | stubs inspected; not live tested |
| material assignment | `body.Material = exact_engineering_data_name` | official material assignment example | documented/example; not live tested |
| fixed support | `analysis.AddFixedSupport()` | official example/stubs | documented/example; not live tested |
| force | `analysis.AddForce()`, `LoadDefineBy.Components`, component `DiscreteValues` | official example/stubs | documented/example; not live tested |
| pressure | `analysis.AddPressure()`, `Magnitude.Output.DiscreteValues` | scripting stubs | package stubs inspected; not live tested |
| gravity | `analysis.AddEarthGravity()`, X/Y/Z component fields | scripting stubs | package stubs inspected; not live tested |
| mesh | `Model.Mesh.ElementSize`, `Model.Mesh.ElementOrder`, `Model.Mesh.GenerateMesh()` | official 2026 R1 end-to-end example/stubs | documented/example; not live tested |
| results | `Solution.AddTotalDeformation()`, `AddDirectionalDeformation()`, `AddEquivalentStress()`, `AddForceReaction()` | scripting stubs | package stubs inspected; not live tested |
| solve | `analysis.Solve(True)` | official example/stubs | documented/example; not live tested |
| save | `ExtAPI.DataModel.Project.SaveAs(path)` | official example | documented/example; not live tested |
| image export | `GraphicsImageExportSettings()` and `ExtAPI.Graphics.ExportImage(path, PNG, settings)` | PyMechanical embedding helper/v261 stubs | package source and stubs inspected; not live tested; failure becomes `NOT_RUN` |

Sources:

- https://examples.mechanical.docs.pyansys.com/examples/01_tips_n_tricks/example_01_simple_structural_remote.html
- https://scripting.mechanical.docs.pyansys.com/version/stable/api/ansys/mechanical/stubs/v261/index.html
- https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/act_script/act_script_examples_create_mat_assign.html
- https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/act_script/act_script_demo_coupled_field_001.html

v0.1 enables only `.step` and `.stp`. The v261 stubs confirm the import call shape but not the
availability of every product-specific CAD interface. STEP import remains **not integration-tested**
on the current machine, so importer/license failure must be preserved rather than generalized to other
formats.

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

This path is documented but **not integration-tested** in the current environment. The report records
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
- available result names including `stress_eqv_von_mises` when present in the result file

Sources:

- https://dpf.docs.pyansys.com/version/stable/api/ansys/dpf/core/model/Model.html
- https://dpf.docs.pyansys.com/version/stable/user_guide/result_types.html
- https://dpf.docs.pyansys.com/version/stable/user_guide/read_data.html

Current environment: client import/signature inspection succeeded in a temporary environment. No DPF
server or redistributable Mechanical RST was available, so displacement/stress/reaction extraction,
field locations, units, reaction-force naming, and image export are **not integration-tested**. The
`reaction_force` to `nodal_force` fallback is isolated and must be confirmed against real v251/v252/v261
result files before claiming broad compatibility.

PyDPF Core 0.15.0 and later use mTLS by default for local DPF server communication. v0.1 relies on the
official client-managed local server created by `dpf.Model`; it does not expose a separate remote DPF
server configuration. This path is package-inspected but not server-tested here.

## Codex Skill/plugin contract

The repository uses one plugin root (`.codex-plugin/plugin.json`) and one Skill source under `skills/`.
`SKILL.md` contains discriminating frontmatter and progressive references; `agents/openai.yaml` contains
quoted interface strings and a default prompt that names `$ansys-mechanical-static`.

Sources:

- https://developers.openai.com/codex/skills
- https://developers.openai.com/codex/plugins
