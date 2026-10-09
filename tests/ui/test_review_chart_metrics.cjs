const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");

const html = require("./review_source.cjs").reviewHtml();
const script = html.split("<script>").pop().split("</script>")[0];
const slice = script.slice(script.indexOf("// ---- chart metrics"), script.indexOf("// ---- end chart metrics"));

const DAYS = [
  { filename: "a.jpg", code: "N", score: 0.1 },
  { filename: "b.jpg", code: "N", score: 0.2 },
  { filename: "c.jpg", code: "P", score: 0.3 },
  { filename: "gap.jpg", code: "M", score: null }
];
const row = (coverage, basis) => ({ coverage, basis });

function make(extra = {}) {
  const sandbox = {
    state: { metric: "pixel" },
    days: DAYS,
    segSeries: { counts: { with_value: 2, images: 3 }, note: "Water coverage is the share of the watched area." },
    segByFile: new Map([
      ["a.jpg", row(0.15, "accepted")],
      ["b.jpg", row(0.35, "draft")],
      ["c.jpg", row(null, "none")]
    ]),
    isoMean: (v) => v.reduce((a, b) => a + b, 0) / v.length,
    escapeHtml: (v) => String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;"),
    Math, Number, Array, Map, Object, String,
    ...extra
  };
  vm.createContext(sandbox);
  vm.runInContext(slice, sandbox);
  return sandbox;
}

test("there are exactly two measurements: the pixel score first and the default, then water coverage", () => {
  const c = make();
  const metrics = vm.runInContext("CHART_METRICS", c);
  assert.deepEqual(Array.from(metrics.map((m) => m.id)), ["pixel", "coverage"]);
  assert.equal(c.currentMetric().id, "pixel");
  assert.equal(c.chartTitleText(), "Region change score"); // the original title is kept
  c.state.metric = "vs_baseline"; // a value saved by an earlier version falls back to the default
  assert.equal(c.currentMetric().id, "pixel");
});

test("the switch explains what each measurement is in plain words", () => {
  const c = make();
  const pixel = c.chartMetricSwitchHtml();
  assert.match(pixel, /How different each image looks from the baseline image, from pixel brightness/);
  assert.doesNotMatch(pixel, /vs baseline|vs previous/i);
  c.state.metric = "coverage";
  const seg = c.chartMetricSwitchHtml();
  assert.match(seg, /the share of your watched area that the segmentation marks as water/);
  assert.match(seg, /A higher point means more of the watched area is water/);
  assert.match(seg, /not water depth or flow/);
  assert.match(seg, /aria-pressed="true" data-act="chart-metric" data-value="coverage"/);
  assert.match(seg, /Segmentation: water coverage <span[^>]*>\(2\/3\)/);
});

test("water coverage is a percent per image and a missing mask is null, never zero", () => {
  const c = make();
  assert.equal(c.segValueFor(DAYS[0], "coverage"), 15);
  assert.equal(c.segValueFor(DAYS[1], "coverage"), 35);
  assert.equal(c.segValueFor(DAYS[2], "coverage"), null);
  assert.equal(c.segValueFor(DAYS[3], "coverage"), null);
  assert.equal(c.segValueFor(DAYS[0], "vs_baseline"), null); // the removed measurements are gone
  const zero = make({ segByFile: new Map([["z.jpg", row(0, "accepted")]]) });
  assert.equal(zero.segValueFor({ filename: "z.jpg" }, "coverage"), 0); // a real 0% is kept
});

test("buckets average only the values that exist, and pixel keeps its own mean", () => {
  const c = make();
  const bucket = { indices: [0, 1, 2], meanScore: 0.2 };
  assert.equal(c.bucketMetricValue(bucket, { id: "pixel" }), 0.2);
  assert.equal(c.bucketMetricValue(bucket, { id: "coverage" }), 25);
  assert.equal(c.bucketMetricValue({ indices: [2] }, { id: "coverage" }), null);
});

test("a point is hollow only when every image behind it uses an unreviewed draft mask", () => {
  const c = make();
  assert.equal(c.bucketIsDraft({ indices: [1] }), true);
  assert.equal(c.bucketIsDraft({ indices: [0] }), false);
  assert.equal(c.bucketIsDraft({ indices: [0, 1] }), false); // one accepted mask makes it solid
  assert.equal(c.bucketIsDraft({ indices: [2] }), false); // no value at all
});

test("scales keep the original pixel axis and give coverage a percent axis", () => {
  const c = make();
  const pixel = c.metricScale({ id: "pixel" }, [0.1, 0.31]);
  assert.equal(pixel.min, 0);
  assert.ok(Math.abs(pixel.max - 0.33) < 1e-9);
  const cov = c.metricScale({ id: "coverage" }, [15, 35]);
  assert.equal(cov.min, 0);
  assert.equal(cov.max, 40);
  assert.equal(cov.fmt(25), "25%");
  assert.equal(c.metricScale({ id: "coverage" }, [95]).max, 100);
});

test("tooltips say what the number is", () => {
  const c = make();
  assert.equal(c.metricValueText({ id: "pixel" }, 0.1234), "score 0.123");
  assert.equal(c.metricValueText({ id: "coverage" }, 35), "35.0% of the watched area is water");
});

test("an empty chart says what to do instead of drawing zeros or using the pixel score", () => {
  const none = make({ segSeries: { counts: { with_value: 0, images: 3 }, note: "" } });
  const text = none.metricEmptyHtml({ id: "coverage" });
  assert.match(text, /No image in this run has a usable water mask yet/);
  assert.match(text, /hollow until you accept each mask/);
  assert.match(text, /Nothing is estimated from the pixel score/);
  assert.equal(none.metricEmptyHtml({ id: "pixel" }), '<div class="hint">No scores available.</div>');
  assert.match(make({ segSeries: null }).metricEmptyHtml({ id: "coverage" }), /could not be loaded/);
});

test("the chart legend, notes and wiring", () => {
  assert.equal((script.match(/function scoreChartSvg\(\)/g) || []).length, 1);
  assert.match(script, /act === "chart-metric"\) \{\s*state\.metric = el\.dataset\.value;\s*saveChartMetric\(state\.metric\);/);
  assert.match(script, /\["pixel", "coverage"\]\.includes\(saved\)/);
  assert.match(script, /chartMetricSwitchHtml\(\)\}\s*\$\{selectedDaySummaryHtml\(\)\}/);
  assert.match(script, /Mask accepted by a reviewer/);
  assert.match(script, /Unreviewed draft mask/);
  assert.match(script, /images have a mask/);
  assert.match(script, /typical range ends \$\{changeInfo\.threshold\.toFixed\(3\)\}/);
  assert.match(script, /const thresholdY = pixel && changeInfo\.threshold != null/);
  assert.match(script, /const changeX = pixel \? changeXPosition\(buckets\) : null/);
  assert.doesNotMatch(script, /vs_baseline|vs_previous|Change vs baseline|Change vs previous/);
});

test("accepting a mask refreshes the segmentation chart and the selected image says if it is a draft", () => {
  assert.match(script, /async function loadSegSeries\(\)/);
  assert.match(script, /\/api\/compare\/series\?/);
  assert.match(script, /await loadSegSeries\(\); \/\/ an accepted or rejected mask changes/);
  assert.match(script, /\(draft mask\)/);
});
