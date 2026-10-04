const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../../tools/console/form-add-media.html"), "utf8");
const script = html.split("<script>").pop().split("</script>")[0];
const helpers = script.slice(
  script.indexOf("let wl = "),
  script.indexOf("// ---- end water-level sampling")
);

function context() {
  const values = { camera_url: " https://apps.usgs.gov/hivis/camera/CAM ", start_date: "2026-03-01", end_date: "2026-04-29" };
  const sandbox = {
    escapeHtml: (value) => String(value),
    $: (id) => ({ value: values[id] || "" }),
    Intl, Date, Number, String, Object, Map
  };
  vm.createContext(sandbox);
  vm.runInContext(helpers, sandbox);
  return sandbox;
}

const reading = (when, value, extra = {}) => ({
  datetime_utc: when, value, unit: "ft", qualifiers: ["A"], quality_status: "approved", ...extra
});
const sample = (group, name, when, value, extra = {}) => ({
  group,
  motivating_reading: reading(when, value, extra.reading),
  image: { filename: name, captured_at_utc: when },
  gap_seconds: extra.gap ?? -300,
  image_reading: reading(when, value),
  image_reading_gap_seconds: -300,
  readings_differ: false,
  ...extra.sample
});
const proposal = (groups) => ({
  state: "ok",
  note: "Low, middle, and high are relative to this station and date range only.",
  policy_version: "water-level-sampling-v1",
  timezone: "America/Denver",
  association: { nwis_site_id: "09999999", source: "https://example.test/registry" },
  gauge: { parameter_label: "gage height", unit: "ft", valid_reading_count: 60 },
  selection: { thresholds: { minimum: 1, maximum: 60, median: 30.5 }, groups }
});
const group = (name, samples, requested = 3, shortfall = null) => ({ group: name, requested, samples, shortfall, skipped: {} });

function load(ctx, p) {
  ctx.proposal = p;
  vm.runInContext("wl.proposal = proposal; wlSetRowsFromProposal(proposal);", ctx);
}

test("gaps and times are exact and unambiguous", () => {
  const ctx = context();
  assert.equal(ctx.wlFormatGap(-300), "5 min before the image");
  assert.equal(ctx.wlFormatGap(900), "15 min after the image");
  assert.equal(ctx.wlFormatGap(0), "same moment as the image");
  assert.equal(ctx.wlFormatGap(-90), "1 min 30 s before the image");
  assert.match(ctx.wlWhen("2026-03-01T12:00:00+00:00", "America/Denver"), /2026-03-01 12:00 UTC \(.*MST local\)/);
});

test("the preview shows group, gauge time, height and unit, quality, image time and gap", () => {
  const ctx = context();
  load(ctx, proposal([group("high", [sample("high", "a.jpg", "2026-03-01T12:00:00+00:00", 60.25, { reading: { quality_status: "provisional", qualifiers: ["P"] } })], 1)]));
  const out = vm.runInContext("wlPanelHtml()", ctx);
  assert.match(out, /High water/);
  assert.match(out, /relative to this range/);
  assert.match(out, /60\.25 ft/);
  assert.match(out, /Provisional, may be revised/);
  assert.match(out, /Reading is 5 min before the image/);
  assert.match(out, /Policy water-level-sampling-v1/);
  assert.match(out, /not flood thresholds|relative to this station/);
});

test("both readings are shown when the image's own nearest reading differs", () => {
  const ctx = context();
  load(ctx, proposal([group("high", [sample("high", "a.jpg", "2026-03-01T12:00:00+00:00", 60, { sample: { readings_differ: true, image_reading: reading("2026-03-01T12:13:00+00:00", 59.5), image_reading_gap_seconds: -60 } })], 1)]));
  const out = vm.runInContext("wlPanelHtml()", ctx);
  assert.match(out, /The image's own nearest reading: 59\.50 ft, 1 min before the image/);
});

test("a shortfall is stated, not hidden", () => {
  const ctx = context();
  load(ctx, proposal([group("high", [sample("high", "a.jpg", "2026-03-01T12:00:00+00:00", 60)], 3, { missing: 2, reason: "not_enough_distinct_dates_with_images" })]));
  const out = vm.runInContext("wlPanelHtml()", ctx);
  assert.match(out, /Found 1 of 3 requested/);
  assert.match(out, /Not enough separate dates/);
});

test("limited variation says nothing was made up", () => {
  const ctx = context();
  load(ctx, proposal([group("low", [], 3, { missing: 3, reason: "limited_level_variation" })]));
  assert.match(vm.runInContext("wlPanelHtml()", ctx), /Nothing is made up/);
});

test("unavailable states replace the preview and offer no download", () => {
  const ctx = context();
  ctx.p = { state: "gauge_height_unavailable", message: "This station reports flow (discharge) but no gauge height. Flow is never used in its place." };
  vm.runInContext("wl.proposal = p;", ctx);
  const out = vm.runInContext("wlPanelHtml()", ctx);
  assert.match(out, /discharge/);
  assert.doesNotMatch(out, /wlDownload/);
  ctx.p = { state: "no_station_association" };
  vm.runInContext("wl.proposal = p;", ctx);
  assert.match(vm.runInContext("wlPanelHtml()", ctx), /No USGS gauge is linked/);
});

test("only approved rows are sent for download, and the download needs the confirmation", () => {
  const ctx = context();
  load(ctx, proposal([group("high", [
    sample("high", "a.jpg", "2026-03-01T12:00:00+00:00", 60),
    sample("high", "b.jpg", "2026-03-04T12:00:00+00:00", 57)
  ], 2)]));
  vm.runInContext("wl.rows.high[1].approved = false;", ctx);

  assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext("wlApprovedRefs()", ctx))), [
    { group: "high", reading_datetime_utc: "2026-03-01T12:00:00+00:00", filename: "a.jpg" }
  ]);
  assert.match(vm.runInContext("wlPanelHtml()", ctx), /id="wlDownload"[^>]* disabled/);
  vm.runInContext("wl.confirmed = true;", ctx);
  const ready = vm.runInContext("wlPanelHtml()", ctx);
  assert.doesNotMatch(ready, /id="wlDownload"[^>]* disabled/);
  assert.match(ready, /Download 1 selected image/);
  assert.match(ready, /confirm downloading 1 approved image/);
});

test("a replacement request is scoped to one group, keeps the others, and declines the replaced image", () => {
  const ctx = context();
  load(ctx, proposal([
    group("high", [sample("high", "a.jpg", "2026-03-01T12:00:00+00:00", 60), sample("high", "b.jpg", "2026-03-04T12:00:00+00:00", 57)], 2),
    group("low", [sample("low", "c.jpg", "2026-03-08T12:00:00+00:00", 1)], 1)
  ]));
  vm.runInContext("wl.groups = ['high','low']; wl.declined = ['old.jpg'];", ctx);

  const body = JSON.parse(JSON.stringify(vm.runInContext("wlReplacementBody('high', 'b.jpg')", ctx)));

  assert.deepEqual(body.groups, ["high"]);
  assert.deepEqual(body.declined, ["old.jpg", "b.jpg"]);
  assert.deepEqual(body.kept.map((k) => k.filename), ["a.jpg"]);
  assert.equal(body.camera_url, "https://apps.usgs.gov/hivis/camera/CAM");
  assert.equal(body.images_per_group, 3);
});
