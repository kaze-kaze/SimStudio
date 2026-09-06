# Mechanical execution

## Default boundary

`ansys-sim run` is a dry-run. Only `--execute` may start or contact Mechanical. Execution is blocked by
schema errors, missing files, open questions, unsupported custom material authoring, unsafe remote
configuration, an unavailable environment, or a non-empty output directory. A run never reuses a
directory containing prior solver artifacts. Compilation also requires a new or empty directory.
Each compile saves an input snapshot under `inputs/` and a relative reference in the normalized YAML;
execution consumes that snapshot rather than rereading a potentially changed original input.

## Session model

### Explicit local Windows batch

`execution.backend: mechanical_batch` invokes the discovered `AnsysWBU.exe` with
`-DSApplet -AppModeMech -b -script <saved-script> -x`. The compiler's input snapshot and fixed
runtime are used with the isolated run directory as the process working directory.
`mechanical-batch-stdout.log` and `mechanical-batch-stderr.log` retain native diagnostics.
The backend requires the structured `SOLVED` status and real RST files even when the process exits
with `0`; caught script failures can also return `0` from Mechanical.

This backend is local Windows only. It starts and exits its own process, rejects settings requesting
a remote or existing instance, and uses no gRPC transport. A timeout terminates only the process tree
created by that run. There is no automatic switch from a failed gRPC call to batch execution.
Standalone `doctor` describes the default gRPC setup; `run` also records a doctor report for the
backend selected in the specification.

The 2026-09-06 Student 2026 R1 installation passed local batch numerical acceptance, while local
gRPC failed at HTTP/2 handshake. Read the
[test report](../../../docs/reports/mechanical-test-2026-09-06.md) before claiming a tested path.

### PyMechanical gRPC

This backend uses official PyMechanical remote-session APIs. It executes saved files with
`run_python_script_from_file`; it does not send the full Mechanical program as an untracked string. A
small saved bootstrap script sets the run working directory.

The backend either:

- starts a local batch instance when `start_instance: yes`, or `auto` with localhost and no port; or
- connects to the exact configured host/port when `start_instance: no`, or a port/remote host implies
  an existing service.

For a non-local service, a saved preparation script creates a unique server-side temporary directory.
The input snapshot is uploaded with `file_location_destination` into that directory, all scripts start there, and
a saved cleanup script removes it after artifact download. A timed-out request on a user-owned server
or a failed artifact transfer preserves the directory for recovery. Deleting it while the solver may
still be active or before required results have been retrieved would be unsafe.

One process-level lock prevents concurrent analyses through the same backend. A solver-call timeout is enforced. If
the current run created the instance, a timeout force-stops that owned instance and cancels pending
client work. For a connected pre-existing instance, cancellation is best effort because the workflow
must not terminate a user-owned server; the instance itself is never closed. The client wait uses a
daemon worker so an unresponsive RPC does not keep the CLI process alive after a timeout. A timeout
does not prove that a user-owned server has stopped solving.

## Host and transport

Localhost is the default. Any other host requires `allow_remote: true` and authenticated transport.
Never enable remote access as a convenience assumption. Always specify the same transport on the
client and Mechanical server; v0.1 deliberately has no ambiguous transport default.

- `insecure`: explicit unencrypted gRPC; permitted only for localhost by this Skill.
- `wnua`: Windows Negotiate User Authentication; Windows only.
- `mtls`: mutual TLS; requires an existing `certs_dir`.

The official compatibility table currently lists all Mechanical 2026 R1 service packs, 2025 R2
SP03+, 2025 R1 SP04+, and 2024 R2 SP05+ for modern transports, with mode-specific limits. Older
versions retain legacy gRPC behavior but are not claimed by this Skill. Read `official-api-map.md`
before changing transport handling.

## Artifacts

The Mechanical script writes `mechanical-artifacts.json` and `face-selection-report.json`, searches for
real `.rst` and `solve.out` files, records Mechanical messages, saves the project when configured, and
attempts result-image exports. Result files come from the selected analysis's documented result path
and solver directory, not from a recursive search of the Python working directory. Collected RST/log
copies are stored under `solver/`; inspection prefers the recorded result over duplicate project copies.
The backend downloads known remote artifacts into the isolated run directory. A structured result
return is never sufficient evidence of an engineering-successful solve.

Saved template results are cleared in the isolated input snapshot before changing their locations.
Assigning `Location` updates Geometry/Component scoping; setting `ScopingMethod` directly can be
read-only on saved v261 results. The original template remains unchanged. Mechanical messages retain
severity, text, and source object details, including errors whose localized display text is empty.
