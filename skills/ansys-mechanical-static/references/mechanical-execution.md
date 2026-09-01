# Mechanical execution

## Default boundary

`ansys-sim run` is a dry-run. Only `--execute` may start or contact Mechanical. Execution is blocked by
schema errors, missing files, open questions, unsupported custom material authoring, unsafe remote
configuration, an unavailable environment, or a non-empty output directory. A run never reuses a
directory containing prior solver artifacts.

## Session model

The real backend uses official PyMechanical remote-session APIs. It executes saved files with
`run_python_script_from_file`; it does not send the full Mechanical program as an untracked string. A
small saved bootstrap script sets the run working directory.

The backend either:

- starts a local batch instance when `start_instance: yes`, or `auto` with localhost and no port; or
- connects to the exact configured host/port when `start_instance: no`, or a port/remote host implies
  an existing service.

For a non-local service, a saved preparation script creates a unique server-side temporary directory.
The input is uploaded with `file_location_destination` into that directory, all scripts run there, and
a saved cleanup script removes it after artifact download. A timed-out request on a user-owned server
is the exception: the directory is preserved and reported because deleting it while the solver may
still be active would be unsafe.

One process-level lock prevents concurrent analyses through the same backend. A timeout is enforced. If
the current run created the instance, a timeout force-stops that owned instance and cancels pending
client work. For a connected pre-existing instance, cancellation is best effort because the workflow
must not terminate a user-owned server; the instance itself is never closed.

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
attempts result-image exports. The backend downloads known remote artifacts into the isolated run
directory. A result sentinel helps parse the API response but is never sufficient evidence of an
engineering-successful solve.
