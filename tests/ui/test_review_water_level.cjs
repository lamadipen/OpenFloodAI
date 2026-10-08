const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = require("./review_source.cjs").reviewHtml();
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const helpers =
  script.slice(script.indexOf("function formatUtc"), script.indexOf("const GAUGE_STATUS_TEXT")) +
  script.slice(script.indexOf("// ---- water-level review"), script.indexOf("// ---- end overlay comparison"));

function context(detail) {
  const sandbox = { escapeHtml: (v) => String(v), Number, String, Date, Array };
  vm.createContext(sandbox);
  vm.runInContext(helpers + "\nvar detail;", sandbox);
  sandbox.detail = detail;
  return sandbox;
}

const selection = {
  policy_version: "water-level-sampling-v1",
  note: "Relative to one station and date range.",
  samples: {
    "a.jpg": {
      group: "high",
      motivating_reading: { value: 12.5, unit: "ft", datetime_utc: "2026-03-01T12:00:00+00:00", quality_status: "provisional" },
      image_reading: { value: 12.4, unit: "ft" },
      image_reading_gap_seconds: -60,
      readings_differ: true
    }
  }
};

test("the collection group badge explains the reading and is not a label", () => {
  const out = context({ water_level_selection: selection }).waterLevelInfoHtml({ filename: "a.jpg" });
  assert.match(out, /High water collection group/);
  assert.match(out, /relative to the sampled date range/);
  assert.match(out, /12\.50 ft/);
  assert.match(out, /Provisional, may be revised/);
  assert.match(out, /own nearest reading is 12\.40 ft/);
  assert.match(out, /not a flood finding, a machine observation, or a human label/);
});

test("images outside the selection, and regular runs, show no group badge", () => {
  assert.equal(context({ water_level_selection: selection }).waterLevelInfoHtml({ filename: "baseline.jpg" }), "");
  assert.equal(context({ water_level_selection: null }).waterLevelInfoHtml({ filename: "a.jpg" }), "");
});

test("the overlay has an adjustable opacity, both images, and an alignment caution", () => {
  const ctx = context({ setup_used: { reference_region: { x: 10, y: 20, width: 30, height: 40 }, normal_waterline_guides: [{ id: "g", status: "confirmed", points: [{ x: 1, y: 2 }, { x: 3, y: 4 }] }] } });
  const out = ctx.onionHtml("folder_name=s&filename=base.jpg", "folder_name=s&filename=sel.jpg");
  assert.match(out, /type="range"/);
  assert.match(out, /filename=base\.jpg/);
  assert.match(out, /filename=sel\.jpg/);
  assert.match(out, /assumes the camera did not move/);
  assert.match(out, /not a measured water height/);
  assert.match(out, /<rect x="10" y="20" width="30" height="40"/);
  assert.match(out, /<polyline points="1,2 3,4"/);
});

test("invalid guides are not drawn, and the overlay needs both images", () => {
  const ctx = context({ setup_used: { reference_region: null, normal_waterline_guides: [{ status: "invalid", points: [{ x: 1, y: 2 }, { x: 3, y: 4 }] }] } });
  assert.doesNotMatch(ctx.onionHtml("a", "b"), /<polyline/);
  assert.match(ctx.onionHtml(null, "b"), /needs a baseline/);
  assert.match(ctx.onionHtml("a", null), /needs a baseline/);
});
