const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync("tools/console/review-assisted.html", "utf8");
const css = fs.readFileSync("tools/console/review-assisted.css", "utf8");
const script = fs.readFileSync("tools/console/review-assisted.js", "utf8");
const focusScript = fs.readFileSync("tools/console/review-focus.js", "utf8");

test("assisted review is its own page, linked beside Review and Blind review", () => {
  assert.match(html, /shared\.css/);
  assert.match(html, /review-assisted\.css/);
  assert.match(html, /review-assisted\.js/);
  // the script starts itself; calling main() from the page too would load everything twice
  assert.doesNotMatch(html, /main\(\)/);
  assert.match(script, /\nmain\(\);\s*$/);
  const site = fs.readFileSync("tools/console/site.html", "utf8");
  const review = fs.readFileSync("tools/console/review.js", "utf8");
  assert.match(site, /review-assisted\.html/);
  assert.match(site, /Assisted review/);
  assert.match(review, /review-assisted\.html/);
  assert.match(focusScript, /review-assisted\.html/);
});

test("the page keeps the viewer, reading panel and dial structure in the console theme", () => {
  assert.match(script, /id="assistViewer"/);
  assert.match(script, /id="assistPanel"/);
  assert.match(script, /id="dialCanvas"/);
  assert.match(css, /\.dialwrap/);
  assert.match(css, /position: sticky/);
  assert.match(css, /var\(--rail\)/);
  assert.doesNotMatch(css, /Barlow|Public Sans|IBM Plex/);
});

function load(extra = {}) {
  const storage = {};
  const calls = [];
  const sandbox = {
    qs: (name) => ({ site: "demo", run_id: "run-1" }[name] || ""),
    $: () => null,
    escapeHtml: (value) => String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;"),
    localStorage: { getItem: (k) => storage[k] ?? null, setItem: (k, v) => { storage[k] = v; } },
    document: { addEventListener() {}, querySelectorAll: () => [], querySelector: () => null },
    toast(text) { calls.push({ toast: text }); },
    mountShell: () => ({}),
    api: async (path, body) => { calls.push({ path, body }); return { points: [] }; },
    requestAnimationFrame: () => 1,
    setTimeout, clearTimeout, performance: { now: () => 0 },
    Date, Number, String, Object, Map, Set, Array, JSON, URLSearchParams, Math, window: {},
    ...extra
  };
  vm.createContext(sandbox);
  vm.runInContext(script.replace(/\nmain\(\);\s*$/, "\n"), sandbox);
  const detail = {
    summary: { sequence_id: "seq-a", baseline_filename: "base.jpg" },
    records: [
      { filename: "base.jpg", captured_at_utc: "2026-01-01T18:00:00+00:00", local_time: "2026-01-01T11:00:00-07:00", download_status: "downloaded", result: "no_water_level_change", region_change_score: 0 },
      { filename: "a.jpg", captured_at_utc: "2026-01-02T18:00:00+00:00", local_time: "2026-01-02T11:00:00-07:00", download_status: "downloaded", result: "no_water_level_change", region_change_score: 0.05 },
      { filename: "b.jpg", captured_at_utc: "2026-01-03T18:00:00+00:00", local_time: "2026-01-03T11:00:00-07:00", download_status: "downloaded", result: "possible_water_level_change", region_change_score: 0.2 },
      { filename: "gone.jpg", captured_at_utc: "2026-01-04T18:00:00+00:00", local_time: "2026-01-04T11:00:00-07:00", download_status: "failed", result: "no_water_level_change" }
    ],
    gauge_evidence: { images: [{ filename: "b.jpg", captured_at_utc: "2026-01-03T18:00:00+00:00", time_difference_seconds: -600, reading: { value: 4.25, unit: "ft" } }] },
    evidence_records: [],
    setup_used: { normal_waterline_guides: [{ status: "confirmed", points: [{ x: 10, y: 60 }, { x: 90, y: 50 }] }] }
  };
  vm.runInContext("detail = " + JSON.stringify(detail) + "; days = buildDays(detail.records);", sandbox);
  vm.runInContext('coverageByFile = new Map([["a.jpg", { coverage: 0.25, basis: "draft" }], ["b.jpg", { coverage: 0.4, basis: "accepted" }]]);', sandbox);
  vm.runInContext('gaugeByImage = new Map(detail.gauge_evidence.images.map((r) => [gaugeKey(r.filename, r.captured_at_utc), r]));', sandbox);
  sandbox.__calls = calls;
  sandbox.__storage = storage;
  return sandbox;
}

function withPoints(ctx, files) {
  ctx.points = files.map((filename) => ({ key: `k-${filename}`, filename, reviews: [] }));
  vm.runInContext("evidencePoints = points;", ctx);
}

const day = (ctx, i) => vm.runInContext(`days[${i}]`, ctx);

test("a missing value is never plotted or shown as zero", () => {
  const ctx = load();
  assert.equal(ctx.metricValue(day(ctx, 1), "pixel"), 0.05);
  assert.equal(ctx.metricValue(day(ctx, 0), "coverage"), null);
  assert.equal(ctx.metricValue(day(ctx, 1), "coverage"), 25);
  assert.equal(ctx.metricValue(day(ctx, 2), "gauge"), 4.25);
  assert.equal(ctx.metricValue(day(ctx, 1), "gauge"), null);
  // an image that did not download has no value for any measurement
  ["pixel", "coverage", "gauge"].forEach((id) => assert.equal(ctx.metricValue(day(ctx, 3), id), null));
  assert.equal(ctx.formatMetric("coverage", null), "–");
  assert.equal(ctx.metricCount("coverage"), 2);
});

test("changes against the previous image are signed and need both values", () => {
  const ctx = load();
  assert.equal(ctx.deltaText("coverage", day(ctx, 1), day(ctx, 2)), "+15.0 pp");
  assert.equal(ctx.deltaText("coverage", day(ctx, 2), day(ctx, 1)), "−15.0 pp");
  assert.equal(ctx.deltaText("coverage", day(ctx, 0), day(ctx, 1)), "–");
  assert.equal(ctx.deltaText("coverage", null, day(ctx, 1)), "–");
  assert.equal(ctx.deltaText("pixel", day(ctx, 1), day(ctx, 2)), "+0.150");
});

test("the dial scale starts at zero for the pixel score and pads the others", () => {
  const ctx = load();
  vm.runInContext('metricId = "pixel"; computeSeries();', ctx);
  const pixel = JSON.parse(vm.runInContext("JSON.stringify(dialSeries)", ctx));
  assert.equal(pixel.lo, 0);
  assert.ok(pixel.hi > 0.2);
  assert.equal(pixel.values[3], null);
  vm.runInContext('metricId = "coverage"; computeSeries();', ctx);
  const coverage = JSON.parse(vm.runInContext("JSON.stringify(dialSeries)", ctx));
  assert.ok(coverage.lo < 25 && coverage.hi > 40);
  assert.deepEqual(coverage.values, [null, 25, 40, null]);
});

test("the baseline is not reviewed against itself and the reference can be the previous image", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  assert.equal(ctx.canReview(day(ctx, 0)), false);
  assert.equal(ctx.canReview(day(ctx, 1)), true);
  assert.equal(ctx.canReview(day(ctx, 3)), false); // not downloaded
  assert.equal(ctx.reviewableCount(), 2);
  assert.equal(ctx.referenceFor(day(ctx, 2)).filename, "base.jpg");
  vm.runInContext('referenceMode = "previous";', ctx);
  assert.equal(ctx.referenceFor(day(ctx, 2)).filename, "a.jpg");
  assert.equal(ctx.referenceFor(day(ctx, 2)).kind, "previous");
  assert.equal(ctx.canReview(day(ctx, 0)), false); // nothing before it
  assert.equal(ctx.chooseInitialIndex(), 1);
});

test("labels saved here are always informed and carry the reference", async () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  vm.runInContext('reviewerId = "reviewer-a"; selectedIndex = 1; selectedLabel = "water_level_rising"; draftCameraStable = "yes"; draftNote = " rose ";', ctx);
  await ctx.saveLabel(false);
  const post = ctx.__calls.find((call) => call.path === "/api/workspace-label");
  assert.ok(post, "the label was posted");
  assert.equal(post.body.review_stage, "informed");
  assert.equal(post.body.human_label, "water_level_rising");
  assert.equal(post.body.reviewer_id, "reviewer-a");
  assert.equal(post.body.camera_stable, "yes");
  assert.equal(post.body.note, "rose");
  assert.deepEqual(JSON.parse(JSON.stringify(post.body.reference)), { sequence_id: "seq-a", run_id: "run-1", filename: "base.jpg" });
  assert.equal(post.body.sample_key, "k-a.jpg");
});

test("saving needs a reviewer, a label and a camera answer, as in Blind review", async () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  const posted = () => ctx.__calls.some((call) => call.path === "/api/workspace-label");
  vm.runInContext('reviewerId = ""; selectedIndex = 1; selectedLabel = "water_level_rising"; draftCameraStable = "yes";', ctx);
  await ctx.saveLabel(false);
  assert.equal(posted(), false);
  vm.runInContext('reviewerId = "reviewer-a"; selectedLabel = null;', ctx);
  await ctx.saveLabel(false);
  assert.equal(posted(), false);
  vm.runInContext('selectedLabel = "water_level_rising"; draftCameraStable = "";', ctx);
  await ctx.saveLabel(false);
  assert.equal(posted(), false, "a direction needs the camera answer");
  vm.runInContext('selectedLabel = "cannot_judge_water_level";', ctx);
  await ctx.saveLabel(false);
  assert.equal(posted(), true, "cannot judge does not need the camera answer");
});

test("opening the page is confirmed once and then counts every image as informed in Blind review", () => {
  const ctx = load();
  vm.runInContext('reviewerId = "";', ctx);
  assert.equal(ctx.needsGate(), true);
  vm.runInContext('reviewerId = "Reviewer-A";', ctx);
  assert.equal(ctx.needsGate(), true);
  vm.runInContext("loadRevealed(); markAllRevealed();", ctx);
  assert.equal(ctx.needsGate(), false);
  // Blind review reads exactly this key, so its own stage check sees these images as already revealed.
  const key = "openfloodai.revealed.run-1.reviewer-a";
  assert.deepEqual(JSON.parse(ctx.__storage[key]).sort(), ["a.jpg", "b.jpg", "base.jpg", "gone.jpg"]);
  const focusKey = focusScript.match(/function revealKeyStorage\(\) \{\s*return (`[^`]+`);/)[1];
  const assistedKey = script.match(/function revealKeyStorage\(\) \{\s*return (`[^`]+`);/)[1];
  assert.equal(assistedKey, focusKey);
  // another reviewer has not been shown anything yet
  vm.runInContext('reviewerId = "reviewer-b"; loadRevealed();', ctx);
  assert.equal(ctx.needsGate(), true);
});

test("the reference follows the chosen view, and a preview is used while the dial moves", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  vm.runInContext("selectedIndex = 2;", ctx);
  const current = day(ctx, 2);
  const original = ctx.viewerHtml(current, false);
  assert.match(original, /image-sequence-image/);
  assert.match(original, /class="assist-inset"/);
  assert.match(original, /compare\/thumbnail/); // the small reference is a thumbnail in the original view
  assert.match(original, /Reference · run baseline/);
  vm.runInContext('viewMode = "guide";', ctx);
  const guide = ctx.viewerHtml(current, false);
  assert.equal((guide.match(/class="guide-svg"/g) || []).length, 2, "the base guide is drawn on both pictures");
  assert.match(guide, /Base guide/);
  vm.runInContext('viewMode = "segmentation";', ctx);
  assert.match(ctx.viewerHtml(current, false), /No segmentation saved/);
  const quick = ctx.viewerHtml(current, true);
  assert.doesNotMatch(quick, /image-sequence-image/);
  assert.match(quick, /Preview while moving/);
});

test("swapping shows the reference large and the baseline explains it cannot be compared with itself", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  vm.runInContext("selectedIndex = 2; swapped = true;", ctx);
  const swapped = ctx.viewerHtml(day(ctx, 2), false);
  assert.match(swapped, /3 \/ 4 · Reference/);
  assert.match(swapped, /inset-caption">Current/);
  vm.runInContext("selectedIndex = 0; swapped = true;", ctx);
  const baseline = ctx.viewerHtml(day(ctx, 0), false);
  assert.match(baseline, /This image is the reference\./);
  assert.doesNotMatch(baseline, /assist-inset/);
});

test("the reading panel shows machine evidence as assistance, never as a decision", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  vm.runInContext('selectedIndex = 2; metricId = "coverage";', ctx);
  const panel = ctx.panelHtml(day(ctx, 2));
  assert.match(panel, /Machine reading · assist only/);
  assert.match(panel, /Possible visual change/);
  assert.match(panel, /Water coverage · accepted mask/);
  assert.match(panel, /4\.25 ft · 10 min before image/);
  assert.match(panel, /What changed between the images\?/);
  assert.doesNotMatch(panel, /data-label="[^"]+" aria-pressed="true"/); // nothing is pre-selected for the reviewer
  vm.runInContext("selectedIndex = 1;", ctx);
  assert.match(ctx.panelHtml(day(ctx, 1)), /Water coverage · machine draft only/);
  vm.runInContext('selectedIndex = 0; metricId = "coverage";', ctx);
  assert.match(ctx.panelHtml(day(ctx, 0)), /Missing segmentation is not evidence of no water/);
});

test("a blind label made earlier stays on record and the panel says so", () => {
  const ctx = load();
  ctx.points = [{ key: "k-a.jpg", filename: "a.jpg", reviews: [{ label: { human_label: "no_water_level_change", reviewer_id: "Reviewer-A" }, review_stage: "blind" }] }];
  vm.runInContext('evidencePoints = points; reviewerId = "reviewer-a";', ctx);
  assert.match(ctx.panelHtml(day(ctx, 1)), /labelled this image blind earlier/);
  vm.runInContext("resetDraftForDay(days[1]);", ctx);
  assert.equal(vm.runInContext("selectedLabel", ctx), "no_water_level_change");
});

test("keyboard use, a pinned dial, and responsive layout are present", () => {
  assert.match(script, /Ctrl\/⌘\+Enter \$\{pairMode\(\)/);
  assert.match(script, /event\.key === "ArrowLeft"/);
  assert.match(script, /role="slider"/);
  assert.match(script, /prefers-reduced-motion/);
  assert.match(script, /sideways/);
  assert.match(css, /@media \(max-width: 1120px\)/);
  assert.match(css, /@media \(max-width: 760px\)/);
});

function withDatasets(ctx) {
  vm.runInContext('datasets = [{ dataset_id: "d-vis", name: "Visible", task: "visual_change", task_title: "Visible water change" }, { dataset_id: "d-seg", name: "Seg", task: "water_segmentation", task_title: "Water segmentation" }]; selectedDatasetId = "d-vis";', ctx);
}

test("the dataset panel sits in the right column and the pair is sent earlier first", () => {
  assert.match(script, /id="assistDataset"/);
  assert.match(script, /class="assist-right"/);
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  withDatasets(ctx);
  vm.runInContext("selectedIndex = 2;", ctx);
  const request = ctx.datasetRequest(day(ctx, 2));
  assert.equal(request.pair, true);
  assert.deepEqual(JSON.parse(JSON.stringify(request.body)), {
    dataset_id: "d-vis",
    earlier: { folder_name: "demo", run_id: "run-1", filename: "base.jpg" },
    later: { folder_name: "demo", run_id: "run-1", filename: "b.jpg" }
  });
  const panel = ctx.datasetPanelHtml(day(ctx, 2));
  assert.match(panel, /Add to dataset/);
  assert.match(panel, /Visible · Visible water change/);
  assert.match(panel, /One judgment is enough to add the pair/);
  assert.match(panel, /data-add-dataset disabled/); // nothing can be added before the check says eligible
});

test("a single-image dataset sends the run, the image and the accepted mask", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  vm.runInContext('selectedDatasetId = "d-seg"; samResults = [{ filename: "b.jpg", status: "completed", review_status: "accepted", prompt: "river water", run_id: "sam-1", result_id: "r-1" }];', ctx);
  withDatasets(ctx);
  vm.runInContext('selectedDatasetId = "d-seg";', ctx);
  const body = JSON.parse(JSON.stringify(ctx.datasetRequest(day(ctx, 2)).body));
  assert.deepEqual(body, { dataset_id: "d-seg", folder_name: "demo", run_id: "run-1", filename: "b.jpg", mask_run_id: "sam-1", mask_result_id: "r-1" });
  assert.match(ctx.datasetPanelHtml(day(ctx, 2)), /Accepted mask/);
});

test("the add button is enabled only when the check says eligible, and ineligible shows the reasons", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  withDatasets(ctx);
  vm.runInContext('datasetCheck = { status: "ineligible", reasons: [{ message: "Needs two blind reviewers", severity: "error" }], agreement: { reviewers: 0, needed: 2, by_direction: {} } };', ctx);
  const blocked = ctx.datasetPanelHtml(day(ctx, 2));
  assert.match(blocked, /Not eligible for this dataset/);
  assert.match(blocked, /Needs two blind reviewers/);
  assert.match(blocked, /0 reviewers judged this pair \(at least 2 needed\)/);
  assert.match(blocked, /data-add-dataset disabled/);
  vm.runInContext('datasetCheck = { status: "eligible", reasons: [] };', ctx);
  const open = ctx.datasetPanelHtml(day(ctx, 2));
  assert.match(open, /Eligible: nothing has been added yet/);
  assert.doesNotMatch(open, /data-add-dataset disabled/);
});

test("with no dataset the panel points to where one is created, and the baseline cannot be added alone", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  assert.match(ctx.datasetPanelHtml(day(ctx, 2)), /No dataset drafts exist yet/);
  withDatasets(ctx);
  assert.match(ctx.datasetPanelHtml(day(ctx, 0)), /This image is the reference, so it cannot be added on its own/);
});

test("the eligibility check runs once the dial settles, not on every image it passes", async () => {
  const posts = [];
  const ctx = load({ fetch: async (path, init) => { posts.push({ path, body: JSON.parse(init.body) }); return { ok: true, status: 200, json: async () => ({ status: "eligible", reasons: [] }) }; } });
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  withDatasets(ctx);
  vm.runInContext("selectedIndex = 2;", ctx);
  ctx.show(1, true);
  ctx.show(2, true);
  assert.equal(posts.length, 0, "moving the dial does not check");
  await ctx.refreshDatasetCheck(day(ctx, 2));
  await ctx.refreshDatasetCheck(day(ctx, 2));
  assert.equal(posts.length, 1, "the same request is not repeated");
  assert.equal(posts[0].path, "/api/dataset-check");
});

test("side by side shows the reference and the current image together, both in the chosen view", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  vm.runInContext('selectedIndex = 2; compareMode = "side";', ctx);
  const html = ctx.viewerHtml(day(ctx, 2), false);
  assert.equal((html.match(/class="assist-fig"/g) || []).length, 2);
  assert.match(html, /assist-chip">Reference · run baseline/);
  assert.match(html, /assist-chip">Current</);
  assert.match(html, /data-pan-group/);
  assert.doesNotMatch(html, /assist-inset/); // nothing to inset when both are shown
  assert.match(html, /alt="Reference river image"/);
  assert.match(html, /alt="Current river image"/);
  vm.runInContext('viewMode = "guide";', ctx);
  assert.equal((ctx.viewerHtml(day(ctx, 2), false).match(/class="guide-svg"/g) || []).length, 2, "the base guide is on both pictures");
  assert.doesNotMatch(ctx.viewerHtml(day(ctx, 2), true), /image-sequence-image/, "a preview is used while the dial moves");
});

test("overlay blends the current image over the reference with an opacity", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  vm.runInContext('selectedIndex = 2; compareMode = "overlay"; overlayOpacity = 30;', ctx);
  const html = ctx.viewerHtml(day(ctx, 2), false);
  assert.match(html, /assist-overlay-current" style="width:100%;opacity:0\.3"/);
  assert.match(html, /Current 30%/);
  assert.match(html, /assist-chip left">Reference/);
  const toolbar = ctx.toolbarHtml();
  assert.match(toolbar, /id="opacityControl"/);
  vm.runInContext('compareMode = "side";', ctx);
  assert.doesNotMatch(ctx.toolbarHtml(), /opacityControl/);
});

test("the layout choice needs a reference, so the baseline stays on the single view", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  vm.runInContext('selectedIndex = 0; compareMode = "side";', ctx);
  const baseline = ctx.viewerHtml(day(ctx, 0), false);
  assert.match(baseline, /This image is the reference\./);
  assert.doesNotMatch(baseline, /assist-fig/);
  assert.match(ctx.toolbarHtml(), /data-compare="side" aria-pressed="true" disabled/);
  vm.runInContext("selectedIndex = 2;", ctx);
  assert.doesNotMatch(ctx.toolbarHtml(), /data-compare="overlay" aria-pressed="false" disabled/);
  assert.match(ctx.toolbarHtml(), /data-compare="single"/);
});

test("an ineligible check says what to do next, with a link", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  withDatasets(ctx);
  vm.runInContext("selectedIndex = 2;", ctx);
  vm.runInContext('datasetCheck = { status: "ineligible", reasons: [{ code: "needs_a_judgment", message: "Nobody has judged this pair yet.", severity: "error" }] };', ctx);
  const pair = ctx.datasetPanelHtml(day(ctx, 2));
  assert.match(pair, /Label this pair first/);
  assert.doesNotMatch(pair, /Blind review/); // nothing to hand off: the person adding it labels it
  vm.runInContext('datasetCheck = { status: "ineligible", reasons: [{ code: "mask_missing", message: "No saved water segmentation", severity: "error" }] };', ctx);
  assert.match(ctx.datasetPanelHtml(day(ctx, 2)), /accept a water mask[\s\S]*review\.html/);
  vm.runInContext('datasetCheck = { status: "eligible", reasons: [] };', ctx);
  assert.doesNotMatch(ctx.datasetPanelHtml(day(ctx, 2)), /dataset-next/);
});

test("the water mask can be accepted, rejected or sent for correction under the segmentation picture", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  vm.runInContext('samResults = [{ filename: "b.jpg", status: "completed", review_status: "unreviewed", prompt: "river water", run_id: "sam-1", result_id: "r-1" }]; selectedIndex = 2;', ctx);
  // only in the segmentation view
  assert.doesNotMatch(ctx.viewerHtml(day(ctx, 2), false), /mask-bar/);
  vm.runInContext('viewMode = "segmentation";', ctx);
  const html = ctx.viewerHtml(day(ctx, 2), false);
  assert.match(html, /Water mask of the current image/);
  assert.match(html, /pill warn">unreviewed/);
  ["accepted", "rejected", "needs_correction"].forEach((value) => assert.match(html, new RegExp(`data-mask-decision="${value}" data-mask-run="sam-1" data-mask-result="r-1"`)));
  // not while the dial is moving, and not in the other layouts' pictures
  assert.doesNotMatch(ctx.viewerHtml(day(ctx, 2), true), /mask-bar/);
  vm.runInContext('compareMode = "side";', ctx);
  assert.match(ctx.viewerHtml(day(ctx, 2), false), /mask-bar/);
  // an image with no segmentation has nothing to approve
  vm.runInContext('compareMode = "single"; selectedIndex = 1;', ctx);
  assert.doesNotMatch(ctx.viewerHtml(day(ctx, 1), false), /mask-bar/);
  // the accepted mask shows as accepted, with its button marked
  vm.runInContext('samResults[0].review_status = "accepted"; selectedIndex = 2;', ctx);
  const accepted = ctx.viewerHtml(day(ctx, 2), false);
  assert.match(accepted, /pill ok">accepted/);
  assert.match(accepted, /btn primary" data-mask-decision="accepted"/);
});

test("reviewing a mask posts the decision, reloads results and re-checks eligibility", async () => {
  const calls = [];
  const ctx = load({
    api: async (path, body) => {
      calls.push({ path, body });
      if (path.startsWith("/api/hosted-sam/results")) return { results: [{ filename: "b.jpg", status: "completed", review_status: "accepted", prompt: "river water", run_id: "sam-1", result_id: "r-1" }] };
      if (path.startsWith("/api/compare/series")) return { images: [{ filename: "b.jpg", coverage: 0.4, basis: "accepted" }] };
      return {};
    }
  });
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  vm.runInContext('selectedIndex = 2; datasetCheckKey = "stale"; reviewerId = "reviewer-a";', ctx);
  await ctx.reviewMask({ dataset: { maskRun: "sam-1", maskResult: "r-1", maskDecision: "accepted" } });
  const post = calls.find((call) => call.path === "/api/hosted-sam/review");
  assert.deepEqual(JSON.parse(JSON.stringify(post.body)), { folder_name: "demo", run_id: "sam-1", result_id: "r-1", decision: "accepted" });
  assert.ok(calls.some((call) => call.path.startsWith("/api/hosted-sam/results")));
  assert.ok(calls.some((call) => call.path.startsWith("/api/compare/series")));
  assert.equal(vm.runInContext("samResults[0].review_status", ctx), "accepted");
  assert.equal(vm.runInContext("coverageByFile.get('b.jpg').basis", ctx), "accepted");
  assert.equal(vm.runInContext("savingMask", ctx), false);
});

test("the agreement line names reviewers who judged after seeing machine evidence", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  withDatasets(ctx);
  vm.runInContext('datasetCheck = { status: "eligible", reasons: [{ code: "informed_judgments_counted", message: "reviewer-b judged this pair after seeing machine evidence (informed).", severity: "warning" }], agreement: { reviewers: 2, needed: 1, informed: ["reviewer-b"], by_direction: { more_water: ["reviewer-a", "reviewer-b"] } } };', ctx);
  const html = ctx.datasetPanelHtml(day(ctx, 2));
  assert.match(html, /2 reviewers judged this pair \(at least 1 needed\)/);
  assert.match(html, /informed \(saw machine evidence\): reviewer-b/);
  assert.match(html, /after seeing machine evidence/);
  assert.doesNotMatch(html, /data-add-dataset disabled/);
});

test("the dial gets a reference marker button only while a pair dataset is selected", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  assert.equal(ctx.pairPickHtml(), "", "no dataset, no button");
  withDatasets(ctx); // starts on the visible-change (pair) dataset
  assert.match(ctx.pairPickHtml(), /data-set-marker[^>]*>Set reference here</);
  vm.runInContext('selectedDatasetId = "d-seg";', ctx);
  assert.equal(ctx.pairPickHtml(), "", "a single-image dataset needs no pair");
  vm.runInContext('datasets.push({ dataset_id: "d-lvl", name: "Rise", task: "level_change", task_title: "Rising / falling" }); selectedDatasetId = "d-lvl";', ctx);
  assert.match(ctx.pairPickHtml(), /Set reference here/);
});

test("setting the marker pins the image under the needle as the reference for the others", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  withDatasets(ctx);
  vm.runInContext("selectedIndex = 1;", ctx);
  ctx.setMarkerAtNeedle();
  assert.equal(vm.runInContext("referenceMode", ctx), "marker");
  assert.equal(vm.runInContext("markerFilename", ctx), "a.jpg");
  // the needle moves on; the reference stays put
  vm.runInContext("selectedIndex = 2;", ctx);
  const ref = ctx.referenceFor(day(ctx, 2));
  assert.equal(ref.filename, "a.jpg");
  assert.equal(ref.kind, "marker");
  assert.equal(ctx.canReview(day(ctx, 2)), true);
  assert.equal(ctx.canReview(day(ctx, 1)), false, "the marked image is not compared with itself");
  const pair = JSON.parse(JSON.stringify(ctx.datasetRequest(day(ctx, 2)).body));
  assert.equal(pair.earlier.filename, "a.jpg");
  assert.equal(pair.later.filename, "b.jpg");
  // the choice shows as its own tab and in the button
  assert.match(ctx.referenceChoiceHtml(day(ctx, 2)), /data-ref-mode="marker" aria-pressed="true"/);
  assert.match(ctx.pairPickHtml(), /Move reference here/);
  assert.match(ctx.pairPickHtml(), /Reference: 2026-01-02 11:00/);
  assert.match(ctx.viewerHtml(day(ctx, 2), false), /dial marker/);
});

test("a marker earlier or later than the image is ordered by time, and clearing returns to the baseline", () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  withDatasets(ctx);
  vm.runInContext('selectedIndex = 2;', ctx);
  ctx.setMarkerAtNeedle(); // b.jpg is the later image
  vm.runInContext("selectedIndex = 1;", ctx);
  const pair = JSON.parse(JSON.stringify(ctx.datasetRequest(day(ctx, 1)).body));
  assert.equal(pair.earlier.filename, "a.jpg");
  assert.equal(pair.later.filename, "b.jpg");
  ctx.clearMarker();
  assert.equal(vm.runInContext("referenceMode", ctx), "baseline");
  assert.equal(ctx.referenceFor(day(ctx, 1)).filename, "base.jpg");
  assert.doesNotMatch(ctx.referenceChoiceHtml(day(ctx, 1)), /data-ref-mode="marker"/);
});

test("a label made against the marker saves that image as its reference", async () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  withDatasets(ctx);
  vm.runInContext('selectedIndex = 1;', ctx);
  ctx.setMarkerAtNeedle();
  vm.runInContext('selectedIndex = 2; reviewerId = "reviewer-a"; selectedLabel = "water_level_rising"; draftCameraStable = "yes";', ctx);
  await ctx.saveLabel(false);
  const post = ctx.__calls.find((call) => call.path === "/api/workspace-label");
  assert.deepEqual(JSON.parse(JSON.stringify(post.body.reference)), { sequence_id: "seq-a", run_id: "run-1", filename: "a.jpg" });
  assert.equal(post.body.review_stage, "informed");
});

test("the marker control lives in the dial header and has a keyboard shortcut", () => {
  assert.match(script, /id="pairPick"/);
  assert.match(script, /event\.key === "p"/);
  assert.match(css, /\.pair-chip/);
});

test("with a reference marker set, Save replaces Save & next and stays on the image", async () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  withDatasets(ctx);
  assert.match(ctx.panelHtml(day(ctx, 2)), /data-save [^>]*>Save & next</);
  vm.runInContext("selectedIndex = 1;", ctx);
  ctx.setMarkerAtNeedle();
  vm.runInContext('selectedIndex = 2; reviewerId = "reviewer-a"; selectedLabel = "water_level_rising"; draftCameraStable = "yes";', ctx);
  const panel = ctx.panelHtml(day(ctx, 2));
  assert.match(panel, /data-save [^>]*>Save</);
  assert.doesNotMatch(panel, /Save & next</);
  assert.match(panel, /Ctrl\/⌘\+Enter save, then add the pair/);
  await ctx.saveLabel(!ctx.pairMode());
  assert.equal(vm.runInContext("selectedIndex", ctx), 2, "the page stays on the image just saved");
  assert.match(ctx.__calls.filter((call) => call.toast).pop().toast, /Add the pair to the dataset below/);
});

test("after the save, focus goes to Add pair once the check says eligible", () => {
  const focused = [];
  const add = { disabled: false, focus() { focused.push("add"); } };
  const box = { innerHTML: "", scrollIntoView() {}, focus() { focused.push("card"); }, querySelector: () => add, addEventListener() {} };
  const ctx = load({ $: (id) => (id === "assistDataset" ? box : null) });
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  withDatasets(ctx);
  vm.runInContext('selectedIndex = 2; focusAddAfterSave = true; datasetCheck = { pending: true };', ctx);
  ctx.focusAddWhenReady();
  assert.deepEqual(focused, [], "no focus while the check is still running");
  vm.runInContext('datasetCheck = { status: "eligible", reasons: [] };', ctx);
  ctx.focusAddWhenReady();
  assert.deepEqual(focused, ["add"]);
  ctx.focusAddWhenReady();
  assert.deepEqual(focused, ["add"], "focus moves once");
  // an ineligible pair has nothing to press, so the card with its reason gets the focus
  add.disabled = true;
  vm.runInContext('focusAddAfterSave = true; datasetCheck = { status: "ineligible", reasons: [] };', ctx);
  ctx.focusAddWhenReady();
  assert.deepEqual(focused, ["add", "card"]);
});

test("without a marker Save & next still moves on and does not take the focus", async () => {
  const ctx = load();
  withPoints(ctx, ["base.jpg", "a.jpg", "b.jpg"]);
  withDatasets(ctx);
  vm.runInContext('selectedIndex = 1; reviewerId = "reviewer-a"; selectedLabel = "water_level_rising"; draftCameraStable = "yes";', ctx);
  await ctx.saveLabel(!ctx.pairMode());
  assert.equal(vm.runInContext("selectedIndex", ctx), 2);
  assert.equal(vm.runInContext("focusAddAfterSave", ctx), false);
});
