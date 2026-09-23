"""Offline presentation assets for deterministic study reports."""

REPORT_CSS = r"""
:root {
  color-scheme: light;
  --paper: #f5f6f4;
  --surface: #fff;
  --ink: #17212b;
  --muted: #65717d;
  --line: #d7dde1;
  --blue: #245f98;
  --blue-soft: #eaf2f8;
  --warn: #8a5b16;
  --fail: #963e3e;
  --pass: #315f4b;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}
* { box-sizing: border-box; }
html { background: var(--paper); color: var(--ink); scroll-behavior: smooth; }
body { margin: 0; min-width: 320px; line-height: 1.5; }
a { color: var(--blue); text-decoration-thickness: 1px; text-underline-offset: 3px; }
a:hover { text-decoration-thickness: 2px; }
button, select, input { font: inherit; color: inherit; }
button:focus-visible, select:focus-visible, input:focus-visible, a:focus-visible,
summary:focus-visible { outline: 2px solid var(--blue); outline-offset: 3px; }
.page { width: min(1200px, 100% - 48px); margin: 0 auto; }
.masthead { padding: 34px 0 26px; border-bottom: 1px solid var(--line); }
.eyebrow { margin: 0 0 8px; color: var(--muted); font-size: .76rem;
  font-weight: 700; letter-spacing: .11em; text-transform: uppercase; }
.title-row { display: flex; align-items: baseline; flex-wrap: wrap; gap: 10px 18px; }
h1 { margin: 0; font-size: clamp(1.65rem, 4vw, 2.55rem); line-height: 1.12;
  font-weight: 650; letter-spacing: -.04em; overflow-wrap: anywhere; }
.status { display: inline-flex; align-items: center; min-height: 25px; padding: 2px 9px;
  border: 1px solid currentColor; border-radius: 2px; color: var(--blue);
  font-size: .74rem; font-weight: 750; letter-spacing: .07em; }
.status[data-state=warn], .status[data-state=partial], .status[data-state=not-run] { color: var(--warn); }
.status[data-state=fail], .status[data-state=failed] { color: var(--fail); }
.status[data-state=pass], .status[data-state=solved], .status[data-state=reported] { color: var(--pass); }
.description { max-width: 78ch; margin: 12px 0 0; color: #394652; }
.identity { display: flex; flex-wrap: wrap; gap: 4px 20px; margin-top: 14px;
  color: var(--muted); font-size: .82rem; }
.identity code { color: var(--ink); font-size: .8rem; overflow-wrap: anywhere; }
main { padding-bottom: 44px; }
section { padding: 28px 0 30px; border-bottom: 1px solid var(--line); }
.section-head { display: flex; align-items: baseline; justify-content: space-between;
  gap: 14px; margin-bottom: 16px; }
h2 { margin: 0; font-size: 1.2rem; font-weight: 650; letter-spacing: -.02em; }
h3 { margin: 24px 0 10px; font-size: .98rem; font-weight: 650; }
.section-note, .muted { color: var(--muted); font-size: .84rem; }
.metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 20px 0 4px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.metric { padding: 14px 18px 15px 0; }
.metric + .metric { padding-left: 18px; border-left: 1px solid var(--line); }
.metric-value { display: block; font-size: clamp(1.5rem, 4vw, 2.1rem);
  font-variant-numeric: tabular-nums; font-weight: 620; line-height: 1.1; }
.metric-label { display: block; margin-top: 5px; color: var(--muted); font-size: .8rem; }
.inline-state { font-weight: 700; }
.inline-state[data-state=pass], .inline-state[data-state=solved] { color: var(--pass); }
.inline-state[data-state=fail], .inline-state[data-state=failed] { color: var(--fail); }
.inline-state[data-state=warn], .inline-state[data-state=not-run], .inline-state[data-state=unknown] { color: var(--warn); }
.table-wrap { width: 100%; overflow-x: auto; overscroll-behavior-x: contain; }
table { width: 100%; min-width: max-content; border-collapse: collapse; font-size: .86rem;
  font-variant-numeric: tabular-nums; }
th, td { padding: 9px 12px; border-bottom: 1px solid var(--line); text-align: left;
  vertical-align: top; }
th { color: #45525e; font-size: .73rem; font-weight: 700; letter-spacing: .045em; }
td { overflow-wrap: anywhere; }
.sample-row td:nth-child(2), .sample-row td:nth-child(3),
.sample-row td:nth-child(4), .sample-row td:first-child { white-space: nowrap; }
th:first-child, td:first-child { padding-left: 0; }
th:last-child, td:last-child { padding-right: 0; }
th button { padding: 0; border: 0; background: transparent; color: inherit;
  cursor: pointer; font: inherit; letter-spacing: inherit; text-align: left; }
th button:hover { color: var(--blue); }
.controls { display: flex; flex-wrap: wrap; align-items: end; gap: 10px 14px; margin: 6px 0 12px; }
.control { display: grid; gap: 4px; color: var(--muted); font-size: .74rem; font-weight: 650; }
.control select, .control input { min-height: 36px; padding: 6px 9px; border: 1px solid #b8c1c8;
  border-radius: 2px; background: var(--surface); }
.control input { width: min(270px, 70vw); }
.filter-count { margin-left: auto; color: var(--muted); font-size: .78rem; }
.sample-row:hover, .mesh-row:hover, .candidate-row:hover { background: #edf2f5; }
.sample-row, .mesh-row, .candidate-row { transition: background-color 110ms ease; }
.detail-row > td { padding-top: 0; background: #eef1f2; }
details { padding: 7px 0; }
summary { width: fit-content; color: var(--blue); cursor: pointer; font-size: .8rem; font-weight: 650; }
.evidence-list { display: flex; flex-wrap: wrap; gap: 5px 16px; margin: 9px 0 3px;
  padding: 0; list-style: none; font-size: .79rem; }
.evidence-list li { max-width: 100%; overflow-wrap: anywhere; }
.evidence-list code { font-size: .76rem; }
.subtable { margin: 8px 0 10px; }
.subtable th, .subtable td { padding-top: 6px; padding-bottom: 6px; }
.status-text { white-space: nowrap; }
.metric-value-cell { white-space: nowrap; }
.chart { width: min(100%, 620px); margin: 12px 0 22px; }
.chart svg { display: block; width: 100%; height: auto; background: var(--surface); }
.chart figcaption { margin-top: 6px; color: var(--muted); font-size: .8rem; }
.chart-empty { max-width: 75ch; padding: 10px 0; color: var(--muted); font-size: .84rem; }
.candidate-target { display: block; margin: 0 0 4px; }
.candidate-target:last-child { margin-bottom: 0; }
.evidence-group { margin: 0 0 20px; }
.evidence-group h3 { margin-top: 18px; }
.image-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 18px; margin-top: 12px; }
.image-evidence { margin: 0; min-width: 0; }
.image-evidence img { display: block; width: 100%; max-height: 310px; object-fit: contain;
  background: #e9edef; border: 1px solid var(--line); }
.image-evidence figcaption { margin-top: 6px; color: var(--muted); font-size: .78rem;
  overflow-wrap: anywhere; }
.image-evidence figcaption code { color: var(--ink); }
.callout { margin: 12px 0 0; padding-left: 12px; border-left: 2px solid var(--blue);
  color: #43515c; font-size: .84rem; }
footer { padding: 20px 0 28px; color: var(--muted); font-size: .76rem; }
@media (max-width: 680px) {
  .page { width: min(100% - 28px, 1200px); }
  .masthead { padding-top: 24px; }
  section { padding: 22px 0 24px; }
  .metrics { grid-template-columns: 1fr; }
  .metric, .metric + .metric { padding: 11px 0; border-left: 0; }
  .metric + .metric { border-top: 1px solid var(--line); }
  .section-head { align-items: start; flex-direction: column; gap: 4px; }
  .filter-count { width: 100%; margin-left: 0; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; }
}
@media print {
  :root { --paper: #fff; }
  body { background: #fff; color: #000; font-size: 10pt; }
  .page { width: 100%; }
  .masthead { padding-top: 0; }
  section { break-inside: avoid; padding: 16px 0; }
  .controls, .filter-count { display: none !important; }
  .table-wrap { overflow: visible; }
  table { min-width: 0; font-size: 8.5pt; }
  th, td { padding: 5px 7px; }
  .detail-row[hidden] { display: table-row !important; }
  details:not([open]) > :not(summary) { display: block !important; }
  a { color: #000; text-decoration: none; }
  .image-evidence img { max-height: 230px; }
}
"""

REPORT_JS = r"""
(() => {
  const table = document.querySelector('#sample-table');
  if (!table) return;
  const body = table.tBodies[0];
  const pairs = Array.from(body.querySelectorAll('tr.sample-row')).map((row) => ({
    row, detail: row.nextElementSibling,
  }));
  const split = document.querySelector('#filter-split');
  const status = document.querySelector('#filter-status');
  const query = document.querySelector('#filter-query');
  const count = document.querySelector('#filter-count');
  const update = () => {
    const needle = (query.value || '').trim().toLocaleLowerCase();
    let visible = 0;
    for (const pair of pairs) {
      const match = (split.value === 'all' || pair.row.dataset.split === split.value)
        && (status.value === 'all' || pair.row.dataset.status === status.value)
        && (!needle || (pair.row.dataset.search || '').toLocaleLowerCase().includes(needle));
      pair.row.hidden = !match;
      if (pair.detail) pair.detail.hidden = !match;
      if (match) visible += 1;
    }
  count.textContent = `${visible} / ${pairs.length} samples`;
  };
  [split, status, query].forEach((control) => control && control.addEventListener('input', update));
  [split, status].forEach((control) => control && control.addEventListener('change', update));
  table.querySelectorAll('button[data-sort]').forEach((button) => {
    button.addEventListener('click', () => {
      const key = button.dataset.sort;
      const direction = table.dataset.sortKey === key && table.dataset.sortDirection === 'asc' ? -1 : 1;
      table.dataset.sortKey = key;
      table.dataset.sortDirection = direction === 1 ? 'asc' : 'desc';
      pairs.sort((left, right) => {
        const a = left.row.dataset[key] || '';
        const b = right.row.dataset[key] || '';
        const an = Number(a);
        const bn = Number(b);
        const order = a !== '' && b !== '' && Number.isFinite(an) && Number.isFinite(bn)
          ? an - bn : a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
        return order * direction;
      });
      pairs.forEach(({ row, detail }) => { body.append(row); if (detail) body.append(detail); });
    });
  });
  update();
})();
"""
