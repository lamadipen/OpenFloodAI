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
    folderName: "demo",
    Intl, Date, Number, String, Object, Map, Array, JSON, URLSearchParams
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
  assert.match(out, /id="wlDownload" disabled/); // visible but disabled: nothing can be downloaded
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
  assert.match(ready, /Create a new sequence with 1 image/);
  assert.match(ready, /I confirm this/);
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

test("the time-of-day choice is sent with the preview and with replacement requests", () => {
  const ctx = context();
  assert.equal(JSON.parse(JSON.stringify(vm.runInContext("wlRequestBody()", ctx))).time_of_day, "any");
  vm.runInContext("wl.timeOfDay = 'daytime';", ctx);
  assert.equal(JSON.parse(JSON.stringify(vm.runInContext("wlRequestBody()", ctx))).time_of_day, "daytime");
  load(ctx, proposal([group("high", [sample("high", "a.jpg", "2026-03-01T18:00:00+00:00", 60)], 1)]));
  assert.equal(JSON.parse(JSON.stringify(vm.runInContext("wlReplacementBody('high', 'a.jpg')", ctx))).time_of_day, "daytime");
});

test("the panel offers both choices and states the daytime window when it is used", () => {
  const ctx = context();
  const panel = vm.runInContext("wlPanelHtml()", ctx);
  assert.match(panel, /Any time of day/);
  assert.match(panel, /Daytime only \(10:00&ndash;14:00 local\)/);
  assert.match(panel, /value="any" data-wl-time checked/);

  const p = proposal([group("high", [sample("high", "a.jpg", "2026-03-01T18:00:00+00:00", 60)], 1)]);
  p.request = { time_of_day: { mode: "daytime", window_local_hours: [10, 14] } };
  load(ctx, p);
  vm.runInContext("wl.timeOfDay = 'daytime';", ctx);
  const out = vm.runInContext("wlPanelHtml()", ctx);
  assert.match(out, /daytime only \(10:00&ndash;14:00 local, for both the gauge reading and the image\)/);
  assert.match(out, /value="daytime" data-wl-time checked/);
});

test("a group with no daytime reading explains it", () => {
  const ctx = context();
  load(ctx, proposal([group("high", [], 3, { missing: 3, reason: "no_daytime_reading_in_this_group" })]));
  assert.match(vm.runInContext("wlPanelHtml()", ctx), /taken during the daytime window/);
});

function freshPreview(ctx) {
  load(ctx, proposal([group("high", [sample("high", "a.jpg", "2026-03-01T18:00:00+00:00", 60)], 1)]));
  vm.runInContext("wl.settingsKey = wlSettingsKey(); wl.confirmed = true; wl.declined = ['x.jpg'];", ctx);
}

test("the request always names the site, so the camera can be checked before Find samples", () => {
  const body = JSON.parse(JSON.stringify(vm.runInContext("wlRequestBody()", context())));
  assert.equal(body.folder_name, "demo");
});

test("changing any setting makes the preview's settings key differ", () => {
  const ctx = context();
  freshPreview(ctx);
  const same = vm.runInContext("wl.settingsKey === wlSettingsKey()", ctx);
  assert.equal(same, true);
  for (const change of [
    "wl.groups = ['low']",
    "wl.perGroup = 1",
    "wl.timeOfDay = 'daytime'",
  ]) {
    freshPreview(ctx);
    vm.runInContext(change, ctx);
    assert.equal(vm.runInContext("wl.settingsKey === wlSettingsKey()", ctx), false, change);
  }
});

test("invalidating clears the preview, approvals, declined images and the confirmation", () => {
  const ctx = context();
  freshPreview(ctx);

  vm.runInContext("wlInvalidate('Groups changed. Select Find samples again.')", ctx);

  assert.equal(vm.runInContext("wl.proposal", ctx), null);
  assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext("wl.rows", ctx))), {});
  assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext("wl.declined", ctx))), []);
  assert.equal(vm.runInContext("wl.confirmed", ctx), false);
  assert.equal(vm.runInContext("wl.message", ctx), "Groups changed. Select Find samples again.");
  assert.equal(vm.runInContext("wlApproved().length", ctx), 0);
  assert.match(vm.runInContext("wlPanelHtml()", ctx), /id="wlDownload" disabled/);
});

test("the form refuses a download whose settings changed after Find samples", () => {
  assert.match(script, /wl\.settingsKey !== wlSettingsKey\(\)/);
  const guard = script.slice(script.indexOf("async function wlDownload"), script.indexOf("function setSampleKind"));
  assert.match(guard, /Select Find samples again before downloading/);
  assert.ok(guard.indexOf("wlSettingsKey()") < guard.indexOf("/api/download-water-level-sampling"));
});

test("camera, dates, groups, count and time of day all clear the preview", () => {
  const handlers = script.slice(script.indexOf("function renderWaterLevel"), script.indexOf("async function wlFind"));
  for (const message of ["Groups changed", "Images per group changed", "Time of day changed"]) {
    assert.match(handlers, new RegExp(message));
  }
  assert.match(script, /\["camera_url", "start_date", "end_date"\]\.forEach/);
  assert.match(script, /The camera or dates changed\. Select Find samples again\./);
});

function withApproved(ctx) {
  load(ctx, proposal([group("high", [
    sample("high", "a.jpg", "2026-03-01T18:00:00+00:00", 60),
    sample("high", "b.jpg", "2026-03-04T18:00:00+00:00", 57),
    sample("high", "c.jpg", "2026-03-07T18:00:00+00:00", 54)
  ], 3)]));
  vm.runInContext("wl.settingsKey = wlSettingsKey();", ctx);
}

test("a new sequence is the default and shows the generated default name", () => {
  const ctx = context();
  withApproved(ctx);
  const out = vm.runInContext("wlPanelHtml()", ctx);
  assert.match(out, /value="new" data-wl-dest checked/);
  assert.match(out, /Sequence name \(optional\)/);
  assert.match(out, /usgs-CAM-2026-03-01-2026-04-29-water_level-xxxxxxxx/);
  assert.match(out, /Leave blank to use the generated name/);
  assert.match(out, /A name is only a label; the generated ID stays the sequence's identity/);
  assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext("wlDestination()", ctx))), { mode: "new", name: "" });
});

test("a custom name is sent as plain text and shown escaped in the summary", () => {
  const ctx = context();
  withApproved(ctx);
  vm.runInContext("wl.name = '<img src=x onerror=1> Windy';", ctx);
  assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext("wlDestination()", ctx))), { mode: "new", name: "<img src=x onerror=1> Windy" });
  assert.match(vm.runInContext("wlIntakeSummary(wlCurrentPlan())", ctx), /named &ldquo;/);
});

test("adding to an existing sequence shows what will be added, skipped and left alone", () => {
  const ctx = context();
  withApproved(ctx);
  vm.runInContext(`wl.destMode = 'append'; wl.destinationId = 'usgs-CAM-2026-01-01-2026-02-01-water_level-0a1b2c3d';
    wl.destinations = [{ sequence_id: wl.destinationId, label: 'Windy Gap 2026', display_name: 'Windy Gap 2026', compatible: true, downloaded_count: 5, reasons: [] }];
    wl.plan = { new: 8, duplicates: 3, conflicts: 0 };`, ctx);
  const summary = vm.runInContext("wlIntakeSummary(wlCurrentPlan())", ctx);
  assert.match(summary, /Add 8 new images to Windy Gap 2026\. Skip 3 already present\./);
  assert.match(summary, /Existing images and previous runs will remain unchanged\./);
  assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext("wlDestination()", ctx))), { mode: "append", sequence_id: "usgs-CAM-2026-01-01-2026-02-01-water_level-0a1b2c3d" });
  vm.runInContext("wl.plan = { new: 0, duplicates: 4, conflicts: 1 };", ctx);
  assert.match(vm.runInContext("wlIntakeSummary(wlCurrentPlan())", ctx), /Nothing new to add: 4 images are already in Windy Gap 2026, and 1 conflict will not be added\./);
  vm.runInContext("wl.plan = { new: 2, duplicates: 0, conflicts: 2 };", ctx);
  assert.match(vm.runInContext("wlIntakeSummary(wlCurrentPlan())", ctx), /2 conflicts will not be added/);
});

test("the download stays disabled until the server's plan is known and confirmed", () => {
  const ctx = context();
  withApproved(ctx);
  vm.runInContext("wl.destMode = 'append'; wl.destinationId = 'usgs-CAM-2026-01-01-2026-02-01-water_level-0a1b2c3d'; wl.confirmed = true; wl.plan = null;", ctx);
  assert.match(vm.runInContext("wlPanelHtml()", ctx), /id="wlDownload"[^>]* disabled/);
  assert.match(vm.runInContext("wlPanelHtml()", ctx), /Checking what would be added/);
  vm.runInContext("wl.plan = { new: 2, duplicates: 1, conflicts: 0 };", ctx);
  const ready = vm.runInContext("wlPanelHtml()", ctx);
  assert.doesNotMatch(ready, /id="wlDownload"[^>]* disabled/);
  assert.match(ready, /Add 2 images/);
  vm.runInContext("wl.destinationId = '';", ctx);
  assert.match(vm.runInContext("wlPanelHtml()", ctx), /id="wlDownload"[^>]* disabled/);
});

test("destinations are listed by name with their stable id, and exclusions explain themselves", () => {
  const ctx = context();
  vm.runInContext(`wl.destMode = 'append'; wl.destinations = [
    { sequence_id: 'usgs-CAM-2026-01-01-2026-02-01-water_level-0a1b2c3d', label: 'Same name', display_name: 'Same name', compatible: true, downloaded_count: 5, reasons: [] },
    { sequence_id: 'usgs-CAM-2026-03-01-2026-04-01-water_level-99887766', label: 'Same name', display_name: 'Same name', compatible: true, downloaded_count: 3, reasons: [] },
    { sequence_id: 'usgs-OTHER-2026-01-01-2026-02-01-all', label: 'usgs-OTHER-2026-01-01-2026-02-01-all', display_name: null, compatible: false, downloaded_count: 9, reasons: ['It holds images from a different camera (OTHER), not CAM.'] }
  ];`, ctx);
  const out = vm.runInContext("wlDestinationOptionsHtml()", ctx);
  assert.match(out, /Same name &middot; 0a1b2c3d \(5 images\)/);
  assert.match(out, /Same name &middot; 99887766 \(3 images\)/);  // duplicate names stay distinguishable
  assert.match(out, /Not available:/);
  assert.match(out, /different camera \(OTHER\), not CAM/);
  assert.doesNotMatch(out, /<option[^>]*>usgs-OTHER/);  // an incompatible sequence cannot be chosen
});

test("changing the destination invalidates the preview and the confirmation", () => {
  const handlers = script.slice(script.indexOf("function renderWaterLevel"), script.indexOf("async function wlLoadDestinations"));
  assert.match(handlers, /The destination changed\. Select Find samples again\./);
  assert.match(script, /destMode, wl\.destinationId/);
  const ctx = context();
  withApproved(ctx);
  const before = vm.runInContext("wl.settingsKey", ctx);
  vm.runInContext("wl.destMode = 'append';", ctx);
  assert.notEqual(vm.runInContext("wlSettingsKey()", ctx), before);
  vm.runInContext("wl.destMode = 'new'; wl.destinationId = 'x';", ctx);
  assert.notEqual(vm.runInContext("wlSettingsKey()", ctx), before);
});

test("the result panel reports counts, conflicts and failures, never runs anything, and offers the next step", () => {
  const ctx = context();
  const out = ctx.wlResultHtml({
    message: "Added 8 new image(s) to Windy Gap 2026. Skipped 3 already present.",
    sequence_id: "usgs-CAM-2026-01-01-2026-02-01-water_level-0a1b2c3d",
    conflict_count: 1, conflicts: [{ filename: "x.jpg", reason: "Another image already has this capture time." }],
    failed_count: 1, failed: [{ filename: "y.jpg" }]
  });
  assert.match(out, /Added 8 new image\(s\) to Windy Gap 2026\./);
  assert.match(out, /Not added \(conflicts\):<\/strong> x\.jpg/);
  assert.match(out, /Could not be downloaded:<\/strong> y\.jpg/);
  assert.match(out, /New images start unreviewed\. Nothing was run or labeled automatically/);
  assert.match(out, /tab=sequences/);
  assert.doesNotMatch(out, /run-image-sequence-validation/);
});

test("the download sends the destination and the exact plan the person confirmed", () => {
  const guard = script.slice(script.indexOf("async function wlDownload"), script.indexOf("function setSampleKind"));
  assert.match(guard, /destination: wlDestination\(\)/);
  assert.match(guard, /confirmed_plan: \{ new: plan\.new, duplicates: plan\.duplicates, conflicts: plan\.conflicts \}/);
  assert.ok(guard.indexOf("wlSettingsKey()") < guard.indexOf("/api/download-water-level-sampling"));
});

test("the action button is always visible: disabled with a hint before any preview", () => {
  const ctx = context();
  const out = vm.runInContext("wlPanelHtml()", ctx);
  assert.equal((out.match(/id="wlDownload"/g) || []).length, 1);
  assert.match(out, /id="wlDownload" disabled/);
  assert.match(out, />Create sequence<\/button>/);
  assert.match(out, /Next: select <strong>Find samples<\/strong> to preview the images/);
  vm.runInContext("wl.destMode = 'append';", ctx);
  const append = vm.runInContext("wlPanelHtml()", ctx);
  assert.match(append, />Add images to sequence<\/button>/);
  assert.match(append, /adds them to the chosen sequence/);
});

test("there is exactly one action button when the preview is shown, and when a gauge is unavailable", () => {
  const ctx = context();
  load(ctx, proposal([group("high", [sample("high", "a.jpg", "2026-03-01T18:00:00+00:00", 60)], 1)]));
  const shown = vm.runInContext("wlPanelHtml()", ctx);
  assert.equal((shown.match(/id="wlDownload"/g) || []).length, 1);
  assert.doesNotMatch(shown, /Next: select <strong>Find samples/);

  ctx.p = { state: "no_station_association" };
  vm.runInContext("wl.proposal = p;", ctx);
  const unavailable = vm.runInContext("wlPanelHtml()", ctx);
  assert.equal((unavailable.match(/id="wlDownload"/g) || []).length, 1);
  assert.match(unavailable, /id="wlDownload" disabled/);
});

test("the action button is replaced by the result after a download", () => {
  const ctx = context();
  vm.runInContext("wl.result = { message: 'Added 2 new image(s) to X.', sequence_id: 'usgs-CAM-2026-01-01-2026-02-01-water_level-0a1b2c3d', conflict_count: 0, failed_count: 0, conflicts: [], failed: [] };", ctx);
  const out = vm.runInContext("wlPanelHtml()", ctx);
  assert.doesNotMatch(out, /id="wlDownload"/);
  assert.match(out, /Open Sequences &amp; runs/);
});

test("a camera notice is shown in the preview when the site's label differs from the URL's camera", () => {
  const ctx = context();
  const p = proposal([group("high", [sample("high", "a.jpg", "2026-03-01T18:00:00+00:00", 60)], 1)]);
  p.camera_notice = "This site's own camera id is CAM_camid. Its images will be saved as USGS camera CAM, taken from the URL you entered.";
  load(ctx, p);
  const out = vm.runInContext("wlPanelHtml()", ctx);
  assert.match(out, /own camera id is CAM_camid/);
  assert.match(out, /saved as USGS camera CAM/);
  const without = proposal([group("high", [sample("high", "a.jpg", "2026-03-01T18:00:00+00:00", 60)], 1)]);
  load(ctx, without);
  assert.doesNotMatch(vm.runInContext("wlPanelHtml()", ctx), /own camera id is/);
});

// ---- sampling by month ----------------------------------------------------

const monthGroup = (name, month, label, samples, requested = 3) => ({
  group: name, month, month_label: label, requested, samples, shortfall: null, skipped: {}
});
const monthSample = (group, month, name, when, value) =>
  sample(group, name, when, value, { sample: { month } });
const monthProposal = (groups) => ({
  ...proposal(groups),
  selection: {
    thresholds: null,
    groups,
    months: [
      { month: "2026-03", label: "March 2026", reading_count: 31, thresholds: { minimum: 1, maximum: 31, median: 16 } },
      { month: "2026-04", label: "April 2026", reading_count: 0, thresholds: null }
    ]
  }
});

test("without months the request, the slots and the panel are exactly as before", () => {
  const ctx = context();
  const body = JSON.parse(JSON.stringify(vm.runInContext("wlRequestBody()", ctx)));
  assert.equal("months" in body, false);
  assert.equal(ctx.wlSlot("high", ""), "high");
  assert.equal(ctx.wlSlot("high", undefined), "high");
  const out = vm.runInContext("wlPanelHtml()", ctx);
  assert.match(out, /Months \(optional\)/);
  assert.match(out, /None ticked: the whole date range is sampled as one, exactly as before/);
  assert.equal((out.match(/data-wl-month="/g) || []).length, 12);
  assert.doesNotMatch(out, /data-wl-month="\d+" checked/);
});

test("ticked months are sent sorted and make the preview stale when they change", () => {
  const ctx = context();
  vm.runInContext("wl.months = [8, 1, 2];", ctx);
  assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext("wlRequestBody()", ctx))).months, [1, 2, 8]);
  const before = vm.runInContext("wlSettingsKey()", ctx);
  vm.runInContext("wl.months = [1, 2];", ctx);
  assert.notEqual(vm.runInContext("wlSettingsKey()", ctx), before);
  assert.match(vm.runInContext("wlPanelHtml()", ctx), /data-wl-month="1" checked/);
});

test("the form says how many months of the dates match and the most it can download", () => {
  const ctx = context(); // dates 2026-03-01 to 2026-04-29
  vm.runInContext("wl.months = [3, 4, 8]; wl.perGroup = 3;", ctx);
  assert.equal(ctx.wlMonthPeriodCount(), 2);
  assert.match(ctx.wlMonthsHintHtml(), /2 months\): up to 3 images for each ticked group, so at most 18/);
  vm.runInContext("wl.months = [8];", ctx);
  assert.equal(ctx.wlMonthPeriodCount(), 0);
  assert.match(ctx.wlMonthsHintHtml(), /None of the ticked months fall inside your dates/);
  vm.runInContext("wl.months = [1,2,3,4,5,6,7,8,9,10,11,12];", ctx);
  assert.equal(ctx.wlMonthPeriodCount(), 2);
});

test("a range over several years counts each matching month once per year", () => {
  const values = { camera_url: "u", start_date: "2024-12-15", end_date: "2026-01-20" };
  const sandbox = { escapeHtml: String, $: (id) => ({ value: values[id] || "" }), folderName: "demo",
    Intl, Date, Number, String, Object, Map, Array, JSON, URLSearchParams };
  vm.createContext(sandbox);
  vm.runInContext(helpers, sandbox);
  vm.runInContext("wl.months = [12, 1];", sandbox);
  assert.equal(sandbox.wlMonthPeriodCount(), 4); // Dec 2024, Jan 2025, Dec 2025, Jan 2026
  vm.runInContext("wl.months = [1,2,3,4,5,6,7,8,9,10,11,12];", sandbox);
  assert.equal(sandbox.wlMonthPeriodCount(), 14);
  values.end_date = "2027-12-20"; // 36 months, all ticked: more than one search allows
  assert.match(sandbox.wlMonthsHintHtml(), /limit is 24/);
});

test("samples are listed, approved and sent per month and group", () => {
  const ctx = context();
  const mar = monthSample("high", "2026-03", "m.jpg", "2026-03-30T18:00:00+00:00", 31);
  const apr = monthSample("high", "2026-04", "a.jpg", "2026-04-28T18:00:00+00:00", 29);
  load(ctx, monthProposal([
    monthGroup("high", "2026-03", "March 2026", [mar], 1),
    monthGroup("high", "2026-04", "April 2026", [apr], 1)
  ]));
  assert.deepEqual(Object.keys(JSON.parse(JSON.stringify(vm.runInContext("wl.rows", ctx)))), ["2026-03~high", "2026-04~high"]);
  const refs = JSON.parse(JSON.stringify(vm.runInContext("wlApprovedRefs()", ctx)));
  assert.deepEqual(refs.map((r) => [r.month, r.group, r.filename]), [
    ["2026-03", "high", "m.jpg"], ["2026-04", "high", "a.jpg"]
  ]);
  const out = vm.runInContext("wlPanelHtml()", ctx);
  assert.match(out, /March 2026/);
  assert.match(out, /April 2026/);
  assert.match(out, /relative to this month/);
  assert.match(out, /31 readings in March 2026, ranging 1\.00 to 31\.00 ft/);
  assert.match(out, /no valid gauge readings in April 2026/);
  assert.match(out, /data-wl-approve="2026-03~high:0"/);
  assert.match(out, /data-wl-replace="2026-04~high:0"/);
});

test("the same image in two months does not collide and a plain request omits the month", () => {
  const ctx = context();
  load(ctx, proposal([group("high", [sample("high", "a.jpg", "2026-03-01T18:00:00+00:00", 60)], 1)]));
  const refs = JSON.parse(JSON.stringify(vm.runInContext("wlApprovedRefs()", ctx)));
  assert.equal("month" in refs[0], false);
  assert.notEqual(
    ctx.wlRowKey({ group: "high", month: "2026-03", image: { filename: "a.jpg" } }),
    ctx.wlRowKey({ group: "high", month: "2026-04", image: { filename: "a.jpg" } })
  );
});

test("a replacement is limited to one month and group and keeps that slot's other rows", () => {
  const ctx = context();
  vm.runInContext("wl.months = [3, 4];", ctx);
  const first = monthSample("high", "2026-03", "m1.jpg", "2026-03-30T18:00:00+00:00", 31);
  const second = monthSample("high", "2026-03", "m2.jpg", "2026-03-27T18:00:00+00:00", 28);
  const other = monthSample("high", "2026-04", "a1.jpg", "2026-04-28T18:00:00+00:00", 29);
  load(ctx, monthProposal([
    monthGroup("high", "2026-03", "March 2026", [first, second]),
    monthGroup("high", "2026-04", "April 2026", [other])
  ]));
  const body = JSON.parse(JSON.stringify(vm.runInContext("wlReplacementBody('2026-03~high', 'm1.jpg')", ctx)));
  assert.deepEqual(body.groups, ["high"]);
  assert.equal(body.only_month, "2026-03");
  assert.deepEqual(body.months, [3, 4]);
  assert.deepEqual(body.declined, ["m1.jpg"]);
  assert.deepEqual(body.kept.map((k) => [k.month, k.group, k.filename]), [["2026-03", "high", "m2.jpg"]]);
});
