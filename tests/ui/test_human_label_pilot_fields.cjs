const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(
  path.join(__dirname, "../../tools/console/form-human-label.html"),
  "utf8"
);

test("human label form adds only the two required riverbank pilot questions", () => {
  assert.match(html, /Did visual change cross the normal guide\?/);
  assert.match(html, /Does the highlighted overlay match what you see\?/);
  assert.match(html, /crossing_review: state\.crossingReview/);
  assert.match(html, /overlay_review: state\.overlayReview/);
});

test("pilot section appears only when saved available riverbank evidence is linked", () => {
  assert.match(html, /point && point\.riverbank_evidence_record_id/);
  assert.match(html, /pilotSection" hidden/);
  assert.doesNotMatch(html, /qs\("evidence_record_id"\)/);
  assert.doesNotMatch(html, /evidence_record_id:/);
});

test("optional chips avoid camera movement because camera stability already captures it", () => {
  const conditionBlock = html.match(/const PILOT_CONDITIONS = \[([\s\S]*?)\];/)[1];

  for (const condition of ["muddy_water", "glare", "shadows", "vegetation", "snow", "low_light"]) {
    assert.match(conditionBlock, new RegExp(condition));
  }
  assert.doesNotMatch(conditionBlock, /camera_movement/);
});
