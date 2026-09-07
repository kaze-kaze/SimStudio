"use strict";

(() => {
  const evidence = window.SIMSTUDIO_BENCHMARK;
  const caseLabels = {
    mixed_12mm: "P + G · 12 mm",
    mixed_8mm: "P + G · 8 mm",
    mixed_5mm: "P + G · 5 mm · 主视图",
    gravity_5mm: "仅自重 G · 5 mm",
    double_mechanical_5mm: "2P + G · 5 mm",
  };
  const caseIds = Object.keys(caseLabels);
  const cases = caseIds.map((id) => evidence?.cases?.find((item) => item.id === id));
  const result = cases.find((item) => item?.id === evidence?.primary_case);
  const setText = (id, text) => { document.getElementById(id).textContent = text; };
  const format = (value, digits = 6) => Number.isFinite(value)
    ? new Intl.NumberFormat("en-US", {
      minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: true,
    }).format(value)
    : "—";
  const percentage = (value, digits = 4) => Number.isFinite(value)
    ? format(value * 100, digits) + "%" : "—";
  const statusOf = (checks, name) => checks?.find((item) => item.name === name)?.status || "NOT_RUN";
  const statusClass = (status) => ({
    PASS: "status-pass", WARN: "status-warn", FAIL: "status-fail", NOT_RUN: "status-not-run",
  })[status] || "status-not-run";
  const aggregate = (statuses) => {
    for (const state of ["FAIL", "WARN", "NOT_RUN"]) {
      if (statuses.includes(state)) return state;
    }
    return statuses.length && statuses.every((state) => state === "PASS") ? "PASS" : "NOT_RUN";
  };
  const writeStatus = (id, status, prefix = "") => {
    const element = document.getElementById(id);
    element.textContent = prefix + status;
    element.className = statusClass(status);
  };

  if (evidence?.primary_case !== "mixed_5mm" || evidence.synthetic !== false || !result
      || cases.some((item) => !item || item.synthetic !== false || item.solver_status !== "SOLVED")) {
    const warning = document.getElementById("data-warning");
    warning.hidden = false;
    warning.textContent = "未加载完整的五次真实求解证据，数值验收保持 NOT_RUN。请查看完整报告与公开 JSON。";
    setText("case-rows", "");
    setText("convergence-rows", "");
    writeStatus("numeric-status", "NOT_RUN", "数值验收 ");
    return;
  }

  const numeric = result.results;
  const quantity = (item, unit, digits = 6) => item?.reported_unit === unit
    ? format(item.reported_maximum, digits) : "—";
  setText("deformation-value", quantity(numeric.total_deformation, "mm") + " mm");
  setText("stress-value", quantity(numeric.equivalent_stress, "MPa") + " MPa");
  setText("reaction-value", format(numeric.mounting_reaction.canonical_sum_vector[2], 6) + " N");
  setText("node-count", format(result.node_count, 0));
  setText("element-count", format(result.element_count, 0));
  setText("dimensions-value", evidence.fixture.dimensions_mm.map((value) => format(value, 0)).join(" × ") + " mm");
  setText("mass-value", format(evidence.fixture.mass_kg, 4));
  setText("force-value", "[" + evidence.fixture.force_N.map((value) => format(value, 0)).join(", ") + "] N");
  setText("case-count", format(evidence.suite.tests, 0));

  const views = {
    mesh: {
      file: "mesh.png", alt: "双肋设备托架 5 mm 组合工况二次网格原图",
      caption: "5 mm 组合工况；" + format(result.node_count, 0) + " 个节点，"
        + format(result.element_count, 0) + " 个单元。图像来自已保存工程，未重新求解。",
    },
    deformation: {
      file: "total-deformation.png", alt: "双肋设备托架 5 mm 组合工况总变形原始云图",
      caption: "5 mm 组合工况；最大总位移 " + quantity(numeric.total_deformation, "mm", 9)
        + " mm。原始图例保留，点击查看完整原图。",
    },
    stress: {
      file: "equivalent-stress.png", alt: "双肋设备托架 5 mm 组合工况等效应力原始云图",
      caption: "5 mm 组合工况；节点平均最大等效应力 " + quantity(numeric.equivalent_stress, "MPa")
        + " MPa。全局峰值仅报告，局部应力审查保持 WARN。",
    },
  };
  const buttons = [...document.querySelectorAll("[data-view]")];
  function show(name) {
    const view = views[name];
    const image = document.getElementById("result-image");
    image.src = "assets/" + view.file;
    image.alt = view.alt;
    document.getElementById("image-link").href = "assets/" + view.file;
    setText("view-caption", view.caption);
    buttons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.view === name)));
  }
  buttons.forEach((button) => button.addEventListener("click", () => show(button.dataset.view)));
  show("deformation");

  function addRow(body, values, primary = false) {
    const row = document.createElement("tr");
    if (primary) row.className = "primary-case";
    values.forEach((value, index) => {
      const cell = document.createElement(index === 0 ? "th" : "td");
      if (index === 0) cell.scope = "row";
      cell.textContent = value;
      row.appendChild(cell);
    });
    body.appendChild(row);
  }

  const caseRows = document.getElementById("case-rows");
  caseRows.replaceChildren();
  cases.forEach((item) => {
    addRow(caseRows, [
      caseLabels[item.id], format(item.mesh_mm, 0), format(item.node_count, 0), format(item.element_count, 0),
      quantity(item.results.total_deformation, "mm", 9), quantity(item.results.equivalent_stress, "MPa"),
      statusOf(item.engineering_checks, "force_balance") + " / " + statusOf(item.engineering_checks, "moment_balance"),
    ], item.id === evidence.primary_case);
  });

  const seriesLabels = {
    maximum_total_displacement_m: { label: "最大总位移 mm", factor: 1000 },
    pad_mean_uz_m: { label: "承载台平均 Z 位移 mm", factor: 1000 },
    pad_mean_von_mises_Pa: { label: "承载台平均等效应力 MPa", factor: 1e-6 },
    pad_p95_von_mises_Pa: { label: "承载台第 95 百分位应力 MPa", factor: 1e-6 },
  };
  const convergenceRows = document.getElementById("convergence-rows");
  convergenceRows.replaceChildren();
  Object.entries(seriesLabels).forEach(([key, display]) => {
    const series = evidence.convergence.series[key];
    addRow(convergenceRows, [
      display.label, ...series.values.map((value) => format(value * display.factor, 6)),
      ...series.relative_changes.map((value) => percentage(value)), percentage(series.relative_tolerance, 0),
    ]);
  });
  writeStatus("convergence-status", evidence.convergence.status);
  const linearity = evidence.linearity;
  writeStatus("linearity-status", linearity.status);
  setText("linearity-error", Number.isFinite(linearity.relative_l2_error) ? linearity.relative_l2_error.toExponential(4) : "—");
  setText("linearity-nodes", format(linearity.compared_nodes, 0) + " / " + format(linearity.failing_nodes, 0));

  const numericalStates = cases.flatMap((item) => [
    statusOf(item.engineering_checks, "force_balance"), statusOf(item.engineering_checks, "moment_balance"),
  ]);
  numericalStates.push(evidence.convergence.status, linearity.status);
  if (evidence.suite.failures || evidence.suite.errors) numericalStates.push("FAIL");
  if (evidence.suite.tests !== 5 || evidence.suite.skipped) numericalStates.push("NOT_RUN");
  writeStatus("numeric-status", aggregate(numericalStates), "数值验收 ");

  function renderChecks(id, checks) {
    const list = document.getElementById(id);
    list.replaceChildren();
    checks.forEach((check) => {
      const row = document.createElement("div");
      const label = document.createElement("dt");
      const value = document.createElement("dd");
      label.textContent = check.name;
      value.textContent = check.status;
      value.className = statusClass(check.status);
      row.appendChild(label);
      row.appendChild(value);
      list.appendChild(row);
    });
  }
  renderChecks("cli-checks", result.checks);
  renderChecks("engineering-checks", result.engineering_checks);
})();
