const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(
  path.join(__dirname, "../../tools/openfloodai-site-details.html"), "utf8"
);
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function grab(name) {
  const match = script.match(
    new RegExp(`      (?:async )?function ${name}\\([\\s\\S]*?\\n      \\}`)
  );
  assert.ok(match, `${name} not found`);
  return match[0];
}

function run(source, extra) {
  const context = vm.createContext({ ...extra });
  vm.runInContext(source, context);
  return context;
}

test("escapeHtml escapes every reserved HTML character", () => {
  const context = run(grab("escapeHtml"));
  assert.equal(
    context.escapeHtml(`<script>&"'</script>`),
    "&lt;script&gt;&amp;&quot;&#039;&lt;/script&gt;"
  );
});

test("formatDateTime renders a readable date and falls back for missing or invalid values", () => {
  const context = run(grab("formatDateTime"));
  assert.equal(context.formatDateTime(null), "Unknown time");
  assert.equal(context.formatDateTime(""), "Unknown time");
  assert.equal(context.formatDateTime("not-a-date"), "not-a-date");
  assert.match(context.formatDateTime("2026-01-15T12:00:00Z"), /2026/);
});

test("fallback substitutes a readable placeholder only for missing values, not zero or false", () => {
  const context = run(grab("fallback"));
  assert.equal(context.fallback(undefined), "Not available");
  assert.equal(context.fallback(null), "Not available");
  assert.equal(context.fallback(""), "Not available");
  assert.equal(context.fallback(0), 0);
  assert.equal(context.fallback(false), false);
  assert.equal(context.fallback("x", "custom"), "x");
  assert.equal(context.fallback(undefined, "custom"), "custom");
});

test("runDirFromReportPath strips the report filename to get the run folder", () => {
  const context = run(grab("runDirFromReportPath"));
  assert.equal(
    context.runDirFromReportPath("/sites/demo/outputs/runs/20260101T000000Z-aaaa/validation-report.md"),
    "/sites/demo/outputs/runs/20260101T000000Z-aaaa"
  );
  assert.equal(context.runDirFromReportPath(null), null);
  assert.equal(context.runDirFromReportPath(""), null);
});

test("loadRunBody never fetches run detail for a legacy run, even one whose path parses like a run dir", async () => {
  const fetchCalls = [];
  const context = run(
    [grab("escapeHtml"), grab("runDirFromReportPath"), grab("loadRunBody")].join("\n"),
    { fetchRunDetail: async (runDir) => fetchCalls.push(runDir), renderRunBody: () => {} }
  );
  const body = { innerHTML: "" };
  const card = { querySelector: () => body };
  await context.loadRunBody(card, {}, {
    path: "/sites/demo/outputs/validation-report.md",
    legacy: true,
  });
  assert.deepEqual(fetchCalls, []);
  assert.match(body.innerHTML, /older run saved before detailed run folders existed/);
});

test("statusBadge renders a positive or negative badge depending on the ok flag", () => {
  const context = run(grab("escapeHtml") + "\n" + grab("statusBadge"));
  assert.match(context.statusBadge(true, "Machine ready", "Not ready"), /badge ok/);
  assert.match(context.statusBadge(true, "Machine ready", "Not ready"), /Machine ready/);
  assert.match(context.statusBadge(false, "Machine ready", "Not ready"), /badge missing/);
  assert.match(context.statusBadge(false, "Machine ready", "Not ready"), /Not ready/);
});

test("comparisonBadge maps known statuses and falls back for an unknown one", () => {
  const context = run(grab("escapeHtml") + "\n" + grab("comparisonBadge"));
  assert.match(context.comparisonBadge("agree"), /badge ok/);
  assert.match(context.comparisonBadge("disagree"), /badge missing/);
  assert.match(context.comparisonBadge("cannot_compare"), /badge warn/);
  assert.match(context.comparisonBadge("cannot_compare"), /Cannot compare/);
  assert.match(context.comparisonBadge("something_else"), /Status unavailable/);
});

test("round keeps two decimal places for numbers and passes other values through", () => {
  const context = run(grab("round"));
  assert.equal(context.round(16.317505), 16.32);
  assert.equal(context.round(21.925362), 21.93);
  assert.equal(context.round("not-a-number"), "not-a-number");
  assert.equal(context.round(undefined), undefined);
});

test("regionSvg draws the watched-area box and every non-invalid guide, dashed unless trusted", () => {
  const context = run(grab("regionSvg"));
  const region = { x: 10, y: 20, width: 30, height: 40 };
  const guides = [
    {
      status: "confirmed",
      normal_condition: true,
      points: [{ x: 1, y: 2 }, { x: 3, y: 4 }],
    },
    {
      status: "draft",
      normal_condition: true,
      points: [{ x: 5, y: 6 }, { x: 7, y: 8 }],
    },
    {
      status: "invalid",
      normal_condition: true,
      points: [{ x: 9, y: 9 }, { x: 10, y: 10 }],
    },
  ];
  const svg = context.regionSvg(region, guides);
  assert.match(svg, /<rect x="10" y="20" width="30" height="40"/);
  assert.match(svg, /stroke="#1d4ed8" stroke-width="1.6" stroke-dasharray="0"/);
  assert.match(svg, /stroke="#d97706" stroke-width="1.6" stroke-dasharray="3,2"/);
  assert.equal((svg.match(/<polyline/g) || []).length, 2, "the invalid guide must not be drawn");
});

test("regionSvg renders no watched-area box when there is none yet", () => {
  const context = run(grab("regionSvg"));
  const svg = context.regionSvg(null, []);
  assert.ok(!svg.includes('fill="rgba(23,105,170,0.08)"'));
});

test("regionSvg skips a guide with fewer than two points instead of drawing a broken line", () => {
  const context = run(grab("regionSvg"));
  const svg = context.regionSvg(null, [{ status: "confirmed", normal_condition: true, points: [] }]);
  assert.ok(!svg.includes("<polyline"));
});

test("buildCompareTable highlights only the metrics that differ between runs", () => {
  const context = run(
    [grab("escapeHtml"), grab("formatDateTime"), grab("fallback"), grab("buildCompareTable")].join("\n")
  );
  const details = [
    {
      run: { run_id: "run-a", modified_time: "2026-01-01T00:00:00Z", status: "completed" },
      detail: {
        scorecard: {
          videos_reviewed: 2,
          videos_with_human_label: 1,
          label_windows: 1,
          agree_count: 0,
          disagree_count: 0,
          cannot_compare_count: 1,
          baseline_ready_count: 0,
          practice_only_count: 1,
        },
      },
    },
    {
      run: { run_id: "run-b", modified_time: "2026-01-02T00:00:00Z", status: "completed" },
      detail: {
        scorecard: {
          videos_reviewed: 2,
          videos_with_human_label: 1,
          label_windows: 1,
          agree_count: 1,
          disagree_count: 0,
          cannot_compare_count: 0,
          baseline_ready_count: 0,
          practice_only_count: 1,
        },
      },
    },
  ];
  const html = context.buildCompareTable(details);
  assert.match(html, /Comparing 2 runs/);
  assert.match(html, /run-a/);
  assert.match(html, /run-b/);
  // "Created" always differs (different timestamps); "Videos tested" never does here.
  const createdRow = html.match(/<tr><td class="metric-label">Created<\/td>.*?<\/tr>/s)[0];
  assert.equal((createdRow.match(/class="differs"/g) || []).length, 2);
  const videosRow = html.match(/<tr><td class="metric-label">Videos tested<\/td>.*?<\/tr>/s)[0];
  assert.equal((videosRow.match(/class="differs"/g) || []).length, 0);
  // Agree/Cannot compare differ between the two runs (0 vs 1, 1 vs 0).
  const agreeRow = html.match(/<tr><td class="metric-label">Agree<\/td>.*?<\/tr>/s)[0];
  assert.equal((agreeRow.match(/class="differs"/g) || []).length, 2);
});

test("buildCompareTable falls back to 'Not available' when a run has no scorecard yet", () => {
  const context = run(
    [grab("escapeHtml"), grab("formatDateTime"), grab("fallback"), grab("buildCompareTable")].join("\n")
  );
  const details = [
    { run: { run_id: "run-a", modified_time: null, status: "failed" }, detail: {} },
    { run: { run_id: "run-b", modified_time: null, status: "failed" }, detail: {} },
  ];
  const html = context.buildCompareTable(details);
  assert.match(html, /Not available/);
});

test("the Run Validation button is disabled only when the site is not ready to run", () => {
  assert.ok(
    script.includes(
      '<button class="btn primary" id="runValidationButton" ${site.ready_for_validation ? "" : "disabled"}>'
    )
  );
});

test("quick actions that need canvas drawing link out to the dashboard instead of duplicating it", () => {
  // This page only ever links out to the dashboard's own drawing forms; it
  // must not duplicate canvas-based region drawing itself.
  assert.ok(!script.includes("createRegionSelector"));
  assert.ok(script.includes("action=add_video"));
  assert.ok(script.includes("action=set_watched_area"));
  assert.ok(script.includes("action=set_normal_waterline_guide"));
  assert.ok(script.includes("action=watch"));
});
