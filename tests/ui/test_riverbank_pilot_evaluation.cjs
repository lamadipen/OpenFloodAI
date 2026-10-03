const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(
  path.join(__dirname, "../../tools/console/review.html"),
  "utf8"
);
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const start = script.indexOf("function pilotMetricPercent");
const end = script.indexOf("function gaugeKey");
const helpers = script.slice(start, end);

function context() {
  const sandbox = { escapeHtml: (value) => String(value), Object };
  vm.createContext(sandbox);
  vm.runInContext(helpers, sandbox);
  return sandbox;
}

test("pilot evaluation card shows metrics, conditions, cost, and safety wording", () => {
  const output = context().pilotEvaluationHtml({
    reviewed_count: 8,
    unavailable_or_failure_rate: 0.125,
    overlay_acceptance_rate: 0.75,
    metrics: { precision: 0.8, recall: 0.6, false_positive: 2 },
    processing_cost: {
      mean_processing_time_ms: 3.25,
      p95_processing_time_ms: 5.5,
      max_estimated_frame_memory_bytes: 1048576,
    },
    false_crossing_causes: { camera_movement: 2 },
    condition_metrics: [{
      condition: "muddy_water",
      reviewed_count: 3,
      available_count: 2,
      metrics: { precision: 0.5, recall: 1, false_positive: 1 },
    }],
  });

  assert.match(output, /8 reviewed/);
  assert.match(output, /80\.0%/);
  assert.match(output, /60\.0%/);
  assert.match(output, /12\.5%/);
  assert.match(output, /3\.250 ms/);
  assert.match(output, /1\.000 MiB/);
  assert.match(output, /muddy water/);
  assert.match(output, /camera movement \(2\)/);
  assert.match(output, /does not confirm flooding, prove safety, or create a public warning/);
});

test("pilot evaluation card explains when a run has no saved result", () => {
  const output = context().pilotEvaluationHtml(null);

  assert.match(output, /No pilot evaluation is saved for this run yet/);
  assert.match(output, /riverbank-pilot-evaluation\.json/);
});
