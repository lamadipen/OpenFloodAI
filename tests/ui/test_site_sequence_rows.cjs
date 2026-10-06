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
  water_level_groups: { "b.jpg": "high", "a.jpg": "low", "c.jpg": "middle" },
  water_level_samples: {
    "b.jpg": { group: "high", level: 12.5, unit: "ft", quality_status: "provisional" },
    "a.jpg": { group: "low", level: 3.1, unit: "ft", quality_status: "approved" },
    "c.jpg": { group: "middle", level: 7.25, unit: "ft", quality_status: "approved" }
  },
  records: [
    { filename: "b.jpg", captured_at_utc: "2025-06-02T12:05:00+00:00", download_status: "downloaded" },
    { filename: "a.jpg", captured_at_utc: "2025-03-01T12:05:00+00:00", download_status: "downloaded" },
    { filename: "c.jpg", captured_at_utc: "2025-09-09T12:05:00+00:00", download_status: "downloaded" },
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

test("baseline options show the gauge level and are ordered lowest level first", () => {
  const out = context().baselineOptionsHtml(waterSet);
  const values = [...out.matchAll(/value="([^"]+)"/g)].map((m) => m[1]).filter(Boolean);
  assert.deepEqual(values, ["a.jpg", "c.jpg", "b.jpg"]); // 3.10, 7.25, 12.50 ft
  assert.match(out, /3\.10 ft &middot; Low water sample &middot; 2025-03-01 12:05 UTC/);
  assert.match(out, /7\.25 ft &middot; Middle water sample/);
  assert.match(out, /12\.50 ft \(provisional\) &middot; High water sample/);
  assert.doesNotMatch(out, /value=""[^>]*>[^<]*missing/);
});

test("images without a recorded level are listed last and say so", () => {
  const seq = { ...waterSet, water_level_samples: { "a.jpg": { group: "low", level: 3.1, unit: "ft" } } };
  const out = context().baselineOptionsHtml(seq);
  const values = [...out.matchAll(/value="([^"]+)"/g)].map((m) => m[1]).filter(Boolean);
  assert.equal(values[0], "a.jpg");
  assert.equal(values.length, 3);
  assert.match(out, /level not recorded/);
});

test("a fingerprinted water-level sequence name is recognised too", () => {
  const out = context().sequenceRowHtml({ sequence_id: "usgs-CAM-2026-01-01-2026-10-04-water_level-0a1b2c3d", downloaded_count: 9, records: [] });
  assert.match(out, /data-baseline-for=/);
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
