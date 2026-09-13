const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-home-ui.html"), "utf8");
const panel = html.split('<section id="labelFormPanel"')[1].split("</section>")[0];

test("the label form has a select for each new riverbank/reference quality field", () => {
  assert.match(panel, /<select name="riverbank_visible" id="labelRiverbankVisibleSelect"/);
  assert.match(panel, /<select name="stable_marker_visible" id="labelStableMarkerVisibleSelect"/);
  assert.match(panel, /<select name="water_boundary_visible" id="labelWaterBoundaryVisibleSelect"/);
  assert.match(panel, /<select name="camera_stable" id="labelCameraStableSelect"/);
  assert.match(panel, /<select name="visibility_condition" id="labelVisibilityConditionSelect"/);
});

test("the quality selects are populated from the sites payload's option lists", () => {
  assert.ok(html.includes("payload.tristate_options"));
  assert.ok(html.includes("payload.visibility_condition_options"));
  assert.ok(html.includes("labelRiverbankVisibleSelect"));
  assert.ok(html.includes("labelStableMarkerVisibleSelect"));
  assert.ok(html.includes("labelWaterBoundaryVisibleSelect"));
  assert.ok(html.includes("labelCameraStableSelect"));
  assert.ok(html.includes("labelVisibilityConditionSelect"));
});

test("a failed baseline-ready check is surfaced to the reviewer after saving a label", () => {
  assert.ok(html.includes("result.quality.baseline_ready === false"));
  assert.ok(html.includes("result.quality.failure_reason_text"));
});
