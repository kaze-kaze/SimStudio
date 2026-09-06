# Saved real cantilever demonstration

Open `index.html` directly in a browser after downloading or extracting the source.
Direct file mode is the verified viewing path; no local server is needed.
No npm installation, CDN, server API, ANSYS installation, or license is needed to view it.

The viewer displays the recorded 2026-09-06 real `mechanical_batch` cantilever result.
The three tabs switch unmodified Mechanical exports. Numbers come from `evidence.js`, generated
from the [public evidence](../../../docs/reports/evidence/2026-09-06/summary.json). The viewer does
not run a solver or produce new simulation values.

The base example remains a default dry-run workflow. See the
[Windows guide](../../../docs/windows-testing.md) for explicit batch reproduction.
gRPC, mesh convergence, and safety-factor acceptance remain outside this recorded case.

## Sources and regeneration

`index.html`, `style.css`, and `demo.js` are viewer source. `evidence.js` and `assets/*.png` are
generated artifacts. Maintainers regenerate them from the saved archive with
`python tools/export_benchmark_evidence.py --archive <local-archive>`.
Readers can verify the committed snapshot without an archive or solver:

```bash
python tools/export_benchmark_evidence.py
```

The provenance file records source hashes, the field-allowlist transformation, and public-file
hashes. Raw Mechanical projects, RST files, licensing diagnostics, and desktop screenshots are
retained locally. See [NOTICE](../../../NOTICE).

Images used courtesy of ANSYS, Inc.
