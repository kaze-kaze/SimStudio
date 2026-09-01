# Template-mode example

This example shows the required exact-name contract without distributing an ANSYS project. Replace
`REPLACE-WITH-YOUR-TEMPLATE.mechdat` with a licensed local template and update every object/body/named
selection name to match that template exactly.

The committed file intentionally has an unresolved question and a missing placeholder input, so it is
safe to inspect but is not execution-ready. After replacement:

```bash
ansys-sim validate examples/template-mode/simulation.yaml --json
ansys-sim compile examples/template-mode/simulation.yaml \
  --out build/template-mode \
  --json
ansys-sim run examples/template-mode/simulation.yaml \
  --out build/template-mode-dry-run \
  --json
```

Only add `--execute` after `doctor` reports a real execution path and all exact names have been
reviewed.
