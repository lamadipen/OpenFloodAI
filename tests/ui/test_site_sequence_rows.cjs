const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../../tools/console/site.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const helpers = script.slice(script.indexOf("// ---- sequence rows"), script.indexOf("// ---- end sequence rows"));

function context() {
  const sandbox = { escapeHtml: (v) => String(v), String, Object };
  vm.createContext(sandbox);
  vm.runInContext(helpers, sandbox);
  return sandbox;
}

const waterSet = {
  sequence_id: "usgs-CAM-2025-01-01-2025-12-31-water_level",
  downloaded_count: 3,
  water_level_groups: { "b.jpg": "high", "a.jpg": "low" },
  records: [
    { filename: "b.jpg", captured_at_utc: "2025-06-02T12:05:00+00:00", download_status: "downloaded" },
    { filename: "a.jpg", captured_at_utc: "2025-03-01T12:05:00+00:00", download_status: "downloaded" },
    { filename: "", captured_at_utc: "2025-04-01T00:00:00+00:00", download_status: "missing" }
  ]
};

test("a water-level set needs a baseline choice before it can run", () => {
  const out = context().sequenceRowHtml(waterSet);
  assert.match(out, /data-baseline-for="usgs-CAM-2025-01-01-2025-12-31-water_level"/);
  assert.match(out, /Choose a baseline image/);
  assert.match(out, /data-run-sequence="[^"]*" disabled/);
  assert.match(out, /no assumed normal first image/);
});

test("baseline options are in time order, label the sample group, and skip missing images", () => {
  const out = context().baselineOptionsHtml(waterSet);
  const values = [...out.matchAll(/value="([^"]+)"/g)].map((m) => m[1]).filter(Boolean);
  assert.deepEqual(values, ["a.jpg", "b.jpg"]);
  assert.match(out, /2025-03-01 12:05 UTC &middot; Low water sample/);
  assert.match(out, /2025-06-02 12:05 UTC &middot; High water sample/);
});

test("a regular sequence is unchanged: no picker, button enabled", () => {
  const out = context().sequenceRowHtml({ sequence_id: "usgs-CAM-2026-08-01-2026-09-03-one_daylight_image_per_day", downloaded_count: 29 });
  assert.doesNotMatch(out, /data-baseline-for/);
  assert.doesNotMatch(out, /data-run-sequence="[^"]*" disabled/);
});

test("each sequence has its own error box, so a failure shows under the row that was clicked", () => {
  const ctx = context();
  const a = ctx.sequenceRowHtml(waterSet);
  const b = ctx.sequenceRowHtml({ sequence_id: "usgs-CAM-2026-08-01-2026-09-03-all" });
  assert.match(a, /data-run-error="usgs-CAM-2025-01-01-2025-12-31-water_level"/);
  assert.match(b, /data-run-error="usgs-CAM-2026-08-01-2026-09-03-all"/);
});
