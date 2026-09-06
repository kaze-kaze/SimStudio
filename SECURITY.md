# Security policy

## Supported versions

Security fixes are applied to the latest released minor version.

## Reporting a vulnerability

Do not include credentials, license files, private Mechanical projects, proprietary geometry, or
result archives in a public issue. Contact the repository maintainers privately through the source
hosting platform's security advisory feature. Include a minimal reproduction that uses synthetic or
redistributable data.

## Security invariants

- Real execution is opt-in through `--execute`.
- Non-local Mechanical hosts require explicit `allow_remote: true` plus WNUA or mTLS; insecure gRPC
  is limited to localhost.
- mTLS requires an explicit certificate directory. Secrets are never copied into manifests.
- Specification values are parsed as data; the runtime does not execute user Python or use
  `eval`/`exec`.
- Output artifact paths are contained under the selected run directory.
- The backend closes only Mechanical instances it started.
- Fake backend output is permanently labeled synthetic.
