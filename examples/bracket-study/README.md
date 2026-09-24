# Gusseted-bracket study example

This folder contains the authored `study.yaml` and its matching `base-simulation.yaml`. The parameter family is a controlled, single-solid gusseted bracket. The loads, material density evidence, displacement/stress limits, and bounds are demonstration inputs, not a production design or approved engineering criteria. Review and replace them with traceable project requirements before using the study for engineering decisions.

The authored displacement response limit is 0.025 mm and the stress response limit is 10 MPa. They were selected with reference to a recorded baseline response of about 0.01935 mm and 9.04 MPa. The 10 MPa value is a manually authored response constraint, not a material allowable, yield value, or certification limit.

From the repository root, install the study dependencies and build the immutable plan:

```console
python -m pip install -e ".[dev,study]"
ansys-sim study validate examples/bracket-study/study.yaml --json
ansys-sim study plan examples/bracket-study/study.yaml --out build/bracket-study --json
ansys-sim study run build/bracket-study --limit 1 --json
ansys-sim study report build/bracket-study --json
```

`plan` creates the plan and manifest. The bounded `run` prepares the sample CAD and previews its mesh jobs without starting Mechanical. A complete dry-run requires no `--execute`, but still prepares CAD and previews every planned design point; it may take time. The study's `max_solver_calls: 400` is the shared ceiling for initial samples, adaptive additions, candidate re-solves, retries, and the equal-budget direct-search comparison. The current plan has 120 initial mesh solver calls; the ceiling does not mean all calls will be used. Real solver calls require an explicit `--execute` request and stay within `max_solver_calls` and `max_wall_seconds`. Use `--resume` only to continue a study with recorded attempts.

Do not validate or run `base-simulation.yaml` as an ordinary standalone input. It is a study template whose geometry path is supplied by per-sample preparation. For field meanings, review evidence, bundles, and Windows acceptance limits, see [design studies](../../docs/design-studies.md), [中文说明](../../docs/design-studies.zh-CN.md), and [Windows execution](../../docs/windows-study.md). No accuracy, mass-reduction, or runtime improvement has been established by this example alone.
