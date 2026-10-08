const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = require("./review_source.cjs").reviewHtml();
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const start = script.indexOf("function evidenceRowsForDay");
const end = script.indexOf("function gaugeKey");
const helpers = script.slice(start, end);

function context() {
  const sandbox = {
    folderName: "demo-site",
    runId: "run-1",
    sequenceId: () => "sequence-1",
    escapeHtml: (value) => String(value),
    URLSearchParams,
  };
  vm.createContext(sandbox);
  vm.runInContext(helpers, sandbox);
  return sandbox;
}

test("available riverbank evidence renders the safety-conscious review overlay", () => {
  const sandbox = context();
  const day = { capturedAtUtc: "2026-09-01T01:00:00+00:00", filename: "current.jpg" };
  const evidence = [{
    plugin_id: "riverbank_crossing_v1",
    timestamp: day.capturedAtUtc,
    status: "available",
    value: 25,
    reason_codes: ["POSSIBLE_VISUAL_CHANGE_BEYOND_NORMAL_LINE", "CAMERA_ALIGNMENT_UNAVAILABLE"],
    quality: {
      samples: [{ point_x: 50, point_y: 50, crossed: true }],
      changed_bank_length_percentage: 20,
      maximum_crossing_pixels: 12,
    },
  }];

  const output = sandbox.riverbankReviewHtml(evidence, day);

  assert.match(output, /image-sequence-riverbank-overlay/);
  assert.match(output, /land side/);
  assert.match(output, /Human review is required/);
  assert.match(output, /not flood confirmation or a public warning/);
  assert.match(output, /not camera-aligned/);
});

test("unavailable or historical evidence without samples shows no overlay", () => {
  const sandbox = context();
  const day = { capturedAtUtc: "2026-09-01T01:00:00+00:00", filename: "current.jpg" };
  const unavailable = [{
    plugin_id: "riverbank_crossing_v1",
    timestamp: day.capturedAtUtc,
    status: "unavailable",
  }];
  const historical = [{
    plugin_id: "riverbank_crossing_v1",
    timestamp: day.capturedAtUtc,
    status: "available",
    quality: {},
  }];

  assert.equal(sandbox.riverbankReviewHtml(unavailable, day), "");
  assert.equal(sandbox.riverbankReviewHtml(historical, day), "");
});
