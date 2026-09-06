"use strict";

(() => {
  const evidence = window.SIMSTUDIO_BENCHMARK;
  const result = evidence?.cases?.find((item) => item.id === "cantilever");
  if (!result || result.synthetic !== false) {
    document.getElementById("view-caption").textContent = "未加载经过验证的真实数值，请查看公开证据文件。";
    return;
  }
  const checks = Object.fromEntries(result.checks.map((item) => [item.name, item]));
  const numeric = result.results;
  const format = (value, digits) => new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: true,
  }).format(value);
  document.getElementById("tip-value").textContent = format(numeric.tip_z.reported_maximum, 6) + " mm";
  document.getElementById("error-value").textContent = format(checks.cantilever_analytical.evidence.relative_error * 100, 4) + "%";
  document.getElementById("reaction-value").textContent = format(numeric.fixed_reaction.canonical_sum_vector[2], 6) + " N";
  document.getElementById("node-count").textContent = format(result.node_count, 0);
  document.getElementById("element-count").textContent = format(result.element_count, 0);
  const views = {
    mesh: {
      file: "mesh.png", alt: "悬臂梁原始网格图",
      caption: "全局网格尺寸 10 mm；" + result.node_count + " 个节点，" + result.element_count + " 个单元。单一网格不构成收敛验证。",
    },
    deformation: {
      file: "total-deformation.png", alt: "悬臂梁总变形原始云图，图内单位为 m",
      caption: "图内单位为 m；最大总变形 " + format(numeric.total_deformation.reported_maximum, 6) + " mm。点击图片查看原图。",
    },
    stress: {
      file: "equivalent-stress.png", alt: "悬臂梁等效应力原始云图，图内单位为 Pa",
      caption: "图内单位为 Pa；节点平均最大等效应力 " + format(numeric.equivalent_stress.reported_maximum, 6) + " MPa。应力奇异性复核仍为 WARN。",
    },
  };
  const buttons = [...document.querySelectorAll("[data-view]")];
  function show(name) {
    const view = views[name];
    const image = document.getElementById("result-image");
    image.src = "assets/" + view.file;
    image.alt = view.alt;
    document.getElementById("image-link").href = image.src;
    document.getElementById("view-caption").textContent = view.caption;
    buttons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.view === name)));
  }
  buttons.forEach((button) => button.addEventListener("click", () => show(button.dataset.view)));
  show("deformation");
})();
